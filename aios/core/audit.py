"""Audit log helper — records sensitive operations for security monitoring."""

from aios.db.backend import DatabaseBackend
from aios.db.models import AuditLog


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
