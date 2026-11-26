#!/usr/bin/env python3
"""Idempotent: ensure Showcar org exists and pixordigital@gmail.com is owner.

Safe to run multiple times. Does not create users or print secrets.

Run inside app container / deployment environment:
    python scripts/ensure_showcar_org.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text

from aios.db.backend import db_session
from aios.db.models import Organization, User

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

        user = (await db.execute(select(User).where(User.email == OWNER_EMAIL))).scalars().first()
        if not user:
            print(f"ERROR:user_not_found email={OWNER_EMAIL}")
            await db.rollback()
            return 2

        now = datetime.now(timezone.utc)
        mem_row = (await db.execute(
            text("SELECT id, role FROM organization_memberships WHERE user_id = :uid AND org_id = :oid LIMIT 1")
            .bindparams(uid=user.id, oid=org.id)
        )).first()
        created_mem = False
        if not mem_row:
            await db.execute(
                text("""
                    INSERT INTO organization_memberships (id, user_id, org_id, role, created_at, updated_at)
                    VALUES (:id, :uid, :oid, :role, :now, :now)
                """).bindparams(id=str(uuid.uuid4()), uid=user.id, oid=org.id, role="owner", now=now)
            )
            created_mem = True
        elif mem_row[1] != "owner":
            await db.execute(
                text("UPDATE organization_memberships SET role = 'owner', updated_at = :now WHERE id = :id")
                .bindparams(id=mem_row[0], now=now)
            )

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
