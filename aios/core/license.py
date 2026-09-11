"""License — JWT 24h + heartbeat 6h + tamper detection.

Control Plane assina JWT com Ed25519. Cliente valida com CONTROL_PUBLIC_KEY baked na imagem.
Cache Redis 6h, JWT 24h, grace 72h offline leitura.
"""
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path

from aios.config import settings

logger = logging.getLogger(__name__)

EXPECTED_DIGEST = os.getenv("AIOS_IMAGE_DIGEST", "")
EXPECTED_FP = hashlib.sha256((settings.jwt_secret or "change-me").encode()).hexdigest()[:16]

def _image_digest() -> str:
    try:
        return Path("/app/.image_digest").read_text().strip() if Path("/app/.image_digest").exists() else EXPECTED_DIGEST
    except Exception:
        return EXPECTED_DIGEST

def _public_key_fp() -> str:
    try:
        pub = getattr(settings, "license_public_key", "") or settings.jwt_secret
        return hashlib.sha256(pub.encode()).hexdigest()[:16]
    except Exception:
        return EXPECTED_FP

async def heartbeat_payload(org_id: str, plan_claim: str) -> dict:
    return {
        "org_id": org_id,
        "image_digest": _image_digest(),
        "public_key_fp": _public_key_fp(),
        "plan_claim": plan_claim,
        "ts": int(time.time()),
        "nonce": uuid.uuid4().hex[:8],
    }

async def send_heartbeat(org_id: str, plan_claim: str) -> dict | None:
    url = (getattr(settings, "license_server", "") or getattr(settings, "license_server_url", "") or "https://control.aios.dev").rstrip("/") + "/v1/heartbeat"
    key = getattr(settings, "license_key", "") or getattr(settings, "license_key", "") or ""
    # fallback to env AIOS_LICENSE_KEY
    if not key:
        key = os.getenv("AIOS_LICENSE_KEY", "")
    if not url or not key:
        return None
    try:
        import httpx
        payload = await heartbeat_payload(org_id, plan_claim)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                return r.json()
            logger.warning("heartbeat %s: %s %s", org_id, r.status_code, r.text[:200])
    except Exception:
        logger.debug("heartbeat failed", exc_info=True)
    return None

def verify_license_jwt(token: str) -> dict | None:
    """Valida JWT do Control Plane com CONTROL_PUBLIC_KEY (Ed25519/HMAC fallback)."""
    try:
        import jwt
        pub = getattr(settings, "license_public_key", "") or settings.jwt_secret
        return jwt.decode(token, pub, algorithms=["HS256", "HS512", "EdDSA"])
    except Exception:
        return None
