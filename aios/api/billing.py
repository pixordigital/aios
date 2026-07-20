"""Stripe billing — checkout, webhook, portal."""

import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from aios.config import PLANS, STRIPE_PRICE_MAP, settings
from aios.db.engine import async_session
from aios.db.models import Organization

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


@router.post("/create-checkout")
async def create_checkout(body: CheckoutRequest):
    """Create Stripe Checkout Session for org upgrade."""
    if not settings.stripe_secret_key:
        return {"error": "Stripe not configured"}

    stripe = _stripe()
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": body.price_id, "quantity": 1}],
            client_reference_id=body.org_id,
            metadata={"org_id": body.org_id},
            success_url=f"{settings.app_url}/dashboard/billing?success=1",
            cancel_url=f"{settings.app_url}/dashboard/billing?canceled=1",
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Stripe checkout failed: %s", e)
        return {"error": str(e)}


@router.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe events (subscription created/updated/canceled)."""
    if not settings.stripe_webhook_secret:
        return {"error": "Webhook secret not configured"}

    stripe = _stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except Exception as e:
        logger.warning("Stripe webhook signature invalid: %s", e)
        raise HTTPException(400, "Invalid signature")

    event_type = event.type
    data = event.data.object

    if event_type in ("checkout.session.completed", "invoice.paid"):
        org_id = data.get("client_reference_id") or (data.get("metadata") or {}).get("org_id")
        if not org_id:
            return {"status": "ignored"}

        subscription_id = data.get("subscription")
        price_id = ""
        if data.get("lines"):
            for line in data.lines.data:
                price_id = line.price.id

        plan = STRIPE_PRICE_MAP.get(price_id, "starter")
        async with async_session() as db:
            org = await db.get(Organization, org_id)
            if org:
                org.extra_data["plan"] = plan
                org.extra_data["stripe_subscription_id"] = subscription_id
                org.extra_data["stripe_price_id"] = price_id
                await db.commit()
                logger.info("Org %s upgraded to %s", org_id, plan)

    elif event_type == "customer.subscription.deleted":
        org_id = data.metadata.get("org_id") if data.get("metadata") else None
        if not org_id:
            subscriptions = data.get("id", "")
            async with async_session() as db:
                org = (await db.execute(
                    select(Organization).where(
                        Organization.extra_data["stripe_subscription_id"].as_string() == subscriptions
                    )
                )).scalar_one_or_none()
                if org:
                    org_id = org.id

        if org_id:
            async with async_session() as db:
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
        return {"error": "Stripe not configured"}

    async with async_session() as db:
        org = await db.get(Organization, body.org_id)
        sub_id = org.extra_data.get("stripe_subscription_id") if org else None

    if not sub_id:
        return {"error": "No active subscription"}

    stripe = _stripe()
    try:
        session = stripe.billing_portal.Session.create(
            customer=sub_id,
            return_url=f"{settings.app_url}/dashboard/billing",
        )
        return {"url": session.url}
    except Exception as e:
        logger.error("Portal session failed: %s", e)
        return {"error": str(e)}
