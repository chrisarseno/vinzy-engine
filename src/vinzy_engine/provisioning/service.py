"""ProvisioningService — receives payment events and creates customers + licenses."""

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from vinzy_engine.common.config import VinzySettings
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.licensing.tier_templates import get_machines_limit
from vinzy_engine.provisioning.schemas import ProvisioningRequest, ProvisioningResult

logger = logging.getLogger(__name__)


class ProvisioningService:
    """Orchestrates customer + license creation from payment webhooks."""

    def __init__(
        self,
        settings: VinzySettings,
        licensing_service: LicensingService,
        email_sender: Optional[Any] = None,
    ):
        self.settings = settings
        self.licensing = licensing_service
        self.email_sender = email_sender

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
