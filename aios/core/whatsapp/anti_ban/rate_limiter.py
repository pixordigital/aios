import time
_buckets: dict[str,float] = {}
_last: dict[str,float] = {}
def allow(instance: str, per_minute: int = 20) -> bool:
    now = time.time()
    last = _last.get(instance, now)
    tokens = _buckets.get(instance, per_minute)
    tokens = min(per_minute, tokens + (now-last)*(per_minute/60))
    if tokens >= 1:
        _buckets[instance]=tokens-1; _last[instance]=now; return True
    _buckets[instance]=tokens; _last[instance]=now; return False
def record_429(instance: str):
    _buckets[instance]=max(0, _buckets.get(instance, 5)-3)
