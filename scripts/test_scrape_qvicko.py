"""
Test script: Scrape qvicko.com and assign the generated site to a user.

Runs the full pipeline:
  1. Fetch + extract content from qvicko.com
  2. Download images to Supabase storage
  3. Capture screenshots + vision analysis
  4. AI site generation
  5. Save to DB, assigned to william.soderstrom30@gmail.com

Usage:
    cd backend
    python scripts/test_scrape_qvicko.py
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.auth.models import User
from app.sites.models import Lead, LeadStatus
from app.scraper.pipeline import run_pipeline
from sqlalchemy import select

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_scrape")

TARGET_URL = "https://qvicko.com"
USER_EMAIL = "william.soderstrom30@gmail.com"


async def main():
    async with async_session() as db:
        # 1. Find user
        result = await db.execute(select(User).where(User.email == USER_EMAIL))
        user = result.scalar_one_or_none()
        if not user:
            logger.error("User %s not found. Register first.", USER_EMAIL)
            return

        logger.info("Found user: %s (id=%s)", user.email, user.id)

        # 2. Create lead linked to user
        lead = Lead(
            business_name="Qvicko",
            website_url=TARGET_URL,
            industry="it",
            source="test_script",
            status=LeadStatus.NEW,
            created_by=str(user.id),
        )
        db.add(lead)
        await db.flush()
        logger.info("Created lead %s for %s", lead.id, TARGET_URL)

        # 3. Run full pipeline (scrape → vision → AI generate → save)
        logger.info("Starting pipeline — this may take 2-5 minutes...")
        await run_pipeline(db, str(lead.id))

        # 4. Refresh and report results
        await db.refresh(lead)
        logger.info("Pipeline finished. Lead status: %s", lead.status.value)

        if lead.status == LeadStatus.FAILED:
            logger.error("Pipeline failed: %s", lead.error_message)
            return

        # Fetch the generated site
        from app.sites.models import GeneratedSite
        from sqlalchemy.orm import selectinload

        result = await db.execute(
            select(Lead)
            .where(Lead.id == lead.id)
            .options(selectinload(Lead.generated_site))
        )
        lead = result.scalar_one()

        site = lead.generated_site
        if not site:
            logger.error("No generated site found after pipeline.")
            return

        logger.info("="*60)
        logger.info("SUCCESS!")
        logger.info("  Lead ID:    %s", lead.id)
        logger.info("  Site ID:    %s", site.id)
        logger.info("  Subdomain:  %s", site.subdomain)
        logger.info("  Status:     %s", site.status.value)
        logger.info("  AI Model:   %s", site.ai_model)
        logger.info("  Tokens:     %s", site.tokens_used)
        logger.info("  Cost:       $%.4f", site.generation_cost_usd or 0)
        logger.info("  Owner:      %s", USER_EMAIL)
        logger.info("")
        logger.info("  Preview:    http://localhost:3001/%s", site.id)
        logger.info("="*60)


if __name__ == "__main__":
    asyncio.run(main())
