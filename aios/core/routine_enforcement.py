"""Fail-closed enforcement for routine-triggered side effects.

No routine may trigger external/silent side effects without explicit
approval and idempotency. Unknown policy => deny.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)

ROUTINE_SIDE_EFFECT_APPROVAL_TOOL = "routine_side_effect_approve"


class RoutineSideEffectBlocked(PermissionError):
    """Routine side effect denied by fail-closed policy."""


@dataclass(frozen=True)
class RoutineSideEffectPolicy:
    routine_id: str
    org_id: str | None
    source_type: str
    mode: str
    side_effects: list[str] = field(default_factory=list)
    approval_required: bool = False
    idempotency_key: str = ""
    manifest_fingerprint: str | None = None


def routine_idempotency_key(routine_id: str, action: str, suffix: str = "") -> str:
    raw = f"{routine_id}:{action}:{suffix}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:64]


def _normalize_side_effects(side_effects: list[str] | None) -> list[str]:
    out: list[str] = []
    for s in side_effects or []:
        v = str(s or "").strip()
        if v:
            out.append(v)
    return out


def _routine_marker(row: Any) -> dict | None:
    args = getattr(row, "tool_args", None)
    if not isinstance(args, dict):
        return None
    marker = args.get("_routine_approved_action")
    if not isinstance(marker, dict):
        marker = args.get("_hitl_approved_action")
    return marker if isinstance(marker, dict) else None


def _marker_matches(
    marker: dict,
    *,
    org_id: str,
    routine_id: str,
    action: str,
    idempotency_key: str,
    approval_fingerprint: str | None,
) -> bool:
    if str(marker.get("org_id") or "") != org_id:
        return False
    if str(marker.get("routine_id") or "") not in {"", routine_id}:
        return False
    if str(marker.get("action") or "") not in {"", action}:
        return False
    marker_key = str(marker.get("idempotency_key") or "")
    if marker_key and marker_key != idempotency_key:
        return False
    fp = marker.get("approved_fingerprint") or marker.get("manifest_fingerprint")
    if approval_fingerprint and fp != approval_fingerprint:
        return False
    if not marker_key and not approval_fingerprint:
        return False
    return True


async def request_routine_side_effect_approval(
    db: Any,
    *,
    org_id: str,
    routine_id: str,
    action: str,
    idempotency_key: str,
    side_effects: list[str] | None,
    mode: str,
    source_type: str,
    context_summary: str = "",
    requested_by: str | None = None,
    approval_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Create or reuse explicit human-approval request for routine side effect.

    Never fabricates approval. Returns existing approved/pending marker row info.
    """
    org = str(org_id or "").strip()
    rid = str(routine_id or "").strip()
    act = str(action or "").strip()
    key = str(idempotency_key or "").strip()
    if not org or not rid or not act or not key:
        raise RoutineSideEffectBlocked(
            "routine side effect approval denied: missing org/routine/action/idempotency binding"
        )

    try:
        from aios.db.models import PendingAction
    except Exception as exc:
        raise RoutineSideEffectBlocked("routine side effect approval unavailable") from exc

    effects = _normalize_side_effects(side_effects)
    try:
        rows = (
            await db.execute(
                select(PendingAction).where(
                    PendingAction.org_id == org,
                    PendingAction.tool_name == ROUTINE_SIDE_EFFECT_APPROVAL_TOOL,
                    PendingAction.status.in_(["pending", "approved"]),
                )
            )
        ).scalars().all()
    except Exception as exc:
        raise RoutineSideEffectBlocked("routine side effect approval lookup failed") from exc

    for row in rows:
        marker = _routine_marker(row)
        if not marker:
            continue
        if not _marker_matches(
            marker,
            org_id=org,
            routine_id=rid,
            action=act,
            idempotency_key=key,
            approval_fingerprint=approval_fingerprint,
        ):
            continue
        status = str(getattr(row, "status", "") or "")
        if status == "approved" and not str(getattr(row, "decided_by", "") or "").strip():
            continue
        return {
            "ok": True,
            "status": status,
            "approval_id": getattr(row, "id", ""),
            "existing": True,
        }

    marker = {
        "org_id": org,
        "routine_id": rid,
        "action": act,
        "idempotency_key": key,
        "side_effects": effects,
        "mode": str(mode or "").strip().lower(),
        "source_type": str(source_type or "").strip(),
        "approved_fingerprint": approval_fingerprint,
    }
    tool_args = {
        "_routine_approved_action": marker,
        "routine_id": rid,
        "action": act,
        "idempotency_key": key,
        "side_effects": effects,
    }
    if requested_by:
        tool_args["_requested_by"] = str(requested_by)

    approval_id = str(uuid.uuid4())
    row = PendingAction(
        id=approval_id,
        org_id=org,
        agent_id=None,
        conversation_id=None,
        tool_name=ROUTINE_SIDE_EFFECT_APPROVAL_TOOL,
        tool_args=tool_args,
        context_summary=context_summary or f"Routine side effect approval: {rid}:{act}",
        status="pending",
    )
    db.add(row)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        # Race: another worker may have inserted same logical request. Re-read.
        try:
            rows = (
                await db.execute(
                    select(PendingAction).where(
                        PendingAction.org_id == org,
                        PendingAction.tool_name == ROUTINE_SIDE_EFFECT_APPROVAL_TOOL,
                        PendingAction.status.in_(["pending", "approved"]),
                    )
                )
            ).scalars().all()
        except Exception as exc:
            raise RoutineSideEffectBlocked("routine side effect approval create failed") from exc
        for existing in rows:
            marker2 = _routine_marker(existing)
            if marker2 and _marker_matches(
                marker2,
                org_id=org,
                routine_id=rid,
                action=act,
                idempotency_key=key,
                approval_fingerprint=approval_fingerprint,
            ):
                return {
                    "ok": True,
                    "status": str(getattr(existing, "status", "") or "pending"),
                    "approval_id": getattr(existing, "id", ""),
                    "existing": True,
                }
        raise RoutineSideEffectBlocked("routine side effect approval create failed")

    return {"ok": True, "status": "pending", "approval_id": approval_id, "existing": False}


async def _approved_action_exists(
    db: Any,
    *,
    org_id: str,
    routine_id: str,
    action: str,
    idempotency_key: str,
    approval_fingerprint: str | None,
) -> bool:
    """DB-backed approval evidence. Fail closed on missing/invalid evidence."""
    try:
        from aios.db.models import PendingAction
    except Exception:
        logger.warning("routine enforcement: PendingAction model unavailable")
        return False

    try:
        rows = (
            await db.execute(
                select(PendingAction).where(
                    PendingAction.org_id == org_id,
                    PendingAction.status == "approved",
                    PendingAction.decided_by.is_not(None),
                )
            )
        ).scalars().all()
    except Exception:
        logger.warning("routine enforcement: approval lookup failed", exc_info=True)
        return False

    for row in rows:
        if not str(getattr(row, "decided_by", "") or "").strip():
            continue
        marker = _routine_marker(row)
        if not marker:
            continue
        if _marker_matches(
            marker,
            org_id=org_id,
            routine_id=routine_id,
            action=action,
            idempotency_key=idempotency_key,
            approval_fingerprint=approval_fingerprint,
        ):
            return True
    return False


async def enforce_routine_side_effect(
    *,
    db: Any,
    routine: Any,
    action: str,
    side_effects: list[str] | None,
    approval_required: bool,
    idempotency_key: str,
    approved: bool = False,
    approval_fingerprint: str | None = None,
) -> None:
    """Fail-closed routine side-effect gate.

    Denies when org/routine/idempotency missing, or when approval evidence is
    missing for side-effecting/proactive routines. Never fabricates approval.
    """
    routine_id = str(getattr(routine, "routine_id", "") or getattr(routine, "id", "") or "").strip()
    org_id = str(getattr(routine, "org_id", "") or "").strip() or None
    mode = str(getattr(routine, "mode", "") or "").strip().lower()
    source_type = str(getattr(routine, "source_type", "") or "").strip()
    effects = _normalize_side_effects(side_effects)
    key = str(idempotency_key or "").strip()
    act = str(action or "").strip()

    if not routine_id or not key or not act:
        raise RoutineSideEffectBlocked(
            "routine side effect denied: missing routine_id/action/idempotency_key"
        )
    if org_id is None:
        raise RoutineSideEffectBlocked(
            f"routine side effect denied: missing org_id for {routine_id}"
        )

    needs_gate = bool(effects) or bool(approval_required) or mode in {"proactive", "hybrid"}
    if not needs_gate:
        return

    ok = await _approved_action_exists(
        db,
        org_id=org_id,
        routine_id=routine_id,
        action=act,
        idempotency_key=key,
        approval_fingerprint=approval_fingerprint,
    )
    if ok:
        logger.info(
            "routine side effect approved: routine=%s org=%s action=%s key=%s source=%s",
            routine_id, org_id, act, key, source_type,
        )
        return

    # Conservative default: unknown/proactive side effects require explicit approval.
    if not approved:
        logger.warning(
            "routine side effect blocked: routine=%s org=%s action=%s mode=%s effects=%s",
            routine_id, org_id, act, mode, effects,
        )
        raise RoutineSideEffectBlocked(
            f"routine side effect denied: explicit approval required for {routine_id}:{act}"
        )

    logger.warning(
        "routine side effect blocked: missing DB approval evidence routine=%s org=%s action=%s key=%s",
        routine_id, org_id, act, key,
    )
    raise RoutineSideEffectBlocked(
        f"routine side effect denied: DB approval evidence required for {routine_id}:{act}"
    )

    logger.info(
        "routine side effect approved: routine=%s org=%s action=%s key=%s source=%s",
        routine_id, org_id, act, key, source_type,
    )
