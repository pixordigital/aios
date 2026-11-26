#!/usr/bin/env python3
"""Add Ricard.Spinellis@icloud.com: member on org pixor, owner on org showcar.

Idempotent. Creates user with bcrypt password if missing; ensures memberships.

Run inside app container / deployment environment:
    python scripts/add_ricard_user.py
"""
import asyncio

import bcrypt
from sqlalchemy import func, select

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import Organization, OrganizationMembership, User

EMAIL = "Ricard.Spinellis@icloud.com"
PASSWORD = "Ricardo@aios123-"
MEMBERSHIPS = [("pixor", "member"), ("showcar", "owner")]


async def main() -> int:
    async with db_session() as db:
        user = (await db.execute(select(User).where(func.lower(User.email) == EMAIL.lower()))).scalars().first()
        created_user = False
        if not user:
            org = (await db.execute(select(Organization).where(Organization.slug == "showcar"))).scalars().first()
            user = User(
                email=EMAIL,
                hashed_password=bcrypt.hashpw(PASSWORD.encode()[:72], bcrypt.gensalt(rounds=settings.password_bcrypt_rounds)).decode("utf-8"),
                org_id=org.id,
                role="admin",
            )
            db.add(user)
            await db.flush()
            created_user = True

        created = {}
        for slug, role in MEMBERSHIPS:
            org = (await db.execute(select(Organization).where(Organization.slug == slug))).scalars().first()
            if not org:
                print(f"ERROR:org_not_found slug={slug}")
                await db.rollback()
                return 2
            mem = (await db.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.org_id == org.id,
                )
            )).scalars().first()
            if not mem:
                mem = OrganizationMembership(user_id=user.id, org_id=org.id, role=role)
                db.add(mem)
                await db.flush()
            elif mem.role != role:
                mem.role = role
            created[slug] = role

        await db.commit()
        print(
            f"OK user_id={user.id} email={user.email} created_user={created_user} "
            + " ".join(f"org_slug={slug} role={role}" for slug, role in MEMBERSHIPS)
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
