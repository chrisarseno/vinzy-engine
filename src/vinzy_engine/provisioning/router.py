"""Provisioning webhook endpoints — Stripe and Polar.sh."""

import logging
import os

from fastapi import APIRouter, Header, Request, Response

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


async def _get_provisioning_service():
    """Lazy import to avoid circular deps."""
    from vinzy_engine.deps import get_db, get_licensing_service
    from vinzy_engine.provisioning.service import ProvisioningService
    from vinzy_engine.provisioning.email_delivery import EmailSender

    settings = get_settings()
    email_provider = os.environ.get("VINZY_EMAIL_PROVIDER", "")
    email_api_key = os.environ.get("VINZY_EMAIL_API_KEY", "")

    email_sender = None
    if email_provider and email_api_key:
        email_sender = EmailSender(
            provider=email_provider,
            api_key=email_api_key,
        )

    return ProvisioningService(
        settings=settings,
        licensing_service=get_licensing_service(),
        email_sender=email_sender,
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

    import json
    try:
        event_data = json.loads(body)
    except json.JSONDecodeError:
        return ProvisioningResult(success=False, error="Invalid JSON")

    prov_request = parse_stripe_checkout(event_data)
    if prov_request is None:
        return ProvisioningResult(success=False, error="Unhandled event type or missing metadata")

    svc, db = await _get_provisioning_service()
    async with db.get_session("licensing") as session:
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

    import json
    try:
        event_data = json.loads(body)
    except json.JSONDecodeError:
        return ProvisioningResult(success=False, error="Invalid JSON")

    prov_request = parse_polar_event(event_data)
    if prov_request is None:
        return ProvisioningResult(success=False, error="Unhandled event type or missing metadata")

    svc, db = await _get_provisioning_service()
    async with db.get_session("licensing") as session:
        result = await svc.provision(session, prov_request)

    return result
