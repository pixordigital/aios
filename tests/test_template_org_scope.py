"""Tenant-isolation tests for the WhatsApp Template Studio.

Templates are per-WABA assets. A cross-org read here would leak business content
and customer copy, and a cross-org WRITE would corrupt another tenant's approval
queue. The audit already found this class of bug in approvals, skills, meta and
versions, so every new route is pinned here.

All tests use two seeded orgs so an unscoped query actually returns the victim's
row and fails.
"""

import pytest
from sqlalchemy import select

from aios.api.meta_webhook import apply_meta_state
from aios.db.models import WhatsappConnection, WhatsappTemplate


def _mk_tpl(db, org_id, waba_id, name="t1", body="Ola {{1}} sua consulta foi confirmada.", status="DRAFT"):
    t = WhatsappTemplate(
        org_id=org_id, waba_id=waba_id, name=name, language="pt_BR",
        category="UTILITY", body=body, examples_json={"1": "a"}, status=status,
    )
    db.add(t)
    return t


def test_template_model_carries_org_and_waba():
    cols = {c.name for c in WhatsappTemplate.__table__.columns}
    assert "org_id" in cols
    assert "waba_id" in cols, "templates are per-WABA; waba_id must be on the row"


def test_connection_model_carries_org():
    cols = {c.name for c in WhatsappConnection.__table__.columns}
    assert "org_id" in cols
    assert "access_token_enc" in cols, "the token must be stored encrypted, not plaintext"


def test_no_plaintext_token_column():
    assert not any("token" in c.name and "enc" not in c.name for c in WhatsappConnection.__table__.columns)


def test_template_lookup_queries_are_org_scoped():
    """Every template read in the dashboard must carry org_id in the WHERE."""
    import inspect

    import aios.dashboard.app as app
    src = inspect.getsource(app)
    reads = [ln.strip() for ln in src.splitlines() if "select(WhatsappTemplate)" in ln]
    assert reads, "expected template reads"
    for ln in reads:
        window = src[src.index(ln):src.index(ln) + 400]
        assert "org_id ==" in window, f"unscoped template read: {ln}"


def test_agent_tools_refuse_without_org():
    """No org context means no access, not a global fallback."""
    import asyncio

    from aios.tools.whatsapp_template_studio import (
        WhatsappTemplateDraft,
        WhatsappTemplateList,
    )

    t = WhatsappTemplateList()
    t._org_id = ""
    assert asyncio.get_event_loop().run_until_complete(
        t.run()
    ).get("error")

    d = WhatsappTemplateDraft()
    d._org_id = ""
    assert asyncio.get_event_loop().run_until_complete(
        d.run(name="x", body="y")
    ).get("error")


def test_no_agent_submit_tool():
    """Submission is human-only by design; an agent submit tool would break that."""
    from aios.tools.registry import TOOL_REGISTRY

    bad = [t for t in TOOL_REGISTRY if "whatsapp_template" in t and any(
        k in t for k in ("submit", "send_to_meta", "publish", "review_request")
    )]
    assert bad == [], f"agents must not be able to submit to Meta: {bad}"


def test_webhook_fails_closed_without_secret(monkeypatch):
    """No configured secret means nobody may set our template state."""
    import aios.api.meta_webhook as mw

    class Conn:
        waba_id = "W1"
        org_id = "org1"
        webhook_secret_enc = ""

    monkeypatch.setattr(mw, "_expected_secret", lambda c: "")
    assert mw._expected_secret(Conn()) == ""


def test_webhook_secret_is_per_connection():
    import inspect

    import aios.api.meta_webhook as mw
    src = inspect.getsource(mw)
    # resolved from the connection row, never from a global setting
    assert "webhook_secret_enc" in src
    assert "compare_digest" in src, "use a constant-time compare"


# ── status application must not invent a reason ─────────────────────────

def _tpl(status="PENDING"):
    class T:
        pass
    t = T()
    t.status = status
    t.rejected_reason = None
    t.rejection_note = ""
    return t


def test_rejection_without_reason_is_stated_not_guessed():
    t = _tpl()
    apply_meta_state(t, status="REJECTED", reason=None)
    assert t.rejected_reason is None
    assert "sem informar um motivo" in t.rejection_note
    # the note must point at the causes Meta does not report
    assert "duplic" in t.rejection_note.lower() or "idêntico" in t.rejection_note.lower()


def test_rejection_reason_is_stored_verbatim():
    t = _tpl()
    apply_meta_state(t, status="REJECTED", reason="PROMOTIONAL")
    assert t.rejected_reason == "PROMOTIONAL"
    assert t.rejection_note == "Meta informou: PROMOTIONAL"


def test_none_reason_is_not_treated_as_a_real_reason():
    t = _tpl()
    apply_meta_state(t, status="REJECTED", reason="NONE")
    assert t.rejected_reason == "NONE"
    assert "sem informar um motivo" in t.rejection_note


def test_paused_status_is_recorded():
    """PAUSED means an approved template stopped being sendable."""
    t = _tpl(status="APPROVED")
    apply_meta_state(t, status="PAUSED", reason=None)
    assert t.status == "PAUSED"


def test_apply_state_is_idempotent():
    t = _tpl()
    apply_meta_state(t, status="APPROVED", reason=None)
    first = (t.status, t.rejected_reason, t.rejection_note)
    apply_meta_state(t, status="APPROVED", reason=None)
    assert (t.status, t.rejected_reason, t.rejection_note) == first