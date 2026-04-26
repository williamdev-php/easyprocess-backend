"""
REST endpoints for site rendering, SEO, tracking, and webhooks.

These are used by the Next.js frontend and external services (Resend webhooks).
GraphQL handles admin operations; REST handles public/rendering endpoints.
"""

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cache import cache
from app.config import settings
from app.database import get_db
from app.email.service import process_resend_webhook
from app.rate_limit import limiter
from app.sites.migration import normalize_site_data
from app.auth.dependencies import get_current_user, get_optional_user
from app.auth.models import User
from app.sites.models import ContactMessage, CustomDomain, DomainStatus, GeneratedSite, Industry, Lead, LeadStatus, PageView, SiteStatus
from app.sites.site_schema import SiteSchema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sites", tags=["sites"])


# ---------------------------------------------------------------------------
# Public: List industries (for create-site dropdown)
# ---------------------------------------------------------------------------

@router.get("/industries")
async def list_industries(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """List all industries for the create-site dropdown."""
    result = await db.execute(
        select(Industry).order_by(Industry.name)
    )
    industries = result.scalars().all()
    return [
        {"id": ind.id, "name": ind.name, "slug": ind.slug}
        for ind in industries
    ]


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
            return JSONResponse(
                content=cached,
                headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"},
            )

        result = await db.execute(
            select(GeneratedSite).where(
                GeneratedSite.subdomain == subdomain,
                GeneratedSite.status.notin_([SiteStatus.ARCHIVED, SiteStatus.PAUSED]),
                GeneratedSite.deleted_at.is_(None),
            )
        )
        site = result.scalar_one_or_none()

    elif domain:
        # Look up by custom domain
        domain = domain.lower().strip()
        cache_key = f"resolve:dom:{domain}"
        cached = await cache.get(cache_key)
        if cached:
            return JSONResponse(
                content=cached,
                headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"},
            )

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
                    GeneratedSite.status.notin_([SiteStatus.ARCHIVED, SiteStatus.PAUSED]),
                    GeneratedSite.deleted_at.is_(None),
                )
            )
            site = result.scalar_one_or_none()

        # Fallback: check custom_domain field on GeneratedSite directly
        if not site:
            result = await db.execute(
                select(GeneratedSite).where(
                    GeneratedSite.custom_domain == domain,
                    GeneratedSite.status.notin_([SiteStatus.ARCHIVED, SiteStatus.PAUSED]),
                    GeneratedSite.deleted_at.is_(None),
                )
            )
            site = result.scalar_one_or_none()

    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # If resolved via subdomain, check if there's an active custom domain → redirect.
    # Skip subdomain-based domains (*.BASE_DOMAIN) to avoid redirect loops.
    redirect_to: str | None = None
    if subdomain and site.id:
        from app.config import settings as _settings
        base_suffix = f".{_settings.BASE_DOMAIN}"

        cd_result = await db.execute(
            select(CustomDomain.domain).where(
                CustomDomain.site_id == site.id,
                CustomDomain.status == DomainStatus.ACTIVE,
            )
        )
        active_domains = cd_result.scalars().all()
        # Only redirect to a real custom domain, not a platform subdomain
        for d in active_domains:
            if not d.endswith(base_suffix):
                redirect_to = f"https://{d}"
                break

    response = {
        "id": site.id,
        "site_data": normalize_site_data(site.site_data or {}),
        "template": site.template,
        "status": site.status.value,
        "subdomain": site.subdomain,
        "custom_domain": site.custom_domain,
        "redirect_to": redirect_to,
    }

    # Cache resolved sites for 5 minutes
    cache_key = f"resolve:sub:{subdomain}" if subdomain else f"resolve:dom:{domain}"
    await cache.set(cache_key, response, ttl=300)

    return JSONResponse(
        content=response,
        headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"},
    )


# ---------------------------------------------------------------------------
# Public: Site data for rendering
# ---------------------------------------------------------------------------

@router.get("/published")
async def list_published_sites(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """List all published sites (for sitemap generation)."""
    cached = await cache.get("sites:published")
    if cached:
        return JSONResponse(
            content=cached,
            headers={"Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"},
        )

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
            slugs.append("about")
        if data.get("services"):
            slugs.append("services")
        if data.get("gallery"):
            slugs.append("gallery")
        if data.get("business", {}).get("email") or data.get("business", {}).get("phone") or data.get("contact"):
            slugs.append("contact")
        # Multi-page support: add page slugs
        for page in data.get("pages") or []:
            ps = page.get("slug", "")
            if ps:
                parent = page.get("parent_slug")
                slugs.append(f"{parent}/{ps}" if parent else ps)
        response.append({
            "id": site.id,
            "subdomain": site.subdomain,
            "custom_domain": site.custom_domain,
            "updated_at": (site.updated_at or site.created_at).isoformat() if (site.updated_at or site.created_at) else None,
            "slugs": slugs,
        })

    await cache.set("sites:published", response, ttl=3600)
    return JSONResponse(
        content=response,
        headers={"Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"},
    )


# ---------------------------------------------------------------------------
# Claim: public showcase & ownership transfer
# ---------------------------------------------------------------------------


@router.get("/claim/{token}")
async def get_claim_info(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Public endpoint: get site preview info for the claim showcase page."""
    result = await db.execute(
        select(GeneratedSite)
        .where(
            GeneratedSite.claim_token == token,
            GeneratedSite.status.notin_([SiteStatus.ARCHIVED, SiteStatus.PAUSED]),
                GeneratedSite.deleted_at.is_(None),
        )
        .options(selectinload(GeneratedSite.lead))
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Invalid or expired claim link")

    if site.claimed_by:
        raise HTTPException(status_code=410, detail="This site has already been claimed")

    site_data = normalize_site_data(site.site_data or {})
    branding = site_data.get("branding", {})
    business = site_data.get("business", {})
    meta = site_data.get("meta", {})
    hero = site_data.get("hero", {}) or {}

    return {
        "site_id": site.id,
        "subdomain": site.subdomain,
        "logo_url": branding.get("logo_url"),
        "business_name": business.get("name", ""),
        "tagline": business.get("tagline", ""),
        "industry": site.lead.industry if site.lead else None,
        "headline": hero.get("headline", ""),
        "description": meta.get("description", ""),
        "created_at": site.created_at.isoformat() if site.created_at else None,
        "colors": branding.get("colors", {}),
        "video_url": site.video_url,
    }


@router.post("/claim/{token}")
async def claim_site(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Claim ownership of a draft site. Requires authentication."""
    result = await db.execute(
        select(GeneratedSite)
        .where(
            GeneratedSite.claim_token == token,
            GeneratedSite.status.notin_([SiteStatus.ARCHIVED, SiteStatus.PAUSED]),
                GeneratedSite.deleted_at.is_(None),
        )
        .options(selectinload(GeneratedSite.lead))
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Invalid or expired claim link")

    if site.claimed_by:
        raise HTTPException(status_code=410, detail="This site has already been claimed")

    # Transfer ownership: update lead.created_by to point to the claiming user
    if site.lead:
        site.lead.created_by = str(current_user.id)
        site.lead.status = LeadStatus.CONVERTED

    site.claimed_by = str(current_user.id)
    site.claim_token = None  # Invalidate token after claim

    # Transfer any custom domains linked to this site to the new owner
    from sqlalchemy import select as _select
    cd_result = await db.execute(
        _select(CustomDomain).where(CustomDomain.site_id == site.id)
    )
    for cd in cd_result.scalars().all():
        if cd.user_id != str(current_user.id):
            cd.user_id = str(current_user.id)

    await db.commit()

    # Notify Smartlead that lead converted (pause follow-up emails)
    if site.lead and site.lead.status == LeadStatus.CONVERTED:
        import asyncio
        from app.smartlead.service import mark_lead_converted
        asyncio.create_task(mark_lead_converted(site.lead.id))

    # Invalidate caches
    await cache.delete(f"site:{site.id}")
    await cache.delete(f"site:data:{site.id}")
    await cache.delete(f"site:meta:{site.id}")
    await cache.delete("admin:dashboard_stats")
    if site.subdomain:
        await cache.delete(f"resolve:sub:{site.subdomain}")

    return {"ok": True, "site_id": site.id}


# ---------------------------------------------------------------------------
# Create site: rate limiting & helpers
# ---------------------------------------------------------------------------

# Daily site creation limits per plan
_SITE_LIMIT_FREE = 2
_SITE_LIMIT_BASIC = 5
_SITE_LIMIT_PRO = 20
_SITE_LIMIT_IP = 5  # absolute IP limit regardless of plan


async def _check_site_creation_rate(
    db: AsyncSession,
    user: User | None,
    request: Request,
) -> None:
    """Enforce daily site creation limits based on plan and IP."""
    from datetime import timedelta
    from app.auth.service import get_client_ip

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. IP-based limit (applies to everyone)
    ip = get_client_ip(request)
    if ip:
        ip_result = await db.execute(
            select(func.count(Lead.id)).where(
                Lead.created_at >= today_start,
                Lead.source.in_(["create_direct", "create_transform"]),
                # Use created_by as a proxy — for unauthenticated we'll track by source
            )
        )
        # We can't track IP in leads table, so we use an in-memory approach via slowapi
        # The IP rate limit is handled by the @limiter decorator on the endpoints

    # 2. User-based limit (if authenticated)
    if user:
        user_result = await db.execute(
            select(func.count(Lead.id)).where(
                Lead.created_by == user.id,
                Lead.created_at >= today_start,
                Lead.source.in_(["create_direct", "create_transform"]),
            )
        )
        user_count = user_result.scalar() or 0

        # Determine plan limit
        from app.billing.service import get_active_subscription
        sub = await get_active_subscription(db, user.id)
        if user.is_superuser:
            limit = 999
        elif sub is not None:
            # Has active subscription — basic or pro
            limit = _SITE_LIMIT_BASIC
            # Check if pro (by checking price ID)
            if sub.stripe_subscription_id:
                try:
                    import stripe
                    stripe_sub = stripe.Subscription.retrieve(sub.stripe_subscription_id)
                    price_id = stripe_sub["items"]["data"][0]["price"]["id"] if stripe_sub.get("items") else ""
                    from app.config import settings as _s
                    if price_id == _s.STRIPE_PRO_PRICE_ID:
                        limit = _SITE_LIMIT_PRO
                except Exception:
                    pass  # Default to basic limit on error
        else:
            limit = _SITE_LIMIT_FREE

        if user_count >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Du har natt gransen for antal hemsidor per dag ({limit}). Uppgradera din plan for att skapa fler.",
            )


# ---------------------------------------------------------------------------
# Create site: direct (no scraping) & from URL (transform)
# ---------------------------------------------------------------------------


class CreateSitePayload(BaseModel):
    """Create a brand-new site from scratch using AI generation."""
    business_name: str = Field(min_length=1, max_length=255)
    industry: str | None = None
    industry_id: str | None = None  # FK to industries table for prompt_hint lookup
    context: str = Field(default="", max_length=2000)
    colors: dict | None = None  # {primary, secondary, accent, background, text}
    logo_url: str | None = None
    email: str | None = None  # user's contact email for the site
    image_urls: list[str] | None = Field(None, max_length=12)  # up to 12 user-uploaded images
    font: str | None = Field(None, max_length=100)  # Google Font name for the site


class CreateSiteFromUrlPayload(BaseModel):
    """Transform an existing website into a new site."""
    website_url: str = Field(min_length=4, max_length=500)


@router.post("/create")
@limiter.limit("5/day")
async def create_site_direct(
    request: Request,
    payload: CreateSitePayload,
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new site from scratch — AI generates content from the provided context.

    Works for both authenticated and unauthenticated users. Unauthenticated users
    get a claim_token to link the site to an account later.
    """
    await _check_site_creation_rate(db, current_user, request)

    import secrets
    from app.ai.generator import generate_site
    from app.sites.subdomain import generate_unique_subdomain

    user_id = str(current_user.id) if current_user else None

    # Create a lead record to track this generation
    lead = Lead(
        website_url=f"https://qvicko.com/create/{payload.business_name.lower().replace(' ', '-')}",
        business_name=payload.business_name,
        industry=payload.industry,
        source="create_direct",
        status=LeadStatus.GENERATING,
        created_by=user_id,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    lead_id = lead.id

    # Build context texts for the AI prompt
    texts: dict = {
        "title": payload.business_name,
        "description": "",
        "about": "",
        "paragraphs": [],
        "headings": [],
    }

    # Use provided colors or None (AI will generate)
    colors = payload.colors

    # Look up industry prompt_hint from DB if industry_id provided
    industry_prompt_hint: str | None = None
    industry_default_sections: list[str] | None = None
    industry_name = payload.industry
    if payload.industry_id:
        result = await db.execute(
            select(Industry).where(Industry.id == payload.industry_id)
        )
        ind = result.scalar_one_or_none()
        if ind:
            industry_prompt_hint = ind.prompt_hint
            industry_default_sections = ind.default_sections
            if not industry_name:
                industry_name = ind.name

    # Run generation in background
    import asyncio

    async def _generate_bg():
        from app.database import get_db_session
        async with get_db_session() as bg_db:
            try:
                # Upload base64 images to Supabase so the AI gets real URLs
                stored_images: list[dict] | None = None
                if payload.image_urls:
                    from app.storage.supabase import upload_file
                    stored_images = []
                    for idx, data_url in enumerate(payload.image_urls[:12]):
                        try:
                            if not data_url or not data_url.startswith("data:"):
                                continue
                            # Parse data URI: data:<mime>;base64,<data>
                            header, b64_data = data_url.split(",", 1)
                            mime = header.split(":")[1].split(";")[0]
                            ext = mime.split("/")[-1].replace("jpeg", "jpg")
                            raw = base64.b64decode(b64_data)
                            public_url = upload_file(
                                file_data=raw,
                                file_name=f"upload-{idx}.{ext}",
                                content_type=mime,
                                prefix=f"user-images/{lead_id}",
                            )
                            stored_images.append({"url": public_url, "alt": "", "category": "user-upload"})
                        except Exception:
                            continue
                    if not stored_images:
                        stored_images = None

                # --- Planning step ---
                blueprint = None
                try:
                    from app.ai.planner import plan_site
                    blueprint = await plan_site(
                        business_name=payload.business_name,
                        context=payload.context,
                        industry=industry_name,
                        industry_hint=industry_prompt_hint,
                        num_images=len(stored_images) if stored_images else 0,
                        colors=colors,
                    )
                    # Save blueprint for debugging
                    if blueprint:
                        result = await bg_db.execute(
                            select(Lead).where(Lead.id == lead_id)
                        )
                        bg_lead = result.scalar_one_or_none()
                        if bg_lead:
                            bg_lead.blueprint_data = blueprint.model_dump(mode="json")
                            await bg_db.commit()
                except Exception as e:
                    logger.warning("Planner failed, using fallback: %s", e)
                    blueprint = None

                gen_result = await generate_site(
                    business_name=payload.business_name,
                    industry=industry_name,
                    website_url="",
                    email=payload.email,
                    phone=None,
                    address=None,
                    texts=texts,
                    colors=colors,
                    services=None,
                    logo_url=payload.logo_url,
                    social_links=None,
                    images=stored_images,
                    visual_analysis=None,
                    industry_prompt_hint=industry_prompt_hint,
                    industry_default_sections=industry_default_sections,
                    blueprint=blueprint,
                    context=payload.context,
                    is_freeform=True,
                )

                site_data = gen_result.site_schema.model_dump(mode="json")

                # Apply user-selected font, or pick a safe default
                import random as _random
                _safe_fonts = [
                    "Inter", "Poppins", "DM Sans", "Outfit",
                    "Plus Jakarta Sans", "Manrope", "Work Sans", "Lato",
                ]
                chosen_font = payload.font or _random.choice(_safe_fonts)
                if "branding" not in site_data or site_data["branding"] is None:
                    site_data["branding"] = {}
                if "fonts" not in site_data["branding"] or site_data["branding"]["fonts"] is None:
                    site_data["branding"]["fonts"] = {}
                site_data["branding"]["fonts"]["body"] = chosen_font
                site_data["branding"]["fonts"]["heading"] = chosen_font

                subdomain = await generate_unique_subdomain(
                    bg_db, payload.business_name, None
                )
                site = GeneratedSite(
                    lead_id=lead_id,
                    site_data=site_data,
                    tokens_used=gen_result.tokens_used,
                    input_tokens=gen_result.input_tokens,
                    output_tokens=gen_result.output_tokens,
                    ai_model=gen_result.model,
                    generation_cost_usd=gen_result.cost_usd,
                    planner_tokens=getattr(blueprint, '_tokens_used', None) if blueprint else None,
                    planner_cost_usd=getattr(blueprint, '_cost_usd', None) if blueprint else None,
                    status=SiteStatus.DRAFT,
                    subdomain=subdomain,
                    claim_token=secrets.token_urlsafe(32),
                    claimed_by=user_id,
                )
                bg_db.add(site)
                await bg_db.flush()  # ensure site.id is set

                # Auto-install apps requested by AI
                if gen_result.install_apps:
                    from app.apps.models import App as AppModel, AppInstallation as AppInstModel
                    for app_slug in gen_result.install_apps:
                        app_row = await bg_db.execute(
                            select(AppModel).where(
                                AppModel.slug == app_slug,
                                AppModel.is_active == True,  # noqa: E712
                            )
                        )
                        app_obj = app_row.scalar_one_or_none()
                        if app_obj:
                            bg_db.add(AppInstModel(
                                app_id=app_obj.id,
                                site_id=site.id,
                                installed_by=user_id,
                            ))

                # Update lead status
                result = await bg_db.execute(
                    select(Lead).where(Lead.id == lead_id)
                )
                bg_lead = result.scalar_one_or_none()
                if bg_lead:
                    bg_lead.status = LeadStatus.GENERATED
                    bg_lead.error_message = None

                await bg_db.commit()
                await cache.delete("admin:dashboard_stats")

            except Exception as e:
                import re as _re
                await bg_db.rollback()
                result = await bg_db.execute(
                    select(Lead).where(Lead.id == lead_id)
                )
                bg_lead = result.scalar_one_or_none()
                if bg_lead:
                    bg_lead.status = LeadStatus.FAILED
                    error_msg = str(e)[:500]
                    error_msg = _re.sub(r'(sk-|key-|token-)[a-zA-Z0-9]{10,}', '[REDACTED]', error_msg)
                    bg_lead.error_message = error_msg
                    await bg_db.commit()

    asyncio.create_task(_generate_bg())

    return {
        "ok": True,
        "lead_id": lead_id,
        "status": "GENERATING",
    }


@router.post("/create-from-url")
@limiter.limit("5/day")
async def create_site_from_url(
    request: Request,
    payload: CreateSiteFromUrlPayload,
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Transform an existing website into a new Qvicko site.

    Runs the full scrape+generate pipeline. Works for both authenticated
    and unauthenticated users.
    """
    await _check_site_creation_rate(db, current_user, request)

    from urllib.parse import urlparse

    url = payload.website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    if not parsed.hostname or "." not in parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid website URL")

    user_id = str(current_user.id) if current_user else None

    lead = Lead(
        website_url=url,
        source="create_transform",
        status=LeadStatus.NEW,
        created_by=user_id,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    lead_id = lead.id

    # Run pipeline in background (concurrency-controlled)
    from app.pipeline_manager import pipeline_manager
    from app.database import get_db_session

    async def _auto_claim():
        """Auto-claim the generated site if user is authenticated."""
        if not user_id:
            return
        async with get_db_session() as bg_db:
            result = await bg_db.execute(
                select(Lead)
                .where(Lead.id == lead_id)
                .options(selectinload(Lead.generated_site))
            )
            bg_lead = result.scalar_one_or_none()
            if bg_lead and bg_lead.generated_site:
                bg_lead.generated_site.claimed_by = user_id
                bg_lead.created_by = user_id
                await bg_db.commit()

    await pipeline_manager.enqueue(lead_id, post_pipeline_callback=_auto_claim)

    return {
        "ok": True,
        "lead_id": lead_id,
        "status": "NEW",
    }


@router.get("/create-status/{lead_id}")
async def get_creation_status(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poll the status of a site being generated."""
    result = await db.execute(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(selectinload(Lead.generated_site))
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Not found")

    response: dict = {
        "lead_id": lead.id,
        "status": lead.status.value,
        "business_name": lead.business_name,
        "error_message": lead.error_message,
    }

    if lead.generated_site:
        site = lead.generated_site
        response["site_id"] = site.id
        response["subdomain"] = site.subdomain
        response["claim_token"] = site.claim_token if not site.claimed_by else None

    return response


@router.get("/{site_id}")
async def get_site(site_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Get full site data for frontend rendering. Cached."""
    cached = await cache.get(f"site:data:{site_id}")
    if cached:
        return JSONResponse(
            content=cached,
            headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=3600"},
        )

    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site or site.status == SiteStatus.ARCHIVED:
        raise HTTPException(status_code=404, detail="Site not found")

    # Fetch installed apps for this site
    from app.apps.models import App as AppModel, AppInstallation as AppInstModel
    apps_result = await db.execute(
        select(AppModel.slug)
        .join(AppInstModel, AppInstModel.app_id == AppModel.id)
        .where(
            AppInstModel.site_id == site_id,
            AppInstModel.is_active == True,  # noqa: E712
        )
    )
    installed_apps = [row[0] for row in apps_result.all()]

    response: dict = {
        "id": site.id,
        "site_data": normalize_site_data(site.site_data or {}),
        "template": site.template,
        "status": site.status.value,
        "installed_apps": installed_apps,
    }

    # Include draft claim info so the viewer can show a banner
    if site.status == SiteStatus.DRAFT:
        response["created_at"] = site.created_at.isoformat() if site.created_at else None
        response["claim_token"] = site.claim_token if not site.claimed_by else None

    # Published sites: long cache. Drafts: short cache to reduce DB load.
    if site.status == SiteStatus.PUBLISHED:
        await cache.set(f"site:data:{site_id}", response, ttl=3600)
        return JSONResponse(
            content=response,
            headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=3600"},
        )
    else:
        await cache.set(f"site:data:{site_id}", response, ttl=30)
        return JSONResponse(
            content=response,
            headers={"Cache-Control": "private, max-age=30"},
        )


@router.get("/{site_id}/meta")
async def get_site_meta(site_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Get only metadata for SSR/SEO (smaller payload)."""
    cached = await cache.get(f"site:meta:{site_id}")
    if cached:
        return JSONResponse(
            content=cached,
            headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=3600"},
        )

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
        "head_scripts": site_data.get("head_scripts"),
    }

    if site.status == SiteStatus.PUBLISHED:
        await cache.set(f"site:meta:{site_id}", response, ttl=3600)
        return JSONResponse(
            content=response,
            headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=3600"},
        )
    else:
        await cache.set(f"site:meta:{site_id}", response, ttl=30)
        return JSONResponse(
            content=response,
            headers={"Cache-Control": "private, max-age=30"},
        )


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
        page_slugs.append("about")
    if site_data.get("services"):
        page_slugs.append("services")
    if site_data.get("gallery"):
        page_slugs.append("gallery")
    if site_data.get("business", {}).get("email") or site_data.get("contact"):
        page_slugs.append("contact")
    # Multi-page support
    for page in site_data.get("pages") or []:
        ps = page.get("slug", "")
        if ps:
            parent = page.get("parent_slug")
            page_slugs.append(f"{parent}/{ps}" if parent else ps)

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
    # Cache invalidation removed — rely on TTL (1h) instead of invalidating on every view.
    return {"ok": True}


# ---------------------------------------------------------------------------
# Contact form
# ---------------------------------------------------------------------------

class ContactPayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    message: str = Field(min_length=1, max_length=5000)


@router.post("/{site_id}/contact")
async def submit_contact(
    site_id: str,
    payload: ContactPayload,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a contact form submission from a site visitor."""
    # Validate site exists and fetch site data for emails
    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    import html as _html

    visitor_name = payload.name.strip()
    visitor_email = payload.email.strip()
    message_text = payload.message.strip()

    contact_msg = ContactMessage(
        site_id=site_id,
        name=_html.escape(visitor_name),
        email=visitor_email,
        message=_html.escape(message_text),
    )
    db.add(contact_msg)
    await db.commit()

    # Send email notifications
    try:
        from app.email.service import send_transactional_email
        from app.email.contact_templates import (
            build_contact_form_owner_email,
            build_contact_form_visitor_email,
        )

        site_name = "Hemsida"
        if site.site_data:
            site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

        # Notify site owner
        if site.claimed_by:
            owner_result = await db.execute(
                select(User).where(User.id == site.claimed_by)
            )
            owner = owner_result.scalar_one_or_none()
            if owner and owner.email:
                owner_subj, owner_html, owner_text = build_contact_form_owner_email(
                    owner_name=owner.full_name or owner.email,
                    site_name=site_name,
                    visitor_name=visitor_name,
                    visitor_email=visitor_email,
                    message=message_text,
                    dashboard_url=f"{settings.FRONTEND_URL}/dashboard",
                )
                await send_transactional_email(
                    to=owner.email,
                    subject=owner_subj,
                    html=owner_html,
                    text=owner_text,
                    from_name=site_name,
                )

        # Send confirmation to visitor
        visitor_subj, visitor_html, visitor_text = build_contact_form_visitor_email(
            visitor_name=visitor_name,
            site_name=site_name,
        )
        await send_transactional_email(
            to=visitor_email,
            subject=visitor_subj,
            html=visitor_html,
            text=visitor_text,
            from_name=site_name,
        )
    except Exception:
        logger.exception("Failed to send contact form emails")

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

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    await process_resend_webhook(db, payload)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Preview screenshots for site general page (desktop + mobile)
# ---------------------------------------------------------------------------

@router.get("/{site_id}/preview-image")
async def get_site_preview_image(
    site_id: str,
    device: str = "desktop",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return a cached preview screenshot URL for a site.

    Query params:
      - device: "desktop" (1440x900) or "mobile" (375x812)

    Returns: {"url": str | null, "cached": bool}
    """
    cache_key = f"preview:{site_id}:{device}"
    cached = await cache.get(cache_key)
    if cached:
        return {"url": cached, "cached": True}

    # Look up the site to get its viewer URL
    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Build preview URL — use preview subdomain to avoid bare-domain redirects
    from app.config import settings as _settings
    viewer_url = _settings.VIEWER_URL
    if not viewer_url:
        return {"url": None, "cached": False}

    # In production, use the preview subdomain (bare domain has a stale redirect)
    if "localhost" not in viewer_url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(viewer_url)
            host = parsed.hostname or ""
            host = host.removeprefix("www.")
            preview_url = f"{parsed.scheme}://preview.{host}/preview/{site_id}"
        except Exception:
            preview_url = f"{viewer_url}/preview/{site_id}"
    else:
        preview_url = f"{viewer_url}/preview/{site_id}"

    # Capture screenshot
    try:
        from app.scraper.screenshot import capture_preview_screenshot
        screenshot_url = await capture_preview_screenshot(
            url=preview_url,
            site_id=site_id,
            device=device,
        )

        if screenshot_url:
            # Cache for 1 hour
            await cache.set(cache_key, screenshot_url, ttl=3600)
            return {"url": screenshot_url, "cached": False}

        return {"url": None, "cached": False}
    except Exception as e:
        logger.warning(f"Preview screenshot failed for site {site_id}: {e}")
        return {"url": None, "cached": False}


@router.delete("/{site_id}/preview-image")
async def invalidate_site_preview(
    site_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Invalidate cached preview images for a site."""
    for device in ("desktop", "mobile"):
        await cache.delete(f"preview:{site_id}:{device}")
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

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    from app.email.inbound import process_inbound_email
    await process_inbound_email(db, payload)
    return {"ok": True}
