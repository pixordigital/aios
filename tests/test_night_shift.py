"""Night shift maintenance job — read-only reporting, fail-loud, HITL-bounded."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from aios.db.models import (
    AgentLearning,
    AgentReflection,
    AuditLog,
    ChannelConnection,
    CrmDeal,
    IntegrationOutbox,
    Organization,
    Skill,
)
from aios.governance.ocp import SharedTask
from aios.governance.security import SecurityEvent, SecurityIncident
from aios.tasks.jobs import FUNCTIONS, night_shift_job


def _utc(y, m, d, h=0, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=timezone.utc)


def _naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


async def _org(db, slug):
    org = Organization(name=slug, slug=slug, is_active=True)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


def _snap_deals(deals):
    return [
        (d.id, d.stage, d.value, d.lead_name, d.extra_data, d.updated_at, d.agent_id)
        for d in deals
    ]


def _snap_tasks(tasks):
    return [
        (t.id, t.status, t.title, t.deadline, t.updated_at, t.owner_id)
        for t in tasks
    ]


def _snap_channels(channels):
    return [(c.id, c.is_active, c.config, c.label) for c in channels]


@pytest.mark.asyncio
async def test_night_shift_seeded_summaries_no_mutation(test_session, monkeypatch):
    now = _utc(2026, 11, 25, 3, 0)
    monkeypatch.setattr("aios.tasks.jobs._ns_utcnow", lambda: now)

    org = await _org(test_session, "ns-seed")
    old = _naive(now - timedelta(days=10))
    stale_deal = CrmDeal(
        org_id=org.id, lead_name="Stale", stage="sql", value=1000, source="form",
        updated_at=old, extra_data={},
    )
    overdue_task = SharedTask(
        org_id=org.id, title="Overdue", status="pending", owner_type="agent", owner_id="a1",
        deadline=_naive(now - timedelta(hours=2)), updated_at=old,
    )
    test_session.add_all([
        stale_deal,
        overdue_task,
        SecurityIncident(org_id=org.id, incident_key="i1", title="Open", severity="critical", status="detected"),
        SecurityEvent(org_id=org.id, source="auth", event_type="security.auth.failure", severity="medium", payload={}),
        ChannelConnection(org_id=org.id, channel_type="slack", is_active=False, config={"bot_token": "x"}),
        IntegrationOutbox(peer="arvo", event_type="x", payload={}, idempotency_key="ob1", status="failed", attempts=5),
        AgentLearning(agent_id="a1", org_id=org.id, learning_type="success_pattern", trigger_context="t", action_taken="a", outcome="o", pattern_signature="ns-seed-1"),
        Skill(agent_id="a1", org_id=org.id, name="S1", status="draft"),
    ])
    await test_session.commit()

    deals_before = _snap_deals((await test_session.execute(select(CrmDeal))).scalars().all())
    tasks_before = _snap_tasks((await test_session.execute(select(SharedTask))).scalars().all())
    chans_before = _snap_channels((await test_session.execute(select(ChannelConnection))).scalars().all())
    outbox_before = (await test_session.execute(select(IntegrationOutbox.status, IntegrationOutbox.attempts))).all()

    sent = []

    async def _targets(org_id, team_id=""):
        return [{"token": "t", "channel": "C1"}]

    monkeypatch.setattr("aios.core.meetings.human_slack_targets", _targets)
    monkeypatch.setattr("aios.core.meetings.post_to_slack", lambda *a, **k: sent.append(a) or True)

    async def _no_flush(*a, **k):
        raise AssertionError("flush_outbox must not be called")

    monkeypatch.setattr("aios.integrations.arvo.publisher.flush_outbox", _no_flush)
    monkeypatch.setattr("aios.integrations.arvo.publisher.integration_outbox_flush", _no_flush)

    res = await night_shift_job(None)
    assert res["totals"]["processed"] == 1
    rep = res["orgs"][0]
    assert rep["status"] == "ok"
    assert rep["subjobs"]["stale_sweep"]["counts"]["stale_deals"] >= 1
    assert rep["subjobs"]["stale_sweep"]["counts"]["stale_tasks"] >= 1
    assert rep["subjobs"]["security_scan"]["counts"]["security_events_total"] >= 1
    assert rep["subjobs"]["integration_check"]["counts"]["channels_inactive"] >= 1
    assert rep["subjobs"]["memory_consolidation_report"]["counts"]["learnings_24h"] >= 1
    assert sent, "digest should be sent"

    # No mutation asserts
    deals_after = _snap_deals((await test_session.execute(select(CrmDeal))).scalars().all())
    tasks_after = _snap_tasks((await test_session.execute(select(SharedTask))).scalars().all())
    chans_after = _snap_channels((await test_session.execute(select(ChannelConnection))).scalars().all())
    outbox_after = (await test_session.execute(select(IntegrationOutbox.status, IntegrationOutbox.attempts))).all()
    assert deals_after == deals_before
    assert tasks_after == tasks_before
    assert chans_after == chans_before
    assert outbox_after == outbox_before


@pytest.mark.asyncio
async def test_night_shift_unknown_vuln_not_fabricated(test_session, monkeypatch):
    now = _utc(2026, 11, 25, 3, 0)
    monkeypatch.setattr("aios.tasks.jobs._ns_utcnow", lambda: now)
    org = await _org(test_session, "ns-unk")
    # no vuln telemetry
    await test_session.commit()

    monkeypatch.setattr("aios.core.meetings.human_slack_targets", lambda *a, **k: _async([]))
    res = await night_shift_job(None)
    sec = res["orgs"][0]["subjobs"]["security_scan"]
    assert "vulnerability_status:no_vuln_telemetry_24h" in sec["unknown"]
    # must not claim zero vulns/resolved
    assert "vulnerabilities" not in sec["counts"]
    assert "vulns" not in str(sec).lower() or "no_vuln_telemetry_24h" in str(sec)


async def _async(v):
    return v


@pytest.mark.asyncio
async def test_night_shift_no_flush_no_consolidation_rerun(test_session, monkeypatch):
    now = _utc(2026, 11, 25, 3, 0)
    monkeypatch.setattr("aios.tasks.jobs._ns_utcnow", lambda: now)
    await _org(test_session, "ns-noflush")

    calls = {"flush": 0, "consolidate": 0}

    async def _flush(*a, **k):
        calls["flush"] += 1
        return {"sent": 0}

    async def _consolidate(*a, **k):
        calls["consolidate"] += 1

    monkeypatch.setattr("aios.integrations.arvo.publisher.flush_outbox", _flush)
    monkeypatch.setattr("aios.integrations.arvo.publisher.integration_outbox_flush", _flush)
    monkeypatch.setattr("aios.tasks.learning_worker.memory_consolidation_job", _consolidate)
    monkeypatch.setattr("aios.core.meetings.human_slack_targets", lambda *a, **k: _async([]))

    res = await night_shift_job(None)
    assert res["totals"]["processed"] == 1
    assert calls["flush"] == 0
    assert calls["consolidate"] == 0


@pytest.mark.asyncio
async def test_night_shift_subjob_exception_isolated_and_audited(test_session, monkeypatch):
    now = _utc(2026, 11, 25, 3, 0)
    monkeypatch.setattr("aios.tasks.jobs._ns_utcnow", lambda: now)
    org = await _org(test_session, "ns-isolate")

    async def _boom(*a, **k):
        raise RuntimeError("scan boom")

    monkeypatch.setattr("aios.tasks.jobs._night_shift_security_scan", _boom)
    monkeypatch.setattr("aios.core.meetings.human_slack_targets", lambda *a, **k: _async([{"token": "t", "channel": "C"}]))
    texts = []
    monkeypatch.setattr("aios.core.meetings.post_to_slack", lambda tok, ch, text: texts.append(text) or True)

    res = await night_shift_job(None)
    rep = res["orgs"][0]
    assert rep["status"] == "completed_with_failures"
    assert any(f[0] == "security_scan" for f in rep["failures"])
    # other subjobs still ran
    assert "stale_sweep" in rep["subjobs"]
    assert "integration_check" in rep["subjobs"]
    assert "memory_consolidation_report" in rep["subjobs"]
    assert texts and "security_scan" in texts[0]
    assert "falharam" in texts[0].lower() or "failed" in texts[0].lower() or "subjob(s) failed" in texts[0]

    actions = (await test_session.execute(
        select(AuditLog.action).where(AuditLog.org_id == org.id)
    )).scalars().all()
    assert "night_shift.security_scan.failed" in actions
    assert "night_shift.stale_sweep.complete" in actions
    assert "night_shift.morning_digest.complete" in actions


@pytest.mark.asyncio
async def test_night_shift_audit_written(test_session, monkeypatch):
    now = _utc(2026, 11, 25, 3, 0)
    monkeypatch.setattr("aios.tasks.jobs._ns_utcnow", lambda: now)
    org = await _org(test_session, "ns-audit")
    monkeypatch.setattr("aios.core.meetings.human_slack_targets", lambda *a, **k: _async([]))

    await night_shift_job(None)
    actions = set((await test_session.execute(
        select(AuditLog.action).where(AuditLog.org_id == org.id)
    )).scalars().all())
    for sub in ["security_scan", "stale_sweep", "integration_check", "memory_consolidation_report", "morning_digest"]:
        assert f"night_shift.{sub}.start" in actions
        assert f"night_shift.{sub}.complete" in actions or f"night_shift.{sub}.no_target" in actions


@pytest.mark.asyncio
async def test_night_shift_digest_failures_first_and_no_target_warning(test_session, monkeypatch):
    now = _utc(2026, 11, 25, 3, 0)
    monkeypatch.setattr("aios.tasks.jobs._ns_utcnow", lambda: now)
    org = await _org(test_session, "ns-digest")

    async def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("aios.tasks.jobs._night_shift_stale_sweep", _boom)
    monkeypatch.setattr("aios.core.meetings.human_slack_targets", lambda *a, **k: _async([]))

    res = await night_shift_job(None)
    rep = res["orgs"][0]
    assert rep["digest"]["reason"] == "no_owner_slack_dm"
    text = rep["digest"]["text"]
    # failures first
    assert text.index("failed") < text.index("*Security*")
    actions = (await test_session.execute(
        select(AuditLog.action).where(AuditLog.org_id == org.id)
    )).scalars().all()
    assert "night_shift.morning_digest.no_target" in actions


@pytest.mark.asyncio
async def test_night_shift_hitl_boundary_no_external_send_or_mutation(test_session, monkeypatch):
    now = _utc(2026, 11, 25, 3, 0)
    monkeypatch.setattr("aios.tasks.jobs._ns_utcnow", lambda: now)
    org = await _org(test_session, "ns-hitl")
    old = _naive(now - timedelta(days=10))
    test_session.add(CrmDeal(org_id=org.id, lead_name="L", stage="sql", value=1, source="form", updated_at=old, extra_data={}))
    test_session.add(SharedTask(org_id=org.id, title="T", status="pending", owner_type="agent", owner_id="a1", updated_at=old))
    await test_session.commit()

    calls = {"deliver": 0, "send": 0}

    async def _deliver(*a, **k):
        calls["deliver"] += 1

    async def _send(*a, **k):
        calls["send"] += 1
        return True

    monkeypatch.setattr("aios.core.delivery.deliver_message", _deliver)
    monkeypatch.setattr("aios.tasks.jobs.deliver_message", _deliver)
    monkeypatch.setattr("aios.core.meetings.human_slack_targets", lambda *a, **k: _async([{"token": "t", "channel": "C"}]))
    monkeypatch.setattr("aios.core.meetings.post_to_slack", lambda *a, **k: calls.__setitem__("send", calls["send"] + 1) or True)

    before_deals = _snap_deals((await test_session.execute(select(CrmDeal))).scalars().all())
    before_tasks = _snap_tasks((await test_session.execute(select(SharedTask))).scalars().all())

    res = await night_shift_job(None)
    assert res["totals"]["processed"] == 1
    assert calls["deliver"] == 0  # no customer/external delivery
    assert calls["send"] == 1     # only owner digest

    after_deals = _snap_deals((await test_session.execute(select(CrmDeal))).scalars().all())
    after_tasks = _snap_tasks((await test_session.execute(select(SharedTask))).scalars().all())
    assert after_deals == before_deals
    assert after_tasks == before_tasks


@pytest.mark.asyncio
async def test_night_shift_idempotency(test_session, monkeypatch):
    now = _utc(2026, 11, 25, 3, 0)
    monkeypatch.setattr("aios.tasks.jobs._ns_utcnow", lambda: now)
    org = await _org(test_session, "ns-idem")
    monkeypatch.setattr("aios.core.meetings.human_slack_targets", lambda *a, **k: _async([]))

    first = await night_shift_job(None)
    second = await night_shift_job(None)
    assert first["totals"]["processed"] == 1
    assert second["totals"]["skipped_idempotent"] == 1
    # start audit for security_scan only once
    starts = (await test_session.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.org_id == org.id, AuditLog.action == "night_shift.security_scan.start"
        )
    )).scalar() or 0
    assert starts == 1


def test_night_shift_cron_registry_has_job():
    assert night_shift_job in FUNCTIONS
    from aios.tasks.worker import WorkerSettings

    names = []
    for j in WorkerSettings.cron_jobs:
        fn = getattr(j, "coroutine", None) or getattr(j, "func", None)
        names.append(getattr(fn, "__name__", ""))
    assert "night_shift_job" in names

    from aios.core.routines import ARQ_CRON_CATALOG

    assert "night_shift_job" in ARQ_CRON_CATALOG
    assert ARQ_CRON_CATALOG["night_shift_job"]["cron_expr"] == "0 0 3 * * *"
