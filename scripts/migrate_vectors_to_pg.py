"""Copy per-agent SQLite vector memories into Postgres `memory_vectors`.

Idempotent: rows are inserted with their original id, and `ON CONFLICT DO
NOTHING` means a second run adds nothing. Run after `alembic upgrade head` and
before switching `AIOS_VECTOR_BACKEND` away from `sqlite`:

    python scripts/migrate_vectors_to_pg.py --dry-run
    python scripts/migrate_vectors_to_pg.py

Reads `settings.app_data_dir/vectors/*.db` by default; pass a directory to
migrate a copy (e.g. an extracted backup).
"""

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import text

from aios.config import settings
from aios.db.engine import async_session, engine


def _read_store(path: Path) -> tuple[list[dict], dict[str, dict]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        memories = [
            {"id": r[0], "embedding": r[1], "content": r[2], "created_at": r[3]}
            for r in conn.execute("SELECT id, embedding, content, created_at FROM memories")
        ]
        stats = {
            r[0]: {"usage_count": r[1], "success_count": r[2], "last_used": r[3]}
            for r in conn.execute(
                "SELECT id, usage_count, success_count, last_used FROM memory_stats"
            )
        }
        return memories, stats
    finally:
        conn.close()


def _vec_literal(emb: str) -> str | None:
    try:
        values = json.loads(emb)
    except (TypeError, ValueError):
        return None
    if len(values) != 384:
        return None
    return "[" + ",".join(f"{float(v):.7f}" for v in values) + "]"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(Path(settings.app_data_dir) / "vectors"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not engine.dialect.name.startswith("postgres"):
        print("refusing to run: AIOS_DATABASE_URL is not Postgres")
        return 2

    source = Path(args.source)
    files = sorted(source.glob("*.db"))
    read = inserted = skipped = 0

    async with async_session() as session:
        agents = {
            r.id: r.org_id
            for r in await session.execute(text("SELECT id, org_id FROM agents"))
        }

        for path in files:
            agent_id = path.stem
            org_id = agents.get(agent_id)
            if not org_id:
                skipped += 1
                continue
            try:
                memories, stats = _read_store(path)
            except sqlite3.DatabaseError:
                skipped += 1
                continue
            for m in memories:
                read += 1
                embedding = _vec_literal(m["embedding"])
                if embedding is None:
                    skipped += 1
                    continue
                if args.dry_run:
                    continue
                stat = stats.get(m["id"], {})
                result = await session.execute(
                    text(
                        "INSERT INTO memory_vectors"
                        " (id, org_id, agent_id, content, embedding, usage_count,"
                        " success_count, last_used, created_at)"
                        " VALUES (:id, :org, :agent, :content, CAST(:emb AS vector),"
                        " :usage, :success, :last_used, :created_at)"
                        " ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": m["id"],
                        "org": org_id,
                        "agent": agent_id,
                        "content": m["content"],
                        "emb": embedding,
                        "usage": stat.get("usage_count") or 0,
                        "success": stat.get("success_count") or 0,
                        "last_used": stat.get("last_used"),
                        "created_at": m["created_at"],
                    },
                )
                inserted += result.rowcount or 0
        if not args.dry_run:
            await session.commit()

    print(
        f"files={len(files)} memories_read={read} inserted={inserted}"
        f" skipped={skipped} dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
