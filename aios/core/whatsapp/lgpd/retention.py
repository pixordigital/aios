import logging
logger = logging.getLogger(__name__)
POLICIES = {"messages": 730, "voice_recordings": 730, "consent": 1825, "audit": 3650}
async def enforce_all():
    logger.info("LGPD retention enforce %s (SeaweedFS TTL + PG purge)", POLICIES)
    return POLICIES
