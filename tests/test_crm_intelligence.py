"""CRM accounts/contacts, health and prioritisation."""

from datetime import datetime

from aios.core.crm_intelligence import (
    Account,
    Contact,
    InteractionEvent,
    relationship_health,
    retention_cutoff,
    sales_priority,
)


def test_health_penalises_stale_and_overdue():
    good, _ = relationship_health(
        days_since_last_contact=3, open_commitments=0, overdue_commitments=0, support_tickets_open=0
    )
    bad, reason = relationship_health(
        days_since_last_contact=90, open_commitments=2, overdue_commitments=2, support_tickets_open=4
    )
    assert good > bad
    assert "stale" in reason


def test_health_is_bounded():
    score, _ = relationship_health(
        days_since_last_contact=None, open_commitments=5, overdue_commitments=5, support_tickets_open=9
    )
    assert 0.0 <= score <= 1.0


def test_priority_prefers_fit_and_recency():
    hot = sales_priority(icp_fit=0.9, recency_days=1, attempts=3, deal_value=80_000, stage_weight=0.8)
    cold = sales_priority(icp_fit=0.2, recency_days=29, attempts=0, deal_value=0, stage_weight=0.1)
    assert hot > cold


def test_retention_cutoff():
    now = datetime(2026, 11, 22)
    assert (now - retention_cutoff(now, 30)).days == 30
    assert retention_cutoff(now, -5) == now


def test_account_contact_entities_are_separate():
    from aios.db.models import Base

    account = Account(org_id="o", name="ACME", cnpj="12345678000199")
    event = InteractionEvent(org_id="o", account_id="a", contact_id="c", summary="call")
    assert account.cnpj == "12345678000199"
    assert event.contact_id == "c"
    for name in ("crm_accounts", "crm_contacts", "crm_interactions"):
        assert name in Base.metadata.tables
