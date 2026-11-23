"""LIA API: acquisition sources, campaigns, suppression and deterministic contact gate (§12)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization, User
from aios.core.crm_intelligence import Contact
from aios.governance.capability_registry import WORKFLOW_STAGES
from aios.core.lia import (
    CHANNELS,
    DISPOSITIONS,
    SOURCE_TYPES,
    Campaign,
    CampaignMember,
    LeadSource,
    SuppressionEntry,
    can_contact,
    can_transition_stage,
    crm_handoff_decision,
)
from aios.governance.innovation import TRACK_AUTONOMOUS_MODES, autonomous_action_guard
from aios.governance.security import record_cross_tenant_block_if_mismatch


router = APIRouter(prefix="/api/lia", tags=["lia"])



def _lia_track_c_autonomous(body: dict) -> tuple[str | None, bool]:
    perms = body.get("permissions") if isinstance(body.get("permissions"), dict) else {}
    track = body.get("track", perms.get("track"))
    track_norm = str(track).strip().upper() if track is not None else None
    mode = str(body.get("optimization_mode", perms.get("optimization_mode", body.get("mode", perms.get("mode", "")))) or "").strip().lower()
    autonomous = bool(
        body.get("autonomous") is True
        or perms.get("autonomous") is True
        or mode in TRACK_AUTONOMOUS_MODES
    )
    return track_norm, autonomous


def _lia_has_evidence(body: dict) -> bool:
    perms = body.get("permissions") if isinstance(body.get("permissions"), dict) else {}
    for src in (body, perms):
        evidence = src.get("evidence", src.get("evidence_refs", src.get("track_c_evidence")))
        if isinstance(evidence, str):
            if evidence.strip():
                return True
        elif isinstance(evidence, (list, tuple, set, dict)):
            if len(evidence) > 0:
                return True
        elif bool(evidence):
            return True
        if src.get("evidence_before_track_c") is True:
            return True
    return False


def _lia_guard(body: dict, action: str) -> None:
    """Fail-closed Track C autonomous guard for mutating LIA actions.

    Scoped to actions that can execute outreach/automation when explicitly
    marked Track C/autonomous. Not a claim of coverage for all execution systems.
    """
    track_norm, autonomous = _lia_track_c_autonomous(body)
    perms = body.get("permissions") if isinstance(body.get("permissions"), dict) else {}
    founder_approved = bool(body.get("founder_approved") is True or perms.get("founder_approved") is True)
    ok, reason = autonomous_action_guard(
        track=track_norm,
        autonomous=autonomous,
        has_evidence=_lia_has_evidence(body),
        founder_approved=founder_approved,
        action=action,
    )
    if not ok:
        raise HTTPException(403, reason)
def _is_founder(user: User, org: Organization | None) -> bool:
    if org is None:
        return False
    return (org.extra_data or {}).get("founder_user_id") == user.id or user.role == "owner"


@router.get("/sources")
async def list_sources(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(LeadSource).where(LeadSource.org_id == org_id))).scalars().all()
    return {
        "items": [
            {
                "id": s.id, "name": s.name, "source_type": s.source_type,
                "allowed_for_outreach": s.allowed_for_outreach,
            }
            for s in rows
        ]
    }


@router.post("/sources")
async def create_source(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    _lia_guard(body, "lia source create")
    source_type = str(body.get("source_type") or "")
    if source_type not in SOURCE_TYPES:
        raise HTTPException(400, "invalid source_type")
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    src = LeadSource(
        org_id=org_id,
        name=name,
        source_type=source_type,
        url=str(body.get("url") or ""),
        terms_notes=str(body.get("terms_notes") or ""),
        allowed_for_outreach=bool(body.get("allowed_for_outreach", False)),
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return {"id": src.id, "allowed_for_outreach": src.allowed_for_outreach}


@router.get("/campaigns")
async def list_campaigns(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(Campaign).where(Campaign.org_id == org_id))).scalars().all()
    return {
        "items": [
            {
                "id": c.id, "name": c.name, "channel": c.channel, "status": c.status,
                "legal_reviewed": c.legal_reviewed, "approved_by": c.approved_by,
            }
            for c in rows
        ]
    }


@router.post("/campaigns")
async def create_campaign(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    _lia_guard(body, "lia campaign create")
    channel = str(body.get("channel") or "email")
    if channel not in CHANNELS:
        raise HTTPException(400, "invalid channel")
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    campaign = Campaign(
        org_id=org_id,
        name=name,
        channel=channel,
        icp_profile=dict(body.get("icp_profile") or {}),
        budget_brl=float(body.get("budget_brl") or 0.0),
        legal_reviewed=bool(body.get("legal_reviewed", False)),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return {"id": campaign.id, "status": campaign.status, "channel": campaign.channel}


@router.post("/campaigns/{campaign_id}/approve")
async def approve_campaign(
    campaign_id: str,
    body: dict | None = None,
    user: User = Depends(get_current_user),
    db: DatabaseBackend = Depends(get_db_backend),
):
    payload = body or {}
    _lia_guard(payload, "lia campaign approve")
    campaign = (
        await db.execute(
            select(Campaign).where(Campaign.id == campaign_id, Campaign.org_id == user.org_id)
        )
    ).scalars().first()
    if campaign is None:
        other = await db.get(Campaign, campaign_id)
        evt = await record_cross_tenant_block_if_mismatch(
            db,
            org_id=user.org_id,
            resource=other,
            source="lia.api.approve_campaign",
            actor_type="human",
            actor_id=str(getattr(user, "id", "") or "") or None,
            payload={"campaign_id": str(campaign_id)},
        )
        if evt is not None:
            await db.commit()
        raise HTTPException(404, "campaign not found")
    if not campaign.legal_reviewed:
        raise HTTPException(400, "legal review required before approval")
    org = await db.get(Organization, user.org_id)
    if not _is_founder(user, org):
        raise HTTPException(403, "Founder approval required")
    campaign.status = "approved"
    campaign.approved_by = user.id
    await db.commit()
    return {"id": campaign.id, "status": campaign.status, "approved_by": user.id}


@router.get("/suppression")
async def list_suppression(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(SuppressionEntry).where(SuppressionEntry.org_id == org_id))).scalars().all()
    return {
        "items": [
            {"id": e.id, "kind": e.kind, "value": e.value, "reason": e.reason}
            for e in rows
        ]
    }


@router.post("/suppression")
async def add_suppression(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    _lia_guard(body, "lia suppression update")
    kind = str(body.get("kind") or "email")
    value = str(body.get("value") or "").strip()
    if kind not in ("email", "phone", "domain", "cnpj") or not value:
        raise HTTPException(400, "valid kind and value required")
    exists = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.org_id == org_id,
                SuppressionEntry.kind == kind,
                SuppressionEntry.value == value,
            )
        )
    ).scalars().first()
    if exists:
        return {"id": exists.id, "already_present": True}
    entry = SuppressionEntry(
        org_id=org_id, kind=kind, value=value,
        reason=str(body.get("reason") or "opt_out"),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "already_present": False}


async def _suppressed(db: DatabaseBackend, org_id: str, contact: Contact | None) -> bool:
    if contact is None:
        return False
    values = [v for v in (contact.email, contact.phone) if v]
    if not values:
        return False
    rows = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.org_id == org_id,
                SuppressionEntry.value.in_(values),
            )
        )
    ).scalars().all()
    return bool(rows)


@router.post("/contact-check")
async def contact_check(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    value = str(body.get("value") or "").strip()
    suppressed = False
    if value:
        suppressed = bool(
            (await db.execute(
                select(SuppressionEntry).where(
                    SuppressionEntry.org_id == org_id, SuppressionEntry.value == value
                )
            )).scalars().first()
        )
    source_allowed = bool(body.get("source_allowed_for_outreach", True))
    source_id = body.get("source_id")
    if source_id:
        src = (
            await db.execute(
                select(LeadSource).where(LeadSource.id == str(source_id), LeadSource.org_id == org_id)
            )
        ).scalars().first()
        if src is None:
            other = await db.get(LeadSource, str(source_id))
            evt = await record_cross_tenant_block_if_mismatch(
                db,
                org_id=org_id,
                resource=other,
                source="lia.api.contact_check.source",
                payload={"source_id": str(source_id)},
            )
            if evt is not None:
                await db.commit()
            raise HTTPException(404, "source not found")
        source_allowed = bool(src.allowed_for_outreach)
    allowed, reason = can_contact(
        channel=str(body.get("channel") or "email"),
        contact_allowed=bool(body.get("contact_allowed", False)),
        opt_out=bool(body.get("opt_out", False)),
        suppressed=suppressed,
        campaign_approved=bool(body.get("campaign_approved", False)),
        campaign_legal_reviewed=bool(body.get("campaign_legal_reviewed", False)),
        whatsapp_authorized=bool(body.get("whatsapp_authorized", False)),
        email_verified=bool(body.get("email_verified", False)),
        source_allowed_for_outreach=source_allowed,
    )
    return {"allowed": allowed, "reason": reason, "suppressed": suppressed, "source_allowed_for_outreach": source_allowed}


@router.post("/members")
async def create_member(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    _lia_guard(body, "lia member create")
    campaign_id = str(body.get("campaign_id") or "")
    campaign = (
        await db.execute(
            select(Campaign).where(Campaign.id == campaign_id, Campaign.org_id == org_id)
        )
    ).scalars().first()
    if campaign is None:
        other = await db.get(Campaign, campaign_id)
        evt = await record_cross_tenant_block_if_mismatch(
            db,
            org_id=org_id,
            resource=other,
            source="lia.api.create_member.campaign",
            payload={"campaign_id": str(campaign_id)},
        )
        if evt is not None:
            await db.commit()
        raise HTTPException(404, "campaign not found")
    disposition = str(body.get("disposition") or "research_required")
    if disposition not in DISPOSITIONS:
        raise HTTPException(400, "invalid disposition")
    stage = str(body.get("stage") or "company_discovery")
    if stage not in WORKFLOW_STAGES:
        raise HTTPException(400, "invalid stage")
    member = CampaignMember(
        org_id=org_id,
        campaign_id=campaign.id,
        account_id=body.get("account_id"),
        contact_id=body.get("contact_id"),
        stage=stage,
        disposition=disposition,
        icp_fit=float(body.get("icp_fit") or 0.0),
        solution_fit=float(body.get("solution_fit") or 0.0),
        buying_readiness=float(body.get("buying_readiness") or 0.0),
        evidence_confidence=float(body.get("evidence_confidence") or 0.0),
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return {"id": member.id, "disposition": member.disposition, "stage": member.stage}


@router.post("/members/{member_id}/stage")
async def advance_stage(
    member_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    _lia_guard(body, "lia stage advance")
    member = (
        await db.execute(
            select(CampaignMember).where(
                CampaignMember.id == member_id, CampaignMember.org_id == org_id
            )
        )
    ).scalars().first()
    if member is None:
        other = await db.get(CampaignMember, member_id)
        evt = await record_cross_tenant_block_if_mismatch(
            db,
            org_id=org_id,
            resource=other,
            source="lia.api.advance_stage.member",
            payload={"member_id": str(member_id)},
        )
        if evt is not None:
            await db.commit()
        raise HTTPException(404, "member not found")
    target = str(body.get("stage") or "").strip()
    allowed, reason = can_transition_stage(member.stage or "company_discovery", target)
    if not allowed:
        raise HTTPException(400, reason)
    member.stage = target
    await db.commit()
    return {"id": member.id, "stage": member.stage, "transition": reason}


@router.post("/members/{member_id}/handoff")
async def handoff(
    member_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    _lia_guard(body, "lia crm handoff")
    member = (
        await db.execute(
            select(CampaignMember).where(
                CampaignMember.id == member_id, CampaignMember.org_id == org_id
            )
        )
    ).scalars().first()
    if member is None:
        other = await db.get(CampaignMember, member_id)
        evt = await record_cross_tenant_block_if_mismatch(
            db,
            org_id=org_id,
            resource=other,
            source="lia.api.handoff.member",
            payload={"member_id": str(member_id)},
        )
        if evt is not None:
            await db.commit()
        raise HTTPException(404, "member not found")
    contact = None
    if member.contact_id:
        contact = (
            await db.execute(
                select(Contact).where(Contact.id == member.contact_id, Contact.org_id == org_id)
            )
        ).scalars().first()
    source_allowed = bool(body.get("source_allowed_for_outreach", True))
    source_id = body.get("source_id")
    if source_id:
        src = (
            await db.execute(
                select(LeadSource).where(LeadSource.id == str(source_id), LeadSource.org_id == org_id)
            )
        ).scalars().first()
        if src is None:
            other = await db.get(LeadSource, str(source_id))
            evt = await record_cross_tenant_block_if_mismatch(
                db,
                org_id=org_id,
                resource=other,
                source="lia.api.handoff.source",
                payload={"source_id": str(source_id)},
            )
            if evt is not None:
                await db.commit()
            raise HTTPException(404, "source not found")
        source_allowed = bool(src.allowed_for_outreach)
    return crm_handoff_decision(
        member,
        contact,
        channel=str(body.get("channel") or "email"),
        suppressed=await _suppressed(db, org_id, contact),
        campaign_approved=bool(body.get("campaign_approved", False)),
        campaign_legal_reviewed=bool(body.get("campaign_legal_reviewed", False)),
        whatsapp_authorized=bool(body.get("whatsapp_authorized", False)),
        source_allowed_for_outreach=source_allowed,
    )
