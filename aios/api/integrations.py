from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Credential
from .deps import get_current_user, get_org_id
import uuid

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

OAUTH_PROVIDERS = {
    "hubspot": {"auth_url": "https://app.hubspot.com/oauth/authorize", "scopes": "crm.objects.contacts.write crm.objects.deals.write"},
    "pipedrive": {"auth_url": "https://oauth.pipedrive.com/oauth/authorize", "scopes": ""},
}

@router.get("/{provider}/auth")
async def oauth_start(provider: str, request: Request, org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    if provider not in OAUTH_PROVIDERS:
        from fastapi import HTTPException
        raise HTTPException(404, "provider desconhecido")
    # gera state com org_id
    state = f"{org_id}:{uuid.uuid4().hex[:8]}"
    # se credenciais OAuth não configuradas, retorna instrução
    from aios.config import settings
    client_id = getattr(settings, f"{provider}_client_id", "") or ""
    if not client_id:
        return {"auth_url": None, "message": f"Configure {provider.upper()}_CLIENT_ID no .env para OAuth real. Use credential manual enquanto isso: POST /api/automations/credentials {{name, cred_type: bearer, data: {{token}}}}"}
    # redirect real
    redir = f"{settings.app_url}/api/integrations/{provider}/callback"
    url = f"{OAUTH_PROVIDERS[provider]['auth_url']}?client_id={client_id}&redirect_uri={redir}&state={state}&scope={OAUTH_PROVIDERS[provider]['scopes']}"
    return RedirectResponse(url)

@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str = "",
    state: str = "",
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    # The provider redirects through the user's browser, so the dashboard
    # cookie is present and these deps resolve. Without them anyone could mint
    # credentials into any org by guessing its id in `state`.
    if not state or ":" not in state:
        return {"error": "state inválido"}
    state_org, _, nonce = state.partition(":")
    if not nonce or state_org != org_id:
        return {"error": "state inválido"}
    # No provider OAuth credentials exist in settings (no HUBSPOT_/PIPEDRIVE_
    # client id/secret), so a real code exchange is impossible. The old code
    # minted a mock token here and stored it as a working credential — a row
    # that looked connected and failed at first use. Refuse instead; manual
    # credential creation remains available.
    return {"error": "OAuth não configurado: crie a credential manualmente em /dashboard/automations"}

@router.get("/status")
async def oauth_status(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from sqlalchemy import select
    rows = (await db.execute(select(Credential).where(Credential.org_id==org_id))).scalars().all()
    return [{"id": r.id, "name": r.name, "type": r.cred_type, "provider": r.extra_data.get("provider") if r.extra_data else None} for r in rows]
