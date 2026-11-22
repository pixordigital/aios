"""Model Intelligence API: registry, eligibility, selection, proposals, rollback (§17)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization, User
from aios.governance.model_intelligence import (
    MODEL_TIERS,
    ModelRegistryEntry,
    eligible_models,
    recommend_change,
    rollback_target,
    select_model,
)

router = APIRouter(prefix="/api/models", tags=["model-intelligence"])


def _visible(org_id: str):
    return or_(ModelRegistryEntry.org_id == org_id, ModelRegistryEntry.org_id.is_(None))


async def _entries(db: DatabaseBackend, org_id: str) -> list[ModelRegistryEntry]:
    return list(
        (await db.execute(select(ModelRegistryEntry).where(_visible(org_id)))).scalars().all()
    )


async def _entry(entry_id: str, org_id: str, db: DatabaseBackend) -> ModelRegistryEntry:
    entry = (
        await db.execute(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.id == entry_id, _visible(org_id)
            )
        )
    ).scalars().first()
    if entry is None:
        raise HTTPException(404, "model registry entry not found")
    return entry


@router.get("")
async def list_models(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = await _entries(db, org_id)
    return {
        "items": [
            {
                "id": e.id, "model_key": e.model_key, "provider": e.provider,
                "tier": e.tier, "price_currency": e.price_currency,
                "quality_score": e.quality_score, "reliability": e.reliability,
                "approved": e.approved,
            }
            for e in rows
        ]
    }


@router.post("")
async def create_model(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    key = str(body.get("model_key") or "").strip()
    provider = str(body.get("provider") or "").strip()
    if not key or not provider:
        raise HTTPException(400, "model_key and provider required")
    tier = int(body.get("tier") or 1)
    if tier not in MODEL_TIERS:
        raise HTTPException(400, "invalid tier")
    entry = ModelRegistryEntry(
        org_id=org_id,
        model_key=key,
        provider=provider,
        tier=tier,
        input_price_per_1m=float(body.get("input_price_per_1m") or 0.0),
        output_price_per_1m=float(body.get("output_price_per_1m") or 0.0),
        price_currency=str(body.get("price_currency") or "USD"),
        quality_score=float(body.get("quality_score") or 0.0),
        reliability=float(body.get("reliability") or 1.0),
        latency_p95_ms=int(body.get("latency_p95_ms") or 0),
        capabilities=list(body.get("capabilities") or []),
        context_window=int(body.get("context_window") or 0),
        privacy_ok=bool(body.get("privacy_ok", True)),
        contract_ok=bool(body.get("contract_ok", True)),
        config_version=str(body.get("config_version") or "1"),
        notes=str(body.get("notes") or ""),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "model_key": entry.model_key, "approved": entry.approved}


@router.post("/{entry_id}/approve")
async def approve_model(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: DatabaseBackend = Depends(get_db_backend),
):
    entry = await _entry(entry_id, user.org_id, db)
    if entry.org_id != user.org_id:
        raise HTTPException(403, "cannot approve a global registry entry")
    org = await db.get(Organization, user.org_id)
    founder = bool(org and ((org.extra_data or {}).get("founder_user_id") == user.id or user.role == "owner"))
    if not founder:
        raise HTTPException(403, "Founder approval required")
    entry.approved = True
    await db.commit()
    return {"id": entry.id, "approved": True, "approved_by": user.id}


def _filters(body: dict) -> dict:
    allowed = (
        "min_quality", "min_reliability", "required_capabilities", "max_latency_p95_ms",
        "privacy_required", "contract_required", "tier", "min_context_window", "currency",
    )
    filters = {k: body[k] for k in allowed if k in body}
    if "required_capabilities" in filters:
        filters["required_capabilities"] = tuple(filters["required_capabilities"] or [])
    return filters


@router.post("/eligible")
async def eligible(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    rows = eligible_models(await _entries(db, org_id), **_filters(body))
    return {"items": [e.model_key for e in rows]}


@router.post("/select")
async def select_route(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    entry, cost = select_model(
        await _entries(db, org_id),
        avg_input_tokens=float(body.get("avg_input_tokens") or 0.0),
        avg_output_tokens=float(body.get("avg_output_tokens") or 0.0),
        **_filters(body),
    )
    return {
        "model_key": entry.model_key if entry else None,
        "cost_per_success": None if cost == float("inf") else cost,
    }


@router.post("/recommend")
async def recommend(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    entries = {e.model_key: e for e in await _entries(db, org_id)}
    current = entries.get(str(body.get("current_model_key") or ""))
    proposed = entries.get(str(body.get("proposed_model_key") or ""))
    if current is None or proposed is None:
        raise HTTPException(404, "current or proposed model not found")
    return recommend_change(
        current,
        proposed,
        avg_input_tokens=float(body.get("avg_input_tokens") or 0.0),
        avg_output_tokens=float(body.get("avg_output_tokens") or 0.0),
        monthly_tasks=int(body.get("monthly_tasks") or 0),
        required_quality=float(body.get("required_quality") or 0.0),
    )


@router.get("/rollback-target")
async def rollback(
    agent_default_key: str,
    previous_key: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    return {"model_key": rollback_target(await _entries(db, org_id),
                                         agent_default_key=agent_default_key,
                                         previous_key=previous_key)}
