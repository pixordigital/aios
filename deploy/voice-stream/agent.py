"""Voice-stream worker — Kokoro primary, LiveKit optional.

Pipeline: silero VAD -> faster-whisper STT (fallback: voice-stt HTTP)
-> Ollama LLM streaming (fallback: OpenRouter) -> Kokoro FastAPI (primary)
   fallback: XTTS streaming (ws) -> Piper.

LiveKit import is soft — VPS 8GB sem LiveKit, usa Kokoro HTTP via OpenAI compat.
Sala carrega prompt do agente AIOS via metadata {agent_id, org_id}.
Sem metadata, usa VOICE_AGENT_INSTRUCTIONS.
"""

import json
import logging
import os

logger = logging.getLogger("voice-stream")

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

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=build_stt(),
        llm=build_llm(),
        tts=build_tts(),
        turn_detection=MultilingualModel(),
    )
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
