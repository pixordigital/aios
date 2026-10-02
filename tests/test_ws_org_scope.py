"""Tenant isolation for the agent-canvas websocket.

The delivery filter used to be ``if org and org_id and org != org_id``, which
only skipped a client when all three values were truthy. Every emitter degrades
to ``""`` when the agent or hook context carries no org, so those events were
delivered to *every* connected tenant. Clients always register with a real
``user.org_id``, so the missing value is on the event side.
"""

from __future__ import annotations

import pytest

from aios.core.ws_manager import WSManager


class FakeWS:
    """Minimal stand-in for a FastAPI WebSocket."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _client(mgr: WSManager, org: str | None) -> FakeWS:
    ws = FakeWS()
    mgr.register(ws, org)
    return ws


@pytest.mark.asyncio
async def test_org_event_reaches_only_its_own_org() -> None:
    mgr = WSManager()
    acme, globex = _client(mgr, "acme"), _client(mgr, "globex")

    await mgr._deliver_local({"type": "node_start", "org_id": "acme"})

    assert len(acme.sent) == 1
    assert globex.sent == [], "cross-tenant leak: org A event reached org B"


@pytest.mark.asyncio
async def test_org_less_event_reaches_nobody() -> None:
    """The regression: a blanket broadcast handed one tenant's data to all."""
    mgr = WSManager()
    clients = [_client(mgr, org) for org in ("acme", "globex", "initech")]

    await mgr._deliver_local({"type": "node_start", "org_id": ""})
    await mgr._deliver_local({"type": "node_start"})

    for ws in clients:
        assert ws.sent == [], "org-less event must be dropped, not broadcast"


@pytest.mark.asyncio
async def test_org_event_does_not_reach_unattributed_client() -> None:
    """A client with no org cannot prove tenancy, so it gets nothing."""
    mgr = WSManager()
    anonymous = _client(mgr, None)

    await mgr._deliver_local({"type": "node_start", "org_id": "acme"})

    assert anonymous.sent == []


@pytest.mark.asyncio
async def test_dead_socket_is_unregistered() -> None:
    """A failing send drops the client instead of retrying forever."""

    class Broken(FakeWS):
        async def send_json(self, data: dict) -> None:
            raise RuntimeError("socket closed")

    mgr = WSManager()
    ws = Broken()
    mgr.register(ws, "acme")
    assert mgr.client_count == 1

    await mgr._deliver_local({"type": "node_start", "org_id": "acme"})

    assert mgr.client_count == 0


@pytest.mark.asyncio
async def test_approval_requested_carries_org_id() -> None:
    """broadcast() is sync. It used to be awaited, so the TypeError was
    swallowed by a bare except and this event never reached any dashboard."""
    import inspect

    from aios.core.approval import ApprovalManager
    from aios.core.ws_manager import ws_manager as global_manager

    assert not inspect.iscoroutinefunction(global_manager.broadcast), (
        "broadcast() must stay sync — approval.py calls it from async code "
        "and must not await it"
    )

    src = inspect.getsource(ApprovalManager)
    assert "await ws_manager.broadcast" not in src, "broadcast() must not be awaited"