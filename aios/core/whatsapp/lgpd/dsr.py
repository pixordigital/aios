async def handle_access(phone_hash: str) -> dict:
    return {"phone_hash": phone_hash, "data": [], "note": "Phase B: query org.extra_data.lgpd_consent + messages via Evolution (15d SLA)"}
async def handle_delete(phone_hash: str) -> dict:
    return {"phone_hash": phone_hash, "purged": True, "note": "Phase B: purge + Evolution delete webhook"}
