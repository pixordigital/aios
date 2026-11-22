import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from aios.core.crm_intelligence import (
    Account,
    Contact,
    InteractionEvent,
    deal_360_payload,
    deal_entity_kind,
    find_account_for_deal,
    find_account_for_deal_with_meta,
    find_contact_for_deal,
    find_contact_for_deal_with_meta,
    record_interaction_event,
    relationship_health,
    sales_priority,
)
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import CrmDeal
from aios.schemas import PageResponse

from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crm", tags=["crm"])

STAGES = ["prospection","mql","sql","opportunity","closed_won","closed_lost"]
STAGE_WEIGHT = {"prospection": 0.2, "mql": 0.35, "sql": 0.55, "opportunity": 0.75, "closed_won": 1.0, "closed_lost": 0.0}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


async def _deal_or_404(db, deal_id: str, org_id: str) -> CrmDeal:
    deal = await db.get(CrmDeal, deal_id)
    if not deal or deal.org_id != org_id:
        raise HTTPException(404)
    return deal


async def _account_or_404(db, account_id: str, org_id: str) -> Account:
    row = await db.get(Account, account_id)
    if not row or row.org_id != org_id:
        raise HTTPException(404)
    return row


async def _contact_or_404(db, contact_id: str, org_id: str) -> Contact:
    row = await db.get(Contact, contact_id)
    if not row or row.org_id != org_id:
        raise HTTPException(404)
    return row

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
    total = (await db.execute(select(func.count(CrmDeal.id)).where(CrmDeal.org_id == org_id))).scalar()
    enriched = []
    for d in items:
        account, account_link = await find_account_for_deal_with_meta(db, d)
        contact, contact_link = await find_contact_for_deal_with_meta(db, d)
        payload = deal_360_payload(d, account=account, contact=contact, account_link=account_link, contact_link=contact_link)
        payload["prioritization"] = {
            "kind": "deterministic_heuristic",
            "validated_predictive": False,
            "score": sales_priority(
                icp_fit=float((d.extra_data or {}).get("icp_fit", 0.5) or 0.5),
                recency_days=max(0, int((datetime.utcnow() - (d.updated_at or datetime.utcnow())).total_seconds() // 86400)),
                attempts=int((d.extra_data or {}).get("attempts", 0) or 0),
                deal_value=float(d.value or 0),
                stage_weight=STAGE_WEIGHT.get(d.stage, 0.2),
            ),
        }
        enriched.append(payload)
    return PageResponse(items=enriched, next_cursor=next_cursor, has_more=has_more, total=total)

@router.post("/deals")
async def create_deal(body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    stage = body.get("stage","prospection")
    if stage not in STAGES: stage="prospection"
    raw_extra = body.get("extra_data") if isinstance(body.get("extra_data"), dict) else {}
    # extra_data legacy adapter: allow only known keys, block ad-hoc growth.
    allowed_extra = {}
    blocked = []
    from aios.core.crm_intelligence import _KNOWN_EXTRA_KEYS
    for k, v in raw_extra.items():
        if k in _KNOWN_EXTRA_KEYS:
            allowed_extra[k] = v
        else:
            blocked.append(k)
    if blocked:
        logger.warning("crm2.create_deal blocked ad-hoc extra_data keys: %s", blocked)
    d = CrmDeal(org_id=org_id, lead_name=body.get("lead_name","") or body.get("name",""), lead_email=body.get("lead_email","") or body.get("email",""), lead_phone=body.get("lead_phone","") or body.get("phone",""), stage=stage, value=float(body.get("value",0)), score=int(body.get("score",0)), agent_id=body.get("agent_id"), team_id=body.get("team_id"), source=body.get("source","whatsapp"), extra_data=allowed_extra)
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
    deal = await _deal_or_404(db, deal_id, org_id)
    account, account_link = await find_account_for_deal_with_meta(db, deal)
    contact, contact_link = await find_contact_for_deal_with_meta(db, deal)
    payload = deal_360_payload(deal, account=account, contact=contact, account_link=account_link, contact_link=contact_link)
    payload["prioritization"] = {
        "kind": "deterministic_heuristic",
        "validated_predictive": False,
        "score": sales_priority(
            icp_fit=float((deal.extra_data or {}).get("icp_fit", 0.5) or 0.5),
            recency_days=max(0, int((datetime.utcnow() - (deal.updated_at or datetime.utcnow())).total_seconds() // 86400)),
            attempts=int((deal.extra_data or {}).get("attempts", 0) or 0),
            deal_value=float(deal.value or 0),
            stage_weight=STAGE_WEIGHT.get(deal.stage, 0.2),
        ),
    }
    return payload

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

# --- Accounts / Contacts / Timeline (CRM 360 minimal, no schema change) ------

@router.get("/accounts")
async def list_accounts(q: str = "", limit: int = Query(50, le=200), offset: int = 0, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    query = select(Account).where(Account.org_id == org_id)
    if q:
        like = f"%{q}%"
        query = query.where((Account.name.ilike(like)) | (Account.cnpj.ilike(like)))
    rows = (await db.execute(query.order_by(Account.updated_at.desc()).limit(limit).offset(offset))).scalars().all()
    return [{"id": r.id, "name": r.name, "cnpj": r.cnpj, "industry": r.industry, "status": r.status, "health_score": r.health_score, "lifetime_value": r.lifetime_value, "owner_agent_id": r.owner_agent_id} for r in rows]


@router.post("/accounts")
async def create_account(body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name required")
    cnpj = str(body.get("cnpj") or "").strip() or None
    row = Account(org_id=org_id, name=name[:255], cnpj=cnpj[:18] if cnpj else None, industry=str(body.get("industry") or "")[:120], website=str(body.get("website") or "")[:500], size=str(body.get("size") or "")[:40], status=str(body.get("status") or "prospect")[:30], owner_agent_id=body.get("owner_agent_id") or None)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "name": row.name, "cnpj": row.cnpj, "status": row.status}


@router.get("/accounts/{account_id}")
async def get_account(account_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    row = await _account_or_404(db, account_id, org_id)
    contacts = (await db.execute(select(Contact).where(Contact.org_id == org_id, Contact.account_id == account_id).order_by(Contact.updated_at.desc()).limit(50))).scalars().all()
    deals = (await db.execute(select(CrmDeal).where(CrmDeal.org_id == org_id).order_by(CrmDeal.updated_at.desc()).limit(200))).scalars().all()
    linked_deals = []
    for d in deals:
        acc, acc_link = await find_account_for_deal_with_meta(db, d)
        if acc and acc.id == account_id:
            linked_deals.append(deal_360_payload(d, account=acc, account_link=acc_link))
    interactions = (await db.execute(select(InteractionEvent).where(InteractionEvent.org_id == org_id, InteractionEvent.account_id == account_id).order_by(InteractionEvent.occurred_at.desc()).limit(50))).scalars().all()
    health_score, health_reason = relationship_health(days_since_last_contact=None if not interactions else max(0, int((datetime.utcnow() - interactions[0].occurred_at).total_seconds() // 86400)), open_commitments=0, overdue_commitments=0, support_tickets_open=0)
    return {
        "account": {"id": row.id, "name": row.name, "cnpj": row.cnpj, "industry": row.industry, "status": row.status, "health_score": health_score, "health_reason": health_reason, "health_note": "Deterministic heuristic, not validated predictive."},
        "contacts": [{"id": c.id, "name": c.name, "email": c.email, "phone": c.phone, "role": c.role} for c in contacts],
        "deals": linked_deals[:50],
        "timeline": [interaction_payload(i) for i in interactions],
    }


@router.get("/contacts")
async def list_contacts(q: str = "", account_id: str = "", limit: int = Query(50, le=200), offset: int = 0, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    query = select(Contact).where(Contact.org_id == org_id)
    if account_id:
        query = query.where(Contact.account_id == account_id)
    if q:
        like = f"%{q}%"
        query = query.where((Contact.name.ilike(like)) | (Contact.email.ilike(like)) | (Contact.phone.ilike(like)))
    rows = (await db.execute(query.order_by(Contact.updated_at.desc()).limit(limit).offset(offset))).scalars().all()
    return [{"id": r.id, "account_id": r.account_id, "name": r.name, "email": r.email, "phone": r.phone, "role": r.role, "is_decision_maker": r.is_decision_maker, "contact_allowed": r.contact_allowed} for r in rows]


@router.post("/contacts")
async def create_contact(body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name required")
    account_id = body.get("account_id") or None
    if account_id:
        await _account_or_404(db, str(account_id), org_id)
    row = Contact(org_id=org_id, account_id=account_id, name=name[:255], email=str(body.get("email") or "").strip().lower()[:255], phone=str(body.get("phone") or "")[:40], role=str(body.get("role") or "")[:160], source=str(body.get("source") or "manual")[:120], is_decision_maker=bool(body.get("is_decision_maker", False)))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "name": row.name, "email": row.email, "account_id": row.account_id}


@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    row = await _contact_or_404(db, contact_id, org_id)
    interactions = (await db.execute(select(InteractionEvent).where(InteractionEvent.org_id == org_id, InteractionEvent.contact_id == contact_id).order_by(InteractionEvent.occurred_at.desc()).limit(50))).scalars().all()
    return {
        "contact": {"id": row.id, "account_id": row.account_id, "name": row.name, "email": row.email, "phone": row.phone, "role": row.role, "is_decision_maker": row.is_decision_maker, "contact_allowed": row.contact_allowed},
        "timeline": [interaction_payload(i) for i in interactions],
    }


def interaction_payload(i: InteractionEvent) -> dict:
    return {"id": i.id, "account_id": i.account_id, "contact_id": i.contact_id, "deal_id": i.deal_id, "channel": i.channel, "direction": i.direction, "event_type": i.event_type, "summary": i.summary, "occurred_at": i.occurred_at.isoformat() if i.occurred_at else None, "source": i.source, "provenance": i.provenance or {}}


@router.get("/interactions")
async def list_interactions(deal_id: str = "", account_id: str = "", contact_id: str = "", limit: int = Query(50, le=200), db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    query = select(InteractionEvent).where(InteractionEvent.org_id == org_id)
    if deal_id:
        query = query.where(InteractionEvent.deal_id == deal_id)
    if account_id:
        query = query.where(InteractionEvent.account_id == account_id)
    if contact_id:
        query = query.where(InteractionEvent.contact_id == contact_id)
    rows = (await db.execute(query.order_by(InteractionEvent.occurred_at.desc()).limit(limit))).scalars().all()
    return [interaction_payload(r) for r in rows]


@router.post("/interactions")
async def create_interaction(body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    deal_id = body.get("deal_id") or None
    account_id = body.get("account_id") or None
    contact_id = body.get("contact_id") or None
    if deal_id:
        await _deal_or_404(db, str(deal_id), org_id)
    if account_id:
        await _account_or_404(db, str(account_id), org_id)
    if contact_id:
        await _contact_or_404(db, str(contact_id), org_id)
    ev = await record_interaction_event(
        db, org_id=org_id, deal_id=deal_id, account_id=account_id, contact_id=contact_id,
        channel=str(body.get("channel") or "manual"), direction=str(body.get("direction") or "outbound"),
        event_type=str(body.get("event_type") or "message"), summary=str(body.get("summary") or ""),
        occurred_at=_parse_dt(body.get("occurred_at")), source=str(body.get("source") or "api"),
        provenance=body.get("provenance") if isinstance(body.get("provenance"), dict) else {},
    )
    await db.commit()
    await db.refresh(ev)
    return interaction_payload(ev)


@router.get("/360/overview")
async def crm_360_overview(limit: int = Query(20, le=100), db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    """Minimal read-only 360 from existing data. No schema change."""
    from aios.db.models import Organization

    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    deals = (await db.execute(select(CrmDeal).where(CrmDeal.org_id == org_id).order_by(CrmDeal.updated_at.desc()).limit(limit))).scalars().all()
    accounts = (await db.execute(select(Account).where(Account.org_id == org_id).order_by(Account.updated_at.desc()).limit(limit))).scalars().all()
    contacts = (await db.execute(select(Contact).where(Contact.org_id == org_id).order_by(Contact.updated_at.desc()).limit(limit))).scalars().all()
    interactions = (await db.execute(select(InteractionEvent).where(InteractionEvent.org_id == org_id).order_by(InteractionEvent.occurred_at.desc()).limit(limit))).scalars().all()
    return {
        "available": {"deals": True, "accounts": True, "contacts": True, "interactions": True, "customer_360_read": True, "cs_workspace": False, "revenue_intelligence": "minimal_heuristic_only", "command_center": False},
        "notes": [
            "Customer 360 is minimal read model from existing CRM data; no schema change.",
            "CS/command center unavailable in this track (needs dedicated models/UI).",
            "Prioritization is deterministic heuristic, not validated predictive.",
            "Deal->account/contact links are heuristic/inferred; no schema FK (see docs/CRM_SCHEMA_GAPS.md).",
        ],
        "gaps": {
            "deal_account_fk": {"present": False, "kind": "schema_gap", "doc": "docs/CRM_SCHEMA_GAPS.md"},
            "deal_contact_fk": {"present": False, "kind": "schema_gap", "doc": "docs/CRM_SCHEMA_GAPS.md"},
            "command_center": {"present": False, "kind": "product_gap"},
            "cs_workspace": {"present": False, "kind": "product_gap"},
            "validated_predictive_revenue_intelligence": {"present": False, "kind": "evidence_gap"},
        },
        "counts": {"deals": len(deals), "accounts": len(accounts), "contacts": len(contacts), "interactions": len(interactions)},
        "recent_accounts": [{"id": a.id, "name": a.name, "status": a.status, "health_score": a.health_score} for a in accounts],
        "recent_contacts": [{"id": c.id, "name": c.name, "email": c.email, "account_id": c.account_id} for c in contacts],
        "recent_interactions": [interaction_payload(i) for i in interactions],
    }


@router.get("/360/deals/{deal_id}")
async def crm_360_deal(deal_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    """Read-only 360 for one deal. Same shape as GET /deals/{id} with explicit heuristic labels."""
    return await get_deal(deal_id, db=db, org_id=org_id)


@router.get("/360/accounts/{account_id}")
async def crm_360_account(account_id: str, limit: int = Query(50, le=200), db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    """Read-only account 360 from existing data. No schema change."""
    from aios.db.models import Organization

    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    account = await _account_or_404(db, account_id, org_id)
    contacts = (await db.execute(select(Contact).where(Contact.org_id == org_id, Contact.account_id == account_id).order_by(Contact.updated_at.desc()).limit(limit))).scalars().all()
    deals = (await db.execute(select(CrmDeal).where(CrmDeal.org_id == org_id).order_by(CrmDeal.updated_at.desc()).limit(200))).scalars().all()
    linked_deals = []
    for d in deals:
        acc, acc_link = await find_account_for_deal_with_meta(db, d)
        if acc and acc.id == account_id:
            linked_deals.append(deal_360_payload(d, account=acc, account_link=acc_link))
    interactions = (await db.execute(select(InteractionEvent).where(InteractionEvent.org_id == org_id, InteractionEvent.account_id == account_id).order_by(InteractionEvent.occurred_at.desc()).limit(limit))).scalars().all()
    return {
        "read_only": True,
        "schema_gap": {"deal_account_fk": False, "deal_contact_fk": False, "doc": "docs/CRM_SCHEMA_GAPS.md"},
        "account": {"id": account.id, "name": account.name, "cnpj": account.cnpj, "status": account.status},
        "contacts": [{"id": c.id, "name": c.name, "email": c.email, "phone": c.phone} for c in contacts],
        "deals": linked_deals[:limit],
        "timeline": [interaction_payload(i) for i in interactions],
        "notes": ["Deal links heuristic/inferred; no schema FK."],
    }


@router.get("/360/contacts/{contact_id}")
async def crm_360_contact(contact_id: str, limit: int = Query(50, le=200), db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    """Read-only contact 360 from existing data. No schema change."""
    from aios.db.models import Organization

    org = await db.get(Organization, org_id)
    if not _crm_enabled(org):
        raise HTTPException(402, "CRM IA upsell")
    contact = await _contact_or_404(db, contact_id, org_id)
    interactions = (await db.execute(select(InteractionEvent).where(InteractionEvent.org_id == org_id, InteractionEvent.contact_id == contact_id).order_by(InteractionEvent.occurred_at.desc()).limit(limit))).scalars().all()
    deals = (await db.execute(select(CrmDeal).where(CrmDeal.org_id == org_id).order_by(CrmDeal.updated_at.desc()).limit(200))).scalars().all()
    linked_deals = []
    for d in deals:
        c, c_link = await find_contact_for_deal_with_meta(db, d)
        if c and c.id == contact_id:
            linked_deals.append(deal_360_payload(d, contact=c, contact_link=c_link))
    return {
        "read_only": True,
        "schema_gap": {"deal_account_fk": False, "deal_contact_fk": False, "doc": "docs/CRM_SCHEMA_GAPS.md"},
        "contact": {"id": contact.id, "account_id": contact.account_id, "name": contact.name, "email": contact.email, "phone": contact.phone},
        "deals": linked_deals[:limit],
        "timeline": [interaction_payload(i) for i in interactions],
        "notes": ["Deal links heuristic/inferred; no schema FK."],
    }


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
