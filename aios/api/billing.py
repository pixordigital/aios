"""Stripe billing — checkout, webhook, portal."""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from aios.config import PLANS, STRIPE_PRICE_MAP, settings
from aios.core.limits import get_usage_summary
from aios.db.backend import db_session, get_db_backend, DatabaseBackend
from aios.db.models import Organization
from .deps import get_org_id

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


@router.post("/create-checkout")
async def create_checkout(body: CheckoutRequest, db: DatabaseBackend = Depends(get_db_backend)):
    """Create Stripe Checkout Session for org upgrade."""
    if not settings.stripe_secret_key:
        raise HTTPException(400, "Stripe not configured")

    # verify org exists
    org = await db.get(Organization, body.org_id)
    if not org:
        raise HTTPException(400, "Organization not found")

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
        raise HTTPException(400, "Invalid signature")

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
async def create_portal(body: PortalRequest):
    """Create Stripe Customer Portal session."""
    if not settings.stripe_secret_key:
        raise HTTPException(400, "Stripe not configured")

    async with db_session() as db:
        org = await db.get(Organization, body.org_id)
        stripe_customer_id = org.extra_data.get("stripe_customer_id") if org else None
        sub_id = org.extra_data.get("stripe_subscription_id") if org else None

    if not stripe_customer_id and not sub_id:
        raise HTTPException(400, "No active subscription")

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
