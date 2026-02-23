"""Email delivery for license keys — SendGrid / Resend integration."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EmailSender:
    """Sends license key delivery emails.

    Supports SendGrid and Resend via environment configuration.
    Falls back to logging if no provider is configured.
    """

    def __init__(
        self,
        provider: str = "",
        api_key: str = "",
        from_email: str = "licensing@1450enterprises.com",
        from_name: str = "1450 Enterprises",
    ):
        self.provider = provider.lower()  # "sendgrid" or "resend"
        self.api_key = api_key
        self.from_email = from_email
        self.from_name = from_name

    async def send_license_key(
        self,
        to_email: str,
        customer_name: str,
        product_code: str,
        tier: str,
        license_key: str,
    ) -> bool:
        """Send a license key delivery email."""
        subject = f"Your {product_code} {tier.title()} License Key"
        body = self._build_body(customer_name, product_code, tier, license_key)

        if self.provider == "sendgrid":
            return await self._send_sendgrid(to_email, subject, body)
        elif self.provider == "resend":
            return await self._send_resend(to_email, subject, body)
        else:
            logger.info(
                "No email provider configured; license key for %s: %s...%s",
                to_email,
                license_key[:8],
                license_key[-5:],
            )
            return False

    def _build_body(
        self,
        customer_name: str,
        product_code: str,
        tier: str,
        license_key: str,
    ) -> str:
        return (
            f"Hi {customer_name},\n\n"
            f"Thank you for purchasing {product_code} ({tier.title()} tier).\n\n"
            f"Your license key:\n\n  {license_key}\n\n"
            f"Set this as your VINZY_LICENSE_KEY environment variable.\n\n"
            f"Documentation: https://1450enterprises.com/docs\n"
            f"Support: support@1450enterprises.com\n\n"
            f"— 1450 Enterprises"
        )

    async def _send_sendgrid(self, to: str, subject: str, body: str) -> bool:
        """Send via SendGrid v3 API."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "personalizations": [{"to": [{"email": to}]}],
                        "from": {"email": self.from_email, "name": self.from_name},
                        "subject": subject,
                        "content": [{"type": "text/plain", "value": body}],
                    },
                    timeout=30,
                )
                if resp.status_code in (200, 202):
                    logger.info("SendGrid email sent to %s", to)
                    return True
                logger.warning("SendGrid error: %s %s", resp.status_code, resp.text)
                return False
        except Exception:
            logger.exception("SendGrid send failed")
            return False

    async def _send_resend(self, to: str, subject: str, body: str) -> bool:
        """Send via Resend API."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": f"{self.from_name} <{self.from_email}>",
                        "to": [to],
                        "subject": subject,
                        "text": body,
                    },
                    timeout=30,
                )
                if resp.status_code in (200, 201):
                    logger.info("Resend email sent to %s", to)
                    return True
                logger.warning("Resend error: %s %s", resp.status_code, resp.text)
                return False
        except Exception:
            logger.exception("Resend send failed")
            return False
