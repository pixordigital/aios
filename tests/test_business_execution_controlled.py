from __future__ import annotations

from types import SimpleNamespace

import pytest

from aios.core.business_execution import (
    ExecutionDenied,
    ExecutionRegistry,
    InMemoryIdempotencyStore,
)
from aios.core.business_execution_service import (
    build_controlled_business_registry,
    execute_controlled_business_action,
    get_business_idempotency_store,
    is_business_idempotency_durable,
)


class _CountingAdapter:
    name = "email_resend"
    approved = True

    def __init__(self):
        self.calls = 0

    def execute(self, *, action: str, payload: dict, idempotency_key: str):
        from aios.core.business_execution import ExecutionResult

        self.calls += 1
        return ExecutionResult(
            ok=True,
            adapter=self.name,
            action=action,
            idempotency_key=idempotency_key,
            status="ok",
            detail="sent",
            data={"count": self.calls},
        )


def test_registry_duplicate_claim_returns_duplicate_not_reexecute():
    adapter = _CountingAdapter()
    store = InMemoryIdempotencyStore()
    registry = ExecutionRegistry(audit_callback=lambda e: None, idempotency_store=store)
    registry.register(adapter)

    first = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "a@b.test", "org_id": "org1"},
        idempotency_key="idem-dup",
    )
    second = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "a@b.test", "org_id": "org1"},
        idempotency_key="idem-dup",
    )

    assert first.status == "ok"
    assert second.status == "duplicate"
    assert second.ok is True
    assert adapter.calls == 1


def test_controlled_registry_fail_closed_without_explicit_approval():
    registry = build_controlled_business_registry(
        settings=SimpleNamespace(), idempotency_store=InMemoryIdempotencyStore()
    )
    with pytest.raises(ExecutionDenied, match="not approved|not configured"):
        registry.execute(
            adapter="email_resend",
            action="send_email",
            payload={
                "to": "u@example.test",
                "subject": "s",
                "body": "b",
                "org_id": "org1",
                "approved": True,
            },
            idempotency_key="idem-fail-closed",
        )


def test_controlled_service_requires_idempotency_for_side_effect():
    settings = SimpleNamespace(
        execution_approved_adapters="email_resend",
        resend_api_key="rk-test",
        resend_from_email="sandbox@aios.local",
        business_idempotency_required=False,
    )
    with pytest.raises(ExecutionDenied, match="idempotency_key required"):
        execute_controlled_business_action(
            adapter="email_resend",
            action="send_email",
            payload={"to": "u@example.test", "subject": "s", "body": "b", "org_id": "org1"},
            idempotency_key="",
            settings=settings,
            idempotency_store=InMemoryIdempotencyStore(),
        )


def test_controlled_service_executes_only_with_explicit_approval_and_config():
    sent = []

    def sender(**kw):
        sent.append(kw)
        return {"id": "msg-1"}

    settings = SimpleNamespace(
        execution_approved_adapters="email_resend",
        resend_api_key="rk-test",
        resend_from_email="sandbox@aios.local",
        business_idempotency_required=False,
    )
    registry = build_controlled_business_registry(
        settings=settings,
        idempotency_store=InMemoryIdempotencyStore(),
    )
    adapter = registry.get("email_resend")
    assert adapter is not None
    adapter.sender = sender

    result = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "u@example.test", "subject": "s", "body": "b", "org_id": "org1"},
        idempotency_key="idem-ok-controlled",
    )
    assert result.ok is True
    assert result.status == "ok"
    assert len(sent) == 1


def test_process_local_idempotency_store_singleton(monkeypatch, tmp_path):
    import aios.core.business_execution_service as svc_mod

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'idem.db'}"
    monkeypatch.setattr(svc_mod, "_IDEMPOTENCY_STORE", None)
    monkeypatch.setattr(svc_mod, "_IDEMPOTENCY_STORE_KIND", "unknown")
    store = svc_mod.get_business_idempotency_store(
        settings=SimpleNamespace(database_url=db_url, business_idempotency_required=True)
    )
    assert svc_mod.get_business_idempotency_store(
        settings=SimpleNamespace(database_url=db_url, business_idempotency_required=True)
    ) is store
    assert is_business_idempotency_durable(store) is True


def test_db_idempotency_store_atomic_claim_and_replay(tmp_path):
    from aios.core.business_idempotency import DBIdempotencyStore

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'claim.db'}"
    store = DBIdempotencyStore.from_settings(SimpleNamespace(database_url=db_url))
    assert store is not None
    assert store.claim("k1", org_id="org1", adapter="email_resend", action="send_email") is True
    assert store.claim("k1", org_id="org1", adapter="email_resend", action="send_email") is False
    rec = store.get("k1", org_id="org1")
    assert rec is not None and rec.status == "processing"
    store.complete("k1", org_id="org1", result={"ok": True, "status": "ok", "adapter": "email_resend", "action": "send_email", "idempotency_key": "k1", "detail": "sent", "data": {}})
    rec2 = store.get("k1", org_id="org1")
    assert rec2 is not None and rec2.status == "completed"


def test_registry_durable_duplicate_replays_stored_result(tmp_path):
    from aios.core.business_idempotency import DBIdempotencyStore

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'replay.db'}"
    store = DBIdempotencyStore.from_settings(SimpleNamespace(database_url=db_url))
    adapter = _CountingAdapter()
    registry = ExecutionRegistry(audit_callback=lambda e: None, idempotency_store=store)
    registry.register(adapter)

    first = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "a@b.test", "org_id": "org1"},
        idempotency_key="idem-durable",
    )
    second = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "a@b.test", "org_id": "org1"},
        idempotency_key="idem-durable",
    )

    assert first.status == "ok"
    assert second.status == "ok"  # replayed stored result
    assert second.data.get("duplicate") is True
    assert second.data.get("durable") is True
    assert adapter.calls == 1


def test_db_store_survives_restart(tmp_path):
    from aios.core.business_idempotency import DBIdempotencyStore

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'restart.db'}"
    s1 = DBIdempotencyStore.from_settings(SimpleNamespace(database_url=db_url))
    assert s1 is not None and s1.claim("k-restart", org_id="org1") is True

    s2 = DBIdempotencyStore.from_settings(SimpleNamespace(database_url=db_url))
    assert s2 is not None
    assert s2.claim("k-restart", org_id="org1") is False  # durable across "restart"
    rec = s2.get("k-restart", org_id="org1")
    assert rec is not None


def test_controlled_side_effect_fails_closed_without_durable_store(monkeypatch):
    import aios.core.business_execution_service as svc_mod

    settings = SimpleNamespace(
        execution_approved_adapters="email_resend",
        resend_api_key="rk-test",
        resend_from_email="sandbox@aios.local",
        business_idempotency_required=True,
    )
    monkeypatch.setattr(svc_mod, "_IDEMPOTENCY_STORE", None)
    monkeypatch.setattr(svc_mod, "_IDEMPOTENCY_STORE_KIND", "unknown")

    def _boom(*_a, **_kw):
        raise RuntimeError("db down")

    monkeypatch.setattr("aios.core.business_idempotency.DBIdempotencyStore.from_settings", _boom)

    with pytest.raises(ExecutionDenied, match="durable idempotency store required"):
        execute_controlled_business_action(
            adapter="email_resend",
            action="send_email",
            payload={"to": "u@example.test", "subject": "s", "body": "b", "org_id": "org1"},
            idempotency_key="idem-durable-required",
            settings=settings,
        )


def test_controlled_allows_in_memory_when_explicitly_opted_out(monkeypatch):
    import aios.core.business_execution_service as svc_mod

    sent = []

    def sender(**kw):
        sent.append(kw)
        return {"id": "msg-1"}

    settings = SimpleNamespace(
        execution_approved_adapters="email_resend",
        resend_api_key="rk-test",
        resend_from_email="sandbox@aios.local",
        business_idempotency_required=False,
    )
    monkeypatch.setattr(svc_mod, "_IDEMPOTENCY_STORE", None)
    monkeypatch.setattr(svc_mod, "_IDEMPOTENCY_STORE_KIND", "unknown")
    monkeypatch.setattr(
        "aios.core.business_idempotency.DBIdempotencyStore.from_settings",
        lambda *_a, **_kw: None,
    )

    registry = build_controlled_business_registry(settings=settings)
    adapter = registry.get("email_resend")
    assert adapter is not None
    adapter.sender = sender
    result = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "u@example.test", "subject": "s", "body": "b", "org_id": "org1"},
        idempotency_key="idem-dev-fallback",
    )
    assert result.ok is True
    assert is_business_idempotency_durable(svc_mod.get_business_idempotency_store(settings=settings)) is False


def test_controlled_side_effect_requires_org_scope():
    settings = SimpleNamespace(
        execution_approved_adapters="email_resend",
        resend_api_key="rk-test",
        resend_from_email="sandbox@aios.local",
        business_idempotency_required=False,
    )
    with pytest.raises(ExecutionDenied, match="org_id required"):
        execute_controlled_business_action(
            adapter="email_resend",
            action="send_email",
            payload={"to": "u@example.test", "subject": "s", "body": "b"},
            idempotency_key="idem-no-org",
            settings=settings,
            idempotency_store=InMemoryIdempotencyStore(),
        )


def test_inflight_duplicate_processing_does_not_reexecute(tmp_path):
    from aios.core.business_idempotency import DBIdempotencyStore

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'inflight.db'}"
    store = DBIdempotencyStore.from_settings(SimpleNamespace(database_url=db_url))
    assert store is not None
    # Simulate in-flight claim from another worker/process.
    assert store.claim("idem-inflight", org_id="org1", adapter="email_resend", action="send_email") is True

    adapter = _CountingAdapter()
    registry = ExecutionRegistry(audit_callback=lambda e: None, idempotency_store=store)
    registry.register(adapter)
    result = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "a@b.test", "org_id": "org1"},
        idempotency_key="idem-inflight",
    )
    assert result.status == "duplicate_processing"
    assert result.ok is True
    assert result.data.get("duplicate") is True
    assert result.data.get("durable") is True
    assert adapter.calls == 0


def _backdate_processing(store, *, key: str, org_id: str, age_seconds: int) -> None:
    from datetime import datetime, timedelta, timezone

    from aios.core.business_idempotency import BusinessIdempotencyRecord

    old = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    with store._session() as s:
        row = s.get(BusinessIdempotencyRecord, {"scope": f"org:{org_id}", "idempotency_key": key})
        assert row is not None
        row.status = "processing"
        row.updated_at = old
        row.created_at = old
        s.commit()


def test_stale_processing_duplicate_fails_closed_no_reexecute(tmp_path):
    from aios.core.business_idempotency import DBIdempotencyStore

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'stale.db'}"
    store = DBIdempotencyStore.from_settings(
        SimpleNamespace(database_url=db_url, business_idempotency_processing_ttl_seconds=30)
    )
    assert store is not None
    assert store.claim("idem-stale", org_id="org1", adapter="email_resend", action="send_email") is True
    _backdate_processing(store, key="idem-stale", org_id="org1", age_seconds=120)

    adapter = _CountingAdapter()
    registry = ExecutionRegistry(audit_callback=lambda e: None, idempotency_store=store)
    registry.register(adapter)
    result = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "a@b.test", "org_id": "org1"},
        idempotency_key="idem-stale",
    )
    assert result.status == "stale_processing"
    assert result.ok is False
    assert result.data.get("stale_processing") is True
    assert result.data.get("duplicate") is True
    assert adapter.calls == 0
    # claim still not re-executable/reclaimed implicitly
    rec = store.get("idem-stale", org_id="org1")
    assert rec is not None and rec.status == "processing"


def test_reclaim_stale_processing_marks_failed_no_reexecute(tmp_path):
    from aios.core.business_idempotency import DBIdempotencyStore

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'reclaim.db'}"
    store = DBIdempotencyStore.from_settings(
        SimpleNamespace(database_url=db_url, business_idempotency_processing_ttl_seconds=30)
    )
    assert store is not None
    assert store.claim("idem-reclaim", org_id="org1", adapter="email_resend", action="send_email") is True
    _backdate_processing(store, key="idem-reclaim", org_id="org1", age_seconds=120)

    out = store.reclaim_stale_processing(org_id="org1", older_than_seconds=30)
    assert out["ok"] is True
    assert out["reclaimed"] == 1
    assert out["items"][0]["idempotency_key"] == "idem-reclaim"

    rec = store.get("idem-reclaim", org_id="org1")
    assert rec is not None
    assert rec.status == "failed"
    assert rec.stale_processing is False
    assert rec.result and rec.result.get("reclaimed_stale_processing") is True

    adapter = _CountingAdapter()
    registry = ExecutionRegistry(audit_callback=lambda e: None, idempotency_store=store)
    registry.register(adapter)
    result = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "a@b.test", "org_id": "org1"},
        idempotency_key="idem-reclaim",
    )
    # same key remains fail-closed duplicate; no auto re-exec after reclaim
    assert result.status == "duplicate_failed"
    assert result.ok is False
    assert adapter.calls == 0


def test_service_reclaim_stale_business_idempotency_processing(tmp_path):
    import aios.core.business_execution_service as svc_mod
    from aios.core.business_idempotency import DBIdempotencyStore

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'svc-reclaim.db'}"
    store = DBIdempotencyStore.from_settings(
        SimpleNamespace(database_url=db_url, business_idempotency_processing_ttl_seconds=30)
    )
    assert store is not None
    assert store.claim("idem-svc", org_id="org1", adapter="email_resend", action="send_email") is True
    _backdate_processing(store, key="idem-svc", org_id="org1", age_seconds=120)

    out = svc_mod.reclaim_stale_business_idempotency_processing(
        idempotency_store=store, org_id="org1", older_than_seconds=30
    )
    assert out["reclaimed"] == 1
    assert store.get("idem-svc", org_id="org1").status == "failed"
