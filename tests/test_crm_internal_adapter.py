from unittest.mock import MagicMock

import pytest

from aios.core.business_execution import ExecutionDenied
from aios.core.adapters.crm_internal import CrmInternalAdapter


def _fake_db(existing=None):
    db = MagicMock()
    q = MagicMock()
    q.filter_by.return_value = q
    q.first.return_value = existing
    db.query.return_value = q
    db.add.return_value = None
    db.flush.return_value = None
    db.get.return_value = None
    return db


def test_missing_db_fails_closed():
    adapter = CrmInternalAdapter(db=None, approved=True)

    with pytest.raises(ExecutionDenied, match="db/session not provided"):
        adapter.execute(
            action="upsert_contact",
            payload={"org_id": "org-1", "email": "a@b.com", "name": "A"},
            idempotency_key="idem-1",
        )


def test_idempotency_required():
    adapter = CrmInternalAdapter(db=_fake_db(), approved=True)

    with pytest.raises(ExecutionDenied, match="idempotency_key required"):
        adapter.execute(
            action="upsert_contact",
            payload={"org_id": "org-1", "email": "a@b.com", "name": "A"},
            idempotency_key="",
        )


def test_upsert_contact_dry_run_returns_structured_result_and_audits():
    events = []
    db = _fake_db()
    adapter = CrmInternalAdapter(db=db, approved=True, audit_callback=events.append)

    result = adapter.execute(
        action="upsert_contact",
        payload={"org_id": "org-1", "email": "lead@example.com", "name": "Lead"},
        idempotency_key="idem-contact-1",
    )

    assert result.ok is True
    assert result.adapter == "crm_internal"
    assert result.action == "upsert_contact"
    assert result.idempotency_key == "idem-contact-1"
    assert result.status in {"created", "updated"}
    assert isinstance(result.data, dict)
    assert result.data.get("org_id") == "org-1"
    assert result.data.get("email") == "lead@example.com"
    db.add.assert_called_once()
    assert any(e.get("event") == "crm_internal.result" and e.get("ok") is True for e in events)


def test_org_id_required_fails_closed():
    adapter = CrmInternalAdapter(db=_fake_db(), approved=True)

    with pytest.raises(ExecutionDenied, match="org_id required"):
        adapter.execute(
            action="upsert_contact",
            payload={"email": "a@b.com", "name": "A"},
            idempotency_key="idem-org",
        )


def test_destructive_action_fails_closed():
    adapter = CrmInternalAdapter(db=_fake_db(), approved=True)

    with pytest.raises(ExecutionDenied, match="action not allowed"):
        adapter.execute(
            action="delete_contact",
            payload={"org_id": "org-1", "email": "a@b.com"},
            idempotency_key="idem-del",
        )
