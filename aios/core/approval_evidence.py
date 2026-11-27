"""DB-backed approval evidence verification for side-effect endpoints.

Fail-closed: any missing/invalid evidence denies. Consume is atomic CAS to
prevent replay/races across workers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select, update


@dataclass(frozen=True)
class ApprovalEvidenceResult:
    ok: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


async def verify_and_consume_approval(
    db: Any,
    *,
    org_id: str,
    approval_action_id: str | None,
    expected_tool_name: str | set[str] | tuple[str, ...],
    args_match: Callable[[Any], bool] | None = None,
    expected_fingerprint: str | None = None,
    fingerprint_match: Callable[[Any], bool] | None = None,
    require_decided_by: bool = True,
    expires_at: datetime | None = None,
    now: datetime | None = None,
    not_found_reason: str = "approval action not found",
    missing_id_reason: str = "approval_action_id required",
) -> ApprovalEvidenceResult:
    """Verify approved PendingAction evidence and atomically consume it.

    Checks: id present, row exists in org, status approved, decided_by present,
    not consumed/replayed, tool matches, args/fingerprint match, optional expiry.
    On success marks row consumed with CAS (status=approved, consumed_at IS NULL).
    """
    from aios.db.models import PendingAction

    if not approval_action_id or not str(approval_action_id).strip():
        return ApprovalEvidenceResult(False, missing_id_reason, {"reason": "missing_approval_action_id"})

    action_id = str(approval_action_id).strip()
    org = str(org_id or "")
    row = (
        await db.execute(
            select(PendingAction).where(PendingAction.id == action_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        return ApprovalEvidenceResult(False, not_found_reason, {"reason": "not_found"})
    if str(row.org_id or "") != org:
        return ApprovalEvidenceResult(False, not_found_reason, {"reason": "org_mismatch"})

    status = str(row.status or "")
    if status != "approved":
        return ApprovalEvidenceResult(
            False,
            f"approval action not approved (status={status})",
            {"reason": "not_approved", "status": status},
        )

    decided_by = str(row.decided_by or "").strip()
    if require_decided_by and not decided_by:
        return ApprovalEvidenceResult(False, "approval action missing human decision", {"reason": "missing_decided_by"})

    consumed_at = getattr(row, "consumed_at", None)
    if consumed_at is not None or status == "consumed":
        return ApprovalEvidenceResult(False, "approval action already consumed", {"reason": "already_consumed"})

    if expires_at is not None:
        exp = expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if current > exp:
            return ApprovalEvidenceResult(False, "approval action expired", {"reason": "expired"})

    expected_tools = {expected_tool_name} if isinstance(expected_tool_name, str) else set(expected_tool_name)
    actual_tool = str(row.tool_name or "")
    if actual_tool not in expected_tools:
        return ApprovalEvidenceResult(
            False,
            "approval action tool mismatch",
            {
                "reason": "tool_mismatch",
                "expected_tool": next(iter(expected_tools)) if len(expected_tools) == 1 else sorted(expected_tools),
                "actual_tool": actual_tool,
            },
        )

    if args_match is not None and not bool(args_match(row.tool_args)):
        return ApprovalEvidenceResult(False, "approval action args mismatch", {"reason": "args_mismatch"})

    if expected_fingerprint is not None:
        fp_ok = False
        if fingerprint_match is not None:
            fp_ok = bool(fingerprint_match(row.tool_args))
        elif isinstance(row.tool_args, dict):
            marker = row.tool_args.get("_approval_evidence")
            if isinstance(marker, dict):
                fp_ok = str(marker.get("fingerprint") or "") == str(expected_fingerprint)
        if not fp_ok:
            return ApprovalEvidenceResult(False, "approval action fingerprint mismatch", {"reason": "fingerprint_mismatch"})

    consume_now = now or datetime.now(timezone.utc)
    if consume_now.tzinfo is not None:
        # DB column naive datetime in codebase convention
        consume_now_db = consume_now.replace(tzinfo=None)
    else:
        consume_now_db = consume_now

    cas = await db.execute(
        update(PendingAction)
        .where(
            PendingAction.id == action_id,
            PendingAction.org_id == org,
            PendingAction.status == "approved",
            PendingAction.consumed_at.is_(None),
        )
        .values(status="consumed", consumed_at=consume_now_db)
    )
    if int(getattr(cas, "rowcount", 0) or 0) != 1:
        await db.rollback()
        return ApprovalEvidenceResult(False, "approval action replay or race", {"reason": "consume_race"})

    return ApprovalEvidenceResult(
        True,
        "ok",
        {
            "approval_action_id": action_id,
            "decided_by": decided_by,
            "tool_name": actual_tool,
        },
    )
