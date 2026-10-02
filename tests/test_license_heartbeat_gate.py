"""The license heartbeat mutates license_status/tamper_score from an
unauthenticated org_id in the body. Without a gate, two anonymous curl calls
suspend then ban any tenant. It must require the fleet master key.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from aios.api.admin_api import require_admin_key
from aios.api.license import heartbeat


@pytest.mark.asyncio
async def test_heartbeat_requires_admin_key() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_admin_key(authorization=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_heartbeat_rejects_wrong_key(monkeypatch) -> None:
    monkeypatch.setattr("aios.api.admin_api.settings.admin_master_key", "real-key", raising=False)
    with pytest.raises(HTTPException) as exc:
        await require_admin_key(authorization="Bearer wrong-key")
    assert exc.value.status_code == 403


def test_heartbeat_route_is_gated() -> None:
    """The Depends must stay on the route: Banner semantically, enforced
    structurally. If someone removes the gate, this fails."""
    import inspect

    sig = inspect.signature(heartbeat)
    src = inspect.getsource(heartbeat)
    assert "require_admin_key" in src, "heartbeat lost its admin gate"
    assert any(
        p.default is not inspect.Parameter.empty and "require_admin_key" in str(p.default)
        for p in sig.parameters.values()
    ), "heartbeat Depends(require_admin_key) missing"
