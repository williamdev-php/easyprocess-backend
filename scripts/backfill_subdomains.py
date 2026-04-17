"""
Backfill subdomains for existing GeneratedSite rows that have subdomain=NULL.

Generates a slug from the lead's business_name or website_url, ensures
uniqueness, and saves it.

Usage:
    cd backend
    python scripts/backfill_subdomains.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.auth.models import User  # noqa: F401 - needed for FK resolution
from app.sites.models import GeneratedSite
from app.sites.subdomain import generate_unique_subdomain


async def backfill():
    async with async_session() as session:
        result = await session.execute(
            select(GeneratedSite)
            .where(GeneratedSite.subdomain.is_(None))
            .options(selectinload(GeneratedSite.lead))
        )
        sites = result.scalars().all()

        if not sites:
            print("All sites already have subdomains. Nothing to do.")
            return

        print(f"Found {len(sites)} sites without subdomain.\n")

        for site in sites:
            lead = site.lead
            business_name = lead.business_name if lead else None
            website_url = lead.website_url if lead else None

            subdomain = await generate_unique_subdomain(
                session, business_name, website_url, exclude_site_id=site.id
            )
            site.subdomain = subdomain
            print(f"  {site.id[:8]}... → {subdomain}  (from: {business_name or website_url or '?'})")

        await session.commit()
        print(f"\nDone. Updated {len(sites)} sites.")


if __name__ == "__main__":
    asyncio.run(backfill())
