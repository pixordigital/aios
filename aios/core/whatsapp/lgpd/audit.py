import logging, json
from datetime import datetime, timezone
from aios.core.whatsapp.kms.envelope import encrypt
logger = logging.getLogger(__name__)
async def log_action(action: str, resource: str, user_id: str = "system"):
    try:
        payload = json.dumps({"action": action, "resource": resource, "user": user_id, "at": datetime.now(timezone.utc).isoformat()})
        token = encrypt(payload)
        logger.info("LGPD_AUDIT %s", token[:40])
        # TODO: persist to lgpd_audit_log WORM (MinIO/SeaweedFS) Phase B
    except Exception as e:
        logger.warning("audit fail %s", e)
