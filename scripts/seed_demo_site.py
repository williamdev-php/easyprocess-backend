"""Seed a demo site with the new flat schema format."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.auth.models import User  # noqa: F401 - needed for FK resolution
from app.sites.models import Lead, GeneratedSite, LeadStatus, SiteStatus
from app.sites.subdomain import generate_unique_subdomain

DEMO_SITE_DATA = {
    "meta": {
        "title": "Anderssons Bygg & Renovering AB",
        "description": "Professionella bygg- och renoveringstjänster i Göteborg. Nybyggnation, renovering, badrumsrenovering och tillbyggnader med 25 års erfarenhet.",
        "keywords": ["byggfirma göteborg", "renovering", "badrumsrenovering", "nybyggnation", "tillbyggnad"],
        "language": "sv",
    },
    "theme": "modern",
    "branding": {
        "logo_url": None,
        "colors": {
            "primary": "#1e3a5f",
            "secondary": "#2d5f8a",
            "accent": "#e8a838",
            "background": "#ffffff",
            "text": "#1a1a2e",
        },
        "fonts": {"heading": "Inter", "body": "Inter"},
    },
    "business": {
        "name": "Anderssons Bygg & Renovering AB",
        "tagline": "Bygger dina drömmar sedan 1999",
        "email": "info@anderssonsbygg.se",
        "phone": "031-123 45 67",
        "address": "Byggvägen 12, 412 58 Göteborg",
        "org_number": "556789-0123",
        "social_links": {
            "facebook": "https://facebook.com",
            "instagram": "https://instagram.com",
            "linkedin": "https://linkedin.com",
        },
    },
    "hero": {
        "headline": "Bygger dina drömmar sedan 1999",
        "subtitle": "Från idé till färdigt resultat — vi är Göteborgs mest pålitliga byggfirma med över 25 års erfarenhet av nybyggnation, renovering och tillbyggnader.",
        "cta": {"label": "Begär kostnadsfri offert", "href": "#contact"},
        "background_image": None,
    },
    "about": {
        "title": "Om Anderssons Bygg",
        "text": "Med över 25 års erfarenhet i byggbranschen har Anderssons Bygg & Renovering AB byggt upp ett starkt rykte i Göteborgsregionen. Vi är ett familjeägt företag som värdesätter kvalitet, ärlighet och noggrannhet i varje projekt.\n\nVårt team av erfarna hantverkare levererar alltid resultat som överträffar förväntningarna. Vi är certifierade enligt BKR och har alla nödvändiga försäkringar för att ge dig trygghet genom hela byggprocessen.\n\nOavsett om du planerar en totalrenovering av köket, ett nytt badrum eller en helt ny tillbyggnad — vi finns här för att guida dig hela vägen.",
        "image": None,
        "highlights": [
            {"label": "Års erfarenhet", "value": "25+"},
            {"label": "Nöjda kunder", "value": "500+"},
            {"label": "Slutförda projekt", "value": "1 200+"},
            {"label": "Års garanti", "value": "10"},
        ],
    },
    "services": {
        "title": "Våra tjänster",
        "subtitle": "Vi erbjuder ett brett utbud av bygg- och renoveringstjänster för både privatpersoner och företag.",
        "items": [
            {
                "title": "Nybyggnation",
                "description": "Kompletta nybyggnadsprojekt från grund till tak. Vi hanterar allt från planering och bygglov till färdigställande.",
            },
            {
                "title": "Totalrenovering",
                "description": "Total renovering av kök, badrum och hela bostäder. Vi moderniserar ditt hem med hög kvalitet och finish.",
            },
            {
                "title": "Tillbyggnad",
                "description": "Behöver du mer utrymme? Vi bygger till extra rum, garage, uterum eller balkong som smälter in med befintlig arkitektur.",
            },
            {
                "title": "Badrumsrenovering",
                "description": "Specialister på badrumsrenovering med tätskikt, kakling och VVS-arbeten. Alltid med 10 års garanti.",
            },
            {
                "title": "Fasadrenovering",
                "description": "Ge ditt hus nytt liv med fasadrenovering. Vi arbetar med puts, tegel, trä och moderna fasadmaterial.",
            },
            {
                "title": "Projektledning",
                "description": "Behöver du hjälp med hela projektet? Vi erbjuder komplett projektledning från start till mål.",
            },
        ],
    },
    "gallery": {
        "title": "Våra projekt",
        "images": [
            {"url": "https://images.unsplash.com/photo-1503387762-592deb58ef4e?w=800", "alt": "Modernt kök efter renovering"},
            {"url": "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=800", "alt": "Nybyggnation villa"},
            {"url": "https://images.unsplash.com/photo-1552321554-5fefe8c9ef14?w=800", "alt": "Badrumsrenovering med kakel"},
            {"url": "https://images.unsplash.com/photo-1513694203232-719a280e022f?w=800", "alt": "Renoverat vardagsrum"},
            {"url": "https://images.unsplash.com/photo-1581858726788-75bc0f6a952d?w=800", "alt": "Fasadrenovering"},
            {"url": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=800", "alt": "Färdigställd tillbyggnad"},
        ],
    },
    "testimonials": {
        "title": "Vad våra kunder säger",
        "items": [
            {
                "text": "Anderssons Bygg renoverade vårt kök och badrum. Resultatet blev fantastiskt och de höll både tidplan och budget. Kan varmt rekommendera!",
                "author": "Maria Lindqvist",
                "role": "Villaägare, Mölndal",
            },
            {
                "text": "Professionellt bemötande från första kontakt till slutbesiktning. De löste alla utmaningar som dök upp under bygget på ett snyggt sätt.",
                "author": "Erik Johansson",
                "role": "BRF Seglet",
            },
            {
                "text": "Vi anlitade Anderssons för en tillbyggnad. Hantverkarna var skickliga, punktliga och städade alltid efter sig. Toppbetyg!",
                "author": "Anna & Per Svensson",
                "role": "Villaägare, Kungsbacka",
            },
            {
                "text": "Tredje gången vi anlitar dem. Alltid samma höga kvalitet och trevligt bemötande. De är vår go-to byggfirma.",
                "author": "Lars Bergström",
                "role": "Fastighetsägare, Göteborg",
            },
        ],
    },
    "cta": {
        "title": "Redo att starta ditt projekt?",
        "text": "Kontakta oss idag för en kostnadsfri konsultation och offert. Vi hjälper dig att förverkliga dina byggdrömmar.",
        "button": {"label": "Kontakta oss nu", "href": "#contact"},
    },
    "contact": {
        "title": "Kontakta oss",
        "text": "Hör av dig så återkommer vi inom 24 timmar med en kostnadsfri offert.",
    },
    "seo": {
        "structured_data": {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": "Anderssons Bygg & Renovering AB",
            "description": "Professionella bygg- och renoveringstjänster i Göteborg med 25 års erfarenhet.",
            "telephone": "031-123 45 67",
            "email": "info@anderssonsbygg.se",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Byggvägen 12",
                "postalCode": "412 58",
                "addressLocality": "Göteborg",
                "addressCountry": "SE",
            },
            "areaServed": "Göteborg",
            "priceRange": "$$",
        },
        "robots": "index, follow",
    },
}


async def seed():
    async with async_session() as session:
        lead = Lead(
            business_name="Anderssons Bygg & Renovering AB",
            website_url="https://anderssonsbygg.se",
            email="info@anderssonsbygg.se",
            phone="031-123 45 67",
            address="Byggvägen 12, 412 58 Göteborg",
            industry="bygg",
            source="seed",
            status=LeadStatus.GENERATED,
        )
        session.add(lead)
        await session.flush()

        subdomain = await generate_unique_subdomain(
            session, lead.business_name, lead.website_url
        )
        site = GeneratedSite(
            lead_id=lead.id,
            site_data=DEMO_SITE_DATA,
            template="modern",
            status=SiteStatus.PUBLISHED,
            subdomain=subdomain,
        )
        session.add(site)
        await session.flush()
        await session.commit()

        print(f"\nDemo site seeded!")
        print(f"  Lead ID:    {lead.id}")
        print(f"  Site ID:    {site.id}")
        print(f"  Subdomain:  {subdomain}")
        print(f"\nRoutes:")
        print(f"  Home:     http://{subdomain}.localhost:3001")
        print(f"  About:    http://{subdomain}.localhost:3001/about")
        print(f"  Services: http://{subdomain}.localhost:3001/services")
        print(f"  Gallery:  http://{subdomain}.localhost:3001/gallery")
        print(f"  Contact:  http://{subdomain}.localhost:3001/contact")


if __name__ == "__main__":
    asyncio.run(seed())
