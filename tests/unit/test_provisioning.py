"""Tests for provisioning — webhook parsing, signature verification, service."""

import hashlib
import hmac
import json
import time

import pytest

from vinzy_engine.provisioning.schemas import ProvisioningRequest, ProvisioningResult
from vinzy_engine.provisioning.stripe_webhook import (
    parse_stripe_checkout,
    verify_stripe_signature,
)
from vinzy_engine.provisioning.polar_webhook import (
    parse_polar_event,
    verify_polar_signature,
)
from vinzy_engine.provisioning.email_delivery import EmailSender


# ── Stripe webhook parsing ──

class TestStripeWebhook:
    def _checkout_event(self, **overrides):
        metadata = {
            "product_code": "AGW",
            "tier": "pro",
            "company": "Test Corp",
            **(overrides.pop("metadata", {})),
        }
        return {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "customer_email": "buyer@example.com",
                    "customer_details": {"name": "Jane Buyer", "email": "buyer@example.com"},
                    "metadata": metadata,
                    **overrides,
                }
            },
        }

    def test_parse_valid_checkout(self):
        req = parse_stripe_checkout(self._checkout_event())
        assert req is not None
        assert req.product_code == "AGW"
        assert req.tier == "pro"
        assert req.customer_name == "Jane Buyer"
        assert req.customer_email == "buyer@example.com"
        assert req.payment_provider == "stripe"

    def test_ignores_wrong_event_type(self):
        event = self._checkout_event()
        event["type"] = "payment_intent.succeeded"
        assert parse_stripe_checkout(event) is None

    def test_missing_product_code_returns_none(self):
        event = self._checkout_event(metadata={"tier": "pro"})
        # Override to remove product_code
        event["data"]["object"]["metadata"] = {"tier": "pro"}
        assert parse_stripe_checkout(event) is None

    def test_verify_valid_signature(self):
        secret = "whsec_test_secret"
        payload = b'{"type":"checkout.session.completed"}'
        timestamp = str(int(time.time()))
        signed = f"{timestamp}.".encode() + payload
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        header = f"t={timestamp},v1={sig}"

        assert verify_stripe_signature(payload, header, secret) is True

    def test_verify_invalid_signature(self):
        assert verify_stripe_signature(b"payload", "t=123,v1=bad", "secret") is False

    def test_verify_empty_header(self):
        assert verify_stripe_signature(b"payload", "", "secret") is False


# ── Polar webhook parsing ──

class TestPolarWebhook:
    def _order_event(self, **overrides):
        return {
            "event": "order.completed",
            "data": {
                "id": "polar_order_123",
                "customer": {"name": "Bob Buyer", "email": "bob@example.com"},
                "metadata": {
                    "product_code": "ZUL",
                    "tier": "enterprise",
                    **overrides.pop("metadata", {}),
                },
                "recurring_interval": "month",
                **overrides,
            },
        }

    def test_parse_valid_order(self):
        req = parse_polar_event(self._order_event())
        assert req is not None
        assert req.product_code == "ZUL"
        assert req.tier == "enterprise"
        assert req.customer_name == "Bob Buyer"
        assert req.payment_provider == "polar"

    def test_yearly_billing_cycle(self):
        req = parse_polar_event(self._order_event(recurring_interval="year"))
        assert req.billing_cycle == "yearly"

    def test_ignores_unknown_event(self):
        event = self._order_event()
        event["event"] = "payment.failed"
        assert parse_polar_event(event) is None

    def test_missing_tier_returns_none(self):
        event = self._order_event()
        event["data"]["metadata"] = {"product_code": "ZUL"}
        assert parse_polar_event(event) is None

    def test_verify_valid_signature(self):
        secret = "polar_secret"
        payload = b'{"event":"order.completed"}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert verify_polar_signature(payload, sig, secret) is True

    def test_verify_invalid_signature(self):
        assert verify_polar_signature(b"payload", "badsig", "secret") is False


# ── Email sender ──

class TestEmailSender:
    async def test_no_provider_returns_false(self):
        sender = EmailSender()
        result = await sender.send_license_key("a@b.com", "Test", "AGW", "pro", "KEY-123")
        assert result is False

    def test_build_body_contains_key(self):
        sender = EmailSender()
        body = sender._build_body("Test User", "AGW", "pro", "KEY-ABC-123")
        assert "KEY-ABC-123" in body
        assert "VINZY_LICENSE_KEY" in body
        assert "1450enterprises.com" in body


# ── Provisioning request validation ──

class TestProvisioningRequest:
    def test_valid_request(self):
        req = ProvisioningRequest(
            customer_name="Test",
            customer_email="t@e.com",
            product_code="AGW",
            tier="pro",
        )
        assert req.product_code == "AGW"
        assert req.billing_cycle == "monthly"

    def test_invalid_tier_rejected(self):
        with pytest.raises(Exception):
            ProvisioningRequest(
                customer_name="Test",
                customer_email="t@e.com",
                product_code="AGW",
                tier="gold",
            )

    def test_product_code_length(self):
        with pytest.raises(Exception):
            ProvisioningRequest(
                customer_name="Test",
                customer_email="t@e.com",
                product_code="TOOLONG",
                tier="pro",
            )
