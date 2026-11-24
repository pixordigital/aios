"""Durable org-scoped ICM side-effect idempotency model.

Kept out of aios.db.models so this slice does not collide with concurrent
schema work. Table DDL lives in alembic/versions/icm_side_effect_dedupe.py.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aios.db.engine import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ICMSideEffect(Base):
    """One durable claim per (org_id, idempotency_key), across runs/restarts."""

    __tablename__ = "icm_side_effects"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_icm_side_effects_org_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    stage_id: Mapped[str] = mapped_column(String(100), default="")
    run_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
