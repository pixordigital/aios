"""agents: grant manager/orchestrator agents the collaboration tools

`ask_team_manager` and `notify_human` were added to the manager and
orchestrator templates in code, but an agent's `tools` array is a snapshot
written when the agent row was created. Every manager seeded before this
change keeps its old list forever and simply never sees the new tools.

This adds them to the rows that should have them: agent_type manager /
orchestrator, plus anything actually wired as a team's manager_agent_id (a
team may point at an agent typed something else). Idempotent -- an agent that
already lists a tool is not touched, and order is preserved.

Same JSON bind caveat as y5z6a7b8c9d0: on Postgres the column is sent as the
parsed object, on SQLite as pre-serialised text, or the array is stored as a
JSON *string* and the runtime iterates it character by character.
"""

revision = "m2n3o4p5q6r7"
down_revision = "d9e0f1a2b3c4"

import json

import sqlalchemy as sa

from alembic import op

TABLE = "agents"
GRANTED = ("ask_team_manager", "notify_human")
TYPES = ("manager", "orchestrator")


def _eligible_ids(bind) -> set:
    """Ids of manager/orchestrator agents plus any team's manager_agent_id."""
    ids = set()
    stmt = sa.text(f"SELECT id FROM {TABLE} WHERE agent_type IN :types").bindparams(
        sa.bindparam("types", expanding=True)
    )
    for row in bind.execute(stmt, {"types": list(TYPES)}).fetchall():
        ids.add(row.id)
    try:
        managed = bind.execute(
            sa.text(
                "SELECT manager_agent_id AS id FROM teams "
                "WHERE manager_agent_id IS NOT NULL"
            )
        ).fetchall()
    except sa.exc.SQLAlchemyError:
        # teams table absent (fresh bootstrap): type filter alone is enough.
        managed = []
    ids.update(row.id for row in managed)
    return ids


def _add(current):
    """Return the list with GRANTED appended, or None when nothing to change."""
    if not isinstance(current, list):
        return None
    missing = [t for t in GRANTED if t not in current]
    if not missing:
        return None
    return [*current, *missing]


def upgrade():
    bind = op.get_bind()
    eligible = _eligible_ids(bind)
    if not eligible:
        return
    rows = bind.execute(
        sa.text(f"SELECT id, tools FROM {TABLE} WHERE tools IS NOT NULL")
    ).fetchall()
    for row in rows:
        if row.id not in eligible:
            continue
        try:
            current = json.loads(row.tools) if isinstance(row.tools, str) else row.tools
        except (TypeError, ValueError):
            # not JSON we can reason about -- leave it for a human
            continue
        updated = _add(current)
        if updated is None:
            continue
        # sa.text() carries no column type, so the driver receives the raw
        # Python object. asyncpg cannot encode a list (the Postgres branch
        # used to pass it through), while a JSON string is accepted by both
        # SQLite TEXT and Postgres json columns. Always serialise here.
        payload = json.dumps(updated)
        bind.execute(
            sa.text(f"UPDATE {TABLE} SET tools = :tools WHERE id = :id"),
            {"tools": payload, "id": row.id},
        )


def downgrade():
    # Removing the tools would silently break any manager currently mid-task
    # with them. Agents that still need them keep them until re-seeded.
    pass