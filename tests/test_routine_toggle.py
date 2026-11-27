"""Org-scoped routine toggle (AutomationTrigger.is_active)."""
import jwt
import pytest
from datetime import datetime, timedelta, timezone

from aios.config import settings
from aios.db.models import AutomationTrigger, Workflow


def _cookie(user):
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


async def _trigger(test_session, org_id, *, active=True):
    wf = Workflow(name="wf", org_id=org_id)
    test_session.add(wf)
    await test_session.commit()
    await test_session.refresh(wf)
    trig = AutomationTrigger(
        workflow_id=wf.id, org_id=org_id, type="cron", name="daily", is_active=active, config={}
    )
    test_session.add(trig)
    await test_session.commit()
    await test_session.refresh(trig)
    return trig


@pytest.mark.asyncio(loop_scope="function")
async def test_toggle_disables_org_automation_trigger(async_client, test_session, test_org, test_user):
    trig = await _trigger(test_session, test_org.id)
    async_client.cookies.set("aios_token", _cookie(test_user))

    r = await async_client.post(
        f"/dashboard/routines/automation_cron:{trig.id}/toggle",
        data={"enabled": "0"},
        headers={"referer": "http://test/dashboard/routines"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    await test_session.refresh(trig)
    assert trig.is_active is False

    r = await async_client.post(
        f"/dashboard/routines/automation_cron:{trig.id}/toggle",
        data={"enabled": "1"},
        headers={"referer": "http://test/dashboard/routines"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    await test_session.refresh(trig)
    assert trig.is_active is True


@pytest.mark.asyncio(loop_scope="function")
async def test_toggle_rejects_foreign_org_and_non_automation(
    async_client, test_session, test_org, second_org, test_user
):
    foreign = await _trigger(test_session, second_org.id)
    async_client.cookies.set("aios_token", _cookie(test_user))

    r = await async_client.post(
        f"/dashboard/routines/automation_cron:{foreign.id}/toggle",
        data={"enabled": "0"},
        headers={"referer": "http://test/dashboard/routines"},
        follow_redirects=False,
    )
    assert r.status_code == 404
    await test_session.refresh(foreign)
    assert foreign.is_active is True

    r = await async_client.post(
        "/dashboard/routines/arq_cron:cron_tick_job/toggle",
        data={"enabled": "0"},
        headers={"referer": "http://test/dashboard/routines"},
        follow_redirects=False,
    )
    assert r.status_code == 400
