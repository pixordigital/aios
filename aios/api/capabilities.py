"""Capability registry + deterministic Solution-Fit API (brief §2.3, §12)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select

from aios.api.deps import get_current_user, get_org_id
from aios.governance.security import record_cross_tenant_block_if_mismatch
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.governance.capability_registry import (
    ENGINEERING_REVIEW_DISPOSITIONS,
    MATURITY_LEVELS,
    Capability,
    SolutionFitAssessment,
    capability_fit_score,
    capability_lifecycle_guard,
    engineering_work_guard,
    solution_fit,
)
from aios.governance.innovation import TRACK_AUTONOMOUS_MODES

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


def _cap_track_c_autonomous(body: dict) -> tuple[str | None, bool]:
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


def _cap_has_evidence(body: dict) -> bool:
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


def _cap_guard(body: dict, action: str) -> None:
    track_norm, autonomous = _cap_track_c_autonomous(body)
    perms = body.get("permissions") if isinstance(body.get("permissions"), dict) else {}
    founder_approved = bool(body.get("founder_approved") is True or perms.get("founder_approved") is True)
    ok, reason = capability_lifecycle_guard(
        track=track_norm,
        autonomous=autonomous,
        has_evidence=_cap_has_evidence(body),
        founder_approved=founder_approved,
        action=action,
    )
    if not ok:
        raise HTTPException(403, reason)
_SCORES = (
    "problem_fit",
    "feasibility",
    "commercial_viability",
    "buying_readiness",
    "evidence_confidence",
)


def _visible(org_id: str):
    return or_(Capability.org_id == org_id, Capability.org_id.is_(None))


@router.get("")
async def list_capabilities(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(Capability).where(_visible(org_id)))).scalars().all()
    def _gov(c: Capability) -> dict:
        for ev in reversed(c.deployment_evidence or []):
            if isinstance(ev, dict) and isinstance(ev.get("_governance"), dict):
                return ev["_governance"]
        return {}
    return {
        "items": [
            {
                "id": c.id,
                "capability_key": c.capability_key,
                "name": c.name,
                "maturity": c.maturity,
                "supported_use_cases": c.supported_use_cases or [],
                "limitations": c.limitations or [],
                "is_commercially_available": c.is_commercially_available,
                "owner_id": _gov(c).get("owner_id"),
                "review_status": _gov(c).get("review_status", "pending_review"),
            }
            for c in rows
        ]
    }


@router.post("")
async def create_capability(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    key = str(body.get("capability_key") or "").strip()
    name = str(body.get("name") or "").strip()
    if not key or not name:
        raise HTTPException(400, "capability_key and name required")
    maturity = str(body.get("maturity") or "concept")
    if maturity not in MATURITY_LEVELS:
        raise HTTPException(400, "invalid maturity")
    complexity = str(body.get("complexity") or "medium")
    if complexity not in ("low", "medium", "high"):
        raise HTTPException(400, "invalid complexity")
    owner_id = str(body.get("owner_id") or "").strip() or None
    review_status = str(body.get("review_status") or "pending_review").strip()
    if review_status not in {"pending_review", "reviewed", "approved", "rejected"}:
        raise HTTPException(400, "invalid review_status")
    _cap_guard(body, "capability create")
    deployment_evidence = list(body.get("deployment_evidence") or [])
    deployment_evidence.append({"_governance": {"owner_id": owner_id, "review_status": review_status}})
    capability = Capability(
        org_id=org_id,
        capability_key=key,
        name=name,
        maturity=maturity,
        supported_use_cases=list(body.get("supported_use_cases") or []),
        integrations=list(body.get("integrations") or []),
        complexity=complexity,
        limitations=list(body.get("limitations") or []),
        dependencies=list(body.get("dependencies") or []),
        pricing_notes=str(body.get("pricing_notes") or ""),
        deployment_evidence=deployment_evidence,
        is_commercially_available=bool(body.get("is_commercially_available", False)),
    )
    db.add(capability)
    await db.commit()
    await db.refresh(capability)
    return {
        "id": capability.id,
        "capability_key": capability.capability_key,
        "maturity": capability.maturity,
        "is_commercially_available": capability.is_commercially_available,
        "owner_id": owner_id,
        "review_status": review_status,
    }


@router.post("/evaluate")
async def evaluate_fit(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    _cap_guard(body, "capability evaluate")
    subject_id = str(body.get("subject_id") or "").strip()
    if not subject_id:
        raise HTTPException(400, "subject_id required")
    scores: dict[str, float] = {}
    for field in _SCORES:
        value = float(body.get(field) or 0.0)
        if not 0.0 <= value <= 1.0:
            raise HTTPException(400, f"{field} must be between 0 and 1")
        scores[field] = value

    capability = None
    capability_id = body.get("capability_id")
    if capability_id:
        capability = (
            await db.execute(select(Capability).where(Capability.id == str(capability_id)))
        ).scalars().first()
        if capability is None or (
            capability.org_id is not None and str(capability.org_id) != str(org_id)
        ):
            evt = await record_cross_tenant_block_if_mismatch(
                db,
                org_id=org_id,
                resource=capability,
                source="capabilities.api.evaluate",
                actor_type="human",
                actor_id=str(getattr(user, "id", "") or "") or None,
                payload={"capability_id": str(capability_id)},
            )
            if evt is not None:
                await db.commit()
            raise HTTPException(404, "capability not found")

    disposition, rationale = solution_fit(
        capability,
        contact_allowed=bool(body.get("contact_allowed", True)),
        **scores,
    )
    fit = capability_fit_score(capability, body.get("required_use_case")) if capability else 0.0
    assessment = SolutionFitAssessment(
        org_id=org_id,
        subject_type=str(body.get("subject_type") or "company"),
        subject_id=subject_id,
        capability_id=capability.id if capability else None,
        capability_fit=fit,
        contact_allowed=bool(body.get("contact_allowed", True)),
        disposition=disposition,
        rationale=rationale,
        **scores,
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    eng_allowed, eng_reason = engineering_work_guard(disposition)
    return {
        "id": assessment.id,
        "disposition": disposition,
        "rationale": rationale,
        "capability_fit": fit,
        "engineering_work_allowed": eng_allowed,
        "engineering_work_reason": eng_reason,
    }


@router.post("/blueprint")
async def solution_blueprint(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Read-only diagnosis -> solution-fit -> blueprint. No rows, no ROI promise."""
    from aios.config import DEFAULT_PLAN, PLANS
    from aios.db.models import Organization
    from aios.templates import TEMPLATES, apply_template

    scores: dict[str, float] = {}
    for field in _SCORES:
        value = float(body.get(field) or 0.0)
        if not 0.0 <= value <= 1.0:
            raise HTTPException(400, f"{field} must be between 0 and 1")
        scores[field] = value

    capability = None
    capability_id = body.get("capability_id")
    if capability_id:
        capability = (
            await db.execute(select(Capability).where(Capability.id == str(capability_id)))
        ).scalars().first()
        if capability is None or (
            capability.org_id is not None and str(capability.org_id) != str(org_id)
        ):
            evt = await record_cross_tenant_block_if_mismatch(
                db,
                org_id=org_id,
                resource=capability,
                source="api.capabilities.blueprint",
                actor_type="human",
                actor_id=str(getattr(user, "id", "") or "") or None,
                payload={"capability_id": str(capability_id)},
            )
            if evt is not None:
                await db.commit()
            raise HTTPException(404, "capability not found")

    disposition, rationale = solution_fit(
        capability, contact_allowed=bool(body.get("contact_allowed", True)), **scores
    )
    fit = capability_fit_score(capability, body.get("required_use_case")) if capability else 0.0
    eng_allowed, eng_reason = engineering_work_guard(disposition)

    agent_type = str(body.get("agent_type") or "").strip()
    if agent_type and agent_type not in TEMPLATES:
        raise HTTPException(400, "unknown agent_type")
    template = apply_template(agent_type) if agent_type else None

    org = await db.get(Organization, org_id)
    plan = (org.extra_data or {}).get("plan", DEFAULT_PLAN) if org else DEFAULT_PLAN
    limits = PLANS.get(plan, PLANS[DEFAULT_PLAN])
    enforced_keys = (
        "max_agents", "max_teams", "max_messages_per_day", "max_tokens_per_month",
        "max_cost_brl", "sla_minutes", "channels", "max_evolution_instances",
    )
    return {
        "read_only": True,
        "disposition": disposition,
        "rationale": rationale,
        "capability_fit": fit,
        "engineering_work_allowed": eng_allowed,
        "engineering_work_reason": eng_reason,
        "capability": {
            "id": capability.id,
            "capability_key": capability.capability_key,
            "maturity": capability.maturity,
            "limitations": capability.limitations or [],
            "dependencies": capability.dependencies or [],
        } if capability else None,
        "blueprint": {
            "agent_type": agent_type or None,
            "tools": template["tools"] if template else [],
            "governance_config": template.get("governance_config", {}) if template else {},
        },
        "plan": plan,
        "plan_limits": {k: limits.get(k) for k in enforced_keys},
        "limit_source": "aios/config.py:PLANS",
        "enforced_by": "aios/core/limits.py:check_org_limits",
        "estimate": False,
    }


@router.get("/assessments")
async def list_assessments(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (
        await db.execute(
            select(SolutionFitAssessment).where(SolutionFitAssessment.org_id == org_id)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": a.id,
                "subject_id": a.subject_id,
                "capability_id": a.capability_id,
                "disposition": a.disposition,
                "rationale": a.rationale,
                "capability_fit": a.capability_fit,
                "engineering_work_allowed": engineering_work_guard(a.disposition)[0],
            }
            for a in rows
        ]
    }
