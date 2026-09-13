from fastapi import APIRouter, Request, Header
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

class SendBody(BaseModel):
    instance: str
    to: str
    text: str
    provider: str = "baileys"

class CallBody(BaseModel):
    instance: str
    to: str
    script: str = ""

@router.post("/send")
async def whatsapp_send(body: SendBody, request: Request):
    from aios.core.whatsapp.service import send_via_gateway
    from aios.core.whatsapp.anti_ban.rate_limiter import allow, record_429
    from aios.core.whatsapp.metrics import msg_total
    if not allow(body.instance):
        msg_total.labels(instance=body.instance, direction="out", status="rate_limited").inc()
        return {"ok": False, "error": "rate_limited"}
    res = await send_via_gateway(body.instance, body.to, body.text, body.provider)
    if res.get("status_code")==429:
        record_429(body.instance)
    msg_total.labels(instance=body.instance, direction="out", status="ok" if res.get("ok") else "failed").inc()
    return res

@router.get("/health/{instance}")
async def whatsapp_health(instance: str, provider: str = "baileys"):
    from aios.core.whatsapp.provider.factory import get_provider
    from aios.core.whatsapp.anti_ban.health_monitor import compute
    p = get_provider(provider if provider in ("baileys","cloud","coexistence") else "baileys")
    h = await p.health(instance)
    mon = compute(instance, h.connected, fails_24h=0, qr=0, r429=0)
    return {"instance": instance, "connected": h.connected, "provider": h.provider, "risk": mon["risk"], "level": mon["level"], "coexistence": h.provider=="coexistence"}

@router.post("/migration/check")
async def migration_check(monthly_msgs: int, ban_risk: int, failed_pct: float = 0, is_coexistence: bool = False):
    from aios.core.whatsapp.migration_advisor import evaluate
    rec = evaluate(monthly_msgs, ban_risk, failed_pct, is_coexistence=is_coexistence)
    return {"should_migrate": rec.should_migrate, "reasons": rec.reasons, "urgency": rec.urgency}

@router.post("/webhook/evolution/{instance}")
async def evolution_webhook(instance: str, request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    from aios.config import settings
    from aios.core.whatsapp.webhook_validator import validate
    v = await validate(request, settings.evolution_webhook_secret or "", settings.redis_url)
    if not v["ok"]:
        return {"ok": False, "reason": v["reason"]}
    body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
    # Coexistence: smb_message_echoes (App → API) → log + bypass anti-ban
    from aios.core.whatsapp.provider.evolution_coexistence import EvolutionCoexistenceProvider
    if EvolutionCoexistenceProvider.is_smb_echo(body):
        return {"ok": True, "instance": instance, "coexistence": True, "echo": True}
    # LGPD consent auto: STOP keyword
    txt = (body.get("data",{}).get("message",{}).get("conversation") or body.get("message") or "").lower()
    if txt.strip() in ("stop","parar","cancelar"):
        from aios.core.whatsapp.lgpd.consent import record_consent
        phone = body.get("data",{}).get("key",{}).get("remoteJid","")
        await record_consent(phone, "marketing", False, org_id="unknown")
    return {"ok": True, "instance": instance}

# Voice Phase B
@router.post("/call")
async def whatsapp_call(body: CallBody):
    from aios.core.whatsapp.voice.call_router import start_outbound
    return await start_outbound(body.to, body.script)

@router.get("/voice/ivr/synthesize")
async def ivr_synthesize(text: str):
    from aios.core.voice import synthesize
    return await synthesize(text)

@router.get("/metrics/summary")
async def metrics_summary():
    from aios.core.evolution_api import evo_fetch_instances
    instances = await evo_fetch_instances()
    return {"instances": len(instances), "gateway": "wrapper v0.1.0"}
