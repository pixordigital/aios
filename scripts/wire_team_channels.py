#!/usr/bin/env python3
"""Wire existing ChannelConnection labels to teams. Idempotent, explicit-only.

Only ``team_id`` and ``is_active`` are changed. ``config`` is never read for
output or written back, so tokens cannot leak to stdout or the backup file.
Dry-run is the default; pass ``--apply`` to mutate.

Mapping format (JSON object or Python Mapping): label -> {
  "team": "<Team.name key>",   # or "team_id": "<Team.id uuid>"
  "is_active": true|false      # required, strict bool
}

Recommended mapping from the channel audit. Labels must match the exact
``ChannelConnection.label`` values; these are the short forms from the audit,
so confirm them with a dry-run first. Mismatches are refused, never guessed:

    {
      "WhatsApp":             {"team": "sales", "is_active": true},
      "#dept-sales":          {"team": "sales", "is_active": true},
      "#dept-engineering":    {"team": "dev",   "is_active": true},
      "#dept-data":           {"team": "data",  "is_active": true},
      "#dept-media-growth":   {"team": "media", "is_active": true},
      "#security-incidents":  {"team": "red",   "is_active": true},
      "#security-monitoring": {"team": "blue",  "is_active": true},
      "#red-team":            {"team": "red",   "is_active": true},
      "#blue-team":           {"team": "blue",  "is_active": true}
    }

The red/blue entries activate the currently inactive security channels. No
channel is given ``slack_1on1`` here; that missing config key separately breaks
``notify_human`` and is out of scope.

Usage:
    python scripts/wire_team_channels.py --org-id <org-uuid> \
        --mapping-file /tmp/opencode/team_channel_map.json
    python scripts/wire_team_channels.py --org-id <org-uuid> \
        --mapping-file /tmp/opencode/team_channel_map.json \
        --apply --backup /tmp/opencode/team_channel_backup.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.db.models import ChannelConnection, Team


class WireError(ValueError):
    """Refuse to touch the DB when input or ownership is not unambiguous."""


@dataclass(frozen=True)
class ChannelSpec:
    team_key: str | None
    team_id: str | None
    is_active: bool


@dataclass
class Change:
    label: str
    channel: ChannelConnection
    team: Team
    is_active: bool
    current_team_id: str | None
    current_is_active: bool

    @property
    def changed(self) -> bool:
        return (
            self.current_team_id != self.team.id
            or self.current_is_active != self.is_active
        )

    def report(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "team": self.team.name,
            "team_id": self.team.id,
            "is_active": self.is_active,
            "changed": self.changed,
        }


def normalize_mapping(raw: Any) -> dict[str, ChannelSpec]:
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise WireError(f"mapping is not valid JSON: {exc}") from exc
    if not isinstance(raw, Mapping) or not raw:
        raise WireError("mapping must be a non-empty JSON object")

    specs: dict[str, ChannelSpec] = {}
    for raw_label, item in raw.items():
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise WireError(f"invalid channel label: {raw_label!r}")
        label = raw_label.strip()
        if label in specs:
            raise WireError(f"duplicate channel label in mapping: {label!r}")
        if not isinstance(item, Mapping):
            raise WireError(f"{label!r}: value must be an object")

        allowed = {"team", "team_key", "team_id", "is_active"}
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise WireError(f"{label!r}: unknown field(s): {', '.join(unknown)}")

        refs = [
            (field, item[field])
            for field in ("team", "team_key", "team_id")
            if field in item and item[field] is not None
        ]
        if len(refs) != 1:
            raise WireError(
                f"{label!r}: set exactly one of 'team' (Team.name key) or 'team_id'"
            )
        ref_name, ref_value = refs[0]
        if not isinstance(ref_value, str) or not ref_value.strip():
            raise WireError(f"{label!r}: {ref_name} must be a non-empty string")

        if "is_active" not in item or type(item["is_active"]) is not bool:
            raise WireError(f"{label!r}: is_active must be a strict boolean")

        specs[label] = ChannelSpec(
            team_key=ref_value.strip() if ref_name != "team_id" else None,
            team_id=ref_value.strip() if ref_name == "team_id" else None,
            is_active=item["is_active"],
        )
    return specs


def load_mapping_file(path: str | Path) -> dict[str, ChannelSpec]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise WireError(f"cannot read mapping file {path}: {exc}") from exc
    except ValueError as exc:
        raise WireError(f"mapping file {path} is not valid JSON: {exc}") from exc
    return normalize_mapping(raw)


async def build_plan(db, org_id: str, mapping: Any) -> list[Change]:
    """Resolve labels/teams in the target org. Read-only."""
    specs = normalize_mapping(mapping)

    channels = (
        await db.execute(
            select(ChannelConnection).where(ChannelConnection.org_id == org_id)
        )
    ).scalars().all()
    by_label: dict[str, list[ChannelConnection]] = {}
    for channel in channels:
        by_label.setdefault(channel.label or "", []).append(channel)

    teams = (
        await db.execute(select(Team).where(Team.org_id == org_id))
    ).scalars().all()
    by_name: dict[str, list[Team]] = {}
    by_id: dict[str, list[Team]] = {}
    for team in teams:
        by_name.setdefault(team.name, []).append(team)
        by_id.setdefault(team.id, []).append(team)

    plan: list[Change] = []
    for label, spec in specs.items():
        rows = by_label.get(label, [])
        if not rows:
            raise WireError(f"unknown channel label {label!r} in org {org_id!r}")
        if len(rows) > 1:
            raise WireError(
                f"ambiguous channel label {label!r}: {len(rows)} rows in org {org_id!r}"
            )
        channel = rows[0]
        if str(channel.org_id) != str(org_id):
            raise WireError(f"channel {label!r} belongs to another org; refusing")

        if spec.team_key is not None:
            teams_for_ref = by_name.get(spec.team_key, [])
            ref = f"team key {spec.team_key!r}"
        else:
            teams_for_ref = by_id.get(spec.team_id or "", [])
            ref = f"team id {spec.team_id!r}"
        if not teams_for_ref:
            raise WireError(f"unknown {ref} in org {org_id!r}")
        if len(teams_for_ref) > 1:
            raise WireError(f"ambiguous {ref} in org {org_id!r}")
        team = teams_for_ref[0]
        if str(team.org_id) != str(org_id):
            raise WireError(f"team {team.name!r} belongs to another org; refusing")

        plan.append(
            Change(
                label=label,
                channel=channel,
                team=team,
                is_active=spec.is_active,
                current_team_id=channel.team_id,
                current_is_active=bool(channel.is_active),
            )
        )
    return plan


def default_backup_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return Path(tempfile.gettempdir()) / f"wire_team_channels-{stamp}-{uuid.uuid4().hex[:8]}.json"


def write_backup(path: str | Path, org_id: str, plan: list[Change]) -> Path:
    """Write a secret-free snapshot before any DB attribute is touched."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "org_id": org_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rows": [
            {
                "id": c.channel.id,
                "label": c.label,
                "channel_type": c.channel.channel_type,
                "org_id": c.channel.org_id,
                "team_id": c.channel.team_id,
                "is_active": bool(c.channel.is_active),
            }
            for c in plan
        ],
    }
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return target


async def execute_plan(
    db,
    org_id: str,
    plan: list[Change],
    *,
    apply: bool,
    backup: str | Path | None = None,
    emit=print,
) -> int:
    for change in plan:
        emit(json.dumps(change.report(), sort_keys=True, ensure_ascii=False))

    to_apply = [c for c in plan if c.changed]
    if not apply:
        emit(f"DRY-RUN: {len(to_apply)} of {len(plan)} row(s) would change; no writes, no backup.")
        return 0
    if not to_apply:
        emit("APPLY: no changes; no backup written.")
        return 0

    backup_path = write_backup(backup or default_backup_path(), org_id, plan)
    emit(f"Backup written: {backup_path}")

    for change in to_apply:
        change.channel.team_id = change.team.id
        change.channel.is_active = change.is_active
    await db.commit()
    emit(f"APPLY: committed {len(to_apply)} row(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True, help="Organization that owns every row")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mapping", help="Inline JSON object of label -> team spec")
    source.add_argument("--mapping-file", help="Path to JSON mapping file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Default; no DB writes")
    mode.add_argument("--apply", action="store_true", help="Persist changes after backup")
    parser.add_argument("--backup", help="Backup JSON path (default: temp dir, unique)")
    return parser


async def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from aios.db.backend import db_session

    mapping = args.mapping if args.mapping is not None else load_mapping_file(args.mapping_file)
    async with db_session() as db:
        plan = await build_plan(db, args.org_id, mapping)
        return await execute_plan(
            db, args.org_id, plan, apply=args.apply, backup=args.backup
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
