"""ProvisioningService — receives payment events and creates customers + licenses."""

import logging
import secrets
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.licensing.tier_templates import get_machines_limit
from vinzy_engine.provisioning.schemas import ProvisioningRequest, ProvisioningResult
from vinzy_engine.provisioning.zuultimate_client import ZuultimateClient

logger = logging.getLogger(__name__)


class ProvisioningService:
    """Orchestrates customer + license creation from payment webhooks."""

    def __init__(
        self,
        settings: VinzySettings,
        licensing_service: LicensingService,
        email_sender: Optional[Any] = None,
        zuultimate_client: Optional[ZuultimateClient] = None,
    ):
        self.settings = settings
        self.licensing = licensing_service
        self.email_sender = email_sender
        self.zuultimate_client = zuultimate_client

    async def provision(
        self,
        session: AsyncSession,
        request: ProvisioningRequest,
    ) -> ProvisioningResult:
        """Create customer + license from a provisioning request.

        Steps:
        1. Create or find existing customer
        2. Create license with tier template
        3. Send license key via email (if sender configured)
        """
        try:
            # 1. Create customer
            customer = await self.licensing.create_customer(
                session,
                name=request.customer_name,
                email=request.customer_email,
                company=request.company,
                metadata={
                    "payment_provider": request.payment_provider,
                    "payment_id": request.payment_id,
                    "billing_cycle": request.billing_cycle,
                },
            )

            # 2. Create license with tier template auto-applied
            days = 365 if request.billing_cycle == "yearly" else 30
            license_obj, raw_key = await self.licensing.create_license(
                session,
                product_code=request.product_code,
                customer_id=customer.id,
                tier=request.tier,
                days_valid=days,
                metadata={
                    "payment_provider": request.payment_provider,
                    "payment_id": request.payment_id,
                    **request.metadata,
                },
            )

            await session.commit()

            # 3. Send email with license key
            if self.email_sender:
                try:
                    await self.email_sender.send_license_key(
                        to_email=request.customer_email,
                        customer_name=request.customer_name,
                        product_code=request.product_code,
                        tier=request.tier,
                        license_key=raw_key,
                    )
                except Exception:
                    logger.exception("Failed to send license key email")

            # 4. Provision tenant in Zuultimate (if configured)
            zuul_tenant_id = None
            if self.zuultimate_client:
                try:
                    plan_map = {"pro": "pro", "enterprise": "business"}
                    slug = request.customer_email.split("@")[0].lower().replace(".", "-")
                    zuul_result = await self.zuultimate_client.provision_tenant(
                        name=request.company or request.customer_name,
                        slug=f"{slug}-{secrets.token_hex(4)}",
                        owner_email=request.customer_email,
                        owner_username=slug,
                        owner_password=secrets.token_urlsafe(16),
                        plan=plan_map.get(request.tier, "starter"),
                        stripe_customer_id=request.metadata.get("stripe_customer_id"),
                        stripe_subscription_id=request.payment_id,
                    )
                    zuul_tenant_id = zuul_result.get("tenant_id")
                    logger.info("Zuultimate tenant provisioned: %s", zuul_tenant_id)
                except Exception:
                    logger.exception("Failed to provision Zuultimate tenant")

            logger.info(
                "Provisioned license",
                extra={
                    "customer_id": customer.id,
                    "product_code": request.product_code,
                    "tier": request.tier,
                },
            )

            return ProvisioningResult(
                success=True,
                license_id=license_obj.id,
                customer_id=customer.id,
                product_code=request.product_code,
                tier=request.tier,
                license_key=raw_key,
            )

        except Exception as e:
            logger.exception("Provisioning failed")
            return ProvisioningResult(
                success=False,
                error=str(e),
            )
