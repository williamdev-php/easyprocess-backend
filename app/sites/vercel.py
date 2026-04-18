"""
Vercel domain management for custom domains and domain purchases.

- Custom domains: Register with the Vercel project for TLS and routing.
- Domain purchases: Check availability, buy, and renew domains via Vercel Domains API.

Vercel API docs: https://vercel.com/docs/rest-api/endpoints/projects/domains
"""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

VERCEL_API_BASE = "https://api.vercel.com"

# Approximate USD → SEK rate (updated periodically; consider a live API for production)
USD_TO_SEK = 10.5


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.VERCEL_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _team_params() -> dict[str, str]:
    """Query params for team-scoped requests."""
    if settings.VERCEL_TEAM_ID:
        return {"teamId": settings.VERCEL_TEAM_ID}
    return {}


def _is_configured() -> bool:
    return bool(settings.VERCEL_API_TOKEN and settings.VERCEL_PROJECT_ID)


async def add_domain(domain: str) -> dict[str, Any] | None:
    """Add a custom domain to the Vercel viewer project.

    Returns the Vercel domain object on success, or None on failure.
    The response includes verification records the user needs to configure.
    """
    if not _is_configured():
        logger.warning("Vercel not configured — skipping domain add for %s", domain)
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{VERCEL_API_BASE}/v10/projects/{settings.VERCEL_PROJECT_ID}/domains",
            headers=_headers(),
            params=_team_params(),
            json={"name": domain},
        )

        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info("Added domain %s to Vercel project", domain)
            return data

        # Domain might already exist on the project
        if resp.status_code == 409:
            logger.info("Domain %s already exists on Vercel project", domain)
            return await get_domain(domain)

        logger.error(
            "Failed to add domain %s to Vercel: %s %s",
            domain, resp.status_code, resp.text,
        )
        return None


async def remove_domain(domain: str) -> bool:
    """Remove a custom domain from the Vercel viewer project."""
    if not _is_configured():
        logger.warning("Vercel not configured — skipping domain remove for %s", domain)
        return False

    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{VERCEL_API_BASE}/v9/projects/{settings.VERCEL_PROJECT_ID}/domains/{domain}",
            headers=_headers(),
            params=_team_params(),
        )

        if resp.status_code in (200, 204):
            logger.info("Removed domain %s from Vercel project", domain)
            return True

        if resp.status_code == 404:
            logger.info("Domain %s not found on Vercel project (already removed)", domain)
            return True

        logger.error(
            "Failed to remove domain %s from Vercel: %s %s",
            domain, resp.status_code, resp.text,
        )
        return False


async def get_domain(domain: str) -> dict[str, Any] | None:
    """Get domain info from the Vercel project, including verification status."""
    if not _is_configured():
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VERCEL_API_BASE}/v9/projects/{settings.VERCEL_PROJECT_ID}/domains/{domain}",
            headers=_headers(),
            params=_team_params(),
        )

        if resp.status_code == 200:
            return resp.json()

        logger.error(
            "Failed to get domain %s from Vercel: %s %s",
            domain, resp.status_code, resp.text,
        )
        return None


async def get_domain_config(domain: str) -> dict[str, Any] | None:
    """Get the DNS configuration status for a domain from Vercel.

    This checks whether Vercel can verify the domain's DNS records.
    """
    if not _is_configured():
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VERCEL_API_BASE}/v6/domains/{domain}/config",
            headers=_headers(),
            params=_team_params(),
        )

        if resp.status_code == 200:
            return resp.json()

        logger.error(
            "Failed to get domain config for %s from Vercel: %s %s",
            domain, resp.status_code, resp.text,
        )
        return None


async def verify_domain(domain: str) -> dict[str, Any] | None:
    """Trigger a verification check for a domain on Vercel.

    Returns the updated domain object if verification succeeds.
    """
    if not _is_configured():
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{VERCEL_API_BASE}/v9/projects/{settings.VERCEL_PROJECT_ID}/domains/{domain}/verify",
            headers=_headers(),
            params=_team_params(),
        )

        if resp.status_code == 200:
            data = resp.json()
            verified = data.get("verified", False)
            logger.info(
                "Vercel domain verification for %s: verified=%s", domain, verified
            )
            return data

        logger.error(
            "Failed to verify domain %s on Vercel: %s %s",
            domain, resp.status_code, resp.text,
        )
        return None


async def check_domain_status(domain: str) -> tuple[bool, dict[str, Any] | None]:
    """Check if a domain is fully configured and verified on Vercel.

    Returns (is_verified, domain_info).
    """
    domain_info = await get_domain(domain)
    if not domain_info:
        return False, None

    # Check if domain is verified
    if domain_info.get("verified"):
        return True, domain_info

    # Try to trigger verification
    verify_result = await verify_domain(domain)
    if verify_result and verify_result.get("verified"):
        return True, verify_result

    # Get DNS config for user-facing instructions
    config = await get_domain_config(domain)
    if config:
        domain_info["dnsConfig"] = config

    return False, domain_info


# ---------------------------------------------------------------------------
# Domain purchasing (Vercel Domains API)
# ---------------------------------------------------------------------------

def _has_token() -> bool:
    return bool(settings.VERCEL_API_TOKEN)


async def check_domain_price(domain: str) -> dict[str, Any] | None:
    """Check domain pricing via the new Vercel Registrar API.

    Returns dict with:
    - price_usd: float (purchase price in USD)
    - renewal_price_usd: float
    - period: int (years)
    - price_sek: int (price in SEK öre with markup)
    - markup_percent: int
    """
    if not _has_token():
        logger.warning("Vercel token not configured — cannot check domain price")
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VERCEL_API_BASE}/v1/registrar/domains/{domain}/price",
            headers=_headers(),
            params=_team_params(),
        )

        if resp.status_code != 200:
            logger.error("Failed to check price for %s: %s %s", domain, resp.status_code, resp.text)
            return None

        data = resp.json()
        # New API returns: { "purchasePrice": 9.99, "renewalPrice": 9.99, "years": 1 }
        price_usd = float(data.get("purchasePrice", 0))
        renewal_usd = float(data.get("renewalPrice", 0))
        period = int(data.get("years", 1))

        # Convert USD to SEK öre with markup
        markup = settings.DOMAIN_MARKUP_PERCENT
        price_sek_kr = price_usd * USD_TO_SEK * (1 + markup / 100)
        price_sek_ore = math.ceil(price_sek_kr) * 100  # Round up to whole SEK, then to öre

        return {
            "available": True,
            "price_usd": price_usd,
            "renewal_price_usd": renewal_usd,
            "period": period,
            "price_sek": price_sek_ore,
            "price_sek_display": math.ceil(price_sek_kr),
            "markup_percent": markup,
        }


async def check_domain_availability(domain: str) -> dict[str, Any] | None:
    """Check if a domain is available for registration via the new Registrar API.

    Returns dict with availability status and pricing.
    """
    if not _has_token():
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VERCEL_API_BASE}/v1/registrar/domains/{domain}/availability",
            headers=_headers(),
            params=_team_params(),
        )

        if resp.status_code != 200:
            logger.error("Failed to check availability for %s: %s %s", domain, resp.status_code, resp.text)
            return None

        status_data = resp.json()
        available = status_data.get("available", False)

        if not available:
            return {"available": False, "domain": domain}

        # Get price
        price_info = await check_domain_price(domain)
        if not price_info:
            return {"available": True, "domain": domain, "price_sek": 0}

        return {
            "available": True,
            "domain": domain,
            **price_info,
        }


async def purchase_domain(
    domain: str,
    expected_price: float,
    years: int = 1,
    contact_info: dict[str, Any] | None = None,
    auto_renew: bool = True,
) -> dict[str, Any] | None:
    """Purchase a domain via the new Vercel Registrar API.

    The new API requires contact information and expected price.
    Returns an order dict with orderId for tracking.
    """
    if not _has_token():
        logger.warning("Vercel token not configured — cannot purchase domain")
        return None

    if not contact_info:
        logger.error("Contact information required for domain purchase")
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{VERCEL_API_BASE}/v1/registrar/domains/{domain}/buy",
            headers=_headers(),
            params=_team_params(),
            json={
                "autoRenew": auto_renew,
                "years": years,
                "expectedPrice": expected_price,
                "contactInformation": contact_info,
            },
        )

        if resp.status_code == 200:
            data = resp.json()
            logger.info("Purchased domain %s via Vercel (order: %s)", domain, data.get("orderId"))
            return data

        logger.error(
            "Failed to purchase domain %s: %s %s",
            domain, resp.status_code, resp.text,
        )
        return None


async def renew_domain(
    domain: str,
    expected_price: float,
    years: int = 1,
) -> dict[str, Any] | None:
    """Renew a domain registration via the new Vercel Registrar API."""
    if not _has_token():
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{VERCEL_API_BASE}/v1/registrar/domains/{domain}/renew",
            headers=_headers(),
            params=_team_params(),
            json={
                "years": years,
                "expectedPrice": expected_price,
            },
        )

        if resp.status_code == 200:
            data = resp.json()
            logger.info("Renewed domain %s via Vercel (order: %s)", domain, data.get("orderId"))
            return data

        logger.error(
            "Failed to renew domain %s: %s %s",
            domain, resp.status_code, resp.text,
        )
        return None


# ---------------------------------------------------------------------------
# Domain transfer & lock management
# ---------------------------------------------------------------------------

async def get_order_status(order_id: str) -> dict[str, Any] | None:
    """Get domain order status from the Vercel Registrar API.

    Use after purchase or renewal to track completion.
    """
    if not _has_token():
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VERCEL_API_BASE}/v1/registrar/orders/{order_id}",
            headers=_headers(),
            params=_team_params(),
        )

        if resp.status_code == 200:
            return resp.json()

        logger.error(
            "Failed to get order status for %s: %s %s",
            order_id, resp.status_code, resp.text,
        )
        return None


async def set_domain_auto_renew(domain: str, auto_renew: bool) -> bool:
    """Enable or disable auto-renewal for a domain via the Registrar API."""
    if not _has_token():
        return False

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{VERCEL_API_BASE}/v1/registrar/domains/{domain}/auto-renew",
            headers=_headers(),
            params=_team_params(),
            json={"autoRenew": auto_renew},
        )

        if resp.status_code == 204:
            state = "enabled" if auto_renew else "disabled"
            logger.info("Domain %s auto-renew %s", domain, state)
            return True

        logger.error(
            "Failed to set auto-renew for %s: %s %s",
            domain, resp.status_code, resp.text,
        )
        return False


async def get_transfer_auth_code(domain: str) -> str | None:
    """Get the authorization/EPP code needed to transfer a domain away."""
    if not _has_token():
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VERCEL_API_BASE}/v1/registrar/domains/{domain}/auth-code",
            headers=_headers(),
            params=_team_params(),
        )

        if resp.status_code == 200:
            data = resp.json()
            auth_code = data.get("authCode") or data.get("code")
            if auth_code:
                logger.info("Retrieved auth code for domain %s", domain)
            return auth_code

        logger.warning(
            "Could not retrieve auth code for %s: %s %s",
            domain, resp.status_code, resp.text,
        )
        return None
