#!/usr/bin/env python3
"""Remove user by email: memberships + refresh tokens + user.

Idempotent.

Run inside app container / deployment environment:
    python scripts/remove_user.py
"""
import asyncio

from sqlalchemy import delete, select

from aios.db.backend import db_session
from aios.db.models import OrganizationMembership, RefreshToken, User


async def main() -> int:
    async with db_session() as db:
        user = (await db.execute(select(User).where(User.email == "Ricard.Spinellis@icloud.com"))).scalars().first()
        if not user:
            print("OK user_not_found email=Ricard.Spinellis@icloud.com")
            return 0
        await db.execute(delete(OrganizationMembership).where(OrganizationMembership.user_id == user.id))
        await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
        await db.delete(user)
        await db.commit()
        print(f"OK removed user_id={user.id} email={user.email}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
