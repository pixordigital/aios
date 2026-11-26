#!/usr/bin/env python3
"""List users (id, email, active) for ops debugging.

Idempotent read-only.

Run inside app container / deployment environment:
    python scripts/list_users.py
"""
import asyncio

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import User


async def main() -> int:
    async with db_session() as db:
        users = (await db.execute(select(User.id, User.email, User.is_active))).all()
        for uid, email, active in users:
            print(f"USER id={uid} email={email} active={active}")
        print(f"USER count={len(users)}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
