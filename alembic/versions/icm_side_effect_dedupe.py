"""Durable org-scoped ICM side-effect idempotency claims.

ICM side effects used to be deduped only in run outputs / in-memory state, so
they duplicated across runs and process restarts. One row per (org, key) is the
durable audit boundary.

Downgrade drops the table only when this revision recorded creating it in
_aios_migration_owned_objects. Schema provisioned by create_all is never
recorded, so rollback cannot delete pre-existing claims.
"""

revision = "f0e1d2c3b4a5"
down_revision = "d0e1f2a3b4c5"

from alembic import op
import sqlalchemy as sa

TABLE = "icm_side_effects"
UQ = "uq_icm_side_effects_org_key"
OWNED_TABLE = "_aios_migration_owned_objects"


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {i["name"] for i in _inspector().get_indexes(table)}


def _owned_table() -> sa.Table:
    return sa.table(
        OWNED_TABLE,
        sa.column("revision", sa.String(36)),
        sa.column("object_key", sa.String(255)),
    )


def _ensure_owned_table() -> None:
    if _has_table(OWNED_TABLE):
        return
    op.create_table(
        OWNED_TABLE,
        sa.Column("revision", sa.String(36), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.UniqueConstraint("revision", "object_key", name="uq_migration_owned_object"),
    )


def _owned(rev: str) -> set[str]:
    if not _has_table(OWNED_TABLE):
        return set()
    marker = _owned_table()
    rows = op.get_bind().execute(sa.select(marker.c.object_key).where(marker.c.revision == rev))
    return {row[0] for row in rows}


def _record(rev: str, key: str) -> None:
    _ensure_owned_table()
    if key in _owned(rev):
        return
    op.get_bind().execute(_owned_table().insert().values(revision=rev, object_key=key))


def _drop_owned_table_if_empty() -> None:
    if not _has_table(OWNED_TABLE):
        return
    marker = _owned_table()
    if op.get_bind().execute(sa.select(sa.literal(1)).select_from(marker)).first():
        return
    op.drop_table(OWNED_TABLE)


def upgrade():
    if not _has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("idempotency_key", sa.String(64), nullable=False),
            sa.Column("stage_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("run_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "idempotency_key", name=UQ),
        )
        _record(revision, f"table:{TABLE}")

    # Pre-existing table (create_all or partial upgrade) still needs the guard.
    if UQ not in {u["name"] for u in _inspector().get_unique_constraints(TABLE) if u.get("name")}:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(TABLE) as batch:
                batch.create_unique_constraint(UQ, ["org_id", "idempotency_key"])
        else:
            op.create_unique_constraint(UQ, TABLE, ["org_id", "idempotency_key"])

    for name, columns in (
        ("ix_icm_side_effects_org_id", ["org_id"]),
        ("ix_icm_side_effects_created_at", ["created_at"]),
    ):
        if name not in _indexes(TABLE):
            op.create_index(name, TABLE, columns)


def downgrade():
    owned = _owned(revision)
    if not owned:  # no marker: this revision created nothing (or already rolled back)
        return
    if f"table:{TABLE}" in owned and _has_table(TABLE):
        op.drop_table(TABLE)
    marker = _owned_table()
    op.get_bind().execute(marker.delete().where(marker.c.revision == revision))
    _drop_owned_table_if_empty()
