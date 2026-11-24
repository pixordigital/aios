"""Focused publish-back coverage for process_commitment_at_risk failure paths."""

from types import SimpleNamespace

import pytest

from aios.config import settings
from aios.tasks.jobs import process_commitment_at_risk

AMOUNTS = {
    "exposure_amount": "1375.50",
    "verified_amount": "900.00",
    "recovery_amount": "475.50",
    "currency": "BRL",
}


class FakeResult:
    def __init__(self, agent):
        self.agent = agent

    def scalars(self):
        return self

    def first(self):
        return self.agent


class FakeSession:
    def __init__(self, agent):
        self.agent = agent
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, *args, **kwargs):
        return FakeResult(self.agent)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1


def _patch_common(monkeypatch, agent, captured, on_enqueue=None):
    sessions = []

    def session_factory():
        session = FakeSession(agent)
        sessions.append(session)
        return session

    async def fake_enqueue(event_type, payload, **kwargs):
        captured.append((event_type, payload, kwargs))
        if on_enqueue is not None:
            on_enqueue()
        return "outbox-id"

    monkeypatch.setattr("aios.db.engine.async_session", session_factory)
    monkeypatch.setattr("aios.integrations.arvo.publisher.enqueue_outbox", fake_enqueue)
    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_base_url", "http://peer.test")
    return sessions


def _failed_key(trace_id, reason):
    base = f"agent.action.completed:{str(trace_id)[:80]}"[:128]
    return f"{base}:failed:{reason}"[:128]


def _assert_failed_event(captured, payload, trace_id, reason):
    assert len(captured) == 1
    event_type, event_payload, kwargs = captured[0]
    assert event_type == "agent.action.completed"
    assert event_payload["finding_id"] == payload["finding_id"]
    assert event_payload["org_id"] == payload["org_id"]
    assert event_payload["status"] == "failed"
    assert event_payload["reason"] == reason
    assert event_payload["output"]
    amount_fields = ("exposure_amount", "verified_amount", "recovery_amount", "currency")
    assert event_payload["source_amounts"] == {
        field: value for field, value in payload.items() if field in amount_fields
    }
    for field in amount_fields:
        assert field not in event_payload
    assert kwargs["business_trace_id"] == trace_id
    assert kwargs["idempotency_key"] == _failed_key(trace_id, reason)


async def test_no_agent_publishes_failed_event_with_amounts(monkeypatch):
    captured = []
    sessions = _patch_common(monkeypatch, None, captured)
    payload = {
        "finding_id": "finding-no-agent",
        "org_id": "org-no-agent",
        "business_trace_id": "trace-no-agent",
        **AMOUNTS,
    }

    result = await process_commitment_at_risk(None, payload, "trace-no-agent")

    assert result == {"skipped": True, "reason": "no active agent"}
    assert sessions[0].commits == 0
    _assert_failed_event(captured, payload, "trace-no-agent", "no active agent")
    _, event_payload, _ = captured[0]
    assert event_payload["source_amounts"]["verified_amount"] == AMOUNTS["verified_amount"]
    assert event_payload["source_amounts"]["recovery_amount"] == AMOUNTS["recovery_amount"]


async def test_no_agent_enqueue_failure_reraises(monkeypatch):
    class OutboxBoom(RuntimeError):
        pass

    boom = OutboxBoom("outbox down")
    _patch_common(monkeypatch, None, [])

    async def raising_enqueue(*args, **kwargs):
        raise boom

    monkeypatch.setattr("aios.integrations.arvo.publisher.enqueue_outbox", raising_enqueue)
    payload = {
        "finding_id": "finding-no-agent-outbox",
        "org_id": "org-no-agent-outbox",
        "business_trace_id": "trace-no-agent-outbox",
    }

    with pytest.raises(OutboxBoom) as exc_info:
        await process_commitment_at_risk(None, payload, "trace-no-agent-outbox")

    assert exc_info.value is boom


async def test_agent_exception_publishes_failed_event_then_reraises(monkeypatch):
    class AgentBoom(RuntimeError):
        pass

    boom = AgentBoom("agent down")
    captured = []
    sessions = _patch_common(
        monkeypatch,
        SimpleNamespace(id="agent-boom", governance_config={}),
        captured,
        on_enqueue=lambda: setattr(boom, "published_before_raise", True),
    )

    class FailingRuntime:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv_id, msg):
            raise boom

    monkeypatch.setattr("aios.core.agent.AgentRuntime", FailingRuntime)
    payload = {
        "finding_id": "finding-boom",
        "org_id": "org-boom",
        "business_trace_id": "trace-boom",
        "exposure_amount": "42.00",
        "currency": "USD",
    }

    with pytest.raises(AgentBoom) as exc_info:
        await process_commitment_at_risk(None, payload, "trace-boom")

    assert exc_info.value is boom
    assert boom.published_before_raise is True
    assert sessions[0].commits == 0
    _assert_failed_event(captured, payload, "trace-boom", "agent execution failed")
    _, event_payload, _ = captured[0]
    assert "verified_amount" not in event_payload["source_amounts"]
    assert "recovery_amount" not in event_payload["source_amounts"]


async def test_agent_exception_enqueue_failure_reraises_enqueue_exception(monkeypatch):
    class AgentBoom(RuntimeError):
        pass

    class OutboxBoom(RuntimeError):
        pass

    agent_boom = AgentBoom("agent down")
    outbox_boom = OutboxBoom("outbox down")
    _patch_common(
        monkeypatch,
        SimpleNamespace(id="agent-boom-outbox", governance_config={}),
        [],
    )

    async def raising_enqueue(*args, **kwargs):
        raise outbox_boom

    monkeypatch.setattr("aios.integrations.arvo.publisher.enqueue_outbox", raising_enqueue)

    class FailingRuntime:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv_id, msg):
            raise agent_boom

    monkeypatch.setattr("aios.core.agent.AgentRuntime", FailingRuntime)
    payload = {
        "finding_id": "finding-boom-outbox",
        "org_id": "org-boom-outbox",
        "business_trace_id": "trace-boom-outbox",
    }

    with pytest.raises(OutboxBoom) as exc_info:
        await process_commitment_at_risk(None, payload, "trace-boom-outbox")

    assert exc_info.value is outbox_boom


async def test_success_publishes_exactly_one_non_failed_event(monkeypatch):
    captured = []
    sessions = _patch_common(
        monkeypatch, SimpleNamespace(id="agent-ok", governance_config={}), captured
    )

    class WorkingRuntime:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv_id, msg):
            return "action plan"

    monkeypatch.setattr("aios.core.agent.AgentRuntime", WorkingRuntime)
    payload = {
        "finding_id": "finding-ok",
        "org_id": "org-ok",
        "business_trace_id": "trace-ok",
        "exposure_amount": "10.00",
        "currency": "EUR",
    }

    result = await process_commitment_at_risk(None, payload, "trace-ok")

    assert result == {
        "finding_id": "finding-ok",
        "business_trace_id": "trace-ok",
        "output": "action plan",
    }
    assert sessions[-1].commits == 1
    assert len(captured) == 1
    event_type, event_payload, kwargs = captured[0]
    assert event_type == "agent.action.completed"
    assert event_payload == {
        "finding_id": "finding-ok",
        "org_id": "org-ok",
        "output": "action plan",
        "agent_id": "agent-ok",
        "exposure_amount": "10.00",
        "currency": "EUR",
    }
    assert "status" not in event_payload
    assert "reason" not in event_payload
    assert kwargs["business_trace_id"] == "trace-ok"
    assert kwargs["idempotency_key"] == "agent.action.completed:trace-ok"


async def test_failed_then_success_same_trace_publish_distinct_events(monkeypatch):
    captured = []
    _patch_common(monkeypatch, None, captured)

    current_agent = {"value": None}

    def switching_session():
        return FakeSession(current_agent["value"])

    monkeypatch.setattr("aios.db.engine.async_session", switching_session)

    class WorkingRuntime:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv_id, msg):
            return "recovered plan"

    monkeypatch.setattr("aios.core.agent.AgentRuntime", WorkingRuntime)
    payload = {
        "finding_id": "finding-retry",
        "org_id": "org-retry",
        "business_trace_id": "trace-retry",
        "exposure_amount": "99.00",
        "currency": "BRL",
    }

    first = await process_commitment_at_risk(None, payload, "trace-retry")
    current_agent["value"] = SimpleNamespace(id="agent-retry", governance_config={})
    second = await process_commitment_at_risk(None, payload, "trace-retry")

    assert first == {"skipped": True, "reason": "no active agent"}
    assert second == {
        "finding_id": "finding-retry",
        "business_trace_id": "trace-retry",
        "output": "recovered plan",
    }
    assert len(captured) == 2
    (_, failed_payload, failed_kwargs), (_, success_payload, success_kwargs) = captured
    assert failed_payload["status"] == "failed"
    assert "status" not in success_payload
    assert failed_kwargs["idempotency_key"] == _failed_key("trace-retry", "no active agent")
    assert success_kwargs["idempotency_key"] == "agent.action.completed:trace-retry"
    assert failed_kwargs["idempotency_key"] != success_kwargs["idempotency_key"]


async def test_max_64_trace_failed_key_does_not_collide_with_success(monkeypatch):
    from aios.integrations.arvo.events import ArvoEnvelope

    trace = "trace-" + "x" * 58
    assert len(trace) == 64
    ArvoEnvelope(type="agent.action.completed", payload={}, business_trace_id=trace)

    captured = []
    _patch_common(monkeypatch, None, captured)
    payload = {
        "finding_id": "finding-max-trace",
        "org_id": "org-max-trace",
        "business_trace_id": trace,
    }

    result = await process_commitment_at_risk(None, payload, trace)

    assert result == {"skipped": True, "reason": "no active agent"}
    assert len(captured) == 1
    failed_key = captured[0][2]["idempotency_key"]
    success_key = f"agent.action.completed:{trace}"[:128]
    assert ":failed:" in failed_key
    assert failed_key != success_key
    assert failed_key == _failed_key(trace, "no active agent")
    assert len(failed_key) <= 128
