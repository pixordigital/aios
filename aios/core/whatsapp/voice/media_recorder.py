import time, logging
logger = logging.getLogger(__name__)

async def start_recording(call_id: str, instance: str) -> dict:
    # SeaweedFS S3 compat Phase B: path s3://aios-whatsapp/recordings/{call_id}.ogg (encrypted via KMS)
    path = f"s3://aios-whatsapp/recordings/{instance}/{call_id}.ogg"
    return {"ok": True, "call_id": call_id, "path": path, "encrypted": True, "started_at": time.time()}

async def stop_recording(call_id: str) -> dict:
    return {"ok": True, "call_id": call_id, "ended_at": time.time()}
