"""
Pydantic models defining the complete JSON structure for a generated site.

Flat schema — each content block is a top-level key.
If a block is None/null, that section and its corresponding page are disabled.
Navigation and footer are auto-generated from the data by the viewer.

THIS FILE IS THE SOURCE OF TRUTH FOR THE SITE SCHEMA.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BACKWARD COMPATIBILITY RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

After production launch, existing customer sites depend on this schema.
Breaking changes will corrupt live sites. Follow these rules:

  1. NEW FIELDS MUST BE OPTIONAL with sensible defaults.
     Example:  badge: str = ""           # OK — old sites get empty string
     Bad:      badge: str                 # BREAKS — old sites have no value

  2. NEVER REMOVE a field. If deprecated, keep it with a default and ignore
     it in new viewer versions.

  3. NEVER RENAME a field. Add the new name as an alias or new field instead.

  4. NEVER CHANGE A FIELD'S TYPE. If you need a different type, add a new
     field (e.g. cta_v2) and let the viewer prefer the new one.

  5. NEW SECTIONS follow the same rule: optional with None default.
     Example:  pricing: PricingData | None = None

  6. VIEWER VERSION: Each site has a `viewer_version` field that locks it to
     a specific set of viewer components. New viewer features should target
     the latest version only. Old versions ignore unknown fields.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

When adding, removing, or changing a section/field, update ALL of the following:

  Backend (this project):
    [x] backend/app/sites/site_schema.py        — Pydantic models (you are here)
    [ ] backend/app/ai/generator.py             — _VALID_TOP_LEVEL_KEYS (if new top-level key)

  Frontend (dashboard editor):
    [ ] frontend/.../pages/[id]/page.tsx         — SiteData interface, DEFAULT_SECTION_ORDER, SECTION_MAP
    [ ] frontend/.../pages/[id]/code/page.tsx    — VALID_SECTION_KEYS, SECTION_RULES, SECTION_FILES
    [ ] frontend/.../pages/[id]/settings/page.tsx — SiteData interface (only if meta/business/seo changed)

  Viewer (public site renderer):
    [ ] viewer/lib/types.ts                      — SiteData TypeScript interface
    [ ] viewer/lib/version-registry.ts           — Register section in version renderer(s)
    [ ] viewer/components/live-preview-wrapper.tsx — DEFAULT_ORDER, renderSection()
    [ ] viewer/components/preview-shell.tsx       — DEFAULT_ORDER, renderSection()
    [ ] viewer/lib/sanitize.ts                   — arrayFields (if new section has a list field)
    [ ] viewer/lib/navigation.ts                 — buildNavigation() (if section should appear in nav)
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

# The viewer version assigned to newly generated sites.
# Bump this when you release a new viewer design version (v2, v3, ...).
# Existing sites keep whatever version they were created with.
CURRENT_VIEWER_VERSION = "v1"


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

class CTAButton(BaseModel):
    label: str
    href: str


class Colors(BaseModel):
    primary: str = "#2563eb"
    secondary: str = "#1e40af"
    accent: str = "#f59e0b"
    background: str = "#ffffff"
    text: str = "#111827"


class Fonts(BaseModel):
    heading: str = "Inter"
    body: str = "Inter"


class Branding(BaseModel):
    logo_url: str | None = None
    colors: Colors = Colors()
    fonts: Fonts = Fonts()


class MetaInfo(BaseModel):
    title: str = ""
    description: str = ""
    keywords: list[str] = []
    og_image: str | None = None
    favicon_url: str | None = None
    language: str = "sv"


class OpeningHoursDay(BaseModel):
    """A single day's opening hours for LocalBusiness structured data."""
    day: str  # "Monday", "Tuesday", ..., "Sunday"
    open: str = ""  # "09:00"
    close: str = ""  # "17:00"
    closed: bool = False


class BusinessInfo(BaseModel):
    name: str = ""
    tagline: str = ""
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    org_number: str | None = None
    social_links: dict[str, str] = {}
    opening_hours_enabled: bool = False
    opening_hours: list[OpeningHoursDay] = []


class SEOConfig(BaseModel):
    structured_data: dict = {}
    robots: str = "index, follow"


# ---------------------------------------------------------------------------
# Head scripts — user-added analytics / verification snippets
# ---------------------------------------------------------------------------

# Domains allowed as external script sources.
ALLOWED_SCRIPT_DOMAINS: set[str] = {
    # Google
    "www.googletagmanager.com",
    "googletagmanager.com",
    "www.google-analytics.com",
    "www.google.com",
    "pagead2.googlesyndication.com",
    # Meta / Facebook
    "connect.facebook.net",
    "www.facebook.com",
    # Microsoft / Bing
    "bat.bing.com",
    "clarity.ms",
    "www.clarity.ms",
    # LinkedIn
    "snap.licdn.com",
    "platform.linkedin.com",
    # Twitter / X
    "static.ads-twitter.com",
    "platform.twitter.com",
    # TikTok
    "analytics.tiktok.com",
    # Pinterest
    "s.pinimg.com",
    # Snapchat
    "sc-static.net",
    # HubSpot
    "js.hs-scripts.com",
    "js.hs-analytics.net",
    "js.hsforms.net",
    # Hotjar
    "static.hotjar.com",
    # Plausible
    "plausible.io",
    # Matomo / Piwik
    "cdn.matomo.cloud",
    # Crisp
    "client.crisp.chat",
    # Intercom
    "widget.intercom.io",
    # Cookie consent
    "cdn.cookielaw.org",
    "cookiecdn.com",
}

# Dangerous patterns that should NEVER appear in any inline script.
_DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"document\.cookie", re.IGNORECASE),
    re.compile(r"document\.write", re.IGNORECASE),
    re.compile(r"\.innerHTML\s*=", re.IGNORECASE),
    re.compile(r"\.outerHTML\s*=", re.IGNORECASE),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"(?<![a-zA-Z])Function\s*\("),  # capital-F Function constructor only
    re.compile(r"setTimeout\s*\(\s*['\"]", re.IGNORECASE),
    re.compile(r"setInterval\s*\(\s*['\"]", re.IGNORECASE),
    re.compile(r"fetch\s*\(", re.IGNORECASE),
    re.compile(r"XMLHttpRequest", re.IGNORECASE),
    re.compile(r"navigator\.sendBeacon\s*\((?!.*google|.*facebook|.*analytics)", re.IGNORECASE),
    re.compile(r"window\.location\s*=", re.IGNORECASE),
    re.compile(r"window\.open\s*\(", re.IGNORECASE),
    re.compile(r"<\s*iframe", re.IGNORECASE),
    re.compile(r"import\s*\(", re.IGNORECASE),
    re.compile(r"require\s*\(", re.IGNORECASE),
    re.compile(r"localStorage|sessionStorage", re.IGNORECASE),
    re.compile(r"indexedDB", re.IGNORECASE),
    re.compile(r"WebSocket\s*\(", re.IGNORECASE),
]

MAX_HEAD_SCRIPTS = 10
MAX_SCRIPT_LENGTH = 5000


def _is_allowed_script_src(src: str) -> bool:
    """Check if an external script URL points to an allowed domain."""
    try:
        parsed = urlparse(src)
        if parsed.scheme not in ("https",):
            return False
        return parsed.hostname in ALLOWED_SCRIPT_DOMAINS
    except Exception:
        return False


def _is_safe_inline_script(content: str) -> bool:
    """Validate that inline script content matches known analytics patterns
    and contains no dangerous operations."""
    # Check for dangerous patterns first — always block these.
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(content):
            return False
    return True


class HeadScript(BaseModel):
    """A single script entry for the site <head>.

    Supports two modes:
    - External: provide `src` (must be HTTPS from an allowed domain).
    - Inline: provide `content` (must match known analytics patterns).

    Only one of `src` or `content` should be set.
    """
    src: str | None = None
    content: str | None = None
    async_attr: bool = True
    defer: bool = False

    @field_validator("src")
    @classmethod
    def validate_src(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if not _is_allowed_script_src(v):
            raise ValueError(
                f"Script src domain not allowed. "
                f"Only HTTPS scripts from trusted analytics providers are permitted."
            )
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) > MAX_SCRIPT_LENGTH:
            raise ValueError(
                f"Inline script too long ({len(v)} chars). "
                f"Maximum is {MAX_SCRIPT_LENGTH} characters."
            )
        if not _is_safe_inline_script(v):
            raise ValueError(
                "Inline script contains disallowed operations. "
                "Only analytics/tracking initialization code is permitted."
            )
        return v


class HeadMeta(BaseModel):
    """A meta tag for the site <head> (e.g. Google site verification)."""
    name: str
    content: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[a-zA-Z0-9_\-:.]+$", v):
            raise ValueError("Meta tag name contains invalid characters.")
        if len(v) > 200:
            raise ValueError("Meta tag name too long.")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 500:
            raise ValueError("Meta tag content too long.")
        # Block any HTML/script injection in meta content
        if re.search(r"[<>]", v):
            raise ValueError("Meta tag content must not contain HTML.")
        return v


class HeadScripts(BaseModel):
    """Container for all custom head injections. Validated as a unit."""
    scripts: list[HeadScript] = []
    meta_tags: list[HeadMeta] = []

    @field_validator("scripts")
    @classmethod
    def limit_scripts(cls, v: list[HeadScript]) -> list[HeadScript]:
        if len(v) > MAX_HEAD_SCRIPTS:
            raise ValueError(f"Maximum {MAX_HEAD_SCRIPTS} head scripts allowed.")
        return v

    @field_validator("meta_tags")
    @classmethod
    def limit_meta_tags(cls, v: list[HeadMeta]) -> list[HeadMeta]:
        if len(v) > MAX_HEAD_SCRIPTS:
            raise ValueError(f"Maximum {MAX_HEAD_SCRIPTS} meta tags allowed.")
        return v


# ---------------------------------------------------------------------------
# Content blocks (each is optional — null = section/page OFF)
# ---------------------------------------------------------------------------

class HeroData(BaseModel):
    headline: str
    subtitle: str = ""
    cta: CTAButton | None = None
    background_image: str | None = None
    # Editor-only config (not generated by AI — defaults are fine)
    show_cta: bool = True


class Highlight(BaseModel):
    label: str
    value: str


class AboutData(BaseModel):
    title: str = "Om oss"
    text: str = ""
    image: str | None = None
    highlights: list[Highlight] | None = None
    show_highlights: bool = True


class ServiceItem(BaseModel):
    title: str
    description: str


class ServicesData(BaseModel):
    title: str = "Våra tjänster"
    subtitle: str = ""
    items: list[ServiceItem] = []


class GalleryImage(BaseModel):
    url: str
    alt: str = ""
    caption: str = ""


class GalleryData(BaseModel):
    title: str = "Galleri"
    subtitle: str = ""
    images: list[GalleryImage] = []


class TestimonialItem(BaseModel):
    text: str
    author: str
    role: str = ""


class TestimonialsData(BaseModel):
    title: str = "Omdömen"
    subtitle: str = ""
    items: list[TestimonialItem] = []
    show_ratings: bool = True


class CTAData(BaseModel):
    title: str
    text: str = ""
    button: CTAButton | None = None
    show_button: bool = True


class ContactData(BaseModel):
    title: str = "Kontakta oss"
    text: str = ""
    show_form: bool = True
    show_info: bool = True


# ---------------------------------------------------------------------------
# NEW: Extended content blocks
# ---------------------------------------------------------------------------

class FeatureItem(BaseModel):
    title: str
    description: str
    icon: str = ""  # emoji or icon name


class FeaturesData(BaseModel):
    title: str = "Varför välja oss"
    subtitle: str = ""
    items: list[FeatureItem] = []


class StatItem(BaseModel):
    value: str  # e.g. "500+", "25 år", "98%"
    label: str  # e.g. "Nöjda kunder", "Erfarenhet", "Kundnöjdhet"


class StatsData(BaseModel):
    title: str = ""
    items: list[StatItem] = []


class TeamMember(BaseModel):
    name: str
    role: str = ""
    image: str | None = None
    bio: str = ""


class TeamData(BaseModel):
    title: str = "Vårt team"
    subtitle: str = ""
    members: list[TeamMember] = []


class FAQItem(BaseModel):
    question: str
    answer: str


class FAQData(BaseModel):
    title: str = "Vanliga frågor"
    subtitle: str = ""
    items: list[FAQItem] = []


class ProcessStep(BaseModel):
    title: str
    description: str
    step_number: int = 0


class ProcessData(BaseModel):
    title: str = "Så fungerar det"
    subtitle: str = ""
    steps: list[ProcessStep] = []


# ---------------------------------------------------------------------------
# NEW: Additional section types (v1.1)
# ---------------------------------------------------------------------------

class PricingTier(BaseModel):
    name: str
    price: str  # e.g. "499 kr/mån", "Kontakta oss"
    description: str = ""
    features: list[str] = []
    highlighted: bool = False
    cta: CTAButton | None = None


class PricingData(BaseModel):
    title: str = "Priser"
    subtitle: str = ""
    tiers: list[PricingTier] = []


class VideoData(BaseModel):
    title: str = ""
    subtitle: str = ""
    video_url: str = ""  # YouTube/Vimeo URL
    caption: str = ""


class LogoItem(BaseModel):
    name: str
    image_url: str = ""


class LogoCloudData(BaseModel):
    title: str = "Våra partners"
    subtitle: str = ""
    logos: list[LogoItem] = []


class ContentBlock(BaseModel):
    type: str  # "text", "image", "button", "heading"
    content: str = ""
    url: str = ""
    alt: str = ""
    label: str = ""
    href: str = ""


class CustomContentData(BaseModel):
    title: str = ""
    subtitle: str = ""
    layout: str = "one-column"  # "one-column", "two-column"
    blocks: list[ContentBlock] = []


class BannerData(BaseModel):
    text: str
    button: CTAButton | None = None
    background_color: str = ""


# ---------------------------------------------------------------------------
# Section settings — per-section animation & display config
# ---------------------------------------------------------------------------

VALID_ANIMATIONS = ("fade-up", "fade-in", "slide-left", "slide-right", "scale", "none")


class SectionSettings(BaseModel):
    """Per-section display settings. All optional with sensible defaults."""
    animation: str = "fade-up"  # one of VALID_ANIMATIONS
    background_color: str = ""  # override section background; empty = default


class NavItemSchema(BaseModel):
    """A single navigation link (header or footer)."""
    label: str
    href: str


# ---------------------------------------------------------------------------
# Full site schema
# ---------------------------------------------------------------------------

class SiteSchema(BaseModel):
    """
    The complete JSON schema for a generated site.
    Stored in GeneratedSite.site_data.
    """
    meta: MetaInfo = MetaInfo()
    theme: str = "modern"
    branding: Branding = Branding()
    business: BusinessInfo = BusinessInfo()

    # Viewer version — locks this site to a specific set of viewer components.
    # Set automatically on generation from CURRENT_VIEWER_VERSION.
    # Existing sites without this field default to "v1".
    viewer_version: str = CURRENT_VIEWER_VERSION

    # Section display order — list of section keys in desired render order.
    # When absent, the viewer uses the default order.
    section_order: list[str] = Field(
        default_factory=lambda: [
            "hero", "about", "features", "stats", "services", "process",
            "gallery", "team", "testimonials", "faq", "cta", "contact",
            "pricing", "video", "logo_cloud", "custom_content", "banner",
        ]
    )

    # Style variant — randomly assigned after AI generation to give visual variety.
    # All sections on the page share the same variant number.
    # 0 = Original, 1 = Modern Cards, 2 = Clean & Minimal, 3 = Bold & Filled
    style_variant: int = 0

    # Layout overrides — let the user pick nav/footer style independently of
    # the style_variant. Empty string = use the style_variant's default.
    nav_style: str = ""      # "floating" | "sticky" | "minimal" | "" (default)
    footer_style: str = ""   # "columns" | "centered" | "minimal" | "" (default)

    # Custom navigation — when set, viewer uses these instead of auto-generating.
    # null/empty = auto-generate from active sections (backward compatible).
    header_nav: list[NavItemSchema] | None = None
    footer_nav: list[NavItemSchema] | None = None

    # Content blocks — null means OFF
    hero: HeroData | None = None
    about: AboutData | None = None
    features: FeaturesData | None = None
    stats: StatsData | None = None
    services: ServicesData | None = None
    process: ProcessData | None = None
    gallery: GalleryData | None = None
    team: TeamData | None = None
    testimonials: TestimonialsData | None = None
    faq: FAQData | None = None
    cta: CTAData | None = None
    contact: ContactData | None = None

    # New section types (v1.1) — all optional with None default
    pricing: PricingData | None = None
    video: VideoData | None = None
    logo_cloud: LogoCloudData | None = None
    custom_content: CustomContentData | None = None
    banner: BannerData | None = None

    # Per-section settings (animation, background, etc.)
    # Keys are section names, e.g. {"hero": {"animation": "fade-in"}, "about": {"animation": "slide-right"}}
    section_settings: dict[str, SectionSettings] = {}

    seo: SEOConfig = SEOConfig()

    # Custom head scripts — user-added only, never AI-generated.
    # Not in _VALID_TOP_LEVEL_KEYS so AI generator strips it automatically.
    head_scripts: HeadScripts | None = None
