"""Regression: granted-record resolution reuses caller DB session."""

import pytest


async def test_resolve_granted_record_ids_reuses_supplied_db(
    monkeypatch, test_db_session, test_org, test_user
):
    from aios.governance.knowledge import KnowledgeGrant, KnowledgeRecord
    from aios.tools import rag_search

    rec = KnowledgeRecord(
        id="kr-session-reuse",
        org_id=test_org.id,
        title="Confidential",
        kind="statement",
        classification="confidential",
        source_type="doc",
        source_id="s1",
        derived_from=[],
        search_text="secret",
    )
    test_db_session.add(rec)
    test_db_session.add(
        KnowledgeGrant(org_id=test_org.id, user_id=test_user.id, record_id=rec.id)
    )
    await test_db_session.commit()

    def no_new_session():
        pytest.fail("async_session called despite supplied db")

    monkeypatch.setattr("aios.db.engine.async_session", no_new_session)

    grants = await rag_search.resolve_granted_record_ids(
        test_org.id, test_user.id, db=test_db_session
    )
    assert grants == {rec.id}
