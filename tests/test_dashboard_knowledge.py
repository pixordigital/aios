"""Dashboard governed knowledge flow: ingest/provenance/promote/scope UX."""

import jwt
import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import select

from aios.config import settings
from aios.db.models import Memory, Organization
from aios.governance.knowledge import KnowledgeRecord


def _cookie_for(user):
    return jwt.encode(
        {
            "sub": user.id,
            "org": user.org_id,
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_ingest_creates_governed_records_not_memory(
    async_client, test_session, test_org, test_user
):
    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_session.commit()
    async_client.cookies.set("aios_token", _cookie_for(test_user))

    r = await async_client.post(
        "/dashboard/knowledge/ingest",
        data={
            "title": "Policy",
            "source_type": "doc",
            "source_id": "p1",
            "classification": "internal",
            "kind": "statement",
        },
        files={"file": ("policy.txt", b"alpha beta gamma delta epsilon zeta", "text/plain")},
        follow_redirects=False,
        headers={"referer": "http://test/dashboard/knowledge"},
    )
    assert r.status_code == 303
    assert "ingested=1" in r.headers.get("location", "")

    recs = (await test_session.execute(select(KnowledgeRecord).where(KnowledgeRecord.org_id == test_org.id))).scalars().all()
    mems = (await test_session.execute(select(Memory).where(Memory.org_id == test_org.id))).scalars().all()
    assert recs
    assert all(r.source_type == "doc" and r.provenance.get("filename") == "policy.txt" for r in recs)
    assert not mems


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_ingest_fail_closed_missing_provenance(
    async_client, test_session, test_org, test_user
):
    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_session.commit()
    async_client.cookies.set("aios_token", _cookie_for(test_user))

    r = await async_client.post(
        "/dashboard/knowledge/ingest",
        data={"title": "", "source_type": "", "classification": "internal", "kind": "statement"},
        files={"file": ("x.txt", b"content", "text/plain")},
        headers={"referer": "http://test/dashboard/knowledge"},
    )
    assert r.status_code == 200
    assert "provenance fail-closed" in r.text.lower() or "obrigat" in r.text.lower()
    recs = (await test_session.execute(select(KnowledgeRecord).where(KnowledgeRecord.org_id == test_org.id))).scalars().all()
    assert not recs


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_ingest_requires_founder(
    async_client, test_session, test_org, test_user
):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.post(
        "/dashboard/knowledge/ingest",
        data={"title": "Doc", "source_type": "doc", "classification": "internal", "kind": "statement"},
        files={"file": ("x.txt", b"content", "text/plain")},
        headers={"referer": "http://test/dashboard/knowledge"},
    )
    assert r.status_code == 200
    assert "founder" in r.text.lower() or "owner" in r.text.lower()
    recs = (await test_session.execute(select(KnowledgeRecord).where(KnowledgeRecord.org_id == test_org.id))).scalars().all()
    assert not recs


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_knowledge_page_shows_governed_record_and_promote(
    async_client, test_session, test_org, test_user
):
    test_org.extra_data = {"founder_user_id": test_user.id}
    rec = KnowledgeRecord(
        org_id=test_org.id, title="Claim", content="alpha", kind="statement",
        classification="internal", source_type="meeting", source_id="m1",
        provenance={"src": "m1"}, search_text="alpha",
    )
    test_session.add(rec)
    await test_session.commit()
    async_client.cookies.set("aios_token", _cookie_for(test_user))

    page = await async_client.get("/dashboard/knowledge")
    assert page.status_code == 200
    assert "Claim" in page.text
    assert "source=meeting" in page.text
    assert "Promover a fato" in page.text

    pr = await async_client.post(
        f"/dashboard/knowledge/{rec.id}/promote",
        data={"human_confirmed": "1"},
        follow_redirects=False,
        headers={"referer": "http://test/dashboard/knowledge"},
    )
    assert pr.status_code == 303
    await test_session.refresh(rec)
    assert rec.kind == "fact"


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_knowledge_pagination_uses_visible_total(
    async_client, test_session, test_org, test_user
):
    for index in range(3):
        test_session.add(KnowledgeRecord(
            org_id=test_org.id, title=f"Visible {index}", content="alpha", kind="statement",
            classification="internal", source_type="meeting", source_id=f"m{index}",
            provenance={"src": f"m{index}"}, search_text="alpha",
        ))
    test_session.add(KnowledgeRecord(
        org_id=test_org.id, title="Hidden restricted", content="secret", kind="statement",
        classification="restricted", source_type="meeting", source_id="hidden",
        provenance={"src": "hidden"}, search_text="secret",
    ))
    await test_session.commit()
    async_client.cookies.set("aios_token", _cookie_for(test_user))

    page1 = await async_client.get("/dashboard/knowledge?limit=2&offset=0")
    assert page1.status_code == 200
    assert "Registros (3)" in page1.text
    assert sum(f"Visible {i}" in page1.text for i in range(3)) == 2
    assert "Hidden restricted" not in page1.text
    assert "/dashboard/knowledge?offset=2&limit=2" in page1.text

    page2 = await async_client.get("/dashboard/knowledge?limit=2&offset=2")
    assert page2.status_code == 200
    assert "Registros (3)" in page2.text
    assert sum(f"Visible {i}" in page2.text for i in range(3)) == 1
    assert "Hidden restricted" not in page2.text
    assert "/dashboard/knowledge?offset=0&limit=2" in page2.text
    assert ">Próxima</a>" not in page2.text


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_promote_requires_authenticated_founder(
    async_client, test_session, test_org, test_user
):
    rec = KnowledgeRecord(
        org_id=test_org.id, title="Claim", content="alpha", kind="statement",
        classification="internal", source_type="meeting", source_id="m1",
        provenance={"src": "m1"}, search_text="alpha",
    )
    test_session.add(rec)
    await test_session.commit()
    async_client.cookies.set("aios_token", _cookie_for(test_user))

    page = await async_client.get("/dashboard/knowledge")
    assert page.status_code == 200
    assert "aguarda confirmação do founder" in page.text

    denied = await async_client.post(
        f"/dashboard/knowledge/{rec.id}/promote",
        data={"human_confirmed": "1"},
        follow_redirects=False,
        headers={"referer": "http://test/dashboard/knowledge"},
    )
    assert denied.status_code == 303
    assert "founder_required" in denied.headers.get("location", "")
    await test_session.refresh(rec)
    assert rec.kind == "statement"

    test_org.extra_data = {**(test_org.extra_data or {}), "founder_user_id": test_user.id}
    await test_session.commit()
    allowed = await async_client.post(
        f"/dashboard/knowledge/{rec.id}/promote",
        data={"human_confirmed": "1"},
        follow_redirects=False,
        headers={"referer": "http://test/dashboard/knowledge"},
    )
    assert allowed.status_code == 303
    assert "promoted=1" in allowed.headers.get("location", "")
    await test_session.refresh(rec)
    assert rec.kind == "fact"


def test_pending_approval_counter_includes_unassigned_rows():
    from aios.dashboard.app import _build_teams_map_ops

    rows = [SimpleNamespace(agent_id=None), SimpleNamespace(agent_id="a1")]
    ops = _build_teams_map_ops(teams=[], pending_rows=rows, routines=[])
    assert ops["pending_approvals"] == {"total": 2, "by_agent": {"a1": 1}, "by_team": {}}


@pytest.mark.asyncio(loop_scope="function")
async def test_simple_knowledge_warns_not_auto_governed(async_client, test_org, test_user):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.get("/dashboard/simple/knowledge")
    assert r.status_code == 200
    assert "não viram conhecimento governado automaticamente" in r.text.lower()
