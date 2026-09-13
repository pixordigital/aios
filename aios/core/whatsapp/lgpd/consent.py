import hashlib
from datetime import datetime, timezone
from sqlalchemy import select
from aios.db.engine import async_session
from aios.db.models import Organization

# Minimal consent store in org.extra_data.lgpd_consent {hash(phone): {purpose: bool}}
def _hash(phone: str) -> str: return hashlib.sha256(phone.encode()).hexdigest()[:16]

async def record_consent(phone: str, purpose: str, granted: bool, org_id: str):
    h = _hash(phone)
    async with async_session() as s:
        org = await s.get(Organization, org_id)
        if not org: return
        extra = dict(org.extra_data or {})
        lgpd = extra.get("lgpd_consent", {})
        lgpd.setdefault(h, {})[purpose] = {"granted": granted, "at": datetime.now(timezone.utc).isoformat()}
        extra["lgpd_consent"] = lgpd
        org.extra_data = extra
        await s.commit()

async def check_consent(phone: str, purpose: str, org_id: str) -> bool:
    h = _hash(phone)
    async with async_session() as s:
        org = await s.get(Organization, org_id)
        if not org: return False
        return bool((org.extra_data or {}).get("lgpd_consent", {}).get(h, {}).get(purpose, {}).get("granted"))
