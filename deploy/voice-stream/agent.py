"""LiveKit voice-stream worker — SDR/support realtime, $0 marginal.

Pipeline: silero VAD -> faster-whisper STT (fallback: voice-stt HTTP)
-> Ollama LLM streaming (fallback: OpenRouter) -> XTTS streaming TTS
(fallback: Kokoro FastAPI -> Piper voice-tts).

Sala carrega prompt do agente AIOS via metadata {agent_id, org_id}.
Sem metadata, usa VOICE_AGENT_INSTRUCTIONS.
"""

import json
import logging
import os

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli

logger = logging.getLogger("voice-stream")

AIOS_URL = os.environ.get("AIOS_URL", "http://app:8777").rstrip("/")
AIOS_KEY = os.environ.get("AIOS_ADMIN_MASTER_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
TTS_WS_URL = os.environ.get("TTS_WS_URL", "ws://voice-tts-stream:8001/tts/ws")
TTS_ENGINE = os.environ.get("VOICE_TTS_ENGINE", "xtts")
TTS_VOICE = os.environ.get("VOICE_TTS_VOICE", "ptbr")
KOKORO_URL = os.environ.get("KOKORO_URL", "http://voice-tts-kokoro:8880/v1")
PIPER_URL = os.environ.get("PIPER_URL", "http://voice-tts:8000/v1")
STT_URL = os.environ.get("STT_URL", "http://voice-stt:9000/v1")

DEFAULT_INSTRUCTIONS = (
    "Você é o SDR da empresa. Fala PT-BR, direta, humana. "
    "Qualifica (nome, interesse, orçamento, prazo) e agenda próximo passo. "
    "Respostas curtas, 1-2 frases, nunca inventa preço ou prazo."
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
        from livekit.plugins import openai

        return openai.STT(model="whisper-1", base_url=STT_URL, api_key="not-needed")


def build_llm():
    from livekit.plugins import openai

    try:
        import httpx

        r = httpx.get(f"{OLLAMA_URL}/models", timeout=5)
        if r.status_code == 200:
            return openai.LLM.with_ollama(model=OLLAMA_MODEL, base_url=OLLAMA_URL)
    except Exception as e:
        logger.warning("ollama indisponível (%s)", e)
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        logger.warning("sem ollama nem openrouter — LLM vai falhar, configure OLLAMA_URL")
    return openai.LLM(model=os.environ.get("VOICE_LLM_MODEL", "openai/gpt-4o-mini"), base_url="https://openrouter.ai/api/v1", api_key=key or "missing")


def build_tts():
    from livekit_streaming_tts import StreamingTTS

    primary = TTS_ENGINE if TTS_ENGINE in ("xtts", "kokoro") else "xtts"
    order = [primary] + (["kokoro"] if primary == "xtts" else ["xtts"])
    last_err = None
    for engine in order:
        try:
            tts = StreamingTTS(ws_url=TTS_WS_URL, voice=TTS_VOICE, language="pt", sample_rate=24000, format="pcm", binary=True)
            tts.prewarm()
            logger.info("tts engine ativo: %s", engine)
            return tts
        except Exception as e:
            last_err = e
            logger.warning("tts %s falhou (%s), tentando próximo", engine, e)
    logger.warning("tts-stream fora (%s), fallback kokoro/piper HTTP", last_err)
    from livekit.plugins import openai

    try:
        import httpx

        httpx.get(f"{KOKORO_URL}/models", timeout=5)
        return openai.TTS(model="kokoro", voice="af_sky", api_key="not-needed", base_url=KOKORO_URL)
    except Exception:
        return openai.TTS(model="tts-1", voice="af_sky", api_key="not-needed", base_url=PIPER_URL)


async def entrypoint(ctx: JobContext):
    await ctx.connect()
    meta = {}
    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except Exception:
        pass
    instructions = await fetch_agent_prompt(meta.get("agent_id", ""))
    from livekit.plugins import silero
    from livekit.plugins.turn_detector.multilingual import MultilingualModel

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=build_stt(),
        llm=build_llm(),
        tts=build_tts(),
        turn_detection=MultilingualModel(),
    )
    await session.start(room=ctx.room, agent=Agent(instructions=instructions))
    await session.generate_reply(instructions="Cumprimenta e pergunta como pode ajudar.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
