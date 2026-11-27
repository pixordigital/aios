"""Agent Pack internal install/activate API.

No external runtime install/fetch/clone/pip/docker pull/exec.
Activation/rollback are HITL-gated via PendingAction; no mutation before approval.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from aios.core.agent_pack import (
    AgentPackValidationError,
    manifest_fingerprint,
    validate_agent_pack,
)
from aios.core.audit import log_audit
from aios.core.solution_pack import build_solution_pack_dict, solution_pack_keys
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import AgentPack, AgentPackActivation, AgentPackVersion, PendingAction
from aios.governance.security import record_cross_tenant_block_if_mismatch

from .deps import get_current_user, verify_org_access_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-packs", tags=["agent-packs"])

ACTIVATE_TOOL = "agent_pack_activate"
ROLLBACK_TOOL = "agent_pack_rollback"


class AgentPackInstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any]
    accept_high_severity_loss: bool = False
    capability_loss: list[dict[str, Any]] = Field(default_factory=list)


class AgentPackVersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any]
    accept_high_severity_loss: bool = False
    capability_loss: list[dict[str, Any]] = Field(default_factory=list)


class AgentPackActivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    reason: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _has_high_severity_loss(losses: list[dict[str, Any]] | None) -> bool:
    for item in losses or []:
        sev = str((item or {}).get("severity", "")).lower()
        if sev == "high":
            return True
    return False


def _manifest_checksum(manifest) -> str:
    prov = manifest.provenance
    checksum = prov.checksum_sha256
    if checksum:
        return checksum
    # compute deterministic checksum over content envelope
    from aios.core.agent_pack import _checksum_fingerprint
    return _checksum_fingerprint(manifest)


def _pack_summary(pack: AgentPack) -> dict[str, Any]:
    return {
        "id": pack.id,
        "org_id": pack.org_id,
        "pack_key": pack.pack_key,
        "name": pack.name,
        "description": pack.description,
        "agent_type": pack.agent_type,
        "active_version_id": pack.active_version_id,
        "created_at": str(pack.created_at),
        "updated_at": str(pack.updated_at),
    }


def _version_summary(v: AgentPackVersion, *, include_manifest: bool = False) -> dict[str, Any]:
    data = {
        "id": v.id,
        "pack_id": v.pack_id,
        "org_id": v.org_id,
        "version_semver": v.version_semver,
        "version_num": v.version_num,
        "checksum_sha256": v.checksum_sha256,
        "fingerprint_sha256": v.fingerprint_sha256,
        "capability_loss": v.capability_loss_json or [],
        "provenance": v.provenance_json or {},
        "created_at": str(v.created_at),
    }
    if include_manifest:
        data["manifest"] = v.manifest_json or {}
    return data


async def _get_pack_or_404(db: DatabaseBackend, pack_id: str, org_id: str, *, actor_id: str, source: str) -> AgentPack:
    pack = await db.get(AgentPack, pack_id)
    await verify_org_access_async(
        org_id,
        pack,
        db=db,
        actor_id=actor_id,
        actor_type="human",
        source=source,
        payload={"pack_id": str(pack_id)},
    )
    return pack


async def _get_version_or_404(db: DatabaseBackend, version_id: str, org_id: str, *, actor_id: str, source: str) -> AgentPackVersion:
    ver = await db.get(AgentPackVersion, version_id)
    await verify_org_access_async(
        org_id,
        ver,
        db=db,
        actor_id=actor_id,
        actor_type="human",
        source=source,
        payload={"version_id": str(version_id)},
    )
    return ver


def _validate_manifest_or_422(manifest: dict[str, Any]):
    try:
        return validate_agent_pack(manifest)
    except AgentPackValidationError as exc:
        raise HTTPException(422, f"invalid agent pack manifest: {exc}") from exc


async def _create_version(
    db: DatabaseBackend,
    *,
    org_id: str,
    pack: AgentPack,
    manifest_dict: dict[str, Any],
    capability_loss: list[dict[str, Any]],
    accept_high_severity_loss: bool,
    actor_id: str,
) -> AgentPackVersion:
    if _has_high_severity_loss(capability_loss) and not accept_high_severity_loss:
        raise HTTPException(422, "high-severity capability_loss requires accept_high_severity_loss=true")

    m = _validate_manifest_or_422(manifest_dict)
    # fail closed on checksum mismatch already done by validate_agent_pack via model validator
    checksum = _manifest_checksum(m)
    fingerprint = manifest_fingerprint(m)
    if m.identity.id != pack.pack_key:
        raise HTTPException(422, "manifest identity.id must match pack_key")

    existing = (
        await db.execute(
            select(AgentPackVersion).where(
                AgentPackVersion.pack_id == pack.id,
                AgentPackVersion.version_semver == m.version,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.checksum_sha256 != checksum or existing.fingerprint_sha256 != fingerprint:
            raise HTTPException(409, "version exists with different checksum/fingerprint")
        return existing

    max_num = (
        await db.execute(select(AgentPackVersion.version_num).where(AgentPackVersion.pack_id == pack.id))
    ).scalars().all()
    next_num = (max(max_num) if max_num else 0) + 1
    ver = AgentPackVersion(
        pack_id=pack.id,
        org_id=org_id,
        version_semver=m.version,
        version_num=next_num,
        manifest_json=m.model_dump(mode="json"),
        checksum_sha256=checksum,
        fingerprint_sha256=fingerprint,
        capability_loss_json=capability_loss or [],
        provenance_json=m.provenance.model_dump(mode="json"),
        created_by=actor_id,
    )
    db.add(ver)
    await db.commit()
    await db.refresh(ver)
    await log_audit(
        db, org_id, "agent_pack.version.publish", "agent_pack_version",
        user_id=actor_id, resource_id=ver.id,
        details={"pack_id": pack.id, "version": ver.version_semver, "checksum": checksum},
    )
    return ver


@router.post("/install")
async def install_agent_pack(
    body: AgentPackInstallBody,
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    org_id = user.org_id
    manifest = _validate_manifest_or_422(body.manifest)
    if _has_high_severity_loss(body.capability_loss) and not body.accept_high_severity_loss:
        raise HTTPException(422, "high-severity capability_loss requires accept_high_severity_loss=true")

    pack_key = manifest.identity.id
    existing = (
        await db.execute(select(AgentPack).where(AgentPack.org_id == org_id, AgentPack.pack_key == pack_key))
    ).scalar_one_or_none()
    if existing:
        pack = existing
    else:
        pack = AgentPack(
            org_id=org_id,
            pack_key=pack_key,
            name=manifest.identity.name,
            description=manifest.identity.description,
            agent_type=manifest.identity.agent_type,
            created_by=user.id,
        )
        db.add(pack)
        await db.commit()
        await db.refresh(pack)
        await log_audit(
            db, org_id, "agent_pack.install", "agent_pack",
            user_id=user.id, resource_id=pack.id,
            details={"pack_key": pack_key, "version": manifest.version},
        )

    ver = await _create_version(
        db,
        org_id=org_id,
        pack=pack,
        manifest_dict=body.manifest,
        capability_loss=body.capability_loss,
        accept_high_severity_loss=body.accept_high_severity_loss,
        actor_id=user.id,
    )
    return {"pack": _pack_summary(pack), "version": _version_summary(ver)}


@router.get("")
async def list_agent_packs(
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    rows = (
        await db.execute(select(AgentPack).where(AgentPack.org_id == user.org_id).order_by(AgentPack.created_at.desc()))
    ).scalars().all()
    return {"packs": [_pack_summary(p) for p in rows]}


@router.get("/solutions")
async def list_solution_packs(user=Depends(get_current_user)) -> list[dict[str, Any]]:
    """Named Solution packs as install-ready manifests (no DB writes)."""
    out: list[dict[str, Any]] = []
    for key in solution_pack_keys():
        try:
            out.append(build_solution_pack_dict(key))
        except Exception as e:
            logger.warning("solution pack build failed key=%s err=%s", key, e)
    return out


@router.get("/{pack_id}")
async def get_agent_pack(
    pack_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    pack = await _get_pack_or_404(db, pack_id, user.org_id, actor_id=user.id, source="agent_packs.api.get")
    versions = (
        await db.execute(
            select(AgentPackVersion)
            .where(AgentPackVersion.pack_id == pack.id, AgentPackVersion.org_id == user.org_id)
            .order_by(AgentPackVersion.version_num.desc())
        )
    ).scalars().all()
    return {"pack": _pack_summary(pack), "versions": [_version_summary(v) for v in versions]}


@router.post("/{pack_id}/versions")
async def add_agent_pack_version(
    pack_id: str,
    body: AgentPackVersionBody,
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    pack = await _get_pack_or_404(db, pack_id, user.org_id, actor_id=user.id, source="agent_packs.api.add_version")
    ver = await _create_version(
        db,
        org_id=user.org_id,
        pack=pack,
        manifest_dict=body.manifest,
        capability_loss=body.capability_loss,
        accept_high_severity_loss=body.accept_high_severity_loss,
        actor_id=user.id,
    )
    return {"pack": _pack_summary(pack), "version": _version_summary(ver)}


async def _request_activation(
    db: DatabaseBackend,
    *,
    org_id: str,
    user_id: str,
    pack: AgentPack,
    version: AgentPackVersion,
    action_type: str,
) -> dict[str, Any]:
    if version.pack_id != pack.id:
        raise HTTPException(422, "version does not belong to pack")
    if version.org_id != org_id or pack.org_id != org_id:
        if org_id:
            try:
                evt = await record_cross_tenant_block_if_mismatch(
                    db,
                    org_id=org_id,
                    resource=version if version.org_id != org_id else pack,
                    source="agent_packs.api.request_activation",
                    actor_type="human",
                    actor_id=user_id,
                    payload={"pack_id": str(pack.id), "version_id": str(version.id)},
                )
                if evt is not None:
                    await db.commit()
            except Exception:
                pass
        raise HTTPException(404)

    tool_name = ACTIVATE_TOOL if action_type == "activate" else ROLLBACK_TOOL
    activation = AgentPackActivation(
        org_id=org_id,
        pack_id=pack.id,
        version_id=version.id,
        from_version_id=pack.active_version_id,
        to_version_id=version.id,
        action_type=action_type,
        status="requested",
        requested_by=user_id,
        requested_at=_now(),
        extra_data={
            "pack_key": pack.pack_key,
            "version_semver": version.version_semver,
            "checksum_sha256": version.checksum_sha256,
            "fingerprint_sha256": version.fingerprint_sha256,
        },
    )
    db.add(activation)
    await db.commit()
    await db.refresh(activation)

    pending = PendingAction(
        org_id=org_id,
        agent_id=None,  # system action
        conversation_id=None,
        tool_name=tool_name,
        tool_args={
            "pack_id": pack.id,
            "version_id": version.id,
            "activation_id": activation.id,
            "pack_key": pack.pack_key,
            "version_semver": version.version_semver,
            "checksum_sha256": version.checksum_sha256,
            "fingerprint_sha256": version.fingerprint_sha256,
            "action_type": action_type,
            # never allow fabricated preapproval
            "explicit_preapproved_allowed": False,
        },
        context_summary=f"{action_type} agent pack {pack.pack_key}@{version.version_semver}",
        status="pending",
    )
    db.add(pending)
    activation.approval_action_id = pending.id
    await db.commit()
    await db.refresh(activation)

    await log_audit(
        db, org_id, f"agent_pack.{action_type}.requested", "agent_pack_activation",
        user_id=user_id, resource_id=activation.id,
        details={
            "pack_id": pack.id,
            "version_id": version.id,
            "approval_action_id": pending.id,
            "from_version_id": activation.from_version_id,
            "to_version_id": activation.to_version_id,
        },
    )
    return {
        "activation": {
            "id": activation.id,
            "status": activation.status,
            "action_type": activation.action_type,
            "pack_id": activation.pack_id,
            "version_id": activation.version_id,
            "from_version_id": activation.from_version_id,
            "to_version_id": activation.to_version_id,
            "approval_action_id": activation.approval_action_id,
        },
        "approval_action": {
            "id": pending.id,
            "status": pending.status,
            "tool_name": pending.tool_name,
        },
    }


@router.post("/{pack_id}/activate")
async def activate_agent_pack(
    pack_id: str,
    body: AgentPackActivateBody,
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    pack = await _get_pack_or_404(db, pack_id, user.org_id, actor_id=user.id, source="agent_packs.api.activate")
    version = await _get_version_or_404(db, body.version_id, user.org_id, actor_id=user.id, source="agent_packs.api.activate.version")
    return await _request_activation(db, org_id=user.org_id, user_id=user.id, pack=pack, version=version, action_type="activate")


@router.post("/{pack_id}/rollback")
async def rollback_agent_pack(
    pack_id: str,
    body: AgentPackActivateBody,
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    pack = await _get_pack_or_404(db, pack_id, user.org_id, actor_id=user.id, source="agent_packs.api.rollback")
    version = await _get_version_or_404(db, body.version_id, user.org_id, actor_id=user.id, source="agent_packs.api.rollback.version")
    return await _request_activation(db, org_id=user.org_id, user_id=user.id, pack=pack, version=version, action_type="rollback")


async def _load_activation_for_action(db: DatabaseBackend, action: PendingAction) -> AgentPackActivation | None:
    args = action.tool_args if isinstance(action.tool_args, dict) else {}
    activation_id = args.get("activation_id")
    if activation_id:
        act = await db.get(AgentPackActivation, str(activation_id))
        return act
    q = select(AgentPackActivation).where(AgentPackActivation.approval_action_id == action.id)
    return (await db.execute(q)).scalar_one_or_none()


async def apply_agent_pack_activation(db: DatabaseBackend, approval_action: PendingAction) -> dict[str, Any]:
    """Deterministic, idempotent activation apply. CAS on activation status requested->active."""
    if approval_action.status != "approved":
        return {"ok": False, "reason": "approval_not_approved", "activation_id": None}

    args = approval_action.tool_args if isinstance(approval_action.tool_args, dict) else {}
    tool_name = str(approval_action.tool_name or "")
    if tool_name not in {ACTIVATE_TOOL, ROLLBACK_TOOL}:
        return {"ok": False, "reason": "unsupported_tool", "activation_id": None}

    # Never fabricate approval: explicit preapproval flag ignored/denied.
    if bool(args.get("explicit_preapproved_allowed")):
        logger.warning("agent pack activation attempted with explicit_preapproved_allowed; ignoring")

    activation = await _load_activation_for_action(db, approval_action)
    if not activation:
        return {"ok": False, "reason": "activation_not_found", "activation_id": None}

    org_id = str(approval_action.org_id or "")
    if not org_id or activation.org_id != org_id:
        if org_id:
            try:
                evt = await record_cross_tenant_block_if_mismatch(
                    db,
                    org_id=org_id,
                    resource=activation,
                    source="agent_packs.api.apply_activation.activation",
                    actor_type="human",
                    actor_id=str(approval_action.decided_by or approval_action.requested_by or "") or None,
                    payload={
                        "activation_id": str(activation.id),
                        "approval_action_id": str(approval_action.id),
                    },
                )
                if evt is not None:
                    await db.commit()
            except Exception:
                pass
        return {"ok": False, "reason": "org_mismatch", "activation_id": activation.id}

    if activation.status in {"active", "superseded", "rolled_back"}:
        return {"ok": True, "idempotent": True, "activation_id": activation.id, "status": activation.status}

    if activation.status != "requested":
        return {"ok": False, "reason": f"invalid_status:{activation.status}", "activation_id": activation.id}

    pack = await db.get(AgentPack, activation.pack_id)
    version = await db.get(AgentPackVersion, activation.version_id)
    if not pack or not version:
        activation.status = "failed"
        activation.error = "pack_or_version_missing"
        activation.decided_at = _now()
        await db.commit()
        return {"ok": False, "reason": "pack_or_version_missing", "activation_id": activation.id}
    if pack.org_id != org_id or version.org_id != org_id or version.pack_id != pack.id:
        if org_id and (pack.org_id != org_id or version.org_id != org_id):
            try:
                await record_cross_tenant_block_if_mismatch(
                    db,
                    org_id=org_id,
                    resource=pack if pack.org_id != org_id else version,
                    source="agent_packs.api.apply_activation.pack",
                    actor_type="human",
                    actor_id=str(approval_action.decided_by or approval_action.requested_by or "") or None,
                    payload={
                        "activation_id": str(activation.id),
                        "pack_id": str(pack.id),
                        "version_id": str(version.id),
                        "approval_action_id": str(approval_action.id),
                    },
                )
            except Exception:
                pass
        activation.status = "failed"
        activation.error = "org_or_pack_mismatch"
        activation.decided_at = _now()
        await db.commit()
        return {"ok": False, "reason": "org_or_pack_mismatch", "activation_id": activation.id}

    # Verify args match authoritative version facts
    if str(args.get("pack_id")) != pack.id or str(args.get("version_id")) != version.id:
        activation.status = "failed"
        activation.error = "args_mismatch"
        activation.decided_at = _now()
        await db.commit()
        return {"ok": False, "reason": "args_mismatch", "activation_id": activation.id}
    if str(args.get("checksum_sha256")) != version.checksum_sha256:
        activation.status = "failed"
        activation.error = "checksum_mismatch"
        activation.decided_at = _now()
        await db.commit()
        return {"ok": False, "reason": "checksum_mismatch", "activation_id": activation.id}

    now = _now()
    decided_by = approval_action.decided_by

    # CAS: only requested -> active
    cas = (
        await db.execute(
            update(AgentPackActivation)
            .where(AgentPackActivation.id == activation.id, AgentPackActivation.status == "requested")
            .values(status="active", decided_by=decided_by, decided_at=now, applied_at=now, error="")
        )
    )
    if getattr(cas, "rowcount", 0) != 1:
        await db.rollback()
        fresh = await db.get(AgentPackActivation, activation.id)
        if fresh and fresh.status in {"active", "superseded", "rolled_back"}:
            return {"ok": True, "idempotent": True, "activation_id": activation.id, "status": fresh.status}
        return {"ok": False, "reason": "cas_failed", "activation_id": activation.id}

    # Supersede prior active activations for same pack
    await db.execute(
        update(AgentPackActivation)
        .where(
            AgentPackActivation.pack_id == pack.id,
            AgentPackActivation.org_id == org_id,
            AgentPackActivation.status == "active",
            AgentPackActivation.id != activation.id,
        )
        .values(status="superseded")
    )

    pack.active_version_id = version.id
    await db.commit()

    event = "agent_pack.rollback.applied" if tool_name == ROLLBACK_TOOL else "agent_pack.activation.applied"
    await log_audit(
        db, org_id, event, "agent_pack_activation",
        user_id=decided_by, resource_id=activation.id,
        details={
            "pack_id": pack.id,
            "version_id": version.id,
            "from_version_id": activation.from_version_id,
            "to_version_id": activation.to_version_id,
            "approval_action_id": approval_action.id,
        },
    )
    return {"ok": True, "idempotent": False, "activation_id": activation.id, "status": "active"}


@router.post("/activations/{activation_id}/apply")
async def apply_activation_endpoint(
    activation_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    # admin-only fallback; verifies approval approved and CAS-applies
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role not in {"admin", "org_admin", "superadmin"}:
        raise HTTPException(403, "admin required")

    activation = (
        await db.execute(
            select(AgentPackActivation)
            .where(AgentPackActivation.id == activation_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    await verify_org_access_async(
        user.org_id,
        activation,
        db=db,
        actor_id=user.id,
        actor_type="human",
        source="agent_packs.api.apply_activation",
        payload={"activation_id": activation_id},
    )
    action = None
    if activation.approval_action_id:
        action = (
            await db.execute(
                select(PendingAction)
                .where(PendingAction.id == activation.approval_action_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
    if action is None:
        # fallback for stale identity-map/read; authoritative by activation_id in args
        rows = (
            await db.execute(
                select(PendingAction).where(
                    PendingAction.org_id == user.org_id,
                    PendingAction.tool_name.in_([ACTIVATE_TOOL, ROLLBACK_TOOL]),
                ).order_by(PendingAction.created_at.desc()).limit(200)
            )
        ).scalars().all()
        for row in rows:
            args = row.tool_args if isinstance(row.tool_args, dict) else {}
            if str(args.get("activation_id")) == str(activation.id):
                action = row
                break
    if action is None:
        raise HTTPException(422, "activation has no approval_action_id")
    await verify_org_access_async(
        user.org_id,
        action,
        db=db,
        actor_id=user.id,
        actor_type="human",
        source="agent_packs.api.apply_activation.action",
        payload={"action_id": activation.approval_action_id},
    )
    if action.status != "approved":
        raise HTTPException(409, "approval action not approved")
    result = await apply_agent_pack_activation(db, action)
    if not result.get("ok"):
        raise HTTPException(409, result)
    return result
