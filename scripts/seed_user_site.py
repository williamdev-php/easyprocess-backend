"""Seed a site for a specific user account.

Usage:
    python scripts/seed_user_site.py

Links an xnails.se nail salon site to the user william.soderstrom30@gmail.com.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.auth.models import User
from app.sites.models import Lead, GeneratedSite, LeadStatus, SiteStatus
from sqlalchemy import select

USER_EMAIL = "william.soderstrom30@gmail.com"

XNAILS_SITE_DATA = {
    "meta": {
        "title": "XNails — Professionell Nagelvård i Stockholm",
        "description": "XNails erbjuder professionell nagelvård, gelélack, nagelförlängning och manikyr i Stockholm. Boka din tid idag!",
        "keywords": ["nagelsalong stockholm", "gelélack", "nagelförlängning", "manikyr", "pedikyr", "xnails"],
        "language": "sv",
    },
    "theme": "elegant",
    "branding": {
        "logo_url": None,
        "colors": {
            "primary": "#d4a0a0",
            "secondary": "#8b5e5e",
            "accent": "#f0c987",
            "background": "#fffaf7",
            "text": "#2d2424",
        },
        "fonts": {"heading": "Inter", "body": "Inter"},
    },
    "business": {
        "name": "XNails",
        "tagline": "Din nagelsalong i Stockholm",
        "email": "info@xnails.se",
        "phone": "08-123 45 67",
        "address": "Storgatan 15, 114 51 Stockholm",
        "org_number": "559123-4567",
        "social_links": {
            "instagram": "https://instagram.com/xnails.se",
            "facebook": "https://facebook.com/xnails.se",
        },
    },
    "hero": {
        "headline": "Vackra naglar, varje gång",
        "subtitle": "Välkommen till XNails — Stockholms mest omtyckta nagelsalong. Vi erbjuder professionell nagelvård med fokus på kvalitet, hygien och din trivsel.",
        "cta": {"label": "Boka tid nu", "href": "#contact"},
        "background_image": None,
    },
    "about": {
        "title": "Om XNails",
        "text": "XNails grundades 2019 med visionen att skapa en nagelsalong där kvalitet och kundupplevelse alltid kommer först. Vårt team av certifierade nagelterapeuter har lång erfarenhet och utbildar sig kontinuerligt i de senaste teknikerna och trenderna.\n\nVi använder enbart premiumprodukter som är skonsamma mot dina naglar och hud. Vår salong är designad för att du ska kunna koppla av och njuta av din behandling i en lugn och hygienisk miljö.\n\nOavsett om du vill ha en klassisk manikyr, trendig nail art eller hållbar nagelförlängning — vi hjälper dig att hitta din stil.",
        "image": None,
        "highlights": [
            {"label": "Nöjda kunder", "value": "2 000+"},
            {"label": "Års erfarenhet", "value": "5+"},
            {"label": "Certifierade terapeuter", "value": "6"},
            {"label": "Betyg på Google", "value": "4.9"},
        ],
    },
    "features": {
        "title": "Varför välja XNails?",
        "subtitle": "Vi sticker ut från mängden.",
        "items": [
            {
                "title": "Premiumprodukter",
                "description": "Vi använder enbart högkvalitativa, veganska och djurförsöksfria produkter från ledande varumärken.",
                "icon": "💅",
            },
            {
                "title": "Hygien i fokus",
                "description": "Alla verktyg steriliseras mellan varje kund. Din hälsa och säkerhet är vår högsta prioritet.",
                "icon": "✨",
            },
            {
                "title": "Trendmedvetna",
                "description": "Vårt team håller sig uppdaterade med de senaste nageltrenderna och teknikerna från hela världen.",
                "icon": "🎨",
            },
            {
                "title": "Personlig service",
                "description": "Vi tar oss tid att lyssna på dina önskemål och ger dig skräddarsydda rekommendationer.",
                "icon": "💝",
            },
        ],
    },
    "services": {
        "title": "Våra behandlingar",
        "subtitle": "Utforska vårt utbud av professionella nagelbehandlingar.",
        "items": [
            {
                "title": "Gelélack",
                "description": "Långvarig, högglansig gelélack som håller i upp till 3 veckor utan att flagna. Stort urval av färger och effekter.",
            },
            {
                "title": "Nagelförlängning",
                "description": "Förlängning med gel eller akryl för naturligt vackra, starka naglar. Vi anpassar form och längd efter dina önskemål.",
            },
            {
                "title": "Klassisk manikyr",
                "description": "Komplett nagelvård med filning, kutikelvård, handmassage och lack. Perfekt för att hålla naglarna i toppskick.",
            },
            {
                "title": "Nail Art & Design",
                "description": "Unika nageldesigner — från diskret French till avancerad nail art med glitter, stenar och handmålade motiv.",
            },
            {
                "title": "Pedikyr",
                "description": "Lyxig fotvård med fotbad, peeling, nagelvård och massage. Välj mellan klassisk eller med gelélack.",
            },
            {
                "title": "Nagelreparation",
                "description": "Snabb och effektiv reparation av trasiga eller skadade naglar. Vi återställer och förstärker dina naglar.",
            },
        ],
    },
    "stats": {
        "title": "",
        "items": [
            {"value": "2 000+", "label": "Nöjda kunder"},
            {"value": "15 000+", "label": "Behandlingar utförda"},
            {"value": "4.9/5", "label": "Snittbetyg"},
            {"value": "50+", "label": "Färger i sortimentet"},
        ],
    },
    "gallery": {
        "title": "Inspiration",
        "subtitle": "Se några av våra senaste arbeten.",
        "images": [
            {"url": "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=800", "alt": "Rosa gelénaglar med glitter"},
            {"url": "https://images.unsplash.com/photo-1632345031435-8727f6897d53?w=800", "alt": "Elegant French manikyr"},
            {"url": "https://images.unsplash.com/photo-1519014816548-bf5fe059798b?w=800", "alt": "Nail art med blommönster"},
            {"url": "https://images.unsplash.com/photo-1607779097040-26e80aa78e66?w=800", "alt": "Röda naglar med design"},
            {"url": "https://images.unsplash.com/photo-1577290974570-0d66d1a1b082?w=800", "alt": "Naturlig nagelvård"},
            {"url": "https://images.unsplash.com/photo-1571290274554-6a2eaa74d75b?w=800", "alt": "Nagelförlängning resultat"},
        ],
    },
    "testimonials": {
        "title": "Vad våra kunder säger",
        "subtitle": "",
        "items": [
            {
                "text": "Bästa nagelsalongen jag besökt! Mina gelénaglar håller alltid perfekt i tre veckor. Personalen är fantastisk och salongen är jättefin.",
                "author": "Emma Larsson",
                "role": "Stamkund sedan 2020",
            },
            {
                "text": "Jag gick dit för nagelförlängning inför bröllopet och resultatet blev precis som jag drömt om. Tack XNails!",
                "author": "Sofia Nilsson",
                "role": "Brudkund",
            },
            {
                "text": "Alltid välkomnande, professionellt och hygieniskt. Mina naglar har aldrig sett så bra ut. Rekommenderar till alla!",
                "author": "Lisa Eriksson",
                "role": "Stamkund",
            },
            {
                "text": "Fantastisk nail art! De kunde göra precis den design jag ville ha. Värt varje krona.",
                "author": "Amanda Ström",
                "role": "Nail art-kund",
            },
        ],
    },
    "faq": {
        "title": "Vanliga frågor",
        "subtitle": "",
        "items": [
            {
                "question": "Hur lång tid tar en gelélackning?",
                "answer": "En komplett gelélackning tar ca 45-60 minuter beroende på design och antal lager.",
            },
            {
                "question": "Hur länge håller gelélacket?",
                "answer": "Med rätt eftervård håller gelélacket vanligtvis 2-3 veckor utan att flagna eller tappa glans.",
            },
            {
                "question": "Behöver jag boka tid i förväg?",
                "answer": "Ja, vi rekommenderar att du bokar tid i förväg för att garantera din plats. Du kan boka via telefon eller Instagram.",
            },
            {
                "question": "Är produkterna veganska?",
                "answer": "Ja, vi använder enbart veganska och djurförsöksfria produkter i alla våra behandlingar.",
            },
            {
                "question": "Kan jag ta bort gelélack hos er?",
                "answer": "Absolut! Vi erbjuder skonsam borttagning av gelélack för 150 kr, eller gratis om du bokar en ny lackning.",
            },
        ],
    },
    "process": {
        "title": "Så fungerar det",
        "subtitle": "Enkel bokning i tre steg.",
        "steps": [
            {
                "title": "Boka online",
                "description": "Välj behandling och tid som passar dig via vår bokningssida eller ring oss direkt.",
                "step_number": 1,
            },
            {
                "title": "Besök salongen",
                "description": "Kom till salongen och slappna av. Vi tar hand om resten och skapar dina drömmaglar.",
                "step_number": 2,
            },
            {
                "title": "Njut av resultatet",
                "description": "Gå härifrån med perfekta naglar och boka gärna in ditt nästa besök direkt!",
                "step_number": 3,
            },
        ],
    },
    "cta": {
        "title": "Redo för nya naglar?",
        "text": "Boka din tid idag och upplev skillnaden med professionell nagelvård hos XNails.",
        "button": {"label": "Boka din tid", "href": "#contact"},
    },
    "contact": {
        "title": "Kontakta oss",
        "text": "Har du frågor eller vill boka en tid? Kontakta oss via telefon, email eller besök oss i salongen.",
    },
    "seo": {
        "structured_data": {
            "@context": "https://schema.org",
            "@type": "BeautySalon",
            "name": "XNails",
            "description": "Professionell nagelvård i Stockholm — gelélack, nagelförlängning, manikyr och pedikyr.",
            "telephone": "08-123 45 67",
            "email": "info@xnails.se",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Storgatan 15",
                "postalCode": "114 51",
                "addressLocality": "Stockholm",
                "addressCountry": "SE",
            },
            "priceRange": "$$",
        },
        "robots": "index, follow",
    },
}


async def seed():
    async with async_session() as session:
        # Find the user
        result = await session.execute(
            select(User).where(User.email == USER_EMAIL)
        )
        user = result.scalar_one_or_none()
        if not user:
            print(f"ERROR: User {USER_EMAIL} not found. Register first.")
            return

        print(f"Found user: {user.full_name} ({user.email}) id={user.id}")

        # Create xnails.se lead linked to user
        lead = Lead(
            business_name="XNails",
            website_url="https://xnails.se",
            email="info@xnails.se",
            phone="08-123 45 67",
            address="Storgatan 15, 114 51 Stockholm",
            industry="skönhet",
            source="seed",
            status=LeadStatus.GENERATED,
            created_by=str(user.id),
        )
        session.add(lead)
        await session.flush()

        site = GeneratedSite(
            lead_id=lead.id,
            site_data=XNAILS_SITE_DATA,
            template="elegant",
            status=SiteStatus.PUBLISHED,
            subdomain="xnails",
        )
        session.add(site)
        await session.flush()
        await session.commit()

        print(f"\nXNails site seeded!")
        print(f"  Lead ID:  {lead.id}")
        print(f"  Site ID:  {site.id}")
        print(f"  Owner:    {USER_EMAIL}")
        print(f"\nRoutes:")
        print(f"  Viewer:   http://localhost:3001/{site.id}")
        print(f"  Editor:   http://localhost:3000/sv/dashboard/pages/{site.id}")


if __name__ == "__main__":
    asyncio.run(seed())
