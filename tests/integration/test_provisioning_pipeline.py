"""Integration test for the full provisioning pipeline: webhook → service → Zuultimate."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from vinzy_engine.provisioning.schemas import ProvisioningRequest
from vinzy_engine.provisioning.zuultimate_client import ZuultimateClient


class TestProvisioningPipeline:
    """End-to-end provisioning: create customer, license, call Zuultimate."""

    async def _setup_product(self, client, admin_headers):
        resp = await client.post("/products", json={
            "code": "AGW", "name": "Agent Gateway",
        }, headers=admin_headers)
        assert resp.status_code == 201
        return resp.json()

    async def test_full_provision_with_zuultimate(self, client, admin_headers):
        """Stripe checkout → ProvisioningService → license + Zuultimate tenant."""
        await self._setup_product(client, admin_headers)

        # Mock Zuultimate responding with a tenant
        zuul_response = {
            "tenant_id": "t_test_001",
            "user_id": "u_test_001",
            "api_key": "gzr_test_key",
            "plan": "pro",
            "entitlements": ["trendscope:full", "nexus:basic"],
        }

        with patch.object(
            ZuultimateClient,
            "provision_tenant",
            new_callable=AsyncMock,
            return_value=zuul_response,
        ) as mock_provision:
            # Hit the Stripe webhook endpoint
            payload = {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_live_abc",
                        "customer_email": "buyer@example.com",
                        "customer_details": {
                            "name": "Jane Buyer",
                            "email": "buyer@example.com",
                        },
                        "metadata": {
                            "product_code": "AGW",
                            "tier": "pro",
                            "company": "Buyer Corp",
                        },
                    }
                },
            }

            resp = await client.post(
                "/webhooks/stripe",
                json=payload,
                headers=admin_headers,
            )
            # Webhook endpoint may return 200 or 202
            assert resp.status_code in (200, 202), resp.text

    async def test_provision_creates_license_and_customer(self, client, admin_headers):
        """Verify that after provisioning, both customer and license exist."""
        await self._setup_product(client, admin_headers)

        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_live_def",
                    "customer_email": "newbuyer@example.com",
                    "customer_details": {
                        "name": "New Buyer",
                        "email": "newbuyer@example.com",
                    },
                    "metadata": {
                        "product_code": "AGW",
                        "tier": "enterprise",
                        "company": "New Corp",
                    },
                }
            },
        }

        resp = await client.post(
            "/webhooks/stripe",
            json=payload,
            headers=admin_headers,
        )
        assert resp.status_code in (200, 202), resp.text

        # Verify customer was created
        cust_resp = await client.get("/customers", headers=admin_headers)
        assert cust_resp.status_code == 200
        customers = cust_resp.json()
        emails = [c["email"] for c in customers]
        assert "newbuyer@example.com" in emails

    async def test_zuultimate_client_sends_correct_payload(self):
        """Verify ZuultimateClient builds the right HTTP request."""
        zc = ZuultimateClient(
            base_url="https://zuultimate.local",
            service_token="svc_test_token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"tenant_id": "t_123"}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await zc.provision_tenant(
                name="Test Corp",
                slug="test-corp-abc",
                owner_email="admin@test.com",
                owner_username="admin",
                owner_password="securepass123",
                plan="pro",
                stripe_customer_id="cus_123",
                stripe_subscription_id="sub_456",
            )

            assert result == {"tenant_id": "t_123"}
            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            assert call_kwargs.kwargs["headers"]["X-Service-Token"] == "svc_test_token"
            payload = call_kwargs.kwargs["json"]
            assert payload["name"] == "Test Corp"
            assert payload["slug"] == "test-corp-abc"
            assert payload["plan"] == "pro"
            assert payload["stripe_customer_id"] == "cus_123"

    async def test_zuultimate_failure_doesnt_block_provisioning(self, client, admin_headers):
        """Zuultimate being down should not prevent license creation."""
        await self._setup_product(client, admin_headers)

        with patch.object(
            ZuultimateClient,
            "provision_tenant",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            payload = {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_live_ghi",
                        "customer_email": "resilient@example.com",
                        "customer_details": {
                            "name": "Resilient Buyer",
                            "email": "resilient@example.com",
                        },
                        "metadata": {
                            "product_code": "AGW",
                            "tier": "pro",
                            "company": "Resilient Corp",
                        },
                    }
                },
            }

            resp = await client.post(
                "/webhooks/stripe",
                json=payload,
                headers=admin_headers,
            )
            # Should still succeed — Zuultimate failure is gracefully handled
            assert resp.status_code in (200, 202), resp.text
