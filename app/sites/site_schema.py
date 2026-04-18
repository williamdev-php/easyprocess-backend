"""
Pydantic models defining the complete JSON structure for a generated site.

Flat schema — each content block is a top-level key.
If a block is None/null, that section and its corresponding page are disabled.
Navigation and footer are auto-generated from the data by the viewer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class BusinessInfo(BaseModel):
    name: str = ""
    tagline: str = ""
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    org_number: str | None = None
    social_links: dict[str, str] = {}


class SEOConfig(BaseModel):
    structured_data: dict = {}
    robots: str = "index, follow"


# ---------------------------------------------------------------------------
# Content blocks (each is optional — null = section/page OFF)
# ---------------------------------------------------------------------------

class HeroData(BaseModel):
    headline: str
    subtitle: str = ""
    cta: CTAButton | None = None
    background_image: str | None = None


class Highlight(BaseModel):
    label: str
    value: str


class AboutData(BaseModel):
    title: str = "Om oss"
    text: str = ""
    image: str | None = None
    highlights: list[Highlight] | None = None


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


class CTAData(BaseModel):
    title: str
    text: str = ""
    button: CTAButton | None = None


class ContactData(BaseModel):
    title: str = "Kontakta oss"
    text: str = ""


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

    seo: SEOConfig = SEOConfig()
