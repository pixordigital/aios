"""RFC 7807 Problem Details shape assertions for API errors.

Every API error returns:
    {"type": "about:blank", "title": str, "status": int, "detail": str, "instance": str}
"""

import pytest
from httpx import ASGITransport, AsyncClient

from aios.main import app


@pytest.mark.asyncio
async def test_404_route_miss():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["type"] == "about:blank"
    assert body["title"] == "Not found"
    assert body["status"] == 404
    assert body["detail"] in ("", "Not Found")  # starlette supplies the default message
    assert body["instance"] == "/api/nope"


@pytest.mark.asyncio
async def test_413_oversized_body():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/login",
            content=b"x" * (11 * 1024 * 1024),
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 413
    body = r.json()
    assert body["title"] == "Payload too large"
    assert body["detail"] == "Request too large"
    assert body["status"] == 413
    assert body["type"] == "about:blank"


@pytest.mark.asyncio
async def test_422_validation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # login with no body fields -> 422 validation error
        r = await client.post("/api/auth/login", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["type"] == "about:blank"
    assert body["title"] == "Validation failed"
    assert body["status"] == 422
    assert body["detail"]  # populated with field errors
    assert body["instance"]


