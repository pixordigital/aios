"""pgvector index for governed KnowledgeRecords (ACL checked before ranking)."""

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"

from alembic import op


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE TABLE knowledge_vectors (
            record_id varchar(36) PRIMARY KEY REFERENCES knowledge_records(id) ON DELETE CASCADE,
            org_id varchar(36) NOT NULL REFERENCES organizations(id),
            embedding vector(384) NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_knowledge_vectors_org ON knowledge_vectors (org_id)")
    op.execute(
        "CREATE INDEX ix_knowledge_vectors_embedding ON knowledge_vectors"
        " USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS knowledge_vectors")
