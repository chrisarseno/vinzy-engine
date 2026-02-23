"""Polar.sh webhook handler for order/subscription events."""

import hashlib
import hmac
import logging
from typing import Any, Optional

from vinzy_engine.provisioning.schemas import ProvisioningRequest

logger = logging.getLogger(__name__)


def verify_polar_signature(
    payload: bytes,
    signature_header: str,
    webhook_secret: str,
) -> bool:
    """Verify Polar.sh webhook HMAC-SHA256 signature."""
    if not signature_header or not webhook_secret:
        return False

    computed = hmac.new(
        webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature_header)


def parse_polar_event(event_data: dict[str, Any]) -> Optional[ProvisioningRequest]:
    """Extract provisioning request from Polar order.completed or subscription.active.

    Expected custom fields / metadata on the Polar product:
    - product_code: 3-char code
    - tier: pro or enterprise
    """
    event_type = event_data.get("event", "")
    if event_type not in ("order.completed", "subscription.active"):
        logger.debug("Ignoring Polar event type: %s", event_type)
        return None

    data = event_data.get("data", {})
    metadata = data.get("metadata", {})
    customer = data.get("customer", {})

    product_code = metadata.get("product_code", "")
    tier = metadata.get("tier", "")

    if not product_code or not tier:
        logger.warning("Polar event missing product_code/tier in metadata")
        return None

    billing_cycle = "monthly"
    if data.get("recurring_interval") == "year":
        billing_cycle = "yearly"

    return ProvisioningRequest(
        customer_name=customer.get("name", metadata.get("customer_name", "Customer")),
        customer_email=customer.get("email", data.get("customer_email", "")),
        company=metadata.get("company", ""),
        product_code=product_code.upper(),
        tier=tier.lower(),
        billing_cycle=billing_cycle,
        payment_provider="polar",
        payment_id=data.get("id", ""),
        metadata={"polar_order_id": data.get("id", "")},
    )
