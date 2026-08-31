from fastapi import APIRouter, Depends, HTTPException

from aios.api.deps import get_current_user, get_org_id
from aios.core.secrets import set_org_secret
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization

router = APIRouter(prefix="/api/org/secrets", tags=["secrets"])

_ALLOWED_KEYS = {
    "openai_api_key",
    "anthropic_api_key",
    "openrouter_api_key",
    "s3_access_key",
    "s3_secret_key",
}


@router.get("")
async def list_secrets(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404)
    enc = (org.extra_data or {}).get("_secrets_enc", {})
    return {"keys": list(enc.keys()), "masked": {k: "***" for k in enc.keys()}}


@router.put("/{key}")
async def put_secret(
    key: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    if key not in _ALLOWED_KEYS:
        raise HTTPException(400, detail=f"key not allowed: {key}")
    value = body.get("value", "")
    if not value or len(value) < 4:
        raise HTTPException(400, detail="value too short")
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404)
    set_org_secret(org, key, value)
    await db.commit()
    return {"ok": True, "key": key}


@router.delete("/{key}")
async def delete_secret(
    key: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404)
    data = dict(org.extra_data or {})
    enc = dict(data.get("_secrets_enc") or {})
    if key in enc:
        del enc[key]
        data["_secrets_enc"] = enc
        org.extra_data = data
        await db.commit()
    return {"ok": True}
