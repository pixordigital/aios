#!/usr/bin/env python3
"""Wire an existing Slack ChannelConnection as the owner's 1:1 DM target.

Idempotent, dry-run by default. Reads/decrypts the stored config with the
existing secret helpers, adds ``slack_1on1`` + ``slack_user_id``, re-encrypts
the whole config, and verifies with the real ``human_slack_targets()`` query
against the edited row. No Slack API call, no credential printed.

    python scripts/wire_owner_dm.py --org-id <uuid> \
        --channel "<ChannelConnection label or id>" --slack-user-id U123ABC
    # add --apply to persist (writes a JSON backup first)
"""

import argparse
import asyncio
import json
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.core.meetings import human_slack_targets
from aios.core.secrets import decrypt_channel_config, encrypt_channel_config
from aios.db.backend import db_session as real_db_session
from aios.db.models import ChannelConnection, Organization

USER_ID_RE = re.compile(r"^[UW][A-Z0-9]+$")
BACKUP_DIR = "/tmp/opencode"


class WireError(Exception):
    """Operator-facing validation/verification failure."""


def _mask(value: str) -> str:
    value = str(value or "")
    if not value:
        return "<empty>"
    return "***" + value[-4:] if len(value) > 4 else "****"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _ReadOnlyDB:
    """Only what human_slack_targets() uses: execute() -> scalars().all()."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):
        return _Rows(self._rows)


async def _verify_dm(org_id: str, conn) -> int:
    """Real human_slack_targets() against the edited row, in memory only.

    Keeps the DM-only filter intact: a false positive here would be a report
    sent to a team room. No commit, no network — safe under --dry-run.
    """
    import aios.db.backend as backend

    @asynccontextmanager
    async def _edited_row():
        yield _ReadOnlyDB([conn])

    saved = backend.db_session
    backend.db_session = _edited_row
    try:
        targets = await human_slack_targets(org_id)
    finally:
        backend.db_session = saved

    channel = decrypt_channel_config(conn.config or {}).get("slack_channel_id")
    usable = [t for t in targets if t.get("token") and t.get("channel") == channel]
    if not usable:
        raise WireError("verification failed: human_slack_targets() found no usable owner DM")
    return len(usable)


def _write_backup(path: str, org_id: str, conn, raw_config: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "org_id": org_id,
        "connection": {
            "id": conn.id,
            "label": conn.label,
            "channel_type": conn.channel_type,
            "config": raw_config,
        },
        "note": "config as stored; secret values are ciphertext",
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
    return path


async def wire(org_id: str, channel: str, slack_user_id: str,
               apply: bool = False, backup_path: str | None = None) -> dict:
    if not USER_ID_RE.fullmatch(slack_user_id):
        raise WireError("--slack-user-id must be a Slack user ID like U123ABC")

    async with real_db_session() as db:
        orgs = (await db.execute(
            select(Organization).where(Organization.id == org_id)
        )).scalars().all()
        if not any(o.id == org_id for o in orgs):
            raise WireError(f"org not found: {org_id}")

        conns = (await db.execute(
            select(ChannelConnection).where(ChannelConnection.org_id == org_id)
        )).scalars().all()
        matches = [
            c for c in conns
            if c.org_id == org_id and (c.id == channel or c.label == channel)
        ]
        if not matches:
            raise WireError(f"no ChannelConnection {channel!r} in org {org_id}")
        if len(matches) > 1:
            raise WireError(f"ambiguous channel {channel!r}: {len(matches)} connections matched")
        conn = matches[0]
        if conn.channel_type != "slack":
            raise WireError(f"connection {channel!r} is {conn.channel_type!r}, not slack")
        if not conn.is_active:
            raise WireError(f"connection {channel!r} is inactive")

        raw_config = dict(conn.config or {})
        cfg = decrypt_channel_config(raw_config)
        if not cfg.get("slack_channel_id") or not cfg.get("bot_token"):
            raise WireError(
                "connection needs slack_channel_id and bot_token in config; "
                "refusing to invent credentials"
            )
        desired = dict(cfg)
        desired["slack_1on1"] = True
        desired["slack_user_id"] = slack_user_id
        unchanged = (
            cfg.get("slack_1on1") is True
            and cfg.get("slack_user_id") == slack_user_id
        )

        backup = None
        if apply and not unchanged:
            backup = backup_path or os.path.join(
                BACKUP_DIR, f"wire_owner_dm_{org_id}_{conn.id}.json"
            )
            _write_backup(backup, org_id, conn, raw_config)
        if not unchanged:
            conn.config = encrypt_channel_config(desired)

        try:
            targets = await _verify_dm(org_id, conn)
        except WireError:
            await db.rollback()
            raise

        report = {
            "org_id": org_id,
            "connection": {
                "id": conn.id,
                "label": conn.label,
                "channel_type": conn.channel_type,
            },
            "slack_channel_id": desired["slack_channel_id"],
            "slack_user_id": _mask(slack_user_id),
            "bot_token": "<encrypted>" if str(desired["bot_token"]).startswith("enc:") else "<set>",
            "verified_dm_targets": targets,
            "backup": backup,
        }
        if unchanged:
            report["mode"] = "unchanged"
            await db.rollback()
        elif apply:
            report["mode"] = "apply"
            await db.commit()
        else:
            report["mode"] = "dry-run"
            await db.rollback()
        return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--channel", required=True,
                        help="existing Slack ChannelConnection label or id")
    parser.add_argument("--slack-user-id", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default; no DB write")
    mode.add_argument("--apply", action="store_true", help="persist config change")
    parser.add_argument("--backup", help="backup JSON path (apply only)")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(wire(
            args.org_id, args.channel, args.slack_user_id,
            apply=args.apply, backup_path=args.backup,
        ))
    except WireError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
