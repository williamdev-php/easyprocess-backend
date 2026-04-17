"""
REST endpoints for site rendering, SEO, tracking, and webhooks.

These are used by the Next.js frontend and external services (Resend webhooks).
GraphQL handles admin operations; REST handles public/rendering endpoints.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.database import get_db
from app.email.service import process_resend_webhook
from app.sites.migration import normalize_site_data
from app.sites.models import CustomDomain, DomainStatus, GeneratedSite, Lead, PageView, SiteStatus
from app.sites.site_schema import SiteSchema

router = APIRouter(prefix="/api/sites", tags=["sites"])


# ---------------------------------------------------------------------------
# Public: Resolve site by subdomain or custom domain
# ---------------------------------------------------------------------------

@router.get("/resolve")
async def resolve_site(
    subdomain: str | None = None,
    domain: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve a site by subdomain slug or custom domain. Used by the viewer."""
    if not subdomain and not domain:
        raise HTTPException(status_code=400, detail="Provide subdomain or domain parameter")

    site: GeneratedSite | None = None

    if subdomain:
        # Look up by subdomain field on GeneratedSite
        cache_key = f"resolve:sub:{subdomain}"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        result = await db.execute(
            select(GeneratedSite).where(
                GeneratedSite.subdomain == subdomain,
                GeneratedSite.status != SiteStatus.ARCHIVED,
            )
        )
        site = result.scalar_one_or_none()

    elif domain:
        # Look up by custom domain
        domain = domain.lower().strip()
        cache_key = f"resolve:dom:{domain}"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        # First check CustomDomain table
        cd_result = await db.execute(
            select(CustomDomain).where(
                CustomDomain.domain == domain,
                CustomDomain.status == DomainStatus.ACTIVE,
                CustomDomain.site_id.isnot(None),
            )
        )
        cd = cd_result.scalar_one_or_none()
        if cd and cd.site_id:
            result = await db.execute(
                select(GeneratedSite).where(
                    GeneratedSite.id == cd.site_id,
                    GeneratedSite.status != SiteStatus.ARCHIVED,
                )
            )
            site = result.scalar_one_or_none()

        # Fallback: check custom_domain field on GeneratedSite directly
        if not site:
            result = await db.execute(
                select(GeneratedSite).where(
                    GeneratedSite.custom_domain == domain,
                    GeneratedSite.status != SiteStatus.ARCHIVED,
                )
            )
            site = result.scalar_one_or_none()

    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    response = {
        "id": site.id,
        "site_data": normalize_site_data(site.site_data or {}),
        "template": site.template,
        "status": site.status.value,
        "subdomain": site.subdomain,
        "custom_domain": site.custom_domain,
    }

    # Cache resolved sites for 5 minutes
    cache_key = f"resolve:sub:{subdomain}" if subdomain else f"resolve:dom:{domain}"
    await cache.set(cache_key, response, ttl=300)

    return response


# ---------------------------------------------------------------------------
# Public: Site data for rendering
# ---------------------------------------------------------------------------

@router.get("/published")
async def list_published_sites(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """List all published sites (for sitemap generation)."""
    cached = await cache.get("sites:published")
    if cached:
        return cached

    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.status == SiteStatus.PUBLISHED)
    )
    sites = result.scalars().all()

    response = []
    for site in sites:
        data = normalize_site_data(site.site_data or {})
        # Derive available page slugs from content blocks
        slugs = []
        if data.get("about"):
            slugs.append("om-oss")
        if data.get("services"):
            slugs.append("tjanster")
        if data.get("gallery"):
            slugs.append("galleri")
        if data.get("business", {}).get("email") or data.get("business", {}).get("phone") or data.get("contact"):
            slugs.append("kontakt")
        response.append({
            "id": site.id,
            "subdomain": site.subdomain,
            "custom_domain": site.custom_domain,
            "updated_at": (site.updated_at or site.created_at).isoformat() if (site.updated_at or site.created_at) else None,
            "slugs": slugs,
        })

    await cache.set("sites:published", response, ttl=3600)
    return response


@router.get("/{site_id}")
async def get_site(site_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Get full site data for frontend rendering. Cached."""
    cached = await cache.get(f"site:data:{site_id}")
    if cached:
        return cached

    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site or site.status == SiteStatus.ARCHIVED:
        raise HTTPException(status_code=404, detail="Site not found")

    response = {
        "id": site.id,
        "site_data": normalize_site_data(site.site_data or {}),
        "template": site.template,
        "status": site.status.value,
    }

    # Only cache published sites (drafts may change)
    if site.status == SiteStatus.PUBLISHED:
        await cache.set(f"site:data:{site_id}", response, ttl=3600)
    return response


@router.get("/{site_id}/meta")
async def get_site_meta(site_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Get only metadata for SSR/SEO (smaller payload)."""
    cached = await cache.get(f"site:meta:{site_id}")
    if cached:
        return cached

    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site or site.status == SiteStatus.ARCHIVED:
        raise HTTPException(status_code=404, detail="Site not found")

    site_data = normalize_site_data(site.site_data or {})
    meta = site_data.get("meta", {})
    branding = site_data.get("branding", {})
    business = site_data.get("business", site_data.get("business_info", {}))
    seo = site_data.get("seo", {})

    response = {
        "id": site.id,
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "keywords": meta.get("keywords", []),
        "og_image": meta.get("og_image"),
        "language": meta.get("language", "sv"),
        "logo_url": branding.get("logo_url"),
        "business_name": business.get("name", ""),
        "structured_data": seo.get("structured_data", {}),
        "robots": seo.get("robots", "index, follow"),
    }

    if site.status == SiteStatus.PUBLISHED:
        await cache.set(f"site:meta:{site_id}", response, ttl=3600)
    return response


# ---------------------------------------------------------------------------
# SEO: Sitemap, Robots, Structured Data
# ---------------------------------------------------------------------------

@router.get("/{site_id}/sitemap.xml")
async def get_sitemap(
    site_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Dynamic sitemap.xml for a site."""
    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    site_data = normalize_site_data(site.site_data or {})
    seo = site_data.get("seo", {})

    base = str(request.base_url).rstrip("/")
    site_base = f"{base}/{site_id}"

    # Derive pages from content blocks
    page_slugs = [""]  # Home always
    if site_data.get("about"):
        page_slugs.append("om-oss")
    if site_data.get("services"):
        page_slugs.append("tjanster")
    if site_data.get("gallery"):
        page_slugs.append("galleri")
    if site_data.get("business", {}).get("email") or site_data.get("contact"):
        page_slugs.append("kontakt")

    urlset = Element("urlset")
    urlset.set("xmlns", "http://www.sitemaps.org/schemas/sitemap/0.9")

    for slug in page_slugs:
        url = SubElement(urlset, "url")
        loc = SubElement(url, "loc")
        loc.text = f"{site_base}/{slug}" if slug else site_base
        lastmod = SubElement(url, "lastmod")
        lastmod.text = (site.updated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        prio = SubElement(url, "priority")
        prio.text = "1.0" if not slug else "0.8"

    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(urlset, encoding="unicode").encode()
    return Response(content=xml_bytes, media_type="application/xml")


@router.get("/{site_id}/robots.txt")
async def get_robots(site_id: str, request: Request) -> Response:
    """Dynamic robots.txt for a site."""
    base = str(request.base_url).rstrip("/")
    content = f"""User-agent: *
Allow: /

Sitemap: {base}/api/sites/{site_id}/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@router.get("/{site_id}/structured-data")
async def get_structured_data(site_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """JSON-LD structured data for a site."""
    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site or site.status != SiteStatus.PUBLISHED:
        raise HTTPException(status_code=404, detail="Site not found")

    site_data = site.site_data or {}
    seo = site_data.get("seo", {})
    business = site_data.get("business_info", {})
    meta = site_data.get("meta", {})

    # Use existing structured data or build LocalBusiness schema
    structured = seo.get("structured_data")
    if not structured:
        structured = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": business.get("name", ""),
            "description": meta.get("description", ""),
        }
        if business.get("email"):
            structured["email"] = business["email"]
        if business.get("phone"):
            structured["telephone"] = business["phone"]
        if business.get("address"):
            structured["address"] = {
                "@type": "PostalAddress",
                "streetAddress": business["address"],
            }

    return structured


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------

class TrackEventPayload(BaseModel):
    visitor_id: str
    session_id: str
    path: str = "/"
    referrer: str | None = None
    screen_width: int | None = None
    load_time_ms: int | None = None
    ttfb_ms: int | None = None
    fcp_ms: int | None = None
    lcp_ms: int | None = None
    cls: float | None = None


@router.post("/{site_id}/track/view")
async def track_view(
    site_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record a page view with optional performance metrics."""
    # Accept both JSON body and empty POST (legacy)
    payload: TrackEventPayload | None = None
    try:
        body = await request.json()
        payload = TrackEventPayload(**body)
    except Exception:
        pass

    result = await db.execute(
        select(GeneratedSite.id, GeneratedSite.status).where(
            GeneratedSite.id == site_id
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Site not found")

    ua = request.headers.get("user-agent", "")[:500]

    if payload:
        page_view = PageView(
            site_id=site_id,
            visitor_id=payload.visitor_id[:64],
            session_id=payload.session_id[:64],
            path=payload.path[:500],
            referrer=payload.referrer[:1000] if payload.referrer else None,
            user_agent=ua,
            screen_width=payload.screen_width,
            load_time_ms=payload.load_time_ms,
            ttfb_ms=payload.ttfb_ms,
            fcp_ms=payload.fcp_ms,
            lcp_ms=payload.lcp_ms,
            cls=payload.cls,
        )
        db.add(page_view)

    # Also increment the simple counter for backwards compat
    site_result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = site_result.scalar_one_or_none()
    if site:
        site.views += 1

    await db.commit()
    await cache.delete(f"site:data:{site_id}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@webhook_router.post("/resend")
async def resend_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Handle Resend webhook events (delivery, open, click, bounce)."""
    body = await request.body()
    signature = request.headers.get("svix-signature", "")
    timestamp = request.headers.get("svix-timestamp", "")
    msg_id = request.headers.get("svix-id", "")

    # Verify signature if webhook secret is configured
    from app.config import settings
    if settings.RESEND_WEBHOOK_SECRET:
        signed_content = f"{msg_id}.{timestamp}.{body.decode()}"
        expected = hmac.new(
            settings.RESEND_WEBHOOK_SECRET.encode(),
            signed_content.encode(),
            hashlib.sha256,
        ).digest()
        expected_b64 = base64.b64encode(expected).decode()
        sig_to_check = signature.split(",")[-1] if "," in signature else signature
        if not hmac.compare_digest(sig_to_check, expected_b64):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(body)
    await process_resend_webhook(db, payload)
    return {"ok": True}


@webhook_router.post("/resend/inbound")
async def resend_inbound_webhook(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Handle Resend inbound email webhook."""
    body = await request.body()

    # Verify signature if configured
    signature = request.headers.get("svix-signature", "")
    timestamp = request.headers.get("svix-timestamp", "")
    msg_id = request.headers.get("svix-id", "")

    from app.config import settings as _settings
    secret = _settings.RESEND_INBOUND_WEBHOOK_SECRET or _settings.RESEND_WEBHOOK_SECRET
    if secret:
        signed_content = f"{msg_id}.{timestamp}.{body.decode()}"
        expected = hmac.new(
            secret.encode(),
            signed_content.encode(),
            hashlib.sha256,
        ).digest()
        expected_b64 = base64.b64encode(expected).decode()
        sig_to_check = signature.split(",")[-1] if "," in signature else signature
        if not hmac.compare_digest(sig_to_check, expected_b64):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(body)

    from app.email.inbound import process_inbound_email
    await process_inbound_email(db, payload)
    return {"ok": True}
