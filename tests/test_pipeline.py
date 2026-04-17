"""Tests for the scraping pipeline.

Uses an in-memory SQLite DB so we can test the full DB flow
without hitting the real Postgres or needing greenlet.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.sites.models import GeneratedSite, Lead, LeadStatus, ScrapedData, SiteStatus
from app.sites.site_schema import SiteSchema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_HTML = """\
<html><head><title>Test Salon</title>
<meta name="description" content="A test salon">
</head><body>
<h1>Welcome</h1>
<p>Email: <a href="mailto:hello@test.se">hello@test.se</a></p>
<p>Tel: <a href="tel:+46701234567">070-123 45 67</a></p>
<address>Testgatan 1, 111 22 Stockholm</address>
<img src="/photo.jpg" alt="Salon" width="800" height="600">
</body></html>
"""


def _fake_extract_all(html, base_url):
    """Deterministic extractor for tests."""
    return {
        "contact_info": {
            "emails": ["hello@test.se"],
            "phones": ["+46701234567"],
            "address": "Testgatan 1, 111 22 Stockholm",
            "social_links": {},
        },
        "texts": {
            "title": "Test Salon",
            "description": "A test salon",
            "headings": [{"level": "h1", "text": "Welcome"}],
            "hero_text": "Welcome",
            "paragraphs": [],
            "about": None,
            "services": [],
        },
        "colors": {
            "primary": "#2563eb",
            "secondary": "#1e40af",
            "accent": "#f59e0b",
            "background": "#ffffff",
            "text": "#111827",
        },
        "images": [{"url": f"{base_url}photo.jpg", "alt": "Salon", "category": "general"}],
        "logo_url": None,
        "meta_info": {"title": "Test Salon", "description": "A test salon", "keywords": [], "og_image": None},
        "html_hash": "abc123",
    }


def _minimal_site_schema():
    """Build a minimal valid SiteSchema for mocking."""
    return SiteSchema.model_construct(
        businessName="Test Salon",
        hero={"headline": "Welcome", "subHeadline": "A test salon"},
        colors={"primary": "#2563eb", "secondary": "#1e40af", "accent": "#f59e0b",
                "background": "#ffffff", "text": "#111827"},
        sections=[],
    )


async def _refetch_lead(db: AsyncSession, lead_id: str) -> Lead:
    """Expire all and re-fetch a lead with all relationships."""
    db.expire_all()
    result = await db.execute(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(
            selectinload(Lead.scraped_data),
            selectinload(Lead.generated_site),
        )
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineSuccess:
    """Happy-path: scrape + generate completes without errors."""

    @pytest.mark.asyncio
    async def test_full_pipeline_creates_scraped_data_and_site(self, db: AsyncSession, lead_in_db: Lead):
        lead_id = lead_in_db.id

        fake_gen_result = MagicMock()
        fake_gen_result.site_schema = _minimal_site_schema()
        fake_gen_result.tokens_used = 100
        fake_gen_result.model = "test-model"
        fake_gen_result.cost_usd = 0.001

        with patch("app.scraper.pipeline.fetch_page", new_callable=AsyncMock) as mock_fetch, \
             patch("app.scraper.pipeline.extract_all", side_effect=_fake_extract_all), \
             patch("app.scraper.pipeline.download_and_store_images", new_callable=AsyncMock) as mock_dl, \
             patch("app.scraper.pipeline.capture_screenshot_bytes", new_callable=AsyncMock, return_value=[]), \
             patch("app.scraper.pipeline.analyze_screenshots", new_callable=AsyncMock, return_value=None), \
             patch("app.scraper.pipeline.generate_site", new_callable=AsyncMock, return_value=fake_gen_result), \
             patch("app.scraper.pipeline.cache", new_callable=AsyncMock):

            mock_fetch.return_value = (FAKE_HTML, "https://xnails.se/")
            # download_and_store_images returns (images, logo_url)
            mock_dl.return_value = (
                [{"url": "https://storage.test/photo.jpg", "alt": "Salon", "category": "general"}],
                None,
            )

            from app.scraper.pipeline import run_pipeline
            await run_pipeline(db, lead_id)
            await db.commit()

        lead = await _refetch_lead(db, lead_id)

        assert lead.status == LeadStatus.GENERATED
        assert lead.email == "hello@test.se"
        assert lead.phone == "+46701234567"
        assert lead.error_message is None

        # ScrapedData was created
        assert lead.scraped_data is not None
        assert lead.scraped_data.contact_info["emails"] == ["hello@test.se"]

        # GeneratedSite was created
        assert lead.generated_site is not None
        assert lead.generated_site.status == SiteStatus.DRAFT
        assert lead.generated_site.tokens_used == 100


class TestPipelineScrapeFailure:
    """Pipeline should mark lead as FAILED when scraping raises."""

    @pytest.mark.asyncio
    async def test_scrape_error_marks_lead_failed(self, db: AsyncSession, lead_in_db: Lead):
        lead_id = lead_in_db.id

        with patch("app.scraper.pipeline.fetch_page", new_callable=AsyncMock) as mock_fetch, \
             patch("app.scraper.pipeline.cache", new_callable=AsyncMock):

            mock_fetch.side_effect = Exception("Connection refused")

            from app.scraper.pipeline import run_pipeline
            await run_pipeline(db, lead_id)

        lead = await _refetch_lead(db, lead_id)

        assert lead.status == LeadStatus.FAILED
        assert "Connection refused" in lead.error_message


class TestPipelineGenerationFailure:
    """Pipeline should mark lead as FAILED when AI generation raises."""

    @pytest.mark.asyncio
    async def test_generation_error_marks_lead_failed(self, db: AsyncSession, lead_in_db: Lead):
        lead_id = lead_in_db.id

        with patch("app.scraper.pipeline.fetch_page", new_callable=AsyncMock) as mock_fetch, \
             patch("app.scraper.pipeline.extract_all", side_effect=_fake_extract_all), \
             patch("app.scraper.pipeline.download_and_store_images", new_callable=AsyncMock) as mock_dl, \
             patch("app.scraper.pipeline.capture_screenshot_bytes", new_callable=AsyncMock, return_value=[]), \
             patch("app.scraper.pipeline.analyze_screenshots", new_callable=AsyncMock, return_value=None), \
             patch("app.scraper.pipeline.generate_site", new_callable=AsyncMock) as mock_gen, \
             patch("app.scraper.pipeline.cache", new_callable=AsyncMock):

            mock_fetch.return_value = (FAKE_HTML, "https://xnails.se/")
            mock_dl.return_value = ([{"url": "https://storage.test/photo.jpg", "alt": "Salon", "category": "general"}], None)
            mock_gen.side_effect = Exception("API rate limit exceeded")

            from app.scraper.pipeline import run_pipeline
            await run_pipeline(db, lead_id)

        lead = await _refetch_lead(db, lead_id)

        assert lead.status == LeadStatus.FAILED
        assert "rate limit" in lead.error_message


class TestPipelineNoContactInfo:
    """Lead should still be scraped even without contact info."""

    @pytest.mark.asyncio
    async def test_no_contacts_still_generates(self, db: AsyncSession, lead_in_db: Lead):
        lead_id = lead_in_db.id

        def extract_no_contacts(html, base_url):
            data = _fake_extract_all(html, base_url)
            data["contact_info"]["emails"] = []
            data["contact_info"]["phones"] = []
            data["contact_info"]["address"] = None
            return data

        fake_gen_result = MagicMock()
        fake_gen_result.site_schema = _minimal_site_schema()
        fake_gen_result.tokens_used = 50
        fake_gen_result.model = "test-model"
        fake_gen_result.cost_usd = 0.0005

        with patch("app.scraper.pipeline.fetch_page", new_callable=AsyncMock) as mock_fetch, \
             patch("app.scraper.pipeline.extract_all", side_effect=extract_no_contacts), \
             patch("app.scraper.pipeline.download_and_store_images", new_callable=AsyncMock) as mock_dl, \
             patch("app.scraper.pipeline.capture_screenshot_bytes", new_callable=AsyncMock, return_value=[]), \
             patch("app.scraper.pipeline.analyze_screenshots", new_callable=AsyncMock, return_value=None), \
             patch("app.scraper.pipeline.generate_site", new_callable=AsyncMock, return_value=fake_gen_result), \
             patch("app.scraper.pipeline.cache", new_callable=AsyncMock):

            mock_fetch.return_value = (FAKE_HTML, "https://xnails.se/")
            mock_dl.return_value = ([{"url": "https://storage.test/photo.jpg", "alt": "Salon", "category": "general"}], None)

            from app.scraper.pipeline import run_pipeline
            await run_pipeline(db, lead_id)
            await db.commit()

        lead = await _refetch_lead(db, lead_id)

        assert lead.status == LeadStatus.GENERATED
        assert lead.email is None


class TestPipelineMissingLead:
    """Pipeline should handle missing lead gracefully."""

    @pytest.mark.asyncio
    async def test_nonexistent_lead_returns_without_error(self, db: AsyncSession):
        from app.scraper.pipeline import run_pipeline
        # Should not raise
        await run_pipeline(db, "nonexistent-id-12345")


class TestPipelineRedactsSecrets:
    """Error messages should not leak API keys."""

    @pytest.mark.asyncio
    async def test_api_key_redacted(self, db: AsyncSession, lead_in_db: Lead):
        lead_id = lead_in_db.id

        with patch("app.scraper.pipeline.fetch_page", new_callable=AsyncMock) as mock_fetch, \
             patch("app.scraper.pipeline.cache", new_callable=AsyncMock):

            mock_fetch.side_effect = Exception("Auth failed: sk-1234567890abcdef1234567890")

            from app.scraper.pipeline import run_pipeline
            await run_pipeline(db, lead_id)

        lead = await _refetch_lead(db, lead_id)

        assert lead.status == LeadStatus.FAILED
        assert "sk-" not in lead.error_message
        assert "[REDACTED]" in lead.error_message
