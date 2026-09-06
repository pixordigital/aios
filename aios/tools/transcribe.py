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
                                files = {"file": ("audio.ogg", data, "audio/ogg"), "model": (None, "whisper-1"), "language": (None, language)}
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
                    except Exception as e:
                        continue
            return {"error": "não baixou media"}
        except Exception as e:
            return {"error": str(e)}

TOOL_REGISTRY["transcribe"] = {"code_reference": "aios.tools.transcribe.TranscribeTool"}
