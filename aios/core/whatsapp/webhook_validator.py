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
        except (ValueError, TypeError):
            # Unparseable timestamp means the age check could not be made.
            # Previously a bare `except: pass` swallowed it and the request was
            # treated as fresh, so a garbage ts skipped the 300s replay window.
            return {"ok": False, "reason": "invalid timestamp"}
    # hmac
    # This was `if secret and sig:`, which meant a request with NO signature
    # header skipped verification entirely and returned ok=True -- any
    # unauthenticated caller could drive the LGPD-consent write below and pick
    # the target org from the instance name in the URL. Both a missing secret
    # and a missing signature must reject.
    if not secret:
        return {"ok": False, "reason": "webhook secret not configured"}
    if not sig:
        return {"ok": False, "reason": "missing signature"}
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
