"""Audit log helper — records sensitive operations for security monitoring.
Supports SIEM webhook forwarding for Enterprise security monitoring.
"""

import hmac
import json
import logging
import os
from datetime import datetime, timezone

import httpx

from aios.config import settings
from aios.db.backend import DatabaseBackend
from aios.db.models import AuditLog

logger = logging.getLogger(__name__)


async def log_audit(
    db: DatabaseBackend,
    org_id: str,
    action: str,
    resource_type: str,
    user_id: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Record a security-sensitive operation in the audit log."""
    entry = AuditLog(
        org_id=org_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        ip_address=ip_address,
    )
    db.add(entry)
    await db.commit()
    
    # Forward to SIEM webhook if configured
    await _forward_to_siem(entry)


async def _forward_to_siem(entry: AuditLog) -> None:
    """Forward audit log entry to configured SIEM webhook."""
    webhook_url = getattr(settings, 'siem_webhook_url', '') or os.getenv('AIOS_SIEM_WEBHOOK_URL', '')
    webhook_secret = getattr(settings, 'siem_webhook_secret', '') or os.getenv('AIOS_SIEM_WEBHOOK_SECRET', '')
    
    if not webhook_url:
        return
    
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "org_id": entry.org_id,
        "user_id": entry.user_id,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "details": entry.details or {},
        "ip_address": entry.ip_address,
    }
    
    headers = {"Content-Type": "application/json"}
    if webhook_secret:
        sig = hmac.new(
            webhook_secret.encode(),
            json.dumps(payload, separators=(",", ":")).encode(),
            "sha256"
        ).hexdigest()
        headers["X-AIOS-Signature"] = sig
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json=payload, headers=headers)
    except Exception as e:
        logger.warning("SIEM webhook forward failed: %s", e)
