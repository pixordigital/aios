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

        org_id, user_id = org.id, user.id
        if created_org:
            await db.commit()
        now = datetime.now(timezone.utc)
        created_mem = False
        try:
            mem_row = (await db.execute(
                text("SELECT id, role FROM organization_memberships WHERE user_id = :uid AND org_id = :oid LIMIT 1")
                .bindparams(uid=user_id, oid=org_id)
            )).first()
        except Exception:
            await db.rollback()
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS organization_memberships (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                    role VARCHAR(50) NOT NULL DEFAULT 'admin',
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    CONSTRAINT uq_org_membership_user_org UNIQUE (user_id, org_id)
                )
            """))
            await db.execute(text("CREATE INDEX IF NOT EXISTS ix_org_memberships_user_id ON organization_memberships (user_id)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS ix_org_memberships_org_id ON organization_memberships (org_id)"))
            await db.commit()
            org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
            mem_row = (await db.execute(
                text("SELECT id, role FROM organization_memberships WHERE user_id = :uid AND org_id = :oid LIMIT 1")
                .bindparams(uid=user_id, oid=org_id)
            )).first()
        if not mem_row:
            await db.execute(
                text("""
                    INSERT INTO organization_memberships (id, user_id, org_id, role, created_at, updated_at)
                    VALUES (:id, :uid, :oid, :role, :now, :now)
                """).bindparams(id=str(uuid.uuid4()), uid=user_id, oid=org_id, role="owner", now=now)
            )
            created_mem = True
        elif mem_row[1] != "owner":
            await db.execute(
                text("UPDATE organization_memberships SET role = 'owner', updated_at = :now WHERE id = :id")
                .bindparams(id=mem_row[0], now=now)
            )

        org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
        extra = dict((org.extra_data if org else None) or {})
        if not extra.get("founder_user_id"):
            extra["founder_user_id"] = user_id
            if org:
                org.extra_data = extra
        await db.commit()
        print(
            "OK "
            f"org_id={org_id} org_slug={ORG_SLUG} "
            f"created_org={created_org} "
            f"owner_user_id={user_id} owner_email={OWNER_EMAIL} "
            f"created_membership={created_mem} membership_role=owner"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
