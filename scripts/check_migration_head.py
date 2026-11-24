#!/usr/bin/env python3
"""Preflight: compare a database's alembic version with the migration scripts.

    python scripts/check_migration_head.py --dsn "$AIOS_DATABASE_URL"
    AIOS_DATABASE_URL=postgresql+asyncpg://... python scripts/check_migration_head.py

Reads --dsn or AIOS_DATABASE_URL (DATABASE_URL fallback). Runs no migrations.
Postgres reads aios.alembic_version_aios, SQLite reads alembic_version --
the same tables as alembic/env.py. Exits 1 on behind/divergent/invalid scripts.
No aios imports: no settings, LLM credentials or app startup needed.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

DEFAULT_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


class PreflightError(Exception):
    """Refusal with a message safe to show to an operator."""


@dataclass(frozen=True)
class Script:
    revision: str
    parents: tuple[str, ...]
    filename: str


def mask_dsn(dsn: str) -> str:
    """Never echo userinfo, query params or a SQLite file path."""
    try:
        parts = urlsplit(dsn)
        if parts.scheme and parts.hostname:
            host = parts.hostname + (f":{parts.port}" if parts.port else "")
            return f"{parts.scheme}://***@{host}"
        if parts.scheme:
            return f"{parts.scheme}://***"
    except ValueError:
        pass
    return "***"


class Reporter:
    """Single sanitization point: driver errors can contain the DSN verbatim."""

    def __init__(self, dsn: str) -> None:
        self._secrets = {dsn}
        try:
            parts = urlsplit(dsn)
            # Username is an identifier (often "postgres") and replacing it
            # would mangle ordinary words in messages; password/query are not.
            for value in (parts.password, parts.query, parts.fragment):
                if value:
                    self._secrets.add(value)
        except ValueError:
            pass

    def clean(self, message: str) -> str:
        for secret in sorted(self._secrets, key=len, reverse=True):
            if secret:
                message = message.replace(secret, "***")
        return message

    def say(self, message: str) -> None:
        print(self.clean(message))


def _literal_assignment(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError) as exc:
                raise PreflightError(f"{name} must be a literal, got {exc}") from exc
    raise PreflightError(f"migration has no {name} assignment")


def load_scripts(directory: Path) -> tuple[dict[str, Script], str]:
    """Parse revision/down_revision from source; no migration imports needed."""
    if not directory.is_dir():
        raise PreflightError(f"script directory not found: {directory}")
    scripts: dict[str, Script] = {}
    for path in sorted(directory.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise PreflightError(f"cannot parse {path.name}: {exc}") from exc
        revision = _literal_assignment(tree, "revision")
        down = _literal_assignment(tree, "down_revision")
        if not isinstance(revision, str) or not revision:
            raise PreflightError(f"{path.name}: invalid revision {revision!r}")
        if down is None:
            parents: tuple[str, ...] = ()
        elif isinstance(down, str):
            parents = (down,)
        elif isinstance(down, (tuple, list)) and all(isinstance(p, str) for p in down):
            parents = tuple(down)
        else:
            raise PreflightError(f"{path.name}: invalid down_revision {down!r}")
        if revision in scripts:
            raise PreflightError(
                f"duplicate revision {revision}: {scripts[revision].filename} and {path.name}"
            )
        scripts[revision] = Script(revision, parents, path.name)

    if not scripts:
        raise PreflightError(f"no migration scripts in {directory}")

    for script in scripts.values():
        for parent in script.parents:
            if parent not in scripts:
                raise PreflightError(
                    f"missing down_revision chain: {script.filename} ({script.revision}) "
                    f"revises unknown revision {parent}"
                )

    heads = [r for r in scripts if r not in {p for s in scripts.values() for p in s.parents}]
    if not heads:
        raise PreflightError("missing down_revision chain: no base revision (cycle in scripts)")
    if len(heads) > 1:
        raise PreflightError(
            f"script directory has multiple heads: {', '.join(sorted(heads))}; "
            "merge them with 'alembic merge' before preflight"
        )
    return scripts, heads[0]


def ancestors(scripts: dict[str, Script], revision: str) -> set[str]:
    """Revisions at or below `revision`, including all merged branches."""
    seen: set[str] = set()
    stack = [revision]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(scripts[current].parents)
    return seen


def version_table(dsn: str) -> str:
    """Match alembic/env.py: Postgres keeps versions in the aios schema."""
    try:
        scheme = urlsplit(dsn).scheme
    except ValueError:
        scheme = ""
    return "aios.alembic_version_aios" if "postgres" in scheme else "alembic_version"


async def read_db_head(dsn: str) -> str | None:
    table = version_table(dsn)
    engine = create_async_engine(dsn, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = (await connection.execute(text(f"SELECT version_num FROM {table}"))).scalars().all()
    finally:
        await engine.dispose()
    rows = [str(row) for row in rows]
    if len(rows) > 1:
        raise PreflightError(f"database has multiple versions in {table}: {', '.join(rows)}")
    return rows[0] if rows else None


def check(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", help="SQLAlchemy DB URL (else AIOS_DATABASE_URL / DATABASE_URL)")
    parser.add_argument("--script-dir", type=Path, default=DEFAULT_SCRIPT_DIR)
    args = parser.parse_args(argv)

    dsn = args.dsn or os.getenv("AIOS_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
    reporter = Reporter(dsn)
    try:
        if not dsn:
            raise PreflightError("no database URL: pass --dsn or set AIOS_DATABASE_URL")
        reporter.say(f"Database: {mask_dsn(dsn)}")
        reporter.say(f"Script dir: {args.script_dir}")

        # Validate scripts before touching the DB: a broken script dir must fail
        # even if the target DB is unreachable or unversioned.
        scripts, head = load_scripts(args.script_dir)
        reporter.say(f"Script head: {head}")

        try:
            current = asyncio.run(read_db_head(dsn))
        except PreflightError:
            raise
        except Exception as exc:
            raise PreflightError(f"cannot read {version_table(dsn)}: {exc}") from exc
        if current is None:
            raise PreflightError(
                f"database has no alembic version in {version_table(dsn)}; "
                "run 'alembic upgrade head' (or stamp) first"
            )
        reporter.say(f"DB head: {current}")

        if current not in scripts:
            raise PreflightError(
                f"database revision {current} is not in the script directory "
                f"(script head {head}); refusing to guess pending migrations"
            )
        to_head = ancestors(scripts, head)
        if current not in to_head:
            raise PreflightError(f"database revision {current} is not on the path to {head}")
        pending = sorted(
            to_head - ancestors(scripts, current),
            key=lambda r: (scripts[r].filename, r),
        )
        if pending:
            reporter.say(f"Pending revisions ({len(pending)}):")
            for revision in pending:
                reporter.say(f"  {revision}  {scripts[revision].filename}")
            raise PreflightError(
                f"database behind script head: {current} -> {head}; "
                "run 'alembic upgrade head' before cutover"
            )
        reporter.say("OK: database head matches script directory head")
        return 0
    except PreflightError as exc:
        print(f"FAIL: {reporter.clean(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(check())
