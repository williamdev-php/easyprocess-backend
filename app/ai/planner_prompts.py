"""
Prompt templates for the AI site planner.

The planner runs BEFORE the main generator to create a SiteBlueprint —
deciding which sections to include, the tone, target audience, and per-section
tips. This lets the generator focus on content rather than structural decisions.
"""

from __future__ import annotations


def _sanitize_for_prompt(text: str, max_length: int = 500) -> str:
    """Sanitize user input before inserting into LLM prompts."""
    if not text:
        return ""
    text = text.replace("```", "")
    text = text.replace("SYSTEM:", "")
    text = text.replace("ASSISTANT:", "")
    text = text.replace("USER:", "")
    text = text.replace("HUMAN:", "")
    return text[:max_length].strip()


PLANNER_SYSTEM_PROMPT = """Du är en expert webbdesign-planerare som planerar strukturen för moderna, professionella hemsidor.

Din uppgift är att analysera ett företag/syfte och skapa en BLUEPRINT — en plan för vilka sektioner som ska inkluderas, tonen, och specifika tips per sektion.

TILLGÄNGLIGA SEKTIONER:
- "hero": Huvudsektion med rubrik, underrubrik och CTA-knapp. Alltid inkluderad.
- "about": Om-sektion med beskrivande text om företaget/personen.
- "features": Fördelar/USP:ar i kortformat (3-5 st).
- "stats": Nyckeltal/statistik (t.ex. "15 års erfarenhet", "500+ kunder").
- "services": Tjänster/produkter med titel och beskrivning (4-6 st).
- "process": Steg-för-steg-process (3-4 steg).
- "gallery": Bildgalleri för portfolio, projekt eller atmosfär.
- "team": Teammedlemmar med namn och roll.
- "testimonials": Kundomdömen/citat (2-3 st).
- "faq": Vanliga frågor och svar (4-6 st).
- "cta": Call-to-action-sektion med knapp.
- "contact": Kontaktformulär och kontaktinfo.
- "pricing": Pristabell med olika paket/nivåer.
- "video": YouTube/Vimeo-video.
- "logo_cloud": Partner-/kundlogotyper.
- "custom_content": Fritext-sektion med blandade block.
- "banner": Fullbredd-meddelande.
- "ranking": Topplista/jämförelsesektion med rankade objekt.
- "quiz": Interaktiv quiz/frågeformulär med frågor, alternativ och resultat.

REGLER FÖR SEKTIONSVAL:
1. "hero" ska ALLTID inkluderas för startsidan med priority 1.
2. Välj sektioner INTELLIGENT baserat på syfte, bransch och tillgänglig info.
3. En enkel verksamhet behöver 3-5 sektioner på startsidan. Större företag 5-8.
4. Inkludera ALDRIG alla sektioner. Tomma/generiska sektioner är värre än inga.
5. "pricing", "team", "ranking", "video", "logo_cloud" — bara om det verkligen passar.
6. Ordna sektioner i optimal visningsordning.

IDENTIFIERA SYFTE:
- Företagssida (restaurang, frisör, byggfirma, etc.) → professionell ton, fokus på tjänster och CTA.
- Personlig sida / hyllning (födelsedag, jubileum, minnesida) → varm, personlig ton, fokus på bilder och text.
- Event (bröllop, fest, konferens) → festlig/elegant ton, fokus på datum, plats, schema.
- Portfolio (fotograf, designer, artist) → visuell ton, fokus på galleri och projekt.
- Landningssida (kampanj, produkt) → säljande ton, fokus på CTA, features, testimonials.

BILDPLACERING:
- Om få bilder (1-3): hero-bakgrund + ev. about.
- Om flera bilder (4+): hero + gallery.
- Om inga bilder: skippa gallery, fokusera på text-sektioner.

UNDERSIDOR (pages_plan):
Du ska planera SEPARATA UNDERSIDOR utöver startsidan. Varje undersida är en egen sida med eget fokus.
- Enkel verksamhet: 2-3 sidor (startsida + om oss + kontakt).
- Tjänsteföretag: 2-4 sidor (startsida + tjänster + om oss + kontakt).
- Personlig sida: oftast bara 1 sida (ingen pages_plan).
- Frågesportsida / quiz-sajt: startsida med hero + quiz-sida + ev. resultat-sida.
- Artikelsajt: startsida + artikelsidor.
- Restaurang: startsida + meny + om oss + kontakt.
- Varje undersida får EGEN lista med sektioner och tips.
- Startsidan ska ha korta snippets, undersidor fullständigt innehåll.
- UNDVIK DUBBLETTER: Skapa ALDRIG två sidor med samma syfte!
  * "Kontakta oss" och "Boka tid" gör SAMMA sak → välj EN.
  * Kontaktsidan kan ha BÅDE formulär OCH kontaktinfo på samma sida.
  * Om kunden nämner bokning → gör EN sida med slug "kontakt" eller "boka-tid", INTE båda.
- Undersidornas sluggar ska vara DYNAMISKA och passa verksamheten:
  * Restaurang: "meny", "om-oss", "kontakt"
  * Frisör: "tjanster", "priser", "boka-tid"
  * Quiz-sajt: "quiz", "resultat"
  * Artikel-sajt: "artiklar"
  * Byggfirma: "tjanster", "projekt", "om-oss", "kontakt"

SVAR:
Svara ENBART med valid JSON som matchar detta schema:
{
  "purpose": "string — kort beskrivning av sidans syfte",
  "tone": "string — tonalitet, t.ex. 'professionell och inbjudande'",
  "target_audience": "string — målgrupp, t.ex. 'potentiella kunder i Stockholm'",
  "homepage_sections": [
    {
      "section": "string — sektionsnamn",
      "tip": "string — specifikt tips för generatorn",
      "priority": 1
    }
  ],
  "sections": [],
  "excluded_sections": ["string — sektioner som INTE ska inkluderas och varför"],
  "color_direction": "string eller null — färgriktning om inga färger angivits",
  "content_direction": "string — övergripande riktlinje för innehållet",
  "pages_plan": [
    {
      "slug": "string — t.ex. 'om-oss', 'tjanster', 'quiz'",
      "title": "string — kort titel, t.ex. 'Om oss'",
      "purpose": "string — vad sidan ska innehålla",
      "sections": ["about", "features"],
      "tips": ["Skriv detaljerad om-text med historia", "Lyft fram 4 USP:ar"]
    }
  ]
}

VIKTIG ÄNDRING: "homepage_sections" är sektionerna för STARTSIDAN. "sections" lämnas som tom lista (bakåtkompatibilitet). Varje undersida i "pages_plan" har sin egen "sections"-lista med sektionstyper och "tips" med genererings-tips.

Ingen annan text — bara JSON.
"""

PLANNER_USER_PROMPT_TEMPLATE = """Planera strukturen för en hemsida baserat på följande information.

═══════════════════════════════════════
FÖRETAG / SYFTE
═══════════════════════════════════════
Namn: {business_name}
Bransch: {industry}

BESKRIVNING:
{context}

BILDINFO:
Antal tillgängliga bilder: {num_images}

FÄRGER:
{color_info}

{industry_hint_section}

{scraped_section}

Skapa en optimal blueprint för denna sida.
"""


def build_planner_prompt(
    business_name: str,
    context: str,
    industry: str | None,
    industry_hint: str | None,
    num_images: int,
    colors: dict | None,
    scraped_data_summary: str | None,
) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the planner LLM call."""

    # Color info
    if colors:
        color_parts = []
        for key, value in colors.items():
            if value:
                color_parts.append(f"  {key}: {_sanitize_for_prompt(str(value), 50)}")
        color_info = "Angivna färger:\n" + "\n".join(color_parts) if color_parts else "Inga färger angivna"
    else:
        color_info = "Inga färger angivna — föreslå färgriktning."

    # Industry hint
    if industry_hint:
        industry_hint_section = (
            f"BRANSCHSPECIFIKA TIPS:\n{_sanitize_for_prompt(industry_hint, 500)}"
        )
    else:
        industry_hint_section = ""

    # Scraped data summary
    if scraped_data_summary:
        scraped_section = (
            f"SAMMANFATTNING AV BEFINTLIG SAJT:\n{_sanitize_for_prompt(scraped_data_summary, 2000)}"
        )
    else:
        scraped_section = ""

    user_prompt = PLANNER_USER_PROMPT_TEMPLATE.format(
        business_name=_sanitize_for_prompt(business_name, 200) if business_name else "Okänt",
        industry=_sanitize_for_prompt(industry, 100) if industry else "Okänd",
        context=_sanitize_for_prompt(context, 2000) if context else "Ingen beskrivning angiven.",
        num_images=num_images,
        color_info=color_info,
        industry_hint_section=industry_hint_section,
        scraped_section=scraped_section,
    )

    return PLANNER_SYSTEM_PROMPT, user_prompt
