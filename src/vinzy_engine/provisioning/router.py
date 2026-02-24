"""Provisioning webhook endpoints — Stripe and Polar.sh."""

import json
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel

from vinzy_engine.common.config import get_settings
from vinzy_engine.provisioning.schemas import ProvisioningResult
from vinzy_engine.provisioning.stripe_webhook import (
    parse_stripe_checkout,
    verify_stripe_signature,
)
from vinzy_engine.provisioning.polar_webhook import (
    parse_polar_event,
    verify_polar_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["provisioning"])
checkout_router = APIRouter(prefix="/checkout", tags=["checkout"])


# ── Checkout session creation ──

class CheckoutRequest(BaseModel):
    product_code: str
    tier: str
    billing_cycle: str = "monthly"
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    url: str


@checkout_router.post("/create", response_model=CheckoutResponse)
async def create_checkout_session(body: CheckoutRequest):
    """Create a Stripe Checkout session with product metadata."""
    stripe_key = os.environ.get("VINZY_STRIPE_SECRET_KEY", "")
    price_map_raw = os.environ.get("VINZY_STRIPE_PRICE_MAP", "{}")

    if not stripe_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    try:
        import stripe
    except ImportError:
        raise HTTPException(status_code=503, detail="stripe package not installed")

    try:
        price_map = json.loads(price_map_raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid VINZY_STRIPE_PRICE_MAP")

    # Lookup: e.g. "vnz_pro_monthly" → "price_..."
    lookup = f"{body.product_code.lower()}_{body.tier.lower()}_{body.billing_cycle.lower()}"
    price_id = price_map.get(lookup)
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=f"No Stripe Price ID configured for {lookup}",
        )

    stripe.api_key = stripe_key

    try:
        session = stripe.checkout.Session.create(
            mode="subscription" if body.billing_cycle in ("monthly", "yearly") else "payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            metadata={
                "product_code": body.product_code.upper(),
                "tier": body.tier.lower(),
                "billing_cycle": body.billing_cycle.lower(),
            },
        )
    except stripe.StripeError as e:
        logger.error("Stripe session creation failed: %s", e)
        raise HTTPException(status_code=502, detail="Stripe session creation failed")

    return CheckoutResponse(url=session.url)


async def _get_provisioning_service():
    """Lazy import to avoid circular deps."""
    from vinzy_engine.deps import get_db, get_licensing_service
    from vinzy_engine.provisioning.service import ProvisioningService
    from vinzy_engine.provisioning.email_delivery import EmailSender
    from vinzy_engine.provisioning.zuultimate_client import ZuultimateClient

    settings = get_settings()
    email_provider = os.environ.get("VINZY_EMAIL_PROVIDER", "")
    email_api_key = os.environ.get("VINZY_EMAIL_API_KEY", "")

    email_sender = None
    if email_provider and email_api_key:
        email_sender = EmailSender(
            provider=email_provider,
            api_key=email_api_key,
        )

    zuul_client = None
    if settings.zuultimate_base_url and settings.zuultimate_service_token:
        zuul_client = ZuultimateClient(
            base_url=settings.zuultimate_base_url,
            service_token=settings.zuultimate_service_token,
        )

    return ProvisioningService(
        settings=settings,
        licensing_service=get_licensing_service(),
        email_sender=email_sender,
        zuultimate_client=zuul_client,
    ), get_db()


@router.post("/stripe", response_model=ProvisioningResult)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header("", alias="Stripe-Signature"),
):
    """Handle Stripe checkout.session.completed webhook."""
    body = await request.body()

    # Verify signature if secret is configured
    stripe_secret = os.environ.get("VINZY_STRIPE_WEBHOOK_SECRET", "")
    if stripe_secret:
        if not verify_stripe_signature(body, stripe_signature, stripe_secret):
            logger.warning("Invalid Stripe webhook signature")
            return ProvisioningResult(success=False, error="Invalid signature")

    try:
        event_data = json.loads(body)
    except json.JSONDecodeError:
        return ProvisioningResult(success=False, error="Invalid JSON")

    prov_request = parse_stripe_checkout(event_data)
    if prov_request is None:
        return ProvisioningResult(success=False, error="Unhandled event type or missing metadata")

    svc, db = await _get_provisioning_service()
    async with db.get_session() as session:
        result = await svc.provision(session, prov_request)

    return result


@router.post("/polar", response_model=ProvisioningResult)
async def polar_webhook(
    request: Request,
    polar_signature: str = Header("", alias="X-Polar-Signature"),
):
    """Handle Polar.sh order/subscription webhook."""
    body = await request.body()

    polar_secret = os.environ.get("VINZY_POLAR_WEBHOOK_SECRET", "")
    if polar_secret:
        if not verify_polar_signature(body, polar_signature, polar_secret):
            logger.warning("Invalid Polar webhook signature")
            return ProvisioningResult(success=False, error="Invalid signature")

    try:
        event_data = json.loads(body)
    except json.JSONDecodeError:
        return ProvisioningResult(success=False, error="Invalid JSON")

    prov_request = parse_polar_event(event_data)
    if prov_request is None:
        return ProvisioningResult(success=False, error="Unhandled event type or missing metadata")

    svc, db = await _get_provisioning_service()
    async with db.get_session() as session:
        result = await svc.provision(session, prov_request)

    return result
