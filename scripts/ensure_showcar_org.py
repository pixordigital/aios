#!/usr/bin/env python3
"""Idempotent: ensure Showcar org exists and pixordigital@gmail.com is owner.

Safe to run multiple times. Does not create users or print secrets.

Run inside app container / deployment environment:
    python scripts/ensure_showcar_org.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import Base, Organization, User

OrganizationMembership = Base.registry._class_registry.get("OrganizationMembership")
if OrganizationMembership is None:
    from aios.db.models import OrganizationMembership  # type: ignore[attr-defined]

ORG_SLUG = "showcar"
ORG_NAME = "Showcar"
OWNER_EMAIL = "pixordigital@gmail.com"


async def main() -> int:
    async with db_session() as db:
        org = (await db.execute(select(Organization).where(Organization.slug == ORG_SLUG))).scalars().first()
        created_org = False
        if not org:
            org = Organization(name=ORG_NAME, slug=ORG_SLUG, is_active=True, extra_data={})
            db.add(org)
            await db.flush()
            created_org = True

        user = (
            await db.execute(select(User).where(User.email == OWNER_EMAIL))
        ).scalars().first()
        if not user:
            print(f"ERROR:user_not_found email={OWNER_EMAIL}")
            await db.rollback()
            return 2

        mem = (
            await db.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.org_id == org.id,
                )
            )
        ).scalars().first()
        created_mem = False
        if not mem:
            mem = OrganizationMembership(user_id=user.id, org_id=org.id, role="owner")
            db.add(mem)
            created_mem = True
        elif mem.role != "owner":
            mem.role = "owner"

        extra = dict(org.extra_data or {})
        if not extra.get("founder_user_id"):
            extra["founder_user_id"] = user.id
            org.extra_data = extra

        await db.commit()
        print(
            "OK "
            f"org_id={org.id} org_slug={org.slug} "
            f"created_org={created_org} "
            f"owner_user_id={user.id} owner_email={OWNER_EMAIL} "
            f"created_membership={created_mem} membership_role=owner"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))