"""Stripe checkout.session.completed webhook handler."""

import hashlib
import hmac
import logging
from typing import Any, Optional

from vinzy_engine.provisioning.schemas import ProvisioningRequest

logger = logging.getLogger(__name__)


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    webhook_secret: str,
) -> bool:
    """Verify Stripe webhook signature (v1 scheme).

    Stripe sends: t=<timestamp>,v1=<signature>
    """
    if not signature_header or not webhook_secret:
        return False

    parts = {}
    for item in signature_header.split(","):
        key, _, value = item.partition("=")
        parts[key.strip()] = value.strip()

    timestamp = parts.get("t", "")
    expected_sig = parts.get("v1", "")
    if not timestamp or not expected_sig:
        return False

    signed_payload = f"{timestamp}.".encode() + payload
    computed = hmac.new(
        webhook_secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, expected_sig)


def parse_stripe_checkout(event_data: dict[str, Any]) -> Optional[ProvisioningRequest]:
    """Extract provisioning request from Stripe checkout.session.completed.

    Expected metadata on the Stripe checkout session:
    - product_code: 3-char code (AGW, ZUL, etc.)
    - tier: pro or enterprise
    """
    event_type = event_data.get("type", "")
    if event_type != "checkout.session.completed":
        logger.debug("Ignoring Stripe event type: %s", event_type)
        return None

    session = event_data.get("data", {}).get("object", {})
    metadata = session.get("metadata", {})
    customer_details = session.get("customer_details", {})

    product_code = metadata.get("product_code", "")
    tier = metadata.get("tier", "")

    if not product_code or not tier:
        logger.warning("Stripe checkout missing product_code/tier in metadata")
        return None

    return ProvisioningRequest(
        customer_name=customer_details.get("name", metadata.get("customer_name", "Customer")),
        customer_email=customer_details.get("email", session.get("customer_email", "")),
        company=metadata.get("company", ""),
        product_code=product_code.upper(),
        tier=tier.lower(),
        billing_cycle=metadata.get("billing_cycle", "monthly"),
        payment_provider="stripe",
        payment_id=session.get("id", ""),
        metadata={"stripe_session_id": session.get("id", "")},
    )
