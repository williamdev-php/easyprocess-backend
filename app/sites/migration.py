"""
Normalize site_data from the old nested format to the new flat format.

Old format: { pages: [{ slug, sections: [{ type, ...data }] }], navigation: {...}, business_info: {...} }
New format: { hero: {...}, about: {...}, services: {...}, ... }

Detection: if `raw` has a `pages` key that is a list, it is old format.
"""

from __future__ import annotations


def normalize_site_data(raw: dict) -> dict:
    """Convert old nested schema to new flat schema. Returns new dict (no mutation)."""
    if not isinstance(raw, dict):
        return raw

    # Already new format — no pages array
    if "pages" not in raw or not isinstance(raw.get("pages"), list):
        return raw

    pages = raw.get("pages", [])
    sections = []
    for page in pages:
        sections.extend(page.get("sections", []))

    result: dict = {}

    # Keep unchanged top-level fields
    if "meta" in raw:
        result["meta"] = raw["meta"]
    if "branding" in raw:
        result["branding"] = raw["branding"]
    if "seo" in raw:
        result["seo"] = raw["seo"]

    # Theme
    result["theme"] = raw.get("template", raw.get("theme", "modern"))

    # Normalize business_info → business
    biz = raw.get("business_info", raw.get("business", {}))
    if biz:
        result["business"] = {
            "name": biz.get("name", ""),
            "tagline": biz.get("tagline", ""),
            "email": biz.get("email"),
            "phone": biz.get("phone"),
            "address": biz.get("address"),
            "org_number": biz.get("org_number"),
            "social_links": biz.get("social_links", {}),
        }

    # Extract sections by type
    for section in sections:
        if not isinstance(section, dict):
            continue
        stype = section.get("type")
        if not stype:
            continue

        # Copy section data without the 'type' field
        data = {k: v for k, v in section.items() if k != "type"}

        if stype == "hero":
            # Rename cta_button → cta
            if "cta_button" in data and "cta" not in data:
                data["cta"] = data.pop("cta_button")
            result["hero"] = data

        elif stype == "about":
            result["about"] = data

        elif stype == "services":
            # Rename services → items
            if "services" in data and "items" not in data:
                data["items"] = data.pop("services")
            result["services"] = data

        elif stype == "gallery":
            # Rename images list
            result["gallery"] = data

        elif stype == "testimonials":
            # Rename testimonials → items
            if "testimonials" in data and "items" not in data:
                data["items"] = data.pop("testimonials")
            # Rename company → role in items
            for item in data.get("items", []):
                if "company" in item and "role" not in item:
                    item["role"] = item.pop("company")
            result["testimonials"] = data

        elif stype == "contact":
            result["contact"] = {
                "title": data.get("title", "Kontakta oss"),
                "text": data.get("text", ""),
            }
            # Pull contact details into business if not already there
            if "business" in result:
                if data.get("email") and not result["business"].get("email"):
                    result["business"]["email"] = data["email"]
                if data.get("phone") and not result["business"].get("phone"):
                    result["business"]["phone"] = data["phone"]
                if data.get("address") and not result["business"].get("address"):
                    result["business"]["address"] = data["address"]

        elif stype == "cta":
            # Rename button field
            if "button" not in data and "cta_button" in data:
                data["button"] = data.pop("cta_button")
            result["cta"] = data

        # footer is auto-generated, skip

    return result
