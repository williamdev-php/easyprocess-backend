"""
Scraping + generation pipeline.

Orchestrates: scrape → extract → AI generate → save site.
Triggered on-demand when an admin creates a lead via GraphQL.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sys

import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bs4 import BeautifulSoup

from app.ai.generator import generate_site
from app.ai.vision_analyzer import analyze_screenshots
from app.cache import cache
from app.scraper.crawler import discover_nav_links, crawl_subpages, build_crawl_report
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

            # Check scrape cache (keyed by URL hash) to skip expensive re-scraping
            url_hash = hashlib.sha256(lead.website_url.encode()).hexdigest()[:16]
            scrape_cache_key = f"scrape:{url_hash}"
            cached_data = await cache.get(scrape_cache_key)

            if cached_data and isinstance(cached_data, dict):
                logger.info("Using cached scrape data for %s", lead.website_url)
                homepage_html = None  # not needed when using cache
                final_url = lead.website_url
                data = cached_data
            else:
                homepage_html, final_url = await fetch_page(lead.website_url)

                # --- Step 2: Extract ---
                data = await extract_all(homepage_html, final_url)

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

            # Cache scrape results for 1 hour (speeds up re-generation of same URL)
            try:
                cacheable_data = {
                    k: v for k, v in data.items()
                    if k not in ("visual_analysis",)  # exclude non-serializable/large data
                }
                await cache.set(scrape_cache_key, cacheable_data, ttl=3600)
            except Exception:
                logger.debug("Failed to cache scrape data for %s", lead.website_url)

            logger.info(
                "Scraped %s: emails=%s, phones=%s, images=%d",
                lead.website_url, emails, phones, len(data["images"]),
            )

            # --- Step 2b2 + 2c: Crawl & Screenshot in parallel ---
            async def _do_crawl() -> dict | None:
                """Multi-page crawl — runs concurrently with screenshots."""
                try:
                    if homepage_html:
                        homepage_soup = BeautifulSoup(homepage_html, "lxml")
                        nav_pages = discover_nav_links(homepage_soup, final_url)
                        if nav_pages:
                            logger.info(
                                "Discovered %d subpages for %s, crawling...",
                                len(nav_pages), lead.website_url,
                            )
                            await crawl_subpages(nav_pages, final_url)
                            crawl_report = build_crawl_report(final_url, homepage_soup, nav_pages)
                            cr_data = crawl_report.to_dict()

                            # Merge subpage images into main image list (with context)
                            subpage_images = crawl_report.all_images
                            if subpage_images:
                                existing_urls = {img.get("url") for img in data["images"]}
                                new_images = [
                                    img for img in subpage_images
                                    if img.get("url") and img["url"] not in existing_urls
                                ]
                                data["images"].extend(new_images[:20])
                                logger.info(
                                    "Added %d subpage images (total: %d)",
                                    len(new_images[:20]), len(data["images"]),
                                )

                            _merge_subpage_content(data, nav_pages)

                            logger.info(
                                "Crawl complete for %s: %d pages, notes=%d",
                                lead.website_url,
                                crawl_report.pages_crawled,
                                len(crawl_report.generation_notes),
                            )
                            return cr_data
                        else:
                            logger.info("No subpages discovered for %s", lead.website_url)
                    elif cached_data and cached_data.get("crawl_report"):
                        return cached_data["crawl_report"]
                except Exception as crawl_err:
                    logger.warning(
                        "Multi-page crawl failed for %s, continuing without: %s",
                        lead.website_url, crawl_err,
                    )
                return None

            async def _do_screenshots() -> tuple[list[dict] | None, dict | None]:
                """Capture screenshots + vision analysis — runs concurrently with crawl."""
                s_data = None
                v_analysis = None
                try:
                    logger.info("Capturing screenshots for %s", lead.website_url)
                    s_data = await capture_screenshot_bytes(lead.website_url)
                    if s_data:
                        logger.info("Analyzing %d screenshots with vision model", len(s_data))
                        v_analysis = await analyze_screenshots(s_data)
                        if v_analysis:
                            logger.info("Vision analysis complete for %s", lead.website_url)
                        else:
                            logger.info("Vision analysis returned no results for %s", lead.website_url)
                    else:
                        logger.info("No screenshots captured for %s", lead.website_url)
                except Exception as vis_err:
                    logger.warning("Vision analysis failed for %s, continuing without: %s", lead.website_url, vis_err)
                return s_data, v_analysis

            # Run crawl and screenshot/vision in parallel
            crawl_report_data, (screenshot_data, visual_analysis) = await asyncio.gather(
                _do_crawl(),
                _do_screenshots(),
            )

            # Apply crawl results
            if crawl_report_data:
                data["crawl_report"] = crawl_report_data
                if lead.scraped_data:
                    lead.scraped_data.crawl_report = crawl_report_data
                    await db.commit()

            # Apply vision results
            if visual_analysis:
                data["visual_analysis"] = visual_analysis
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

            # --- Step 2d: Planning ---
            lead.status = LeadStatus.PLANNING
            await db.commit()

            # Look up industry prompt hint from DB if lead has an industry_id
            _industry_hint = None
            _industry_sections = None
            if lead.industry_id:
                from app.sites.models import Industry as IndustryModel
                ind_result = await db.execute(
                    select(IndustryModel).where(IndustryModel.id == lead.industry_id)
                )
                ind = ind_result.scalar_one_or_none()
                if ind:
                    _industry_hint = ind.prompt_hint
                    _industry_sections = ind.default_sections

            blueprint = None
            try:
                from app.ai.planner import plan_site
                scraped_summary = _build_scraped_summary(
                    texts=data["texts"],
                    services=data["texts"].get("services"),
                    images=data["images"],
                    crawl_report=data.get("crawl_report"),
                )
                blueprint = await plan_site(
                    business_name=lead.business_name,
                    context=None,
                    industry=lead.industry,
                    industry_hint=_industry_hint,
                    num_images=len(data["images"]) if data["images"] else 0,
                    colors=data["colors"],
                    scraped_data_summary=scraped_summary,
                )
                if blueprint:
                    lead.blueprint_data = blueprint.model_dump(mode="json")
                    await db.commit()
            except Exception as e:
                logger.warning("Planner failed in pipeline, using fallback: %s", e)
                blueprint = None

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
                industry_prompt_hint=_industry_hint,
                industry_default_sections=_industry_sections,
                crawl_report=data.get("crawl_report"),
                blueprint=blueprint,
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
                site.input_tokens = gen_result.input_tokens
                site.output_tokens = gen_result.output_tokens
                site.ai_model = gen_result.model
                site.generation_cost_usd = gen_result.cost_usd
                site.planner_tokens = getattr(blueprint, '_tokens_used', None) if blueprint else None
                site.planner_cost_usd = getattr(blueprint, '_cost_usd', None) if blueprint else None
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
                    input_tokens=gen_result.input_tokens,
                    output_tokens=gen_result.output_tokens,
                    ai_model=gen_result.model,
                    generation_cost_usd=gen_result.cost_usd,
                    planner_tokens=getattr(blueprint, '_tokens_used', None) if blueprint else None,
                    planner_cost_usd=getattr(blueprint, '_cost_usd', None) if blueprint else None,
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
                "Pipeline complete for %s: model=%s, in=%d, out=%d, cost=$%.4f",
                lead.website_url, gen_result.model, gen_result.input_tokens, gen_result.output_tokens, gen_result.cost_usd,
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


def _build_scraped_summary(
    texts: dict | None,
    services: list | None,
    images: list | None,
    crawl_report: dict | None,
) -> str:
    """Build a compact summary of scraped data for the planner."""
    parts = []
    if texts:
        if texts.get("title"):
            parts.append(f"Sidtitel: {texts['title']}")
        if texts.get("about"):
            parts.append(f"Om-text finns ({len(texts['about'])} tecken)")
        if texts.get("headings"):
            parts.append(f"Rubriker: {len(texts['headings'])} st")
        if texts.get("paragraphs"):
            parts.append(f"Textstycken: {len(texts['paragraphs'])} st")
    if services:
        parts.append(f"Tjänster: {len(services)} st")
    if images:
        parts.append(f"Bilder: {len(images)} st")
    if crawl_report:
        flags = []
        if crawl_report.get("has_blog"):
            flags.append("blogg")
        if crawl_report.get("has_pricing"):
            flags.append("priser")
        if crawl_report.get("has_portfolio"):
            flags.append("portfolio")
        if crawl_report.get("has_booking"):
            flags.append("bokning")
        if flags:
            parts.append(f"Hittade: {', '.join(flags)}")
    return "\n".join(parts) if parts else "Ingen scrapad data tillgänglig."


def _merge_subpage_content(data: dict, pages) -> None:
    """Enrich homepage texts dict with content found on subpages.

    Merges about text, services, FAQ, team, and features from subpages
    into the main data dict — only if the homepage didn't already have them.
    """
    texts = data.get("texts", {})

    for page in pages:
        if not page.content:
            continue

        # About text — prefer subpage version if homepage had none
        if page.page_type == "about" and not texts.get("about"):
            about = page.content.get("about")
            if about:
                texts["about"] = about
            elif page.content.get("paragraphs"):
                # Use first few paragraphs as about text
                texts["about"] = " ".join(page.content["paragraphs"][:3])

        # Services from services page
        if page.page_type == "services":
            sub_services = page.content.get("services", [])
            if sub_services and len(sub_services) > len(texts.get("services", [])):
                texts["services"] = sub_services

        # FAQ from FAQ page
        if page.page_type == "faq":
            sub_faq = page.content.get("faq_items", [])
            if sub_faq and len(sub_faq) > len(texts.get("faq_items", [])):
                texts["faq_items"] = sub_faq

        # Team from team page
        if page.page_type == "team":
            sub_team = page.content.get("team_members", [])
            if sub_team and len(sub_team) > len(texts.get("team_members", [])):
                texts["team_members"] = sub_team

        # Features from any relevant page
        if page.page_type in ("about", "services"):
            sub_features = page.content.get("features", [])
            if sub_features and len(sub_features) > len(texts.get("features", [])):
                texts["features"] = sub_features

    data["texts"] = texts
