"""Seed initial industry categories."""

import asyncio
import sys
import os
import re
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.sites.models import Industry

INDUSTRIES = [
    {"name": "Elektriker", "description": "Elektriska installationer och reparationer"},
    {"name": "Snickare", "description": "Snickeri, möbelbygge och träarbeten"},
    {"name": "VVS", "description": "Värme, ventilation och sanitet"},
    {"name": "Hovslagare", "description": "Hovbeslag och hästhälsa"},
]


async def main():
    async with async_session() as session:
        for ind in INDUSTRIES:
            name = ind["name"]
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

            # Check if exists
            from sqlalchemy import select
            result = await session.execute(
                select(Industry).where(Industry.slug == slug)
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"  [skip] {name} already exists")
                continue

            industry = Industry(
                id=str(uuid.uuid4()),
                name=name,
                slug=slug,
                description=ind["description"],
            )
            session.add(industry)
            print(f"  [add]  {name} ({slug})")

        await session.commit()
        print("\nDone! Industries seeded.")


if __name__ == "__main__":
    asyncio.run(main())
