"""add memory_vectors for multi-replica pgvector memory

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-11-16 00:20:00.000000

Per-agent SQLite vector files only work when every replica sees the same
filesystem, which production does not. This table is the Postgres store used
when the database is Postgres; SQLite deployments keep their per-agent files
and never touch it, so the DDL is skipped there.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE memory_vectors (
            id varchar(36) PRIMARY KEY,
            org_id varchar(36) NOT NULL REFERENCES organizations(id),
            agent_id varchar(36) NOT NULL REFERENCES agents(id),
            content text NOT NULL,
            embedding vector(384) NOT NULL,
            usage_count integer NOT NULL DEFAULT 0,
            success_count integer NOT NULL DEFAULT 0,
            last_used timestamp,
            created_at timestamp NOT NULL,
            content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
        )
        """
    )
    op.execute("CREATE INDEX ix_memory_vectors_agent_created ON memory_vectors (agent_id, created_at DESC)")
    op.execute("CREATE INDEX ix_memory_vectors_org ON memory_vectors (org_id)")
    op.execute("CREATE INDEX ix_memory_vectors_tsv ON memory_vectors USING gin (content_tsv)")
    op.execute(
        "CREATE INDEX ix_memory_vectors_embedding ON memory_vectors"
        " USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS memory_vectors")
