"""Stripe billing — checkout, webhook, portal."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from aios.config import PLANS, STRIPE_PRICE_MAP, settings
from aios.core.limits import get_monthly_usage, get_usage_summary
from aios.core.whatsapp_pricing import estimate_creation_cost, get_rates, whatsapp_cost_for_messages
from aios.db.backend import db_session, get_db_backend, DatabaseBackend
from aios.db.models import Budget, Organization
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _stripe():
    import stripe as _stripe
    _stripe.api_key = settings.stripe_secret_key
    return _stripe


class CheckoutRequest(BaseModel):
    org_id: str
    price_id: str


class PortalRequest(BaseModel):
    org_id: str


def _org_hmac(org_id: str) -> str:
    """HMAC-signed org_id for Stripe metadata — prevents tampering."""
    return hmac.new(
        settings.jwt_secret.encode(), org_id.encode(), hashlib.sha256
    ).hexdigest()


def _verify_org_hmac(org_id: str, signature: str) -> bool:
    return hmac.compare_digest(_org_hmac(org_id), signature)


@router.get("/plans")
async def get_plans():
    """Return available plans and limits."""
    return PLANS


@router.get("/usage")
async def usage_summary(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Return usage summary for org."""
    return await get_usage_summary(org_id, db)


class BudgetCreate(BaseModel):
    name: str = "Operação"
    type: str = "operation"  # creation|operation
    amount_brl: float
    period: str = "monthly"
    scope: dict = {}
    country: str = "BR"
    block_on_exceed: bool = True


@router.get("/budget")
async def list_budgets(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(Budget).where(Budget.org_id == org_id).order_by(Budget.created_at.desc()))).scalars().all()
    return rows


@router.post("/budget")
async def create_budget(body: BudgetCreate, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    if body.amount_brl <= 0:
        raise HTTPException(400, "amount_brl deve ser >0")
    if body.type not in ("creation", "operation"):
        raise HTTPException(400, "type creation|operation")
    b = Budget(org_id=org_id, name=body.name, type=body.type, amount_brl=body.amount_brl, period=body.period, scope=body.scope or {}, country=body.country, block_on_exceed=body.block_on_exceed, alert_at=[80, 90, 100])
    db.add(b)
    await db.commit()
    await db.refresh(b)
    return b


@router.delete("/budget/{bid}")
async def delete_budget(bid: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    b = await db.get(Budget, bid)
    if not b or b.org_id != org_id:
        raise HTTPException(404)
    await db.delete(b)
    await db.commit()
    return {"ok": True}


@router.get("/budget/forecast")
async def budget_forecast(budget_id: str = "", db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    """Quanto tempo dura? Usa burn 7d (LLM+WA). Retorna cenários antes/depois 01/10."""
    from datetime import date, timedelta

    monthly = await get_monthly_usage(org_id, db)
    # burn últimos 7d
    all_daily = monthly.get("daily_series", [])
    last7 = all_daily[-7:] if len(all_daily) >= 7 else all_daily
    daily_brl = sum((d.get("cost", 0) * 5.5) for d in last7) / max(len(last7), 1) if last7 else monthly.get("avg_daily_cost", 0) * 5.5
    # adiciona WA custo se houver
    wa_daily = 0.0
    for d in last7:
        wa_daily += (d.get("whatsapp_cost", 0) or 0) * 5.5 if "whatsapp_cost" in d else 0
    if last7:
        daily_brl = (sum((d.get("cost", 0) * 5.5) for d in last7) + wa_daily) / len(last7)
    spent_brl = monthly.get("total_cost", 0) * 5.5
    # se budget_id fornecido, usa esse budget, senão usa max_cost_brl do plano
    amount_brl = None
    budget = None
    if budget_id:
        budget = await db.get(Budget, budget_id)
        if budget and budget.org_id == org_id:
            amount_brl = budget.amount_brl
    if amount_brl is None:
        # fallback plano
        from aios.config import PLANS

        org = await db.get(Organization, org_id)
        plan = (org.extra_data or {}).get("plan", "free") if org else "free"
        amount_brl = PLANS.get(plan, {}).get("max_cost_brl", 100)
        if amount_brl == 999999:
            amount_brl = 800
    remaining = max(amount_brl - spent_brl, 0)
    days_left = int(remaining / daily_brl) if daily_brl > 0 else 999
    from datetime import datetime, timezone

    date_end = (date.today() + timedelta(days=days_left)).isoformat() if days_left < 999 else None
    # cenário pós 01/10: sem free service/utility dentro janela → +38% WA (estimativa)
    wa_after = daily_brl * 0.38 if any(c in str(monthly) for c in ["whatsapp"]) else 0  # placeholder
    # calcula WA split exemplo para BR: assume 60% inside_window
    scenario_after_days = int(remaining / (daily_brl * 1.38)) if daily_brl > 0 else days_left
    return {
        "amount_brl": amount_brl,
        "spent_brl": round(spent_brl, 2),
        "daily_burn_brl": round(daily_brl, 2),
        "remaining_brl": round(remaining, 2),
        "days_left": days_left,
        "date_end": date_end,
        "scenario_before_oct": {"days_left": days_left, "daily_burn": round(daily_brl, 2)},
        "scenario_after_oct": {"days_left": scenario_after_days, "daily_burn": round(daily_brl * 1.38, 2), "note": "sem free service/utility dentro janela"},
        "monthly": monthly,
        "budget_id": budget_id or None,
    }


@router.get("/whatsapp/rates")
async def whatsapp_rates(country: str = "BR"):
    return get_rates(country)


@router.get("/creation-cost")
async def creation_cost(agent_type: str = "sdr", model: str = "openai/gpt-4o-mini"):
    """Estimativa automática criação agente."""
    return {"agent_type": agent_type, "model": model, "cost_brl": estimate_creation_cost(agent_type, model), "note": "3000 tokens teste"}


@router.post("/create-checkout")
async def create_checkout(
    body: CheckoutRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Create Stripe Checkout Session for org upgrade."""
    if not settings.stripe_secret_key:
        raise HTTPException(400, "Stripe not configured")

    # only allow checkout for your own org
    if body.org_id != org_id:
        raise HTTPException(403, "Não é possível criar o checkout para outra organização")

    # verify org exists
    org = await db.get(Organization, body.org_id)
    if not org:
        raise HTTPException(400, "Organização não encontrada")

    sig = _org_hmac(body.org_id)
    stripe = _stripe()
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": body.price_id, "quantity": 1}],
            client_reference_id=body.org_id,
            metadata={"org_id": body.org_id, "org_sig": sig},
            success_url=f"{settings.app_url}/dashboard/billing?success=1",
            cancel_url=f"{settings.app_url}/dashboard/billing?canceled=1",
        )
        return {"url": session.url}
    except Exception as e:
        logger.exception("Stripe checkout failed")
        return {"error": str(e)}


_processed_events: set[str] = set()  # ponytail: in-memory idempotency. Redis-backed at scale.


@router.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe events (subscription created/updated/canceled)."""
    if not settings.stripe_webhook_secret:
        raise HTTPException(400, "Webhook secret not configured")

    stripe = _stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except Exception as e:
        logger.exception("Stripe webhook signature invalid")
        raise HTTPException(400, "Assinatura inválida")

    # idempotency — skip already-processed events
    event_id = event.get("id", "")
    if event_id in _processed_events:
        logger.info("Stripe webhook %s already processed, skipping", event_id)
        return {"status": "already_processed"}
    _processed_events.add(event_id)
    # prevent unbounded growth
    if len(_processed_events) > 10000:
        _processed_events.clear()

    event_type = event.type
    data = event.data.object

    if event_type in ("checkout.session.completed", "invoice.paid"):
        org_id = data.get("client_reference_id") or (data.get("metadata") or {}).get("org_id")
        org_sig = (data.get("metadata") or {}).get("org_sig", "")
        if not org_id:
            return {"status": "ignored"}

        # verify HMAC signature on org_id
        if org_sig and not _verify_org_hmac(org_id, org_sig):
            logger.warning("Stripe webhook: org_id HMAC mismatch for %s", org_id)
            return {"status": "ignored"}  # silently ignore tampered requests

        subscription_id = data.get("subscription")
        customer_id = data.get("customer")
        price_id = ""
        if data.get("lines"):
            for line in data.lines.data:
                price_id = line.price.id

        plan = STRIPE_PRICE_MAP.get(price_id, "starter")
        async with db_session() as db:
            org = await db.get(Organization, org_id)
            if org:
                old_plan = org.extra_data.get("plan", "free")
                org.extra_data["plan"] = plan
                org.extra_data["stripe_subscription_id"] = subscription_id
                org.extra_data["stripe_customer_id"] = customer_id
                org.extra_data["stripe_price_id"] = price_id
                await db.commit()
                from aios.core.audit import log_audit
                await log_audit(db, org_id, "billing.plan_change", "organization", resource_id=org_id, details={"from": old_plan, "to": plan})
                logger.info("Org %s upgraded from %s to %s", org_id, old_plan, plan)

    elif event_type == "customer.subscription.deleted":
        org_id = data.metadata.get("org_id") if data.get("metadata") else None
        if not org_id:
            subscriptions = data.get("id", "")
            async with db_session() as db:
                org = (await db.execute(
                    select(Organization).where(
                        Organization.extra_data["stripe_subscription_id"].as_string() == subscriptions
                    )
                )).scalar_one_or_none()
                if org:
                    org_id = org.id

        if org_id:
            async with db_session() as db:
                org = await db.get(Organization, org_id)
                if org:
                    org.extra_data["plan"] = "free"
                    org.extra_data.pop("stripe_subscription_id", None)
                    org.extra_data.pop("stripe_price_id", None)
                    await db.commit()
                    logger.info("Org %s downgraded to free after cancellation", org_id)

    return {"status": "ok"}


@router.post("/create-portal")
async def create_portal(
    body: PortalRequest,
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Create Stripe Customer Portal session."""
    if not settings.stripe_secret_key:
        raise HTTPException(400, "Stripe not configured")
    if body.org_id != org_id:
        raise HTTPException(403, "Não é possível criar o portal para outra organização")

    async with db_session() as db:
        org = await db.get(Organization, body.org_id)
        stripe_customer_id = org.extra_data.get("stripe_customer_id") if org else None
        sub_id = org.extra_data.get("stripe_subscription_id") if org else None

    if not stripe_customer_id and not sub_id:
        raise HTTPException(400, "Sem assinatura ativa")

    stripe = _stripe()
    try:
        cust = stripe_customer_id
        if not cust and sub_id:
            # fetch subscription to get customer
            sub = stripe.Subscription.retrieve(sub_id)
            cust = sub.customer
        session = stripe.billing_portal.Session.create(
            customer=cust,
            return_url=f"{settings.app_url}/dashboard/billing",
        )
        return {"url": session.url}
    except Exception as e:
        logger.exception("Portal session failed")
        return {"error": str(e)}
