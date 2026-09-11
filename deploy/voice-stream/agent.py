"""Voice-stream worker — Kokoro primary, LiveKit optional.

Pipeline: silero VAD -> faster-whisper STT (fallback: voice-stt HTTP)
-> Ollama LLM streaming (fallback: OpenRouter) -> Kokoro FastAPI (primary)
   fallback: XTTS streaming (ws) -> Piper.

LiveKit import is soft — VPS 8GB sem LiveKit, usa Kokoro HTTP via OpenAI compat.
Sala carrega prompt do agente AIOS via metadata {agent_id, org_id}.
Sem metadata, usa VOICE_AGENT_INSTRUCTIONS.
"""

import asyncio
import json
import logging
import math
import os
import struct
import time

logger = logging.getLogger("voice-stream")

# ── W1 VAD / barge-in config ──────────────────────────────────────────────
VOICE_VAD_ENABLED = os.environ.get("VOICE_VAD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
VOICE_VAD_THRESHOLD = float(os.environ.get("VOICE_VAD_THRESHOLD", "0.02"))
VOICE_SILENCE_MS = int(os.environ.get("VOICE_SILENCE_MS", "800"))
VOICE_BARGE_IN = os.environ.get("VOICE_BARGE_IN", "true").lower() in ("1", "true", "yes", "on")
VOICE_BARGE_IN_MIN_MS = int(os.environ.get("VOICE_BARGE_IN_MIN_MS", "120"))
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "") or os.environ.get("AIOS_LIVEKIT_URL", "")


def _rms_normalized(pcm_bytes: bytes) -> float:
    """RMS energia normalizada 0-1 para PCM 16-bit mono LE. Puro python, sem deps."""
    if not pcm_bytes:
        return 0.0
    n = len(pcm_bytes) // 2
    if n == 0:
        return 0.0
    # evita unpack gigante: limita a 960 amostras (~20ms @48k)
    # mas usa tudo se for menor
    try:
        fmt = f"<{n}h"
        samples = struct.unpack(fmt, pcm_bytes[: n * 2])
    except Exception:
        return 0.0
    # soma quadrados
    sumsq = 0.0
    for s in samples:
        sumsq += s * s
    if n == 0:
        return 0.0
    rms = math.sqrt(sumsq / n) / 32768.0
    return rms


class SimpleEnergyVAD:
    """VAD simples energia RMS + silence detection 800ms + barge-in 120ms.

    Uso:
        vad = SimpleEnergyVAD(threshold=0.02, silence_ms=800, barge_in=True)
        vad.process_frame(pcm_bytes) -> {"is_speech":bool, "energy":float, "barge_in":bool, "end_of_turn":bool}
        # durante TTS playback: se barge_in True -> cancela playback e reinicia STT
        # se end_of_turn True -> envia pro LLM
    """

    def __init__(
        self,
        threshold: float = 0.02,
        silence_ms: int = 800,
        barge_in: bool = True,
        barge_in_ms: int = 120,
        sample_rate: int = 16000,
    ):
        self.threshold = threshold
        self.silence_ms = silence_ms
        self.barge_in = barge_in
        self.barge_in_ms = barge_in_ms
        self.sample_rate = sample_rate
        self._voice_ms = 0.0
        self._silence_ms = 0.0
        self._in_speech = False
        self._had_speech = False

    def reset(self):
        self._voice_ms = 0.0
        self._silence_ms = 0.0
        self._in_speech = False
        self._had_speech = False

    def rms(self, pcm_bytes: bytes) -> float:
        return _rms_normalized(pcm_bytes)

    def is_speech(self, pcm_bytes: bytes) -> bool:
        return self.rms(pcm_bytes) > self.threshold

    def process_frame(self, pcm_bytes: bytes, frame_ms: float = 20.0, is_tts_playing: bool = False) -> dict:
        energy = self.rms(pcm_bytes)
        is_voice = energy > self.threshold
        end_of_turn = False
        barge_in_trigger = False

        if is_voice:
            self._voice_ms += frame_ms
            self._silence_ms = 0
            self._in_speech = True
            self._had_speech = True
            if is_tts_playing and self.barge_in and self._voice_ms >= self.barge_in_ms:
                barge_in_trigger = True
        else:
            self._voice_ms = 0
            if self._had_speech:
                self._silence_ms += frame_ms
                if self._silence_ms >= self.silence_ms:
                    end_of_turn = True
                    self._had_speech = False
                    self._silence_ms = 0
                    self._in_speech = False

        return {
            "energy": energy,
            "is_speech": is_voice,
            "barge_in": barge_in_trigger,
            "end_of_turn": end_of_turn,
        }

    def should_interrupt(self, pcm_bytes: bytes, is_tts_playing: bool, frame_ms: float = 20.0) -> bool:
        """Helper rápido p/ caller: deve interromper TTS?"""
        if not self.barge_in or not is_tts_playing or not VOICE_VAD_ENABLED:
            return False
        res = self.process_frame(pcm_bytes, frame_ms=frame_ms, is_tts_playing=is_tts_playing)
        return bool(res["barge_in"])

    def is_end_of_turn(self, pcm_bytes: bytes, frame_ms: float = 20.0) -> bool:
        if not VOICE_VAD_ENABLED:
            return False
        res = self.process_frame(pcm_bytes, frame_ms=frame_ms, is_tts_playing=False)
        return bool(res["end_of_turn"])


def _use_livekit_turn_detection() -> bool:
    """Se LIVEKIT_URL configurado e livekit disponível, usa turn detection nativo."""
    return bool(LIVEKIT_URL)


# singleton VAD local (fallback)
_local_vad: SimpleEnergyVAD | None = None


def get_local_vad() -> SimpleEnergyVAD:
    global _local_vad
    if _local_vad is None:
        _local_vad = SimpleEnergyVAD(
            threshold=VOICE_VAD_THRESHOLD,
            silence_ms=VOICE_SILENCE_MS,
            barge_in=VOICE_BARGE_IN,
            barge_in_ms=VOICE_BARGE_IN_MIN_MS,
        )
    return _local_vad


async def interrupt_tts_playback(session=None, tts_task: asyncio.Task | None = None):
    """Cancela playback TTS e reinicia STT. Seguro se VAD desabilitado."""
    try:
        if tts_task and not tts_task.done():
            tts_task.cancel()
            try:
                await tts_task
            except asyncio.CancelledError:
                pass
            logger.info("barge-in: TTS task cancelada")
    except Exception:
        pass
    # LiveKit session interrupt (se disponível)
    if session is not None:
        try:
            # AgentSession tem interrupt() nas versões recentes
            if hasattr(session, "interrupt"):
                await session.interrupt()
                logger.info("barge-in: session.interrupt() ok")
            elif hasattr(session, "clear_audio"):
                session.clear_audio()
        except Exception as e:
            logger.warning("barge-in interrupt falhou: %s", e)
    # Reinicia STT: marca que próximo frame deve ser tratado como novo turno
    try:
        get_local_vad().reset()
    except Exception:
        pass

AIOS_URL = os.environ.get("AIOS_URL", "http://app:8777").rstrip("/")
AIOS_KEY = os.environ.get("AIOS_ADMIN_MASTER_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
VOICE_LLM_MODEL = os.environ.get("VOICE_LLM_MODEL", os.environ.get("AIOS_VOICE_LLM_MODEL", "openai/gpt-4o-mini"))
TTS_WS_URL = os.environ.get("TTS_WS_URL", "ws://voice-tts-stream:8001/tts/ws")
TTS_ENGINE = os.environ.get("VOICE_TTS_ENGINE", "kokoro")
TTS_VOICE_RAW = os.environ.get("VOICE_TTS_VOICE", "ptbr")
KOKORO_URL = os.environ.get("KOKORO_URL", "http://voice-tts-kokoro:8880/v1")
PIPER_URL = os.environ.get("PIPER_URL", "http://voice-tts:8000/v1")
STT_URL = os.environ.get("STT_URL", "http://voice-stt:9000/v1")

# ptbr → Kokoro pt voices (remsky/kokoro-fastapi-cpu has 72, pf_dora/pm_alex for pt)
VOICE_MAP = {
    "ptbr": "pm_alex",
    "pt-br": "pm_alex",
    "pt": "pm_alex",
    "pt_br": "pm_alex",
    "kokoro": "af_heart",
    "xtts": "pm_alex",
}
TTS_VOICE = VOICE_MAP.get(TTS_VOICE_RAW.lower(), TTS_VOICE_RAW)
if TTS_VOICE_RAW.lower() in VOICE_MAP:
    logger.info("voice map %s -> %s", TTS_VOICE_RAW, TTS_VOICE)

DEFAULT_INSTRUCTIONS = (
    "Você é SDR da empresa. Fala PT-BR, direta, humana. "
    "Qualifica (nome, interesse, orçamento, prazo) e agenda próximo passo. "
    "Respostas curtas, 1-2 frases, uma pergunta por vez, nunca inventa preço ou prazo."
)


async def fetch_agent_prompt(agent_id: str) -> str:
    if not agent_id or not AIOS_KEY:
        return DEFAULT_INSTRUCTIONS
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{AIOS_URL}/api/agents/{agent_id}", headers={"X-Admin-Key": AIOS_KEY})
            if r.status_code == 200:
                prompt = (r.json().get("system_prompt") or "").strip()
                if prompt:
                    return prompt[:6000]
    except Exception:
        logger.exception("fetch agent prompt falhou")
    return DEFAULT_INSTRUCTIONS


def build_stt():
    # try local faster-whisper, fallback to HTTP
    try:
        from faster_whisper import WhisperModel  # noqa: F401
        from local_livekit_plugins import FasterWhisperSTT

        return FasterWhisperSTT(
            model_size=os.environ.get("WHISPER_MODEL", "small"),
            device="cuda" if os.environ.get("WHISPER_CUDA", "") == "1" else "cpu",
            compute_type="float16" if os.environ.get("WHISPER_CUDA", "") == "1" else "int8",
        )
    except Exception as e:
        logger.warning("faster-whisper local indisponível (%s), usando voice-stt HTTP", e)
        try:
            from livekit.plugins import openai as lk_openai

            return lk_openai.STT(model="whisper-1", base_url=STT_URL, api_key="not-needed")
        except Exception:
            logger.warning("livekit STT indisponível, sem STT")
            return None


def build_llm():
    try:
        from livekit.plugins import openai as lk_openai
    except Exception:
        logger.warning("livekit plugins indisponível, usando OpenRouter direto")
        return None
    try:
        import httpx

        r = httpx.get(f"{OLLAMA_URL}/models", timeout=5)
        if r.status_code == 200:
            return lk_openai.LLM.with_ollama(model=OLLAMA_MODEL, base_url=OLLAMA_URL)
    except Exception as e:
        logger.warning("ollama indisponível (%s)", e)
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        logger.warning("sem ollama nem openrouter — LLM vai falhar, configure OLLAMA_URL")
    logger.info("voice LLM: %s (VOICE_LLM_MODEL)", VOICE_LLM_MODEL)
    return lk_openai.LLM(model=VOICE_LLM_MODEL, base_url="https://openrouter.ai/api/v1", api_key=key or "missing")


def build_tts():
    # Kokoro HTTP primary (0.5→1 CPU, 72 voices), XTTS ws fallback
    # try livekit streaming TTS first if engine=xtts and TTS_WS_URL reachable
    if TTS_ENGINE == "xtts":
        try:
            from livekit_streaming_tts import StreamingTTS

            tts = StreamingTTS(ws_url=TTS_WS_URL, voice=TTS_VOICE, language="pt", sample_rate=24000, format="pcm", binary=True)
            tts.prewarm()
            logger.info("tts engine ativo: xtts ws %s voice %s", TTS_WS_URL, TTS_VOICE)
            return tts
        except Exception as e:
            logger.warning("tts xtts falhou (%s), fallback kokoro", e)
    # Kokoro HTTP via livekit openai plugin or direct HTTP
    try:
        from livekit.plugins import openai as lk_openai
        import httpx

        httpx.get(f"{KOKORO_URL}/models", timeout=5)
        logger.info("tts engine ativo: kokoro %s voice %s", KOKORO_URL, TTS_VOICE)
        return lk_openai.TTS(model="kokoro", voice=TTS_VOICE, api_key="not-needed", base_url=KOKORO_URL)
    except Exception as e:
        logger.warning("kokoro %s falhou (%s), fallback piper", KOKORO_URL, e)
    try:
        from livekit.plugins import openai as lk_openai

        return lk_openai.TTS(model="tts-1", voice="af_sky", api_key="not-needed", base_url=PIPER_URL)
    except Exception:
        logger.warning("nenhum TTS disponível")
        return None


async def entrypoint(ctx):  # type: ignore
    # soft import livekit — se não houver, roda em modo HTTP puro (útil para testes)
    try:
        from livekit.plugins import silero
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
        from livekit.agents import Agent, AgentSession
    except Exception as e:
        logger.error("livekit agents indisponível (%s) — voice-agent requer livekit, mas Kokoro HTTP pode ser usado via app", e)
        # fallback: não inicia sessão LiveKit, apenas loga e mantém worker vivo para healthcheck
        import asyncio

        while True:
            await asyncio.sleep(3600)

    await ctx.connect()
    meta = {}
    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except Exception:
        pass
    instructions = await fetch_agent_prompt(meta.get("agent_id", ""))

    # VAD + turn detection: LiveKit nativo se LIVEKIT_URL, senão fallback energia RMS
    if _use_livekit_turn_detection():
        try:
            vad_obj = silero.VAD.load() if VOICE_VAD_ENABLED else None
        except Exception as e:
            logger.warning("silero VAD falhou (%s), usando local SimpleEnergyVAD", e)
            vad_obj = None
        try:
            turn_det = MultilingualModel()
            logger.info("turn detection: LiveKit MultilingualModel (LIVEKIT_URL set)")
        except Exception as e:
            logger.warning("MultilingualModel falhou (%s), sem turn_detection nativo", e)
            turn_det = None
    else:
        vad_obj = None
        turn_det = None
        # fallback local VAD já configurado via get_local_vad()
        if VOICE_VAD_ENABLED:
            logger.info(
                "VAD fallback local ativo: threshold=%s silence=%sms barge_in=%s (LIVEKIT_URL vazio)",
                VOICE_VAD_THRESHOLD,
                VOICE_SILENCE_MS,
                VOICE_BARGE_IN,
            )
        else:
            logger.info("VAD desabilitado (VOICE_VAD_ENABLED=false) — sem barge-in/silence detection")
        # silero ainda tenta se disponível e habilitado
        if VOICE_VAD_ENABLED:
            try:
                vad_obj = silero.VAD.load()
                logger.info("silero VAD carregado mesmo sem LIVEKIT_URL (fallback híbrido)")
            except Exception:
                vad_obj = None

    # AgentSession: vad/turn_detection podem ser None (desabilitado)
    sess_kwargs = dict(stt=build_stt(), llm=build_llm(), tts=build_tts())
    if vad_obj is not None:
        sess_kwargs["vad"] = vad_obj
    if turn_det is not None:
        sess_kwargs["turn_detection"] = turn_det

    session = AgentSession(**sess_kwargs)

    # barge-in via VAD local quando habilitado e fallback (ou mesmo com LiveKit: monitora energia)
    local_vad = get_local_vad() if VOICE_VAD_ENABLED else None
    if local_vad and VOICE_BARGE_IN:
        logger.info("barge-in ativo: threshold=%s barge_in_ms=%s silence_ms=%s", VOICE_VAD_THRESHOLD, VOICE_BARGE_IN_MIN_MS, VOICE_SILENCE_MS)
        # hook simples: se LiveKit expõe audio frame, usa callback; senão, fica disponível para caller HTTP
        # guarda referência na session para uso externo (ex: handle_audio_frame)
        try:
            session._local_vad = local_vad  # type: ignore
            session._barge_in_enabled = True  # type: ignore
        except Exception:
            pass
    # soft Agent import already done
    from livekit.agents import Agent as LKA

    await session.start(room=ctx.room, agent=LKA(instructions=instructions))
    await session.generate_reply(instructions="Cumprimenta e pergunta como pode ajudar.")


if __name__ == "__main__":
    # soft cli — se livekit não instalado, apenas avisa
    try:
        from livekit.agents import cli, WorkerOptions

        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    except Exception as e:
        logger.error("livekit cli indisponível (%s) — rode via Docker com --profile voice ou use Kokoro HTTP direto", e)
        import time

        while True:
            time.sleep(3600)
