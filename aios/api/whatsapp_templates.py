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

# cache 1h por (waba, token hash)
_cache: dict[str, tuple[float, dict]] = {}
import time, hashlib
def _ckey(waba: str, token: str) -> str:
    return hashlib.sha256(f"{waba}:{token[:8]}".encode()).hexdigest()[:16]

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
    ck = _ckey(waba, token)
    now = time.time()
    if ck in _cache and now - _cache[ck][0] < 3600:
        # cache hit, mas revalida se fallback anterior falhou
        cached = _cache[ck][1]
        if cached.get("total", 0) > 0:
            return cached
    url = f"https://graph.facebook.com/v20.0/{waba}/message_templates"
    params = {"access_token": token, "fields": "name,language,status,category", "limit": 50}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            data = r.json()
            if r.status_code != 200:
                # fallback: retorna cache mesmo expirado se tiver
                if ck in _cache:
                    logger.warning("Graph API %s, returning stale cache", r.status_code)
                    return _cache[ck][1]
                raise HTTPException(r.status_code, detail=data.get("error", {}).get("message", str(data)))
            templates = [t for t in data.get("data", []) if t.get("status") == "APPROVED"]
            resp = {"templates": templates, "total": len(templates)}
            _cache[ck] = (now, resp)
            return resp
    except HTTPException:
        raise
    except Exception as e:
        if ck in _cache:
            logger.warning("Graph exception, stale cache: %s", e)
            return _cache[ck][1]
        logger.exception("fetch templates failed")
        raise HTTPException(502, f"Falha Graph API: {e}")
