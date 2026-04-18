"""
Scraping + generation pipeline.

Orchestrates: scrape → extract → AI generate → save site.
Triggered on-demand when an admin creates a lead via GraphQL.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys

import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.generator import generate_site
from app.ai.vision_analyzer import analyze_screenshots
from app.cache import cache
from app.scraper.extractor import extract_all, fetch_page
from app.scraper.image_downloader import download_and_store_images
from app.scraper.screenshot import capture_screenshot_bytes
from app.sites.subdomain import generate_unique_subdomain
from app.sites.models import (
    GeneratedSite,
    Lead,
    LeadStatus,
    ScrapedData,
    SiteStatus,
)

logger = logging.getLogger(__name__)

if sys.version_info >= (3, 11):
    _timeout = asyncio.timeout
else:
    @asynccontextmanager
    async def _timeout(delay: float):
        task = asyncio.current_task()
        loop = asyncio.get_event_loop()
        handle = loop.call_later(delay, task.cancel)
        try:
            yield
        except asyncio.CancelledError:
            raise TimeoutError(f"Timed out after {delay}s")
        finally:
            handle.cancel()


async def run_pipeline(db: AsyncSession, lead_id: str) -> None:
    """
    Full pipeline for a single lead:
    1. Fetch page HTML
    2. Extract content (contacts, texts, colors, images, logo)
    3. Capture screenshots + vision analysis
    4. Override CSS colors with vision-detected colors
    5. Generate site via AI (with screenshots in prompt)
    6. Save everything to DB
    """
    result = await db.execute(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(
            selectinload(Lead.scraped_data),
            selectinload(Lead.generated_site),
        )
    )
    lead = result.scalar_one_or_none()
    if not lead:
        logger.error("Lead %s not found", lead_id)
        return

    try:
        async with _timeout(300):
            # --- Step 1: Scrape ---
            lead.status = LeadStatus.SCRAPING
            await db.commit()

            logger.info("Scraping %s", lead.website_url)
            html, final_url = await fetch_page(lead.website_url)

            # --- Step 2: Extract ---
            data = await extract_all(html, final_url)

            contact = data["contact_info"]
            emails = contact.get("emails", [])
            phones = contact.get("phones", [])

            # Update lead with discovered info
            if emails and not lead.email:
                lead.email = emails[0]
            if phones and not lead.phone:
                lead.phone = phones[0]
            if contact.get("address") and not lead.address:
                lead.address = contact["address"]
            if not lead.business_name and data["texts"].get("title"):
                lead.business_name = data["texts"]["title"][:255]

            # --- Step 2b: Download images to storage ---
            try:
                data["images"], data["logo_url"], data["favicon_url"] = await download_and_store_images(
                    images=data["images"],
                    logo_url=data["logo_url"],
                    lead_id=str(lead.id),
                    favicon_url=data.get("favicon_url"),
                )
                logger.info("Downloaded %d images for %s", len(data["images"]), lead.website_url)
            except (httpx.TimeoutException, httpx.ConnectError) as img_err:
                logger.warning("Network error downloading images for %s: %s", lead.website_url, img_err)
            except Exception as img_err:
                logger.exception("Unexpected error downloading images for %s: %s", lead.website_url, img_err)

            # Include favicon_url in meta_info for persistence
            meta_info = data["meta_info"]
            if data.get("favicon_url"):
                meta_info["favicon_url"] = data["favicon_url"]

            # Save scraped data (replace if exists)
            if lead.scraped_data:
                scraped = lead.scraped_data
                scraped.logo_url = data["logo_url"]
                scraped.colors = data["colors"]
                scraped.texts = data["texts"]
                scraped.images = data["images"]
                scraped.contact_info = data["contact_info"]
                scraped.meta_info = meta_info
                scraped.raw_html_hash = data["html_hash"]
            else:
                scraped = ScrapedData(
                    lead_id=lead.id,
                    logo_url=data["logo_url"],
                    colors=data["colors"],
                    texts=data["texts"],
                    images=data["images"],
                    contact_info=data["contact_info"],
                    meta_info=meta_info,
                    raw_html_hash=data["html_hash"],
                )
                db.add(scraped)

            lead.scraped_at = datetime.now(timezone.utc)
            lead.status = LeadStatus.SCRAPED
            await db.commit()

            logger.info(
                "Scraped %s: emails=%s, phones=%s, images=%d",
                lead.website_url, emails, phones, len(data["images"]),
            )

            # --- Step 2c: Screenshot + Vision Analysis ---
            screenshot_data = None
            try:
                logger.info("Capturing screenshots for %s", lead.website_url)
                screenshot_data = await capture_screenshot_bytes(lead.website_url)
                if screenshot_data:
                    logger.info("Analyzing %d screenshots with vision model", len(screenshot_data))
                    visual_analysis = await analyze_screenshots(screenshot_data)
                    if visual_analysis:
                        data["visual_analysis"] = visual_analysis

                        # Override CSS colors with vision-detected colors (much more accurate)
                        if isinstance(visual_analysis.get("colors"), dict):
                            vision_colors = visual_analysis["colors"]
                            css_colors = data.get("colors", {})
                            for key in ["primary", "secondary", "accent", "background", "text"]:
                                if vision_colors.get(key) and vision_colors[key].startswith("#"):
                                    css_colors[key] = vision_colors[key]
                            data["colors"] = css_colors
                            logger.info(
                                "Overrode CSS colors with vision colors: %s",
                                {k: v for k, v in css_colors.items()},
                            )

                        logger.info("Vision analysis complete for %s", lead.website_url)
                    else:
                        logger.info("Vision analysis returned no results for %s", lead.website_url)
                else:
                    logger.info("No screenshots captured for %s", lead.website_url)
            except Exception as vis_err:
                logger.warning("Vision analysis failed for %s, continuing without: %s", lead.website_url, vis_err)

            # --- Step 3: Generate site ---
            lead.status = LeadStatus.GENERATING
            await db.commit()

            gen_result = await generate_site(
                business_name=lead.business_name,
                industry=lead.industry,
                website_url=lead.website_url,
                email=lead.email,
                phone=lead.phone,
                address=lead.address,
                texts=data["texts"],
                colors=data["colors"],
                services=data["texts"].get("services"),
                logo_url=data["logo_url"],
                social_links=contact.get("social_links"),
                images=data["images"],
                visual_analysis=data.get("visual_analysis"),
                screenshot_bytes=screenshot_data,
            )

            # Inject favicon_url into generated site meta (AI may not include it)
            if data.get("favicon_url") and not gen_result.site_schema.meta.favicon_url:
                gen_result.site_schema.meta.favicon_url = data["favicon_url"]

            # Save generated site (replace if exists)
            site_data = gen_result.site_schema.model_dump(mode="json")

            if lead.generated_site:
                site = lead.generated_site
                site.site_data = site_data
                site.tokens_used = gen_result.tokens_used
                site.ai_model = gen_result.model
                site.generation_cost_usd = gen_result.cost_usd
                site.status = SiteStatus.DRAFT
                site.updated_at = datetime.now(timezone.utc)
                # Ensure subdomain is set (backfill if missing)
                if not site.subdomain:
                    site.subdomain = await generate_unique_subdomain(
                        db, lead.business_name, lead.website_url, exclude_site_id=site.id
                    )
                # Ensure claim token exists
                if not site.claim_token:
                    import secrets
                    site.claim_token = secrets.token_urlsafe(32)
            else:
                import secrets
                subdomain = await generate_unique_subdomain(
                    db, lead.business_name, lead.website_url
                )
                site = GeneratedSite(
                    lead_id=lead.id,
                    site_data=site_data,
                    tokens_used=gen_result.tokens_used,
                    ai_model=gen_result.model,
                    generation_cost_usd=gen_result.cost_usd,
                    status=SiteStatus.DRAFT,
                    subdomain=subdomain,
                    claim_token=secrets.token_urlsafe(32),
                )
                db.add(site)

            lead.status = LeadStatus.GENERATED
            lead.error_message = None
            await db.commit()

            # Invalidate caches
            await cache.delete("admin:dashboard_stats")

            logger.info(
                "Pipeline complete for %s: model=%s, tokens=%d, cost=$%.4f",
                lead.website_url, gen_result.model, gen_result.tokens_used, gen_result.cost_usd,
            )

    except Exception as e:
        logger.exception("Pipeline failed for lead %s: %s", lead_id, e)
        await db.rollback()
        # Re-fetch lead in clean session state
        result = await db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if lead:
            lead.status = LeadStatus.FAILED
            error_msg = str(e)[:500]
            # Remove potential API keys/tokens from error messages
            error_msg = re.sub(r'(sk-|key-|token-)[a-zA-Z0-9]{10,}', '[REDACTED]', error_msg)
            lead.error_message = error_msg
            await db.commit()
        await cache.delete("admin:dashboard_stats")
