"""Pydantic schemas for provisioning webhook payloads."""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class ProvisioningRequest(BaseModel):
    """Internal representation of a purchase to provision."""

    customer_name: str
    customer_email: str
    company: str = ""
    product_code: str = Field(..., min_length=3, max_length=3)
    tier: str = Field(..., pattern="^(pro|enterprise)$")
    billing_cycle: str = Field(default="monthly", pattern="^(monthly|yearly)$")
    payment_provider: str = ""
    payment_id: str = ""
    metadata: dict = Field(default_factory=dict)


class ProvisioningResult(BaseModel):
    """Result of a provisioning operation."""

    success: bool
    license_id: Optional[str] = None
    customer_id: Optional[str] = None
    product_code: Optional[str] = None
    tier: Optional[str] = None
    license_key: Optional[str] = None
    error: Optional[str] = None


class StripeCheckoutPayload(BaseModel):
    """Relevant fields from Stripe checkout.session.completed event."""

    id: str
    object: str = "event"
    type: str = ""
    data: dict = Field(default_factory=dict)


class PolarWebhookPayload(BaseModel):
    """Relevant fields from Polar.sh webhook."""

    event: str = ""
    data: dict = Field(default_factory=dict)
