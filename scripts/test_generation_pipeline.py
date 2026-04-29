"""
End-to-end test of the full site generation pipeline.

Runs: Planner → Orchestrator (homepage + per-page) → SEO → Sanitization
Logs every step to a file for inspection.

Usage:
    cd backend
    python scripts/test_generation_pipeline.py
"""

import asyncio
import json
import sys
import os
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

LOG_FILE = Path(__file__).resolve().parent.parent / "generation_test_log.md"


def log(msg: str):
    """Print and append to log file."""
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def log_json(label: str, data, indent=2):
    """Log a JSON-serializable object."""
    text = json.dumps(data, ensure_ascii=False, indent=indent, default=str)
    log(f"\n### {label}\n```json\n{text}\n```\n")


async def main():
    # Clear log file
    LOG_FILE.write_text("# Generation Pipeline Test Log\n\n", encoding="utf-8")

    # =========================================================================
    # TEST INPUT
    # =========================================================================
    business_name = "Glow Beauty Studio"
    context = (
        "Vi är en skönhetssalong i Göteborg som erbjuder ansiktsbehandlingar, "
        "fransförlängning, bryndesign, hudvård och manikyr/pedikyr. "
        "Vi har 3 behandlare och vill ha en elegant, lyxig hemsida. "
        "Kunder ska enkelt kunna se våra behandlingar med priser "
        "och boka tid online. Vi vill visa vår prislista tydligt."
    )
    industry = "skönhet"
    email = "hej@glowbeauty.se"
    phone = "031-987 65 43"
    address = "Avenyn 45, 411 38 Göteborg"
    colors = {
        "primary": "#8B5E83",
        "secondary": "#C9A9C4",
        "accent": "#D4AF37",
        "background": "#FFF9F5",
        "text": "#2D2D2D",
    }
    logo_url = None
    images = None

    log("## Test Input\n")
    log(f"- **Business**: {business_name}")
    log(f"- **Industry**: {industry}")
    log(f"- **Context**: {context}")
    log(f"- **Email**: {email}")
    log(f"- **Phone**: {phone}")
    log(f"- **Address**: {address}")
    log_json("Colors", colors)

    # =========================================================================
    # STEP 1: PLANNER
    # =========================================================================
    log("\n---\n## Steg 1: Planner\n")

    from app.ai.planner import plan_site

    t0 = time.monotonic()
    blueprint = await plan_site(
        business_name=business_name,
        context=context,
        industry=industry,
        industry_hint="Fokusera på pålitlighet, erfarenhet och kvalitet. Använd starka CTA:er som 'Begär offert'. Visa upp projekt/referenser. Lyft fram certifieringar.",
        num_images=0,
        colors=colors,
    )
    planner_ms = int((time.monotonic() - t0) * 1000)

    if not blueprint:
        log("**PLANNER FAILED** — ingen blueprint returnerades.")
        return

    planner_tokens = getattr(blueprint, "_tokens_used", 0)
    planner_cost = getattr(blueprint, "_cost_usd", 0)

    log(f"- **Duration**: {planner_ms}ms")
    log(f"- **Tokens**: {planner_tokens}")
    log(f"- **Cost**: ${planner_cost:.4f}")
    log_json("Blueprint", blueprint.model_dump(mode="json"))

    # Evaluate planner output
    log("\n### Planner-utvärdering\n")
    hp = blueprint.homepage_sections or blueprint.sections
    hp_names = [s.section for s in hp] if hp else []
    log(f"- Homepage-sektioner: {hp_names}")
    pp = blueprint.pages_plan or []
    log(f"- Undersidor planerade: {len(pp)}")
    for p in pp:
        log(f"  - `/{p.slug}` — \"{p.title}\" — sektioner: {p.sections}")

    if not hp_names:
        log("- **PROBLEM**: Inga homepage-sektioner!")
    if "hero" not in hp_names:
        log("- **PROBLEM**: Hero saknas på startsidan!")

    # Check for duplicates
    page_purposes = [p.purpose.lower() for p in pp]
    if len(page_purposes) != len(set(page_purposes)):
        log("- **PROBLEM**: Dubbletter i pages_plan!")

    # =========================================================================
    # STEP 2: ORCHESTRATOR
    # =========================================================================
    log("\n---\n## Steg 2: Orchestrator (homepage + undersidor)\n")

    from app.ai.generator import orchestrate_site_generation

    t0 = time.monotonic()
    gen_result = await orchestrate_site_generation(
        blueprint=blueprint,
        business_name=business_name,
        industry=industry,
        email=email,
        phone=phone,
        address=address,
        colors=colors,
        logo_url=logo_url,
        social_links=None,
        images=images,
        visual_analysis=None,
        context=context,
    )
    orch_ms = int((time.monotonic() - t0) * 1000)

    log(f"- **Duration**: {orch_ms}ms")
    log(f"- **Total tokens**: {gen_result.tokens_used} (in={gen_result.input_tokens}, out={gen_result.output_tokens})")
    log(f"- **Model**: {gen_result.model}")
    log(f"- **Cost**: ${gen_result.cost_usd:.4f}")
    log(f"- **Install apps**: {gen_result.install_apps}")

    # =========================================================================
    # STEP 3: FINAL SITE DATA
    # =========================================================================
    log("\n---\n## Steg 3: Slutgiltig site_data\n")

    site_data = gen_result.site_schema.model_dump(mode="json")

    # Log key parts separately for readability
    log_json("meta", site_data.get("meta"))
    log_json("branding", site_data.get("branding"))
    log_json("business", site_data.get("business"))
    log(f"\n**section_order**: {site_data.get('section_order', [])}")
    log(f"**style_variant**: {site_data.get('style_variant')}")
    log(f"**viewer_version**: {site_data.get('viewer_version')}")

    # Log homepage sections
    section_keys = [
        "hero", "about", "features", "stats", "services", "process",
        "gallery", "team", "testimonials", "faq", "cta", "contact",
        "pricing", "video", "logo_cloud", "custom_content", "banner",
        "ranking", "quiz",
    ]
    active_sections = []
    for key in section_keys:
        val = site_data.get(key)
        if val is not None:
            active_sections.append(key)

    log(f"\n### STARTSIDA (/) — {len(active_sections)} sektioner")
    log(f"**section_order**: {site_data.get('section_order', [])}")
    for key in active_sections:
        log_json(f"Startsida: {key}", site_data.get(key))

    log(f"\n**Aktiva top-level sektioner**: {active_sections}")

    # Log pages
    pages = site_data.get("pages") or []
    log(f"\n### UNDERSIDOR — {len(pages)} st")
    for i, page in enumerate(pages):
        log(f"\n### Undersida {i+1}: /{page.get('slug', '?')} — \"{page.get('title', '?')}\"")
        log(f"- show_in_nav: {page.get('show_in_nav')}")
        log(f"- nav_order: {page.get('nav_order')}")
        sections = page.get("sections", [])
        log(f"- Antal sektioner: {len(sections)}")
        for sec in sections:
            log_json(f"  Page section: {sec.get('type', '?')}", sec.get("data", {}))

    # Log SEO
    log_json("SEO", site_data.get("seo"))
    log_json("section_settings", site_data.get("section_settings"))

    # =========================================================================
    # STEP 4: AUTOMATED VALIDATOR
    # =========================================================================
    log("\n---\n## Steg 4: Automatisk validering (site_validator)\n")

    from app.ai.site_validator import validate_site_data, format_issues

    validator_issues = validate_site_data(
        site_data,
        input_colors=colors,
        input_email=email,
        input_phone=phone,
        input_address=address,
        input_business_name=business_name,
    )
    log(f"```\n{format_issues(validator_issues)}\n```\n")

    # =========================================================================
    # STEP 5: MANUAL QUALITY EVALUATION
    # =========================================================================
    log("\n---\n## Steg 5: Manuell kvalitetsutvärdering\n")

    issues = []
    goods = []

    # Check hero
    hero = site_data.get("hero")
    if hero:
        goods.append(f"Hero finns med headline: \"{hero.get('headline', '')}\"")
        if hero.get("cta"):
            cta = hero["cta"]
            goods.append(f"Hero CTA: \"{cta.get('label')}\" → {cta.get('href')}")
            # Check if href points to existing page
            valid_hrefs = {"/", "/"} | {f"/{p.get('slug', '')}" for p in pages}
            href = cta.get("href", "")
            if href.startswith("/") and href not in valid_hrefs and not href.startswith("http"):
                issues.append(f"Hero CTA href '{href}' pekar inte på en existerande undersida. Tillgängliga: {valid_hrefs}")
        if hero.get("show_cta") is False and hero.get("cta"):
            issues.append("Hero har CTA definierad men show_cta=false")
    else:
        issues.append("Hero SAKNAS")

    # Check business info
    biz = site_data.get("business", {})
    if biz.get("name"):
        goods.append(f"Business name: \"{biz['name']}\"")
    else:
        issues.append("Business name saknas")
    if biz.get("email"):
        goods.append(f"Email: {biz['email']}")
    if biz.get("phone"):
        goods.append(f"Phone: {biz['phone']}")
    if biz.get("address"):
        goods.append(f"Address: {biz['address']}")

    # Check branding colors
    branding = site_data.get("branding", {})
    br_colors = branding.get("colors", {})
    if br_colors.get("primary") == colors["primary"]:
        goods.append(f"Rätt primary-färg: {br_colors['primary']}")
    elif br_colors.get("primary"):
        issues.append(f"Primary-färg ändrad: input={colors['primary']}, output={br_colors['primary']}")

    # Check meta (auto-generated)
    meta = site_data.get("meta", {})
    if meta.get("title"):
        goods.append(f"Meta title: \"{meta['title']}\"")
    else:
        issues.append("Meta title saknas")
    if meta.get("description"):
        goods.append(f"Meta description: \"{meta['description'][:80]}...\"")
    else:
        issues.append("Meta description saknas")
    if meta.get("keywords"):
        goods.append(f"Keywords: {len(meta['keywords'])} st")

    # Check SEO structured data
    seo = site_data.get("seo", {})
    sd = seo.get("structured_data", {})
    if sd.get("@graph"):
        types = [g.get("@type") for g in sd["@graph"]]
        goods.append(f"Structured data: {types}")
    else:
        issues.append("Structured data saknas")

    # Check contact consistency
    contact = site_data.get("contact")
    if contact:
        text = (contact.get("text") or "").lower()
        if "formulär" in text and contact.get("show_form") is False:
            issues.append("Contact text nämner formulär men show_form=false")
        elif contact.get("show_form") is True:
            goods.append("Contact show_form=true (formulär visas)")
        if contact.get("show_info") is True:
            goods.append("Contact show_info=true (kontaktinfo visas)")

    # Check pages contact sections
    for page in pages:
        for sec in page.get("sections", []):
            if sec.get("type") == "contact":
                d = sec.get("data", {})
                text = (d.get("text") or "").lower()
                slug = page.get("slug", "?")
                if "formulär" in text and d.get("show_form") is False:
                    issues.append(f"Page /{slug} contact nämner formulär men show_form=false")
                if d.get("show_form") is True:
                    goods.append(f"Page /{slug} contact show_form=true")
                if d.get("show_form") is False and d.get("show_info") is False:
                    issues.append(f"Page /{slug} contact: BÅDE show_form och show_info är false!")

    # Check for duplicate pages
    page_slugs = [p.get("slug") for p in pages]
    if len(page_slugs) != len(set(page_slugs)):
        issues.append(f"Duplicerade page-sluggar: {page_slugs}")

    # Check navigation
    nav_pages = [p for p in pages if p.get("show_in_nav")]
    log(f"\n**Navigation**: {len(nav_pages)} sidor i nav:")
    for p in sorted(nav_pages, key=lambda x: x.get("nav_order", 0)):
        log(f"  {p.get('nav_order', '?')}. /{p.get('slug', '?')} — \"{p.get('title', '?')}\"")

    # Summary
    log("\n### Bra saker\n")
    for g in goods:
        log(f"- {g}")

    log("\n### Problem/varningar\n")
    if issues:
        for i in issues:
            log(f"- **{i}**")
    else:
        log("- Inga problem hittade!")

    # =========================================================================
    # STEP 6: COST SUMMARY
    # =========================================================================
    log("\n---\n## Steg 6: Kostnadssummering\n")
    total_cost = planner_cost + gen_result.cost_usd
    total_tokens_all = planner_tokens + gen_result.tokens_used
    total_ms = planner_ms + orch_ms
    log(f"- **Planner**: {planner_tokens} tokens, ${planner_cost:.4f}, {planner_ms}ms")
    log(f"- **Orchestrator**: {gen_result.tokens_used} tokens, ${gen_result.cost_usd:.4f}, {orch_ms}ms")
    log(f"- **TOTALT**: {total_tokens_all} tokens, **${total_cost:.4f}**, {total_ms}ms ({total_ms/1000:.1f}s)")

    log(f"\n---\n\n*Loggen sparad: {LOG_FILE}*")


if __name__ == "__main__":
    asyncio.run(main())
