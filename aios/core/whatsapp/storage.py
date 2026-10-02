import httpx
from aios.core.whatsapp.config import settings
async def s3_put(key: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    url = f"{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket}/{key}"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.put(url, content=data, headers={"Content-Type": content_type})
            return {"ok": r.status_code in (200,201), "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}
