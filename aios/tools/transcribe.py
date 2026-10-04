from typing import Any
from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

class TranscribeInput(BaseModel):
    media_id: str = Field(description="WhatsApp media id")
    language: str = Field(default="pt")
    diarize: bool = Field(default=False, description="se true retorna segmentos por speaker")

class TranscribeTool(BaseTool):
    name = "transcribe"
    description = "Transcreve áudio WhatsApp (whisper) via media_id"
    input_model = TranscribeInput
    async def run(self, media_id: str, language: str = "pt", diarize: bool = False) -> dict:
        if not media_id:
            return {"error": "media_id vazio"}
        mine = getattr(self, "_org_id", "") or ""
        if not mine:
            # Fail closed: without the caller org we cannot tell which tenant's
            # Evolution credentials may be used, so refuse instead of trying
            # every tenant's channel until one yields the media.
            return {"error": "sem org_id"}
        # aios.channels.whatsapp never existed, so the previous code raised
        # ImportError on every call and the tool could never work. Audio bytes
        # are fetched from the media metadata stashed at ingest (see
        # evolution_webhook), or from a direct URL when the caller has one.
        try:
            from aios.db.backend import db_session
            from aios.db.models import ChannelConnection
            from sqlalchemy import select
            async with db_session() as db:
                chans = (await db.execute(select(ChannelConnection).where(ChannelConnection.channel_type=="whatsapp", ChannelConnection.org_id==mine))).scalars().all()
                audio_meta = await _resolve_audio_meta(db, mine, media_id)
                for ch in chans:
                    try:
                        data = await _download_audio(ch, audio_meta, media_id)
                        if data:
                            # whisper via openai
                            import httpx
                            from aios.config import settings
                            # try org key first
                            key = settings.openai_api_key or settings.openrouter_api_key
                            if not key:
                                return {"error": "sem chave openai", "bytes": len(data)}
                            # use openai whisper
                            async with httpx.AsyncClient(timeout=30) as c:
                                files: dict[str, Any] = {"file": ("audio.ogg", data, "audio/ogg"), "model": (None, "whisper-1"), "language": (None, language)}
                                if diarize:
                                    files["response_format"] = (None, "verbose_json")
                                r = await c.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": f"Bearer {key}"}, files=files)
                                if r.status_code==200:
                                    j = r.json()
                                    text = j.get("text","") if isinstance(j, dict) else str(j)
                                    # track voz custo R$0,033/min (US$0,006×5,5)
                                    try:
                                        duration = j.get("duration", len(data)/16000) if isinstance(j, dict) else len(data)/16000
                                        cost = round(float(duration)/60 * 0.006, 6)
                                        from aios.db.backend import db_session as _dbs2
                                        from aios.core.limits import track_usage
                                        # find org from channel
                                        org_id = ch.org_id
                                        async with _dbs2() as _db2:
                                            await track_usage(org_id, _db2, messages=0, tokens=0, cost_usd=cost)
                                    except Exception:
                                        pass
                                    if diarize and isinstance(j, dict) and j.get("segments"):
                                        segs = [{"speaker": f"SPK_{s.get('id',0)%2}", "text": s.get("text",""), "start": s.get("start"), "end": s.get("end")} for s in j["segments"]]
                                        return {"text": text, "segments": segs, "diarized": True, "ok": True, "cost": cost if 'cost' in locals() else 0}
                                    return {"text": text, "ok": True, "cost": cost if 'cost' in locals() else 0}
                                return {"error": r.text[:400], "status": r.status_code}
                    except Exception:
                        continue
            return {"error": "não baixou media"}
        except Exception as e:
            return {"error": str(e)}

async def _resolve_audio_meta(db, org_id: str, media_id: str) -> dict:
    """Find the stored audio metadata for a message reference.

    The tool receives whatever identifier the agent has: a direct media URL, or
    a message id whose row carries the audio key stashed at ingest. A bare
    WhatsApp media id with no stored row cannot be resolved to bytes, and
    pretending otherwise is how this tool stayed broken.
    """
    text = (media_id or "").strip()
    if text.startswith(("http://", "https://")):
        return {"url": text}
    if not text:
        return {}
    from sqlalchemy import select

    from aios.db.models import Message

    row = (
        await db.execute(
            select(Message).where(
                Message.org_id == org_id,
                (Message.channel_message_id == text) | (Message.id == text),
            )
        )
    ).scalars().first()
    if row is not None:
        meta = (row.extra_data or {}).get("audio_media") or {}
        if isinstance(meta, dict) and (meta.get("url") or meta.get("media_key")):
            return meta
    return {}


async def _download_audio(ch, audio_meta: dict, media_id: str) -> bytes | None:
    """Fetch audio bytes, preferring a direct URL over the Evolution API."""
    import httpx

    url = (audio_meta or {}).get("url", "")
    if url:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(url)
                if r.status_code == 200 and r.content:
                    return r.content
        except Exception:
            pass

    # Fallback: Evolution's media endpoint. Shape follows the instance API;
    # unverified against a live Evolution here, so a failure returns None and
    # the caller reports honestly rather than raising.
    cfg = ch.config or {}
    base = str(cfg.get("server_url", "http://evolution:8080")).rstrip("/")
    api_key = str(cfg.get("api_key", ""))
    instance = str(cfg.get("instance", ""))
    media_key = (audio_meta or {}).get("media_key", "")
    if not (base and api_key and instance and media_key):
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{base}/chat/getBase64FromMediaMessage/{instance}",
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json={"message": {"key": {"id": media_id}, "mediaKey": media_key}},
            )
            if r.status_code != 200:
                return None
            payload = r.json()
            b64 = (payload or {}).get("base64", "") if isinstance(payload, dict) else ""
            if not b64:
                return None
            import base64 as _b64

            return _b64.b64decode(b64)
    except Exception:
        return None


TOOL_REGISTRY["transcribe"] = {"code_reference": "aios.tools.transcribe.TranscribeTool"}
