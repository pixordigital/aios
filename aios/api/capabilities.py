"""Capability registry + deterministic Solution-Fit API (brief §2.3, §12)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select

from aios.api.deps import get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.governance.capability_registry import (
    MATURITY_LEVELS,
    Capability,
    SolutionFitAssessment,
    capability_fit_score,
    solution_fit,
)

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])

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
        deployment_evidence=list(body.get("deployment_evidence") or []),
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
    }


@router.post("/evaluate")
async def evaluate_fit(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
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
            await db.execute(
                select(Capability).where(
                    Capability.id == str(capability_id), _visible(org_id)
                )
            )
        ).scalars().first()
        if capability is None:
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
    return {
        "id": assessment.id,
        "disposition": disposition,
        "rationale": rationale,
        "capability_fit": fit,
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
            }
            for a in rows
        ]
    }
