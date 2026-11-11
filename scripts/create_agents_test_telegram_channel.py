#!/usr/bin/env python3
"""Create a dedicated Telegram test channel for agent testing.

This script inserts a *ChannelConnection* row of type ``telegram`` with the
identifier ``agents-test-telegram-s9``.  The ``config`` contains placeholder
fields that you can fill in later via the Dashboard UI (or by editing the
row directly in the DB).

Usage:
    $ python scripts/create_agents_test_telegram_channel.py

The script is safe to run multiple times – it will *upsert* the record.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aios.db.backend import db_session
from aios.db.models import ChannelConnection

async def main():
    org_id = os.getenv("AIOS_TEST_ORG", "test-org")
    placeholder_cfg = {"bot_token": "", "chat_id": ""}
    async with db_session() as db:
        # Look for an existing telegram connection for this org using SQLAlchemy Core
        from sqlalchemy import select, update, insert
        stmt = select(ChannelConnection.id).where(
            ChannelConnection.org_id == org_id,
            ChannelConnection.channel_type == "telegram",
        )
        result = await db.execute(stmt)
        row = result.first()
        if row:
            # Update existing record
            upd = (
                update(ChannelConnection)
                .where(ChannelConnection.id == row[0])
                .values(config=placeholder_cfg, label="agents-test-telegram-s9", is_active=True)
            )
            await db.execute(upd)
        else:
            # Insert a new record
            ins = insert(ChannelConnection).values(
                org_id=org_id,
                channel_type="telegram",
                label="agents-test-telegram-s9",
                is_active=True,
                config=placeholder_cfg,
            )
            await db.execute(ins)
        await db.commit()
        print(f"✅ Test Telegram channel 'agents-test-telegram-s9' created for org '{org_id}'.")

if __name__ == "__main__":
    asyncio.run(main())

