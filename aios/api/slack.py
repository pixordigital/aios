"""Slack taxonomy API — read-only proposal and migration gate (§19).

No endpoint creates, renames or archives channels: real workspace inventory
and Founder-approved migration map must exist first.
"""

from fastapi import APIRouter, Depends, HTTPException

from aios.api.deps import get_current_user
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization, User
from aios.governance.slack_taxonomy import (
    FORBIDDEN_CONTENT,
    PROPOSED_CHANNELS,
    RESTRICTED_AREAS,
    SYSTEM_OF_RECORD,
    TaxonomyError,
    migration_steps,
    slack_may_become_decision,
    validate_channel,
)

router = APIRouter(prefix="/api/slack", tags=["slack"])


@router.get("/taxonomy")
async def taxonomy():
    return {"areas": {area: list(channels) for area, channels in PROPOSED_CHANNELS.items()}}


@router.get("/system-of-record")
async def system_of_record():
    return {"systems": dict(SYSTEM_OF_RECORD)}


@router.get("/migration-steps")
async def steps():
    return {"steps": list(migration_steps())}


@router.get("/guardrails")
async def guardrails():
    return {
        "forbidden_content": list(FORBIDDEN_CONTENT),
        "restricted_areas": list(RESTRICTED_AREAS),
        "slack_may_become_decision": slack_may_become_decision(),
        "channel_creation_blocked": True,
    }


@router.post("/validate-channel")
async def validate(body: dict):
    try:
        name = validate_channel(str(body.get("area") or ""), str(body.get("name") or ""))
    except TaxonomyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"valid": True, "name": name}


@router.get("/migration-gate")
async def migration_gate(
    user: User = Depends(get_current_user),
    db: DatabaseBackend = Depends(get_db_backend),
):
    org = await db.get(Organization, user.org_id)
    meta = (org.extra_data or {}) if org else {}
    reasons = []
    if not meta.get("slack_workspace_inventoried"):
        reasons.append("real workspace not inventoried")
    if not meta.get("slack_migration_map_approved"):
        reasons.append("migration map not approved")
    founder = meta.get("founder_user_id") == user.id or user.role == "owner"
    if not founder:
        reasons.append("Founder approval required")
    return {"allowed": not reasons, "reasons": reasons}
