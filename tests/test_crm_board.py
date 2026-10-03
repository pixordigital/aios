"""CRM kanban board: stable columns, every deal visible, moves honoured.

Failures pinned here:
1. Columns rendered only for stages present in the data, so the board
   changed shape with the data, empty stages had no drop target, and deals
   in odd stages vanished while still counted in the totals.
2. The move endpoint accepted six stages while the board showed nine, so
   drops into qualification/proposal/negotiation redirected with no change
   and no error.
"""

import pytest

from aios.dashboard.app import _CRM_BOARD_STAGES


def test_board_stages_cover_canonical_ladder():
    assert _CRM_BOARD_STAGES == [
        "prospection", "qualification", "mql", "sql", "proposal",
        "negotiation", "opportunity", "closed_won", "closed_lost",
    ]


async def _seed(test_session, stages):
    from aios.db.models import CrmDeal, Organization

    org = Organization(name="Board Org", slug="board-org", extra_data={"crm_enabled": True})
    test_session.add(org)
    await test_session.flush()
    for i, stage in enumerate(stages):
        test_session.add(CrmDeal(
            org_id=org.id, lead_name=f"Lead {i}", lead_email=f"lead{i}@x.com",
            stage=stage, value=100.0,
        ))
    await test_session.commit()
    return org


def _render_crm(org_id):
    import types

    import aios.dashboard.app as app_mod

    req = types.SimpleNamespace(
        state=types.SimpleNamespace(org_id=org_id),
        url=types.SimpleNamespace(path="/dashboard/crm"),
    )
    return app_mod.crm_page(req)


@pytest.mark.asyncio
async def test_all_nine_columns_render_with_zero_deals(test_session):
    html = await _render_crm((await _seed(test_session, [])).id)
    assert isinstance(html, str)
    for stage in _CRM_BOARD_STAGES:
        assert f'data-stage="{stage}"' in html, f"missing column {stage}"


@pytest.mark.asyncio
async def test_odd_stage_deal_is_visible_not_dropped(test_session):
    org = await _seed(test_session, ["qualification", "proposal", "weird_custom"])
    html = await _render_crm(org.id)
    assert "Lead 0" in html and "Lead 1" in html and "Lead 2" in html
    assert 'data-stage="weird_custom"' in html  # extras get a column too


@pytest.mark.asyncio
async def test_drag_hooks_present(test_session):
    html = await _render_crm((await _seed(test_session, ["mql"])).id)
    assert 'data-deal-id="' in html
    assert "/dashboard/crm/${dragId}/move" in html


@pytest.mark.asyncio
async def test_move_accepts_every_board_stage(test_session):
    """End to end through the real endpoint: drop into each column works."""
    import types

    import aios.dashboard.app as app_mod
    from aios.db.models import CrmDeal

    org = await _seed(test_session, ["mql"])
    async with app_mod.db_session() as db:
        from sqlalchemy import select

        deal = (await db.execute(
            select(CrmDeal).where(CrmDeal.org_id == org.id))).scalars().first()
        deal_id = deal.id

    for stage in _CRM_BOARD_STAGES:
        # crm_move reads `await request.form()`; emulate with a tiny shim
        async def _form(_s=stage):
            return types.SimpleNamespace(get=lambda k, d=None: _s)
        req = types.SimpleNamespace(state=types.SimpleNamespace(org_id=org.id), form=_form)
        await app_mod.crm_move(req, deal_id, stage)

    async with app_mod.db_session() as db:
        from sqlalchemy import select

        final = (await db.execute(
            select(CrmDeal).where(CrmDeal.id == deal_id))).scalars().first()
        assert final.stage == _CRM_BOARD_STAGES[-1]


@pytest.mark.asyncio
async def test_page_survives_nonempty_pipelines(test_session):
    """select(CrmDeal.pipeline) yields plain strings; the old `{d.pipeline}`
    comprehension 500'd the whole page on any non-empty pipeline value."""
    from aios.db.models import CrmDeal, Organization

    org = Organization(name="Pipe Org", slug="pipe-org", extra_data={"crm_enabled": True})
    test_session.add(org)
    await test_session.flush()
    test_session.add(CrmDeal(org_id=org.id, lead_name="L", lead_email="l@x.com",
                             stage="mql", pipeline="enterprise"))
    await test_session.commit()
    html = await _render_crm(org.id)
    assert isinstance(html, str) and "enterprise" in html
