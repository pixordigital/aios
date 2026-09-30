from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

class VoiceCallInput(BaseModel):
    to: str = Field(description="Telefone destino E.164, ex. +5511999999999")
    script: str = Field(description="Roteiro/abertura da ligação (SDR/support)")
    channel_id: str = Field(default="", description="Canal voz (vazio = settings)")

class VoiceCallTool(BaseTool):
    name = "voice_call"
    description = "Dispara ligação de voz (SDR outbound / support). Sem bridge SIP, agenda com TTS pronto."
    input_model = VoiceCallInput
    async def run(self, to: str, script: str, channel_id: str = "") -> dict:
        from aios.core.voice import place_call, voice_config
        if not to or not script:
            return {"error": "to e script obrigatórios"}
        cfg = voice_config(None)
        if channel_id:
            try:
                from aios.db.backend import db_session
                from aios.db.models import ChannelConnection
                async with db_session() as db:
                    ch = await db.get(ChannelConnection, channel_id)
                    mine = getattr(self, "_org_id", "") or ""
                    if ch and ch.channel_type == "voice" and (not mine or ch.org_id == mine):
                        try:
                            from aios.core.secrets import decrypt_channel_config
                            c = ch.config or {}
                            if any(str(v).startswith("enc:") for v in c.values() if isinstance(v, str)):
                                c = decrypt_channel_config(c)
                            cfg = voice_config(c)
                            cfg["_org_id"] = ch.org_id
                        except Exception:
                            cfg = voice_config(ch.config or {})
                            cfg["_org_id"] = ch.org_id
            except Exception:
                pass
            except Exception:
                pass
        res = await place_call(to, script, cfg, {"via": "tool"})
        try:
            cost = 0.02 if res.get("status") == "dialing" else 0.0
            # Bill the org that owns the channel used, not whatever voice
            # channel happens to sort first globally.
            bill_org = (cfg or {}).get("_org_id") or getattr(self, "_org_id", "") or ""
            if cost and bill_org:
                from aios.db.backend import db_session as _dbs
                from aios.core.limits import track_usage
                async with _dbs() as _db:
                    await track_usage(bill_org, _db, messages=1, tokens=len(script) // 4, cost_usd=cost)
        except Exception:
            pass
        return res

TOOL_REGISTRY["voice_call"] = {"code_reference": "aios.tools.voice_call.VoiceCallTool"}
