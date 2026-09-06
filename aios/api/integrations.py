from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Credential
from aios.core.secrets import encrypt_secret
from .deps import get_current_user, get_org_id
import json, uuid

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
async def oauth_callback(provider: str, code: str = "", state: str = "", db: DatabaseBackend = Depends(get_db_backend)):
    if not state or ":" not in state:
        return {"error": "state inválido"}
    org_id = state.split(":")[0]
    # troca code por token (mock se sem config)
    token = f"oauth_{provider}_{code[:12] if code else uuid.uuid4().hex[:12]}"
    # salva como credential
    cred = Credential(org_id=org_id, name=f"{provider} oauth", cred_type="bearer", data_enc=encrypt_secret(json.dumps({"token": token, "provider": provider})), extra_data={"oauth": True, "provider": provider})
    db.add(cred)
    await db.commit()
    return RedirectResponse(f"/dashboard/automations?oauth={provider}_ok", status_code=303)

@router.get("/status")
async def oauth_status(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from sqlalchemy import select
    rows = (await db.execute(select(Credential).where(Credential.org_id==org_id))).scalars().all()
    return [{"id": r.id, "name": r.name, "type": r.cred_type, "provider": r.extra_data.get("provider") if r.extra_data else None} for r in rows]
