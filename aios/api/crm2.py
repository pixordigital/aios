import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.schemas import PageResponse
from aios.db.models import CrmDeal, Agent, Team
from aios.core.secrets import encrypt_secret
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crm", tags=["crm"])

STAGES = ["prospection","mql","sql","opportunity","closed_won","closed_lost"]

def _crm_enabled(org):
    from aios.config import settings
    if settings.internal_mode:
        return True  # ferramenta interna: CRM sempre ativo
    if not org: return False
    data = org.extra_data or {}
    if data.get("plan") in ("unlimited","enterprise"): return True
    if data.get("crm_enabled"): return True
    if data.get("trial") and data.get("plan")=="pro": return True
    return False

@router.get("/deals", response_model=PageResponse)
async def list_deals(stage: str = "", agent_id: str = "", q: str = "", limit: int = Query(50, le=200), offset: int = 0, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA é upsell R$97 — ative em /dashboard/billing")
    query = select(CrmDeal).where(CrmDeal.org_id==org_id)
    if stage and stage in STAGES:
        query = query.where(CrmDeal.stage==stage)
    if agent_id:
        query = query.where(CrmDeal.agent_id==agent_id)
    if q:
        query = query.where((CrmDeal.lead_name.ilike(f"%{q}%")) | (CrmDeal.lead_email.ilike(f"%{q}%")))
    items = (await db.execute(query.order_by(CrmDeal.updated_at.desc()).limit(limit + 1).offset(offset))).scalars().all()
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    next_cursor = str(offset + limit) if has_more else None
    total = (await db.execute(select(__import__('sqlalchemy').func.count(CrmDeal.id)).where(CrmDeal.org_id == org_id))).scalar()
    return PageResponse(items=items, next_cursor=next_cursor, has_more=has_more, total=total)

@router.post("/deals")
async def create_deal(body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    stage = body.get("stage","prospection")
    if stage not in STAGES: stage="prospection"
    d = CrmDeal(org_id=org_id, lead_name=body.get("lead_name","") or body.get("name",""), lead_email=body.get("lead_email","") or body.get("email",""), lead_phone=body.get("lead_phone","") or body.get("phone",""), stage=stage, value=float(body.get("value",0)), score=int(body.get("score",0)), agent_id=body.get("agent_id"), team_id=body.get("team_id"), source=body.get("source","whatsapp"), extra_data=body.get("extra_data",{}))
    # custo estimado
    try:
        from aios.core.tracing import estimate_cost
        d.cost_usd = estimate_cost(body.get("model","openai/gpt-4o-mini"), 800)
    except Exception:
        pass
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d

@router.patch("/deals/{deal_id}")
async def update_deal(deal_id: str, body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    deal = await db.get(CrmDeal, deal_id)
    if not deal or deal.org_id != org_id:
        raise HTTPException(404)
    # Deal Desk Governado — wedge (PLANS + HITL alert)
    try:
        from aios.governance.deal_desk import audit_deal_change, check_human_deviation
        from aios.db.models import Organization as _Org
        _org = await db.get(_Org, org_id)
        if body.get("value"):
            allowed, pa, exposure = await audit_deal_change(deal, float(body["value"]), body.get("extra_data"), _org, db, changed_by=user.id if hasattr(user, "id") else "human", agent_id=deal.agent_id)
            if not allowed and pa:
                await db.commit()
                return {"pending_approval": True, "discount": pa.tool_args.get("discount"), "exposure": exposure, "pending_id": pa.id, "message": f"Desconto {pa.tool_args.get('discount'):.1f}% > política {pa.tool_args.get('max_discount')}% — aguardando aprovação (Evidence: CrmDealVersion + AuditLog)"}
        # desvio humano
        if body.get("stage"):
            pa2 = await check_human_deviation(deal, body, _org, db, user.id if hasattr(user, "id") else "human")
            if pa2:
                await db.commit()
                # não bloqueia, só alerta — retorna deal + alerta
                pass
    except Exception:
        pass
    old_stage = deal.stage
    for k in ["stage","value","score","lead_name","lead_email","lead_phone","agent_id","team_id","extra_data"]:
        if k in body:
            setattr(deal, k, body[k])
    await db.commit()
    await db.refresh(deal)

    # Stage movement is the signal proactive agents care about (follow up on
    # won/lost, rescue stalled deals). Published only on a real transition —
    # re-saving a deal without changing stage is not news. Idempotency key is
    # deal+old->new so a retried request cannot notify twice.
    new_stage = body.get("stage")
    if new_stage and new_stage != old_stage:
        try:
            from aios.core.events import publish as publish_event

            await publish_event(
                f"crm.stage_changed.{new_stage}",
                org_id,
                {
                    "deal_id": deal.id,
                    "lead_name": deal.lead_name,
                    "lead_email": deal.lead_email,
                    "old_stage": old_stage,
                    "new_stage": new_stage,
                    "value": float(deal.value or 0),
                    "pipeline": deal.pipeline,
                    "owner_agent_id": deal.agent_id or "",
                },
                idempotency_key=f"crm-stage:{deal.id}:{old_stage}->{new_stage}",
            )
        except Exception:
            logger.exception("crm.stage_changed publish failed deal=%s", deal.id)

    # Memory Layer — insight pós closed_won/lost
    if body.get("stage") in ("closed_won", "closed_lost") and old_stage != body.get("stage"):
        try:
            from aios.core.insights import capture_deal_insight
            await capture_deal_insight(org_id, deal_id, body["stage"], conversation=[])
        except Exception:
            pass
    return deal

@router.get("/deals/{deal_id}")
async def get_deal(deal_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    deal = await db.get(CrmDeal, deal_id)
    if not deal or deal.org_id != org_id:
        raise HTTPException(404)
    return deal

@router.delete("/deals/{deal_id}")
async def delete_deal(deal_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    deal = await db.get(CrmDeal, deal_id)
    if not deal or deal.org_id != org_id:
        raise HTTPException(404)
    await db.delete(deal)
    await db.commit()
    return {"ok": True}

@router.get("/stats")
async def stats(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM upsell")
    rows = (await db.execute(select(CrmDeal).where(CrmDeal.org_id==org_id))).scalars().all()
    by_stage = {s: 0 for s in STAGES}
    total_value = 0
    total_cost = 0
    for r in rows:
        by_stage[r.stage] = by_stage.get(r.stage,0)+1
        total_value += r.value or 0
        total_cost += r.cost_usd or 0
    return {"total": len(rows), "by_stage": by_stage, "total_value": total_value, "total_cost": round(total_cost,4), "total_cost_brl": round(total_cost*5.5,2)}

@router.get("/queue")
async def queue(limit: int = Query(20, le=100), db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    """Fila do dia — deals abertos ordenados por timing (origem+recência+tentativas)."""
    from aios.db.models import Organization
    from aios.core.signals import rank_queue, OPEN_STAGES
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    rows = (await db.execute(select(CrmDeal).where(CrmDeal.org_id==org_id, CrmDeal.stage.in_(OPEN_STAGES)).limit(200))).scalars().all()
    return [
        {"id": r["deal"].id, "lead_name": r["deal"].lead_name, "lead_phone": r["deal"].lead_phone, "stage": r["deal"].stage, "timing": r["timing"], "reasons": r["reasons"], "hours_since_touch": r["hours_since_touch"], "attempts": r["attempts"]}
        for r in rank_queue(rows, limit)
    ]

@router.post("/enable")
async def enable_crm(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not org or user.role not in ("admin","org_admin","superadmin"):
        raise HTTPException(403)
    data = dict(org.extra_data or {})
    data["crm_enabled"] = True
    org.extra_data = data
    await db.commit()
    return {"ok": True, "crm_enabled": True}

@router.post("/goals")
async def set_goal(body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    """Set monthly sales goal: {year_month: YYYY-MM, target_brl, team_id?}."""
    from aios.core.sales_goals import set_goal as _set
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    ym = (body.get("year_month") or "")[:7]
    target = float(body.get("target_brl", 0))
    if len(ym) != 7 or target <= 0:
        raise HTTPException(422, "year_month YYYY-MM + target_brl > 0 required")
    goal = await _set(db, org_id, ym, target, team_id=body.get("team_id"),
                      created_by=user.id if hasattr(user, "id") else None)
    return {"id": goal.id, "year_month": goal.year_month, "target_brl": goal.target_brl, "team_id": goal.team_id}


@router.get("/goals/current")
async def goal_current(year_month: str = "", team_id: str = "", db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    """Goal progress + pace for a month (default current)."""
    from aios.core.sales_goals import month_progress
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    return await month_progress(db, org_id, year_month or None, team_id or None)


@router.get("/admin/all")
async def admin_all(q: str = "", limit: int = 50, db: DatabaseBackend = Depends(get_db_backend), user=Depends(get_current_user)):
    if user.role != "superadmin":
        raise HTTPException(403)
    query = select(CrmDeal).order_by(CrmDeal.updated_at.desc()).limit(limit)
    if q:
        query = query.where((CrmDeal.lead_name.ilike(f"%{q}%")) | (CrmDeal.org_id==q))
    rows = (await db.execute(query)).scalars().all()
    return rows
