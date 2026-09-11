"""Control Plane — POST /v1/heartbeat com auto-suspend + blacklist."""

import hashlib
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import Organization

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["license"])

EXPECTED_DIGEST = ""  # set via env AIOS_IMAGE_DIGEST no Control Plane build
EXPECTED_FP = hashlib.sha256((settings.jwt_secret or "change-me").encode()).hexdigest()[:16]

@router.post("/heartbeat")
async def heartbeat(request: Request):
    body = await request.json()
    org_id = (body.get("org_id") or "").strip()
    plan_claim = (body.get("plan_claim") or "").strip()
    digest = (body.get("image_digest") or "").strip()
    fp = (body.get("public_key_fp") or "").strip()
    if not org_id:
        return {"status": "error", "detail": "org_id required"}
    async with db_session() as db:
        org = await db.get(Organization, org_id)
        if not org:
            return {"status": "not_found"}
        real_plan = (getattr(org, "extra_data", {}) or {}).get("plan", "free") if hasattr(org, "extra_data") else "free"
        # legacy: also check license_status col if exists
        status = getattr(org, "license_status", "active") or "active"
        tamper = []
        if EXPECTED_DIGEST and digest and digest != EXPECTED_DIGEST:
            tamper.append("image_digest")
        if fp and fp != EXPECTED_FP:
            tamper.append("public_key")
        if plan_claim and plan_claim != real_plan:
            tamper.append("plan_claim")
        if tamper:
            org.tamper_score = (getattr(org, "tamper_score", 0) or 0) + len(tamper)
            logger.warning("tamper %s %s score=%s", org_id, tamper, org.tamper_score)
            # notify
            try:
                import httpx
                hook = getattr(settings, "slack_webhook_url", "") or ""
                if hook:
                    async with httpx.AsyncClient(timeout=5) as c:
                        await c.post(hook, json={"text": f"🚨 Tamper {org.name} ({org_id}) — {tamper} score={org.tamper_score}"})
            except Exception:
                pass
            if org.tamper_score >= 2 or "plan_claim" in tamper:
                org.license_status = "suspended"
                org.suspended_at = datetime.now(timezone.utc).replace(tzinfo=None)
                logger.warning("auto_suspend %s", org_id)
            if org.tamper_score >= 5:
                org.license_status = "banned"
                org.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await db.flush()
                # blacklist — separate commit to not rollback tamper_score
                try:
                    from sqlalchemy import text
                    import uuid as _uuid
                    email = ""
                    from aios.db.models import User
                    u = (await db.execute(select(User).where(User.org_id == org_id).limit(1))).scalar_one_or_none()
                    if u:
                        email = (u.email or "").lower()
                    domain = email.split("@")[1] if "@" in email else None
                    await db.execute(text(
                        "INSERT INTO blacklist (id, email, domain, reason, evidence, expires_at) "
                        "VALUES (:id, :email, :domain, :reason, :evidence::jsonb, now() + interval '5 years') "
                        "ON CONFLICT DO NOTHING"
                    ), {"id": str(_uuid.uuid4()), "email": email or None, "domain": domain, "reason": f"tamper reincidente: {tamper}", "evidence": __import__("json").dumps(body)})
                    await db.commit()
                except Exception:
                    logger.exception("blacklist insert failed")
                    await db.rollback()
                    org.license_status = "banned"
                    org.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await db.commit()
            else:
                await db.commit()
            status = getattr(org, "license_status", "suspended")
        # issue JWT 24h
        try:
            import jwt
            exp = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=24)
            token = jwt.encode({"org": org_id, "plan": real_plan, "status": status, "exp": exp, "iat": datetime.now(timezone.utc).replace(tzinfo=None)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        except Exception:
            token = ""
        return {"status": status, "plan": real_plan, "jwt": token, "tamper": tamper}
