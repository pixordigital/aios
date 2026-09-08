"""WhatsApp Cloud — listar templates aprovados via Graph API."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
import httpx
from aios.api.deps import get_current_user
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import ChannelConnection
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

@router.get("/templates")
async def list_templates(
    channel_id: str | None = Query(default=None),
    waba_id: str | None = Query(default=None),
    access_token: str | None = Query(default=None),
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    """Lista templates aprovados da WABA via Graph API. Usa channel_id se fornecido, senão waba_id+token."""
    token = access_token
    waba = waba_id
    if channel_id:
        chan = await db.get(ChannelConnection, channel_id)
        if not chan or chan.org_id != user.org_id:
            raise HTTPException(404, "Canal não encontrado")
        cfg = chan.config or {}
        token = token or cfg.get("access_token") or cfg.get("api_key")
        waba = waba or cfg.get("waba_id") or cfg.get("business_account_id")
        # fallback: phone_id não é waba, precisa waba_id explícito
    if not token or not waba:
        raise HTTPException(400, "Informe waba_id e access_token ou selecione canal com WhatsApp Cloud configurado")
    url = f"https://graph.facebook.com/v20.0/{waba}/message_templates"
    params = {"access_token": token, "fields": "name,language,status,category", "limit": 50}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            data = r.json()
            if r.status_code != 200:
                raise HTTPException(r.status_code, detail=data.get("error", {}).get("message", str(data)))
            # filtrar só aprovados
            templates = [t for t in data.get("data", []) if t.get("status") == "APPROVED"]
            return {"templates": templates, "total": len(templates)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("fetch templates failed")
        raise HTTPException(502, f"Falha Graph API: {e}")
