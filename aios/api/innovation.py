"""Lean innovation API: hypotheses, declared experiments, Founder decisions (§11)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization, User
from aios.governance.innovation import (
    DECISIONS,
    EXPERIMENT_TRACKS,
    HYPOTHESIS_KINDS,
    MVP_TYPES,
    Experiment,
    Hypothesis,
    autonomous_action_guard,
    decide_from_result,
    evaluate_experiment,
    has_track_c_evidence,
    innovation_scoreboard,
    is_track_c_autonomous,
    missing_experiment_fields,
    production_promotion_allowed,
    track_b_hypothesis_required,
)


def _innovation_guard(
    body: dict,
    action: str,
    *,
    track: str | None = None,
    autonomous: bool | None = None,
    has_evidence: bool | None = None,
) -> None:
    """Fail-closed Track C autonomous guard for mutating innovation endpoints.

    Narrow/explicit: only triggers when payload/experiment marks Track C autonomous.
    Does not claim coverage for all execution systems.
    """
    perms = body.get("permissions") if isinstance(body.get("permissions"), dict) else {}
    t = track if track is not None else body.get("track", perms.get("track"))
    if autonomous is None:
        mode = str(body.get("optimization_mode") or perms.get("optimization_mode") or perms.get("mode") or "").strip().lower()
        auto = bool(body.get("autonomous", perms.get("autonomous", False))) or mode in {"track_c_autonomous", "autonomous", "auto_optimize"}
    else:
        auto = autonomous
    evidence = body.get("evidence", perms.get("evidence", perms.get("evidence_refs", perms.get("track_c_evidence"))))
    ev = bool(evidence) if not isinstance(evidence, (str, list, tuple, set, dict)) else bool(evidence)
    if has_evidence is not None:
        ev = ev or has_evidence
    founder_approved = bool(body.get("founder_approved", perms.get("founder_approved", False)))
    ok, reason = autonomous_action_guard(
        track=str(t) if t is not None else None,
        autonomous=auto,
        has_evidence=ev,
        founder_approved=founder_approved,
        action=action,
    )
    if not ok:
        raise HTTPException(403, reason)

router = APIRouter(prefix="/api/innovation", tags=["innovation"])


def _is_founder(user: User, org: Organization | None) -> bool:
    if org is None:
        return False
    return (org.extra_data or {}).get("founder_user_id") == user.id or user.role == "owner"


@router.get("/hypotheses")
async def list_hypotheses(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(Hypothesis).where(Hypothesis.org_id == org_id))).scalars().all()
    return {
        "items": [
            {
                "id": h.id, "title": h.title, "kind": h.kind,
                "riskiest_assumption": h.riskiest_assumption, "status": h.status,
            }
            for h in rows
        ]
    }


@router.post("/hypotheses")
async def create_hypothesis(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    _innovation_guard(body, "innovation hypothesis create")
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    kind = str(body.get("kind") or "value")
    if kind not in HYPOTHESIS_KINDS:
        raise HTTPException(400, "invalid hypothesis kind")
    h = Hypothesis(
        org_id=org_id,
        department_id=body.get("department_id"),
        title=title,
        kind=kind,
        statement=str(body.get("statement") or ""),
        riskiest_assumption=str(body.get("riskiest_assumption") or ""),
    )
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return {"id": h.id, "status": h.status}


@router.get("/experiments")
async def list_experiments(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(Experiment).where(Experiment.org_id == org_id))).scalars().all()
    return {
        "items": [
            {
                "id": e.id, "hypothesis_id": e.hypothesis_id, "title": e.title,
                "mvp_type": e.mvp_type, "metric_name": e.metric_name,
                "result": e.result, "decision": e.decision,
            }
            for e in rows
        ]
    }


@router.post("/experiments")
async def create_experiment(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    hypothesis_id = body.get("hypothesis_id")
    if hypothesis_id:
        h = (
            await db.execute(
                select(Hypothesis).where(
                    Hypothesis.id == str(hypothesis_id), Hypothesis.org_id == org_id
                )
            )
        ).scalars().first()
        if h is None:
            raise HTTPException(404, "hypothesis not found")
    mvp_type = str(body.get("mvp_type") or "experimental_prototype")
    if mvp_type not in MVP_TYPES:
        raise HTTPException(400, "invalid mvp_type")
    direction = str(body.get("direction") or "increase")
    if direction not in ("increase", "decrease"):
        raise HTTPException(400, "invalid direction")

    permissions = dict(body.get("permissions") or {})
    track = permissions.get("track")
    if track is not None:
        track_norm = str(track).strip().upper()
        if track_norm not in EXPERIMENT_TRACKS:
            raise HTTPException(400, "invalid track")
        permissions["track"] = track_norm

    exp = Experiment(
        org_id=org_id,
        hypothesis_id=str(hypothesis_id) if hypothesis_id else None,
        title=str(body.get("title") or "").strip(),
        mvp_type=mvp_type,
        riskiest_assumption=str(body.get("riskiest_assumption") or ""),
        metric_name=str(body.get("metric_name") or ""),
        baseline=body.get("baseline"),
        sample_size=int(body.get("sample_size") or 0),
        success_threshold=body.get("success_threshold"),
        direction=direction,
        cost_cap_brl=float(body.get("cost_cap_brl") or 0.0),
        time_cap_days=int(body.get("time_cap_days") or 0),
        owner_id=body.get("owner_id"),
        stop_conditions=str(body.get("stop_conditions") or ""),
        permissions=permissions,
        privacy_reviewed=bool(body.get("privacy_reviewed", False)),
    )
    missing = missing_experiment_fields(exp)
    if missing:
        raise HTTPException(400, f"missing experiment declaration: {', '.join(missing)}")
    ok, reason = track_b_hypothesis_required(exp)
    if not ok:
        raise HTTPException(400, reason)
    _innovation_guard(
        body,
        "innovation experiment create",
        track=permissions.get("track"),
        autonomous=is_track_c_autonomous(exp),
        has_evidence=has_track_c_evidence(exp),
    )
    db.add(exp)
    await db.commit()
    await db.refresh(exp)
    return {"id": exp.id, "result": exp.result, "track": permissions.get("track")}


async def _experiment(exp_id: str, org_id: str, db: DatabaseBackend) -> Experiment:
    exp = (
        await db.execute(
            select(Experiment).where(Experiment.id == exp_id, Experiment.org_id == org_id)
        )
    ).scalars().first()
    if exp is None:
        raise HTTPException(404, "experiment not found")
    return exp


@router.post("/experiments/{exp_id}/evaluate")
async def evaluate(
    exp_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    exp = await _experiment(exp_id, org_id, db)
    _innovation_guard(
        body,
        "innovation experiment evaluate",
        track=(exp.permissions or {}).get("track"),
        autonomous=is_track_c_autonomous(exp),
        has_evidence=has_track_c_evidence(exp),
    )
    if "observed" in body:
        exp.observed = float(body["observed"])
    if "spent_brl" in body:
        exp.spent_brl = float(body["spent_brl"])
    missing = missing_experiment_fields(exp)
    if missing:
        raise HTTPException(400, f"missing experiment declaration: {', '.join(missing)}")
    exp.result = evaluate_experiment(exp)
    if exp.started_at is None:
        exp.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if exp.result != "pending":
        exp.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    suggested = decide_from_result(exp.result)
    exp.interpretation = f"{exp.result} -> suggested {suggested}"
    await db.commit()
    return {"result": exp.result, "suggested_decision": suggested, "interpretation": exp.interpretation}


@router.post("/experiments/{exp_id}/decide")
async def decide(
    exp_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: DatabaseBackend = Depends(get_db_backend),
):
    exp = await _experiment(exp_id, user.org_id, db)
    if exp.result == "pending":
        raise HTTPException(400, "experiment not evaluated")
    org = await db.get(Organization, user.org_id)
    if not _is_founder(user, org):
        raise HTTPException(403, "Founder approval required")
    decision = str(body.get("decision") or decide_from_result(exp.result))
    if decision not in DECISIONS:
        raise HTTPException(400, "invalid decision")
    ok, reason = track_b_hypothesis_required(exp)
    if not ok:
        raise HTTPException(400, reason)
    promote_to_production = bool(body.get("promote_to_production", False))
    if promote_to_production or decision == "persevere" and str(body.get("target") or "") == "production":
        allowed, reason = production_promotion_allowed(exp)
        if not allowed:
            raise HTTPException(403, reason)
    ok, reason = autonomous_action_guard(
        track=(exp.permissions or {}).get("track"),
        autonomous=is_track_c_autonomous(exp),
        has_evidence=has_track_c_evidence(exp),
        founder_approved=True,
        action="experiment decision",
    )
    if not ok:
        raise HTTPException(403, reason)
    if is_track_c_autonomous(exp) and decision == "persevere" and not has_track_c_evidence(exp):
        raise HTTPException(403, "Track C autonomous optimization requires evidence before approval")
    exp.decision = decision
    await db.commit()
    return {"id": exp.id, "decision": decision}


@router.get("/scoreboard")
async def scoreboard(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(Experiment).where(Experiment.org_id == org_id))).scalars().all()
    return innovation_scoreboard(list(rows))
