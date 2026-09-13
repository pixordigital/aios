import hmac, hashlib, time
import redis.asyncio as aioredis

async def validate(request, secret: str, redis_url: str | None = None) -> dict:
    body = await request.body()
    sig = request.headers.get("x-hub-signature-256") or request.headers.get("x-evolution-signature") or ""
    ts = request.headers.get("x-timestamp") or request.headers.get("x-evolution-timestamp") or ""
    # timestamp window 300s
    if ts:
        try:
            if abs(time.time() - int(ts)) > 300:
                return {"ok": False, "reason": "timestamp expired"}
        except: pass
    # hmac
    if secret and sig:
        exp = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(exp, sig):
            return {"ok": False, "reason": "invalid signature"}
    # nonce dedup via redis
    nonce = request.headers.get("x-nonce") or request.headers.get("x-idempotency-key")
    if nonce and redis_url:
        try:
            r = aioredis.from_url(redis_url)
            ok = await r.set(f"webhook_nonce:{nonce}", "1", nx=True, ex=300)
            if not ok:
                return {"ok": False, "reason": "duplicate nonce"}
        except Exception:
            pass
    return {"ok": True}
