from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

class TranscribeInput(BaseModel):
    media_id: str = Field(description="WhatsApp media id")
    language: str = Field(default="pt")

class TranscribeTool(BaseTool):
    name = "transcribe"
    description = "Transcreve áudio WhatsApp (whisper) via media_id"
    input_model = TranscribeInput
    async def run(self, media_id: str, language: str = "pt") -> dict:
        if not media_id:
            return {"error": "media_id vazio"}
        # tenta baixar via WhatsAppChannel helper
        try:
            from aios.db.backend import db_session
            from aios.db.models import ChannelConnection
            from sqlalchemy import select
            async with db_session() as db:
                chans = (await db.execute(select(ChannelConnection).where(ChannelConnection.channel_type=="whatsapp"))).scalars().all()
                for ch in chans:
                    try:
                        from aios.channels.whatsapp import WhatsAppChannel
                        w = WhatsAppChannel(connection=ch)
                        data = await w.download_media(media_id)
                        if data:
                            # whisper via openai
                            import os, httpx
                            from aios.config import settings
                            # try org key first
                            key = settings.openai_api_key or settings.openrouter_api_key
                            if not key:
                                return {"error": "sem chave openai", "bytes": len(data)}
                            # use openai whisper
                            async with httpx.AsyncClient(timeout=30) as c:
                                # openai audio/transcriptions
                                files = {"file": ("audio.ogg", data, "audio/ogg"), "model": (None, "whisper-1"), "language": (None, language)}
                                # need proper multipart
                                r = await c.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": f"Bearer {key}"}, files=files)
                                if r.status_code==200:
                                    return {"text": r.json().get("text",""), "ok": True}
                                return {"error": r.text[:400], "status": r.status_code}
                    except Exception as e:
                        continue
            return {"error": "não baixou media"}
        except Exception as e:
            return {"error": str(e)}

TOOL_REGISTRY["transcribe"] = {"code_reference": "aios.tools.transcribe.TranscribeTool"}
