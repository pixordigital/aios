"""agents: strip phantom tool names from the tools JSON array

Six templates listed a literal "tools" that was never a registered tool, and
the three lojista solution packs listed a "crm" that never existed at all.
ToolEngine skips unknown names, so affected agents were not crashing -- but
they logged a warning on every construction, and the lojista packs had also
discarded their template's real tools entirely.

The templates are fixed in code. This repairs rows already written, so an
agent created by the wizard before the fix does not keep a dead entry forever.
JSON arrays are rewritten in place, order preserved. Idempotent: a row with
no phantom is left byte-identical.
"""

revision = "y5z6a7b8c9d0"
down_revision = "x4y5z6a7b8c9"

import json

from alembic import op
import sqlalchemy as sa

TABLE = "agents"
PHANTOMS = ("tools", "crm")


def _clean(value):
    """Return the cleaned list, or None when there is nothing to change."""
    if not isinstance(value, list):
        return None
    kept = [t for t in value if t not in PHANTOMS]
    if len(kept) == len(value):
        return None
    return kept


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT id, tools FROM {TABLE} WHERE tools IS NOT NULL")
    ).fetchall()
    if not rows:
        return
    for row in rows:
        try:
            current = json.loads(row.tools) if isinstance(row.tools, str) else row.tools
        except (TypeError, ValueError):
            # not JSON we can reason about -- leave it for a human
            continue
        cleaned = _clean(current)
        if cleaned is None:
            continue
        # The read side above already handles `tools` coming back parsed (which
        # is what Postgres does for a JSON column), but the write always sent
        # json.dumps(...). asyncpg then encoded that string again, storing
        # "[\"http_get\"]" -- a JSON *string* -- instead of the array. The agent
        # runtime would iterate it character by character and the API would fail
        # Pydantic validation. Bind the object itself on Postgres and the
        # pre-serialised text on SQLite (which has no JSON bind codec).
        payload = cleaned if bind.dialect.name == "postgresql" else json.dumps(cleaned)
        bind.execute(
            sa.text(f"UPDATE {TABLE} SET tools = :tools WHERE id = :id"),
            {"tools": payload, "id": row.id},
        )


def downgrade():
    # No way to know which "crm" was meant, and re-adding a dead name would
    # just restore the bug. The data fix is intentionally one-way.
    pass
