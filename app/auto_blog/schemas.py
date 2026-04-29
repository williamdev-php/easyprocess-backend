"""Pydantic schemas for the auto-blog system.

Covers all 15 on-page SEO categories from on-page-seo.md.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models for structured SEO data
# ---------------------------------------------------------------------------

class FAQItem(BaseModel):
    """A single FAQ entry with question and answer."""
    question: str
    answer: str


class InternalLink(BaseModel):
    """Internal link suggestion with descriptive anchor text."""
    anchor_text: str
    suggested_url: str  # e.g. "/blog/related-topic"
    context: str = ""  # sentence where the link fits


class ExternalLink(BaseModel):
    """External authority link."""
    anchor_text: str
    url: str
    rel: str = "noopener"  # "noopener" or "noopener nofollow" for sponsored


class TOCEntry(BaseModel):
    """Table of contents entry with anchor link."""
    id: str  # anchor id e.g. "what-is-seo"
    text: str  # heading text
    level: int = 2  # h2=2, h3=3


class AuthorInfo(BaseModel):
    """Author E-E-A-T information."""
    name: str = "Qvicko"
    bio: str = ""  # credentials, years of experience
    url: str = "/about"  # link to author page


class OpenGraphData(BaseModel):
    """Open Graph + Twitter Card metadata."""
    og_title: str = ""
    og_description: str = ""  # can differ from meta_description
    og_image: str = ""  # 1200x630
    og_type: str = "article"
    twitter_card: str = "summary_large_image"


class BreadcrumbItem(BaseModel):
    """Single breadcrumb entry."""
    name: str
    url: str


# ---------------------------------------------------------------------------
# Main blog post models
# ---------------------------------------------------------------------------

class BlogPostMeta(BaseModel):
    """Full metadata for a single blog post (one language variant).

    Covers SEO categories: HEAD & METADATA, URL STRUCTURE, HEADINGS,
    E-E-A-T, SCHEMA MARKUP, SOCIAL PREVIEW, ACCESSIBILITY.
    """
    # --- Core ---
    title: str  # H1 — primary keyword near start, 50-60 chars
    slug: str  # under 60 chars, keyword-forward, hyphens, lowercase
    locale: str
    excerpt: str  # 2-3 sentences for previews

    # --- HEAD & METADATA (cat 1) ---
    meta_title: str  # 50-60 chars, primary keyword near start
    meta_description: str  # 150-160 chars, keyword + benefit + soft CTA
    canonical_url: str = ""  # set by builder

    # --- SOCIAL PREVIEW (cat 13) ---
    open_graph: OpenGraphData = Field(default_factory=OpenGraphData)

    # --- E-E-A-T (cat 10) ---
    author: AuthorInfo = Field(default_factory=AuthorInfo)
    published_at: str  # ISO 8601
    updated_at: str = ""  # "last updated" date

    # --- CONTENT STATS ---
    reading_time_minutes: int = 0
    word_count: int = 0
    featured_image: str | None = None
    featured_image_alt: str = ""  # descriptive alt text (cat 6)

    # --- TAGS & KEYWORDS ---
    tags: list[str] = []
    primary_keyword: str = ""
    secondary_keywords: list[str] = []

    # --- STRUCTURE (cat 15) ---
    toc: list[TOCEntry] = []  # table of contents with anchor links

    # --- FAQ (cat 5) ---
    faq: list[FAQItem] = []  # 4-6 questions with answers

    # --- LINKS (cat 7 + 8) ---
    internal_links: list[InternalLink] = []  # 3-5 internal links
    external_links: list[ExternalLink] = []  # 2-3 authority links

    # --- BREADCRUMBS (cat 7) ---
    breadcrumbs: list[BreadcrumbItem] = []

    # --- HREFLANG ---
    hreflang_links: list[dict[str, str]] = []

    # --- SCHEMA MARKUP (cat 9) --- stored as dicts for JSON-LD output
    schema_article: dict = {}  # Article/BlogPosting schema
    schema_faq: dict = {}  # FAQPage schema
    schema_breadcrumb: dict = {}  # BreadcrumbList schema
    schema_author: dict = {}  # Person schema


class BlogPostContent(BaseModel):
    """Full blog post with HTML content.

    Content HTML includes: semantic tags, TOC anchor ids on headings,
    internal/external links inline, FAQ section, accessibility attributes.
    """
    meta: BlogPostMeta
    content: str  # Full HTML body


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """Request to generate a new blog post in all configured languages."""
    topic: str = Field(..., min_length=3, max_length=500)
    keywords: list[str] = Field(default_factory=list)
    languages: list[str] | None = None  # None = all configured languages
    word_count: int | None = None  # Override default (minimum 1500)
    author_name: str = "Qvicko"
    author_bio: str = ""
    author_url: str = "/about"


class GenerateResponse(BaseModel):
    """Response after generating blog posts."""
    slug: str
    languages_generated: list[str]
    posts: list[BlogPostMeta]


class BuildResponse(BaseModel):
    """Response after building SSG content."""
    posts_written: int
    output_dir: str


class BlogIndexEntry(BaseModel):
    """Entry for the blog index page."""
    slug: str
    title: str
    excerpt: str
    published_at: str
    tags: list[str] = []
    reading_time_minutes: int = 0
    featured_image: str | None = None
    featured_image_alt: str = ""
    locale: str = ""
    primary_keyword: str = ""
