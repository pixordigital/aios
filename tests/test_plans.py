"""Pixor org is always Ilimitado — enforced at the ORM flush choke point."""

import pytest
from sqlalchemy import select

from aios.db.models import Organization


@pytest.mark.asyncio
async def test_pixor_org_forced_unlimited(test_session):
    org = Organization(name="Pixor", slug="pixor", extra_data={})
    test_session.add(org)
    await test_session.commit()  # before_flush hook fires

    await test_session.refresh(org)
    assert org.extra_data["plan"] == "unlimited"
    assert org.extra_data["unlimited"] is True


@pytest.mark.asyncio
async def test_pixor_downgrade_reverted(test_session):
    org = Organization(name="Pixor", slug="pixor", extra_data={"plan": "unlimited", "unlimited": True})
    test_session.add(org)
    await test_session.commit()

    # Stripe cancellation downgrades to free; hook must revert it.
    org.extra_data["plan"] = "free"
    await test_session.commit()

    await test_session.refresh(org)
    assert org.extra_data["plan"] == "unlimited"


@pytest.mark.asyncio
async def test_non_pixor_org_keeps_plan(test_session):
    org = Organization(name="Other", slug="other-org", extra_data={"plan": "pro"})
    test_session.add(org)
    await test_session.commit()

    await test_session.refresh(org)
    assert org.extra_data["plan"] == "pro"


@pytest.mark.asyncio
async def test_default_org_prefers_pixor(test_session):
    from aios.dashboard.app import _default_org_id
    from aios.db.models import Organization

    other = Organization(name="Default", slug="default", extra_data={"plan": "free"})
    pix = Organization(name="Pixor", slug="pixor", extra_data={"plan": "unlimited", "unlimited": True})
    test_session.add_all([other, pix])
    await test_session.commit()

    oid = await _default_org_id()
    assert oid == pix.id
    assert oid != other.id
