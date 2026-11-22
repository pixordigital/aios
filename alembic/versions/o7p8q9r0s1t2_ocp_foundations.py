"""OCP foundations: departments, membership, authority, shared tasks, goals,
decisions and organizational events.

Merges the five open heads that existed before this revision so
`alembic upgrade head` has a single target again.
"""

revision = "o7p8q9r0s1t2"
down_revision = (
    "e7f8a9b0c1d2",
    "b1c2d3e4f5a6",
    "r4s5t6u7v8w9",
    "h4b5c6d7e8f9",
    "n3o4p5q6r7s8",
)

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _ts():
    return [
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    ]


def upgrade():
    if not _has_table("departments"):
        op.create_table(
            "departments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(100), nullable=False),
            sa.Column("mission", sa.Text, nullable=False, server_default=""),
            sa.Column("parent_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("extra_data", sa.JSON, nullable=False, server_default="{}"),
            sa.UniqueConstraint("org_id", "slug", name="uq_department_org_slug"),
            *_ts(),
        )
    if not _has_table("department_members"):
        op.create_table(
            "department_members",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=False),
            sa.Column("member_type", sa.String(10), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
            sa.Column("title", sa.String(120), nullable=False, server_default=""),
            sa.Column("is_manager", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("department_id", "user_id", name="uq_dept_member_user"),
            sa.UniqueConstraint("department_id", "agent_id", name="uq_dept_member_agent"),
            sa.Index("ix_dept_member_org_type", "org_id", "member_type"),
            *_ts(),
        )
    if not _has_table("authority_grants"):
        op.create_table(
            "authority_grants",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
            sa.Column("subject_type", sa.String(10), nullable=False),
            sa.Column("subject_id", sa.String(36), nullable=False),
            sa.Column("role", sa.String(120), nullable=False),
            sa.Column("actions", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("resources", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("scope", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("max_decision_level", sa.Integer, nullable=False, server_default="1"),
            sa.Column("valid_from", sa.DateTime, nullable=True),
            sa.Column("valid_until", sa.DateTime, nullable=True),
            sa.Column("revoked_at", sa.DateTime, nullable=True),
            sa.Column("granted_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Index("ix_authority_subject", "org_id", "subject_type", "subject_id"),
            *_ts(),
        )
    if not _has_table("shared_tasks"):
        op.create_table(
            "shared_tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("objective", sa.Text, nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="new"),
            sa.Column("priority", sa.Integer, nullable=False, server_default="3"),
            sa.Column("requesting_department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
            sa.Column("responsible_department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
            sa.Column("owner_type", sa.String(10), nullable=True),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("deadline", sa.DateTime, nullable=True),
            sa.Column("dependencies", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("inputs", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("expected_deliverable", sa.Text, nullable=False, server_default=""),
            sa.Column("permissions", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("budget_id", sa.String(36), sa.ForeignKey("budgets.id"), nullable=True),
            sa.Column("blocked_reason", sa.Text, nullable=False, server_default=""),
            sa.Column("audit_history", sa.JSON, nullable=False, server_default="[]"),
            sa.Index("ix_shared_task_dept_status", "org_id", "responsible_department_id", "status"),
            *_ts(),
        )
    if not _has_table("org_goals"):
        op.create_table(
            "org_goals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("metric_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("baseline", sa.Float, nullable=True),
            sa.Column("target", sa.Float, nullable=True),
            sa.Column("current", sa.Float, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("owner_type", sa.String(10), nullable=True),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("due_at", sa.DateTime, nullable=True),
            *_ts(),
        )
    if not _has_table("decision_records"):
        op.create_table(
            "decision_records",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("level", sa.Integer, nullable=False, server_default="2"),
            sa.Column("change_type", sa.String(80), nullable=False, server_default=""),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
            sa.Column("justification", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("evidence", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("requested_by_type", sa.String(10), nullable=True),
            sa.Column("requested_by_id", sa.String(36), nullable=True),
            sa.Column("decided_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime, nullable=True),
            sa.Column("linked_task_ids", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("confidentiality", sa.String(30), nullable=False, server_default="internal"),
            *_ts(),
        )
    if not _has_table("org_events"):
        op.create_table(
            "org_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("actor_type", sa.String(10), nullable=True),
            sa.Column("actor_id", sa.String(36), nullable=True),
            sa.Column("entity_type", sa.String(50), nullable=False, server_default=""),
            sa.Column("entity_id", sa.String(36), nullable=True),
            sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
            *_ts(),
        )


def downgrade():
    for t in (
        "org_events",
        "decision_records",
        "org_goals",
        "shared_tasks",
        "authority_grants",
        "department_members",
        "departments",
    ):
        if _has_table(t):
            op.drop_table(t)
