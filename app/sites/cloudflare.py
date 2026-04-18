"""
Cloudflare DNS management for subdomain and custom domain handling.

- Subdomains: Creates CNAME records for slug.BASE_DOMAIN → viewer app
- Custom domains: Verifies CNAME records point to proxy.BASE_DOMAIN
- Wildcard: In production, a *.BASE_DOMAIN wildcard handles all subdomains
"""

from __future__ import annotations

import logging
import socket

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CF_API_BASE = "https://api.cloudflare.com/client/v4"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _is_configured() -> bool:
    return bool(settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ZONE_ID)


async def create_subdomain_record(subdomain: str) -> bool:
    """Create a CNAME record for subdomain.BASE_DOMAIN pointing to the viewer app.

    In production with a wildcard *.BASE_DOMAIN this is optional,
    but creating explicit records enables Cloudflare proxy (orange cloud).
    """
    if not _is_configured():
        logger.warning("Cloudflare not configured — skipping DNS record creation for %s", subdomain)
        return False

    fqdn = f"{subdomain}.{settings.BASE_DOMAIN}"

    async with httpx.AsyncClient() as client:
        # Check if record already exists
        resp = await client.get(
            f"{CF_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/dns_records",
            headers=_headers(),
            params={"name": fqdn, "type": "CNAME"},
        )
        data = resp.json()
        if data.get("result"):
            logger.info("DNS record already exists for %s", fqdn)
            return True

        # Create CNAME record
        resp = await client.post(
            f"{CF_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/dns_records",
            headers=_headers(),
            json={
                "type": "CNAME",
                "name": subdomain,
                "content": settings.BASE_DOMAIN,
                "ttl": 1,  # Auto TTL
                "proxied": True,
            },
        )
        result = resp.json()
        if result.get("success"):
            logger.info("Created DNS CNAME record for %s", fqdn)
            return True

        logger.error("Failed to create DNS record for %s: %s", fqdn, result.get("errors"))
        return False


async def delete_subdomain_record(subdomain: str) -> bool:
    """Delete a CNAME record for subdomain.BASE_DOMAIN."""
    if not _is_configured():
        return False

    fqdn = f"{subdomain}.{settings.BASE_DOMAIN}"

    async with httpx.AsyncClient() as client:
        # Find the record
        resp = await client.get(
            f"{CF_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/dns_records",
            headers=_headers(),
            params={"name": fqdn, "type": "CNAME"},
        )
        data = resp.json()
        records = data.get("result", [])
        if not records:
            return True  # Already gone

        for record in records:
            await client.delete(
                f"{CF_API_BASE}/zones/{settings.CLOUDFLARE_ZONE_ID}/dns_records/{record['id']}",
                headers=_headers(),
            )
        logger.info("Deleted DNS CNAME record for %s", fqdn)
        return True


async def verify_custom_domain(domain: str) -> bool:
    """Verify that a custom domain has a CNAME pointing to an accepted target.

    Accepted CNAME targets:
    - proxy.BASE_DOMAIN (legacy)
    - BASE_DOMAIN (legacy)
    - cname.vercel-dns.com (Vercel)
    """
    expected_target = f"proxy.{settings.BASE_DOMAIN}"
    accepted_targets = {
        expected_target.lower(),
        settings.BASE_DOMAIN.lower(),
        "cname.vercel-dns.com",
    }

    try:
        # For a reliable CNAME check, query via Cloudflare DNS-over-HTTPS
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://cloudflare-dns.com/dns-query",
                headers={"Accept": "application/dns-json"},
                params={"name": domain, "type": "CNAME"},
            )
            if resp.status_code == 200:
                dns_data = resp.json()
                for answer in dns_data.get("Answer", []):
                    target = answer.get("data", "").rstrip(".").lower()
                    if target in accepted_targets:
                        logger.info("Domain %s CNAME verified → %s", domain, target)
                        return True

        logger.warning("Domain %s CNAME does not point to an accepted target", domain)
        return False

    except Exception:
        logger.exception("DNS verification failed for %s", domain)
        return False
