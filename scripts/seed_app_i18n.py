"""
Seed script to update app descriptions with i18n translations.

Run: python -m scripts.seed_app_i18n
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database import get_db_session
from app.apps.models import App

APP_TRANSLATIONS = {
    "blog": {
        "name": "Blog by Qvicko",
        "description": {
            "en": "Create and manage blog posts for your website. Publish articles, organize with categories, and boost your online visibility.",
            "sv": "Skapa och hantera blogginlägg för din webbplats. Publicera artiklar, organisera med kategorier och öka din synlighet online.",
        },
        "long_description": {
            "en": "A full-featured blogging platform built into your Qvicko site. Write and publish articles with a rich text editor, organize content with categories, and drive organic SEO traffic to your website. Perfect for establishing authority in your niche.",
            "sv": "En komplett bloggplattform inbyggd i din Qvicko-sida. Skriv och publicera artiklar med en rik textredigerare, organisera innehåll med kategorier och driv organisk SEO-trafik till din webbplats. Perfekt för att etablera auktoritet inom din nisch.",
        },
    },
    "chat": {
        "description": {
            "en": "Add a chat widget to your website. Visitors can send messages directly and you reply from your dashboard.",
            "sv": "Lägg till en chattbubbla på din webbplats. Besökare kan skicka meddelanden direkt och du svarar från din dashboard.",
        },
        "long_description": {
            "en": "Engage with your website visitors in real time. The chat widget lets visitors send messages directly from your site, and you can reply from your Qvicko dashboard. Get email notifications for new conversations and never miss a lead.",
            "sv": "Kommunicera med dina webbplatsbesökare i realtid. Chattwidgeten låter besökare skicka meddelanden direkt från din sida, och du kan svara från din Qvicko-dashboard. Få e-postnotifikationer för nya konversationer och missa aldrig en lead.",
        },
    },
}


async def main() -> None:
    async with get_db_session() as db:
        for slug, translations in APP_TRANSLATIONS.items():
            result = await db.execute(select(App).where(App.slug == slug))
            app = result.scalar_one_or_none()
            if app is None:
                print(f"  App '{slug}' not found, skipping")
                continue

            if "name" in translations:
                app.name = translations["name"]
            app.description = translations["description"]
            app.long_description = translations.get("long_description")
            print(f"  Updated '{slug}' with i18n descriptions")

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
