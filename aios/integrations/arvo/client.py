"""Cliente HTTP para o peer ARVO.

HMAC + timeout + backoff.
"""

import asyncio
import json
import uuid

import httpx

from aios.config import settings

from .auth import sign_request

PATH_PREFIX = "/api/v1/integrations/aios/v1"
_TIMEOUT = 5.0
_RETRIES = 3


def _headers(method: str, path: str, body: bytes | None = None) -> dict[str, str]:
    return sign_request(
        method, path, body, settings.arvo_service_key_id, settings.arvo_service_key
    )


async def _request_with_retry(method: str, path: str, **kw) -> httpx.Response:
    if not settings.arvo_base_url:
        raise RuntimeError("ARVO integration not configured (arvo_base_url)")
    headers_factory = kw.pop("headers_factory", None)
    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            request_kw = dict(kw)
            if headers_factory:
                request_kw["headers"] = headers_factory()
            async with httpx.AsyncClient(
                base_url=settings.arvo_base_url, timeout=_TIMEOUT
            ) as c:
                r = await c.request(method, path, **request_kw)
                # retry em 5xx e 429, não em 4xx (auth/idempotency)
                if r.status_code >= 500 or r.status_code == 429:
                    raise httpx.HTTPStatusError(
                        f"retryable {r.status_code}", request=r.request, response=r
                    )
                return r
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as e:
            last_exc = e
            if attempt < _RETRIES - 1:
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            raise
    raise last_exc  # type: ignore


async def ping() -> dict:
    """GET /health do peer. Usa http:// pois sslip https 503 (GAPS §6). Retry 3×."""
    path = f"{PATH_PREFIX}/health"
    r = await _request_with_retry("GET", path, headers=_headers("GET", path))
    r.raise_for_status()
    return r.json()


async def send_event(
    event_type: str, payload: dict, idempotency_key: str | None = None
) -> dict:
    """POST /events idempotente. Retry 3× em 5xx/timeout."""
    body_dict = {"type": event_type, "payload": payload}
    body = json.dumps(body_dict, separators=(",", ":")).encode()
    path = f"{PATH_PREFIX}/events"
    key = idempotency_key or str(uuid.uuid4())

    def headers_factory():
        headers = _headers("POST", path, body)
        headers["Idempotency-Key"] = key
        headers["Content-Type"] = "application/json"
        return headers

    r = await _request_with_retry(
        "POST", path, content=body, headers_factory=headers_factory
    )
    r.raise_for_status()
    return r.json()
