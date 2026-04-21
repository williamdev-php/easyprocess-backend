"""Seed initial industry categories with prompt hints for AI generation."""

import asyncio
import sys
import os
import re
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.sites.models import Industry

INDUSTRIES = [
    {
        "name": "Elektriker",
        "description": "Elektriska installationer och reparationer",
        "prompt_hint": (
            "Fokusera på certifiering, säkerhet och auktorisation. Lyft fram akut-jour och snabb service. "
            "Använd CTA:er som 'Ring oss nu' eller 'Boka elektriker'. Visa tjänster tydligt med priser om möjligt. "
            "Inkludera processektion som visar hur en beställning fungerar. Betona garantier och försäkringar."
        ),
        "default_sections": [
            "hero", "about", "services", "features", "process",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Snickare",
        "description": "Snickeri, möbelbygge och träarbeten",
        "prompt_hint": (
            "Framhäv hantverksskicklighet, kvalitet och tradition. Visa upp projekt i galleri med före/efter-bilder. "
            "Betona erfarenhet och certifieringar. CTA:er som 'Begär offert' eller 'Se våra projekt'. "
            "Inkludera processektion som visar arbetsflödet från konsultation till färdigt resultat."
        ),
        "default_sections": [
            "hero", "about", "services", "gallery", "process",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "VVS",
        "description": "Värme, ventilation och sanitet",
        "prompt_hint": (
            "Snabb service och pålitlighet. Jour-CTA som 'Ring VVS-jour'. Visa tjänster tydligt — "
            "rörmokare, värmepumpar, badrumsrenovering etc. Processektion för hur en reparation går till. "
            "Betona garantier, certifieringar och att ni är auktoriserade."
        ),
        "default_sections": [
            "hero", "about", "services", "features", "process",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Hovslagare",
        "description": "Hovbeslag och hästhälsa",
        "prompt_hint": (
            "Professionell och jordnära ton. Framhäv erfarenhet med hästar och certifieringar. "
            "Visa tjänster som hovbeslag, hovvård, akutbesök. Inkludera galleri med bilder. "
            "CTA:er som 'Boka tid' eller 'Kontakta oss'. Betona mobilitet och flexibilitet."
        ),
        "default_sections": [
            "hero", "about", "services", "gallery",
            "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Restaurang",
        "description": "Restauranger, caféer och matställen",
        "prompt_hint": (
            "Framhäv atmosfär, meny och upplevelse. Galleri med matbilder tidigt på sidan. "
            "Inkludera öppettider i about-sektionen. CTA:er som 'Boka bord' eller 'Se menyn'. "
            "Visa omdömen från gäster. Varm och inbjudande ton. Kort och slagkraftig text."
        ),
        "default_sections": [
            "hero", "about", "gallery", "services",
            "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Frisör",
        "description": "Frisörsalonger och hårvård",
        "prompt_hint": (
            "Lyxig, modern känsla. Visa upp tjänster med prisuppgifter om möjligt. "
            "CTA: 'Boka tid'. Galleri med frisyrer och före/efter-bilder. "
            "Framhäv produkter och behandlingar. Inkludera teamsektion med stylister."
        ),
        "default_sections": [
            "hero", "about", "services", "gallery", "team",
            "testimonials", "cta", "contact",
        ],
    },
    {
        "name": "Tandvård",
        "description": "Tandläkare och tandvårdskliniker",
        "prompt_hint": (
            "Professionellt och tryggt. Framhäv behandlingar, modern teknik och patientsäkerhet. "
            "Teamsektion med tandläkare och tandhygienister är viktigt. CTA: 'Boka tid'. "
            "Processektion för första besöket. FAQ om vanliga behandlingar och priser."
        ),
        "default_sections": [
            "hero", "about", "services", "team", "process",
            "features", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Redovisning",
        "description": "Redovisning, bokföring och ekonomitjänster",
        "prompt_hint": (
            "Seriöst och kompetent. Framhäv tjänster som bokföring, deklaration, rådgivning. "
            "Betona erfarenhet, kundrelationer och pålitlighet. Processektion för hur samarbetet fungerar. "
            "CTA: 'Boka konsultation'. Stats med nöjda kunder och års erfarenhet."
        ),
        "default_sections": [
            "hero", "about", "services", "features", "process",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Städ",
        "description": "Städtjänster för hem och företag",
        "prompt_hint": (
            "Pålitlighet, flexibilitet och kvalitet. Visa tjänster tydligt — hemstäd, kontorsstäd, "
            "flyttstäd, fönsterputs etc. Processektion för hur bokning fungerar. "
            "CTA: 'Boka städning' eller 'Begär offert'. Betona kundnöjdhet och miljövänliga produkter."
        ),
        "default_sections": [
            "hero", "about", "services", "process", "features",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Bygg",
        "description": "Byggföretag och entreprenad",
        "prompt_hint": (
            "Fokusera på pålitlighet, erfarenhet och kvalitet. Visa upp projekt i galleri. "
            "CTA: 'Begär offert'. Lyft fram certifieringar och garantier. "
            "Processektion för hur ett byggprojekt går till. Stats med genomförda projekt."
        ),
        "default_sections": [
            "hero", "about", "services", "gallery", "process",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Skönhet",
        "description": "Skönhetssalonger och hudvård",
        "prompt_hint": (
            "Lyxig och elegant känsla. Visa produkter och behandlingar i galleri. "
            "CTA: 'Boka behandling'. Teamsektion med terapeuter. "
            "Framhäv märken och produktlinjer. Varm och välkomnande ton."
        ),
        "default_sections": [
            "hero", "about", "services", "gallery", "team",
            "testimonials", "cta", "contact",
        ],
    },
    {
        "name": "Fitness",
        "description": "Gym, träning och hälsa",
        "prompt_hint": (
            "Energisk och motiverande ton. Visa träningsformer och schema. "
            "CTA: 'Boka provpass' eller 'Kom igång idag'. Galleri med träningsmiljö. "
            "Teamsektion med tränare. Stats med antal medlemmar. Framhäv resultat."
        ),
        "default_sections": [
            "hero", "about", "services", "gallery", "team",
            "stats", "testimonials", "cta", "contact",
        ],
    },
    {
        "name": "Juridik",
        "description": "Advokatbyråer och juridisk rådgivning",
        "prompt_hint": (
            "Professionellt och förtroendeingivande. Framhäv expertområden och erfarenhet. "
            "CTA: 'Boka konsultation'. Teamsektion med jurister och specialisering. "
            "Processektion för hur ett ärende hanteras. FAQ om juridiska frågor."
        ),
        "default_sections": [
            "hero", "about", "services", "team", "process",
            "features", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "IT",
        "description": "IT-konsulter, mjukvaruutveckling och teknik",
        "prompt_hint": (
            "Modern och teknisk känsla. Visa tjänster, teknikstack och case studies. "
            "CTA: 'Boka demo' eller 'Kontakta oss'. Logo cloud med teknologier/partners. "
            "Processektion för utvecklingsmetodik. Stats med levererade projekt."
        ),
        "default_sections": [
            "hero", "about", "services", "features", "process",
            "logo_cloud", "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Målare",
        "description": "Måleritjänster för inomhus och utomhus",
        "prompt_hint": (
            "Framhäv kvalitet, noggrannhet och erfarenhet. Galleri med före/efter-bilder. "
            "CTA: 'Begär offert'. Processektion för hur ett måleriuppdrag går till. "
            "Betona ROT-avdrag och garantier. Visa tjänster tydligt."
        ),
        "default_sections": [
            "hero", "about", "services", "gallery", "process",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Takläggare",
        "description": "Takläggning och takrenovering",
        "prompt_hint": (
            "Betona säkerhet, certifiering och garanti. Visa tjänster som takbyte, takrenovering, "
            "takinspektion. Galleri med genomförda projekt. CTA: 'Begär offert'. "
            "Processektion för arbetsgång. Stats med genomförda tak."
        ),
        "default_sections": [
            "hero", "about", "services", "gallery", "process",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Fastighetsmäklare",
        "description": "Fastighetsförmedling och bostadsaffärer",
        "prompt_hint": (
            "Professionellt och personligt. Framhäv lokal expertis och marknadskunskap. "
            "CTA: 'Boka värdering' eller 'Kontakta mäklare'. Teamsektion med mäklare. "
            "Processektion för köp/sälj-processen. Stats med sålda objekt."
        ),
        "default_sections": [
            "hero", "about", "services", "team", "process",
            "stats", "testimonials", "faq", "cta", "contact",
        ],
    },
    {
        "name": "Fotograf",
        "description": "Fotografer och bildtjänster",
        "prompt_hint": (
            "Visuellt fokus — galleri är centralt och bör komma tidigt. "
            "Visa upp olika kategorier: bröllop, porträtt, företag etc. "
            "CTA: 'Boka fotografering'. Minimalistisk och elegant ton. Låt bilderna tala."
        ),
        "default_sections": [
            "hero", "gallery", "about", "services",
            "testimonials", "cta", "contact",
        ],
    },
]


async def main():
    async with async_session() as session:
        from sqlalchemy import select

        for ind in INDUSTRIES:
            name = ind["name"]
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

            result = await session.execute(
                select(Industry).where(Industry.slug == slug)
            )
            existing = result.scalar_one_or_none()
            if existing:
                # Update prompt_hint and default_sections if they changed
                changed = False
                if existing.prompt_hint != ind.get("prompt_hint"):
                    existing.prompt_hint = ind.get("prompt_hint")
                    changed = True
                if existing.default_sections != ind.get("default_sections"):
                    existing.default_sections = ind.get("default_sections")
                    changed = True
                if existing.description != ind.get("description"):
                    existing.description = ind.get("description")
                    changed = True
                if changed:
                    print(f"  [update] {name}")
                else:
                    print(f"  [skip]   {name} (unchanged)")
                continue

            industry = Industry(
                id=str(uuid.uuid4()),
                name=name,
                slug=slug,
                description=ind.get("description"),
                prompt_hint=ind.get("prompt_hint"),
                default_sections=ind.get("default_sections"),
            )
            session.add(industry)
            print(f"  [add]    {name} ({slug})")

        await session.commit()
        print("\nDone! Industries seeded.")


if __name__ == "__main__":
    asyncio.run(main())
