"""HTTP client for provisioning tenants in Zuultimate."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ZuultimateClient:
    """Calls Zuultimate's /v1/tenants/provision endpoint."""

    def __init__(self, base_url: str, service_token: str):
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token

    async def provision_tenant(
        self,
        name: str,
        slug: str,
        owner_email: str,
        owner_username: str,
        owner_password: str,
        plan: str = "starter",
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """Call Zuultimate to create a tenant + owner user + API key.

        Returns the JSON response with tenant_id, user_id, api_key, plan, entitlements.
        Raises on HTTP errors.
        """
        url = f"{self.base_url}/v1/tenants/provision"
        payload = {
            "name": name,
            "slug": slug,
            "owner_email": owner_email,
            "owner_username": owner_username,
            "owner_password": owner_password,
            "plan": plan,
        }
        if stripe_customer_id:
            payload["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id:
            payload["stripe_subscription_id"] = stripe_subscription_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"X-Service-Token": self.service_token},
            )
            resp.raise_for_status()
            return resp.json()
