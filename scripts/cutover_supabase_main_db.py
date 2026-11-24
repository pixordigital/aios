#!/usr/bin/env python3
"""Read-only guard for Supabase becoming the AIOS main DB.

Checks DSN shape, bridge reachability, schema, version row, code head and
pgvector. Never writes to the database and never prints credentials.

Usage:
  AIOS_SUPABASE_DATABASE_URL='postgresql+asyncpg://...' \
    python scripts/cutover_supabase_main_db.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "aios-supabase-db-8778"
DEFAULT_SCHEMA = "aios"
DEFAULT_DB = "aios"
DEFAULT_USER = "postgres"
DEFAULT_PRE_REVISION = "e7f8a9b0c1d2"
DEFAULT_HEAD = "e1f2a3b4c5d6"
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GuardFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class Dsn:
    scheme: str
    user: str
    password: str
    host: str
    port: int
    database: str

    def redacted(self) -> str:
        return (
            f"{self.scheme}://{self.user}:***@{self.host}:{self.port}/{self.database}"
        )


def parse_dsn(dsn: str) -> Dsn:
    split = urlsplit(dsn)
    if split.scheme != "postgresql+asyncpg":
        raise GuardFailure("DSN scheme must be postgresql+asyncpg")
    if "@" not in split.netloc:
        raise GuardFailure("DSN must contain user:password@host")
    userinfo, hostpart = split.netloc.rsplit("@", 1)
    user, sep, password = userinfo.partition(":")
    if not sep:
        raise GuardFailure("DSN password missing")
    host, port_sep, port = hostpart.rpartition(":")
    if not port_sep:
        host, port = hostpart, "5432"
    database = unquote(split.path.lstrip("/"))
    if not all((user, password, host, database)):
        raise GuardFailure("DSN user/password/host/database must be non-empty")
    try:
        port_int = int(port)
    except ValueError as exc:
        raise GuardFailure("DSN port must be numeric") from exc
    return Dsn(
        scheme=split.scheme,
        user=unquote(user),
        password=unquote(password),
        host=host,
        port=port_int,
        database=database,
    )


def scrub(message: str, secrets: list[str]) -> str:
    text = message
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def fail(message: str, secrets: list[str]) -> "NoReturn":  # type: ignore[name-defined]
    raise GuardFailure(scrub(message, secrets))


def code_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        raise GuardFailure(
            f"code has {len(heads)} Alembic heads ({', '.join(heads)}); expected one"
        )
    return heads[0]


def ident(name: str) -> str:
    if not IDENT_RE.match(name):
        raise GuardFailure(f"unsafe SQL identifier: {name!r}")
    return f'"{name}"'


async def read_db(dsn: Dsn, schema: str, secrets: list[str]) -> dict[str, object]:
    import asyncpg

    try:
        conn = await asyncpg.connect(
            user=dsn.user,
            password=dsn.password,
            host=dsn.host,
            port=dsn.port,
            database=dsn.database,
            ssl=False,
            timeout=5.0,
        )
    except Exception as exc:
        fail(f"cannot connect to {dsn.redacted()}: {exc}", secrets)

    try:
        schema_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = $1)", schema
        )
        if not schema_exists:
            fail(f"schema {schema!r} is missing on target DB", secrets)

        usage, create = await conn.fetchrow(
            "SELECT has_schema_privilege(current_user, $1, 'USAGE'), "
            "has_schema_privilege(current_user, $1, 'CREATE')",
            schema,
        )
        vector = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = $1 AND tablename LIKE 'alembic_version%' "
            "ORDER BY tablename",
            schema,
        )
        versions: dict[str, str] = {}
        for row in rows:
            table = row["tablename"]
            values = await conn.fetch(
                f"SELECT version_num FROM {ident(schema)}.{ident(table)}"
            )
            if len(values) != 1:
                fail(
                    f"{schema}.{table} has {len(values)} version rows; expected 1",
                    secrets,
                )
            versions[table] = values[0]["version_num"]
        return {
            "usage": bool(usage),
            "create": bool(create),
            "vector": bool(vector),
            "versions": versions,
        }
    finally:
        await conn.close()


def evaluate_versions(
    versions: dict[str, str], expected_pre: str, expected_head: str, secrets: list[str]
) -> str:
    if not versions:
        fail(f"no alembic_version table found in schema {DEFAULT_SCHEMA!r}", secrets)
    new = versions.get("alembic_version_aios")
    legacy = versions.get("alembic_version")

    if new == expected_head:
        if legacy is not None and legacy != expected_head:
            fail(
                "aios.alembic_version_aios is at head but legacy aios.alembic_version "
                f"is {legacy}; stale version table — human review required",
                secrets,
            )
        return "head"
    if new == expected_pre:
        if legacy is not None and legacy != expected_pre:
            fail(f"version tables disagree: {versions}", secrets)
        return "pre"
    if new is None and legacy == expected_pre:
        print(
            "WARN: only legacy aios.alembic_version found; upgrade must create "
            "aios.alembic_version_aios"
        )
        return "pre"
    fail(f"unsupported alembic version state: {versions}", secrets)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-host", default=os.getenv("AIOS_CUTOVER_EXPECTED_HOST", DEFAULT_HOST))
    parser.add_argument("--expected-schema", default=os.getenv("AIOS_CUTOVER_EXPECTED_SCHEMA", DEFAULT_SCHEMA))
    parser.add_argument("--expected-db", default=os.getenv("AIOS_CUTOVER_EXPECTED_DB", DEFAULT_DB))
    parser.add_argument("--expected-user", default=os.getenv("AIOS_CUTOVER_EXPECTED_USER", DEFAULT_USER))
    parser.add_argument("--expected-pre", default=os.getenv("AIOS_CUTOVER_EXPECTED_REVISION", DEFAULT_PRE_REVISION))
    parser.add_argument("--expected-head", default=os.getenv("AIOS_CUTOVER_EXPECTED_HEAD", DEFAULT_HEAD))
    args = parser.parse_args()

    raw = os.environ.get("AIOS_SUPABASE_DATABASE_URL", "")
    if not raw:
        print("FAIL: AIOS_SUPABASE_DATABASE_URL is not set", file=sys.stderr)
        return 1
    secrets = [raw]
    try:
        dsn = parse_dsn(raw)
        secrets.append(dsn.password)
        secrets.append(unquote(dsn.password))

        print(f"DSN: {dsn.redacted()}")
        if dsn.host != args.expected_host:
            fail(f"DSN host is {dsn.host!r}; expected bridge {args.expected_host!r}", secrets)
        if dsn.database != args.expected_db:
            fail(f"DSN database is {dsn.database!r}; expected {args.expected_db!r}", secrets)
        if dsn.user != args.expected_user:
            fail(f"DSN user is {dsn.user!r}; expected {args.expected_user!r}", secrets)

        head = code_head()
        if head != args.expected_head:
            fail(f"code head is {head}; expected {args.expected_head}", secrets)
        print(f"code head: {head}")

        try:
            with socket.create_connection((dsn.host, dsn.port), timeout=5.0):
                pass
        except OSError as exc:
            fail(f"bridge {dsn.host}:{dsn.port} unreachable: {exc}", secrets)
        print(f"bridge TCP: ok ({dsn.host}:{dsn.port})")

        state = asyncio.run(read_db(dsn, args.expected_schema, secrets))
        if not state["usage"] or not state["create"]:
            fail(f"user lacks USAGE/CREATE on schema {args.expected_schema!r}", secrets)
        if not state["vector"]:
            fail("pgvector extension 'vector' is not installed", secrets)

        phase = evaluate_versions(state["versions"], args.expected_pre, args.expected_head, secrets)
        versions = state["versions"]
        print(f"schema {args.expected_schema}: ok; USAGE/CREATE ok; pgvector ok")
        print(f"version rows: {versions}")
        if phase == "head":
            print("PASS: Supabase aios schema already at head; DSN cutover permitted")
        else:
            print(
                "PASS: pre-cutover state confirmed; run 'alembic upgrade head' "
                "before switching app/worker DSN"
            )
        return 0
    except GuardFailure as exc:
        print(f"FAIL: {scrub(str(exc), secrets)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAIL: unexpected error: {scrub(str(exc), secrets)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
