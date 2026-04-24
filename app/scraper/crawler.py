"""
Multi-page crawler.

Discovers internal pages from navigation menus, crawls them in parallel,
and builds a structured CrawlReport with content from all pages.

The report includes:
- Site map with page types (about, contact, services, blog, etc.)
- Content extracted from each subpage
- Images with page-context annotations
- Generation notes / recommendations for AI site generation
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.scraper.extractor import fetch_page, _extract_texts, _extract_images, _extract_contacts, HEADERS

logger = logging.getLogger(__name__)

# --- Configuration -----------------------------------------------------------
MAX_SUBPAGES = 8            # max internal pages to crawl (excluding homepage)
FETCH_TIMEOUT = 12.0        # seconds per subpage fetch
CONCURRENCY = 4             # parallel fetches

# Page-type classification keywords (Swedish + English)
_PAGE_TYPE_PATTERNS: dict[str, list[str]] = {
    "about": [
        "om-oss", "om oss", "about", "about-us", "foretaget",
        "företaget", "vår-historia", "var-historia", "vilka-vi-ar",
        "who-we-are",
    ],
    "contact": [
        "kontakt", "kontakta", "contact", "kontakta-oss", "contact-us",
        "hitta-oss", "find-us", "besok-oss",
    ],
    "services": [
        "tjanster", "tjänster", "services", "vara-tjanster",
        "våra-tjänster", "erbjudanden", "offerings", "vad-vi-gor",
        "what-we-do",
    ],
    "blog": [
        "blogg", "blog", "nyheter", "news", "artiklar", "articles",
        "aktuellt", "pressrum", "press", "insights",
    ],
    "portfolio": [
        "projekt", "projects", "portfolio", "case", "case-studies",
        "cases", "referens", "referenser", "references", "gallery",
        "galleri", "vara-projekt",
    ],
    "pricing": [
        "priser", "pris", "pricing", "prislista", "prices",
        "kostnader", "plans",
    ],
    "faq": [
        "faq", "vanliga-fragor", "vanliga-frågor", "frequently-asked",
        "fragor-och-svar",
    ],
    "team": [
        "team", "teamet", "personal", "medarbetare", "staff",
        "vara-medarbetare", "our-team",
    ],
    "careers": [
        "karriar", "karriär", "jobb", "jobs", "careers", "lediga-tjanster",
        "work-with-us", "jobba-hos-oss",
    ],
    "booking": [
        "boka", "bokning", "booking", "book", "boka-tid",
        "appointment", "schedule",
    ],
}

# Links to always skip
_SKIP_PATTERNS = [
    r"#", r"javascript:", r"mailto:", r"tel:", r"\.pdf$", r"\.zip$",
    r"/wp-admin", r"/wp-login", r"/cart", r"/checkout", r"/varukorg",
    r"/login", r"/logga-in", r"/register", r"/registrera",
    r"/my-account", r"/mitt-konto", r"/search", r"/sok",
    r"/cdn-cgi/", r"/feed", r"/rss", r"/sitemap",
    r"\.(jpg|jpeg|png|gif|svg|webp|mp4|mp3)$",
]
_SKIP_RE = re.compile("|".join(_SKIP_PATTERNS), re.IGNORECASE)


# --- Data structures ---------------------------------------------------------

@dataclass
class PageInfo:
    """Represents a discovered internal page."""
    url: str
    path: str                       # e.g. "/om-oss"
    nav_label: str                  # link text from navigation, e.g. "Om oss"
    page_type: str                  # classified type: about, contact, services, etc.
    content: dict | None = None     # extracted texts (if crawled)
    images: list[dict] = field(default_factory=list)
    has_blog_posts: bool = False
    blog_post_count: int = 0


@dataclass
class CrawlReport:
    """Aggregated result from crawling multiple pages."""
    homepage_url: str
    pages_discovered: int = 0
    pages_crawled: int = 0
    site_map: list[PageInfo] = field(default_factory=list)
    has_blog: bool = False
    blog_post_count: int = 0
    has_booking: bool = False
    has_pricing: bool = False
    has_portfolio: bool = False
    all_images: list[dict] = field(default_factory=list)    # images with context
    generation_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for JSON storage / cache."""
        return {
            "homepage_url": self.homepage_url,
            "pages_discovered": self.pages_discovered,
            "pages_crawled": self.pages_crawled,
            "site_map": [
                {
                    "url": p.url,
                    "path": p.path,
                    "nav_label": p.nav_label,
                    "page_type": p.page_type,
                    "has_blog_posts": p.has_blog_posts,
                    "blog_post_count": p.blog_post_count,
                    "content_summary": _summarize_page_content(p.content) if p.content else None,
                    "image_count": len(p.images),
                }
                for p in self.site_map
            ],
            "has_blog": self.has_blog,
            "blog_post_count": self.blog_post_count,
            "has_booking": self.has_booking,
            "has_pricing": self.has_pricing,
            "has_portfolio": self.has_portfolio,
            "generation_notes": self.generation_notes,
        }


# --- Navigation discovery ----------------------------------------------------

def discover_nav_links(soup: BeautifulSoup, base_url: str) -> list[PageInfo]:
    """Extract internal navigation links from header/nav menus.

    Looks at <nav>, <header>, and common menu class patterns.
    Returns deduplicated PageInfo list sorted by nav position.
    """
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower().replace("www.", "")
    seen_paths: set[str] = set()
    pages: list[PageInfo] = []

    # Collect all anchors from navigation areas
    nav_anchors: list[tuple[Tag, str]] = []

    # 1. <nav> elements
    for nav in soup.find_all("nav"):
        for a in nav.find_all("a", href=True):
            nav_anchors.append((a, "nav"))

    # 2. <header> anchors
    header = soup.find("header")
    if header:
        for a in header.find_all("a", href=True):
            nav_anchors.append((a, "header"))

    # 3. Elements with menu-like class names
    for el in soup.find_all(class_=re.compile(
        r"(main-menu|primary-menu|nav-menu|site-nav|navbar|menu-item|navigation)",
        re.IGNORECASE,
    )):
        for a in el.find_all("a", href=True):
            nav_anchors.append((a, "menu-class"))

    for anchor, source in nav_anchors:
        href = anchor["href"].strip()

        # Skip non-page links
        if _SKIP_RE.search(href):
            continue

        # Resolve to absolute URL
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)

        # Must be same domain
        link_domain = parsed.netloc.lower().replace("www.", "")
        if link_domain != base_domain:
            continue

        # Normalize path
        path = parsed.path.rstrip("/") or "/"
        if path == "/" or path == parsed_base.path.rstrip("/"):
            continue  # skip homepage

        # Deduplicate by path
        if path in seen_paths:
            continue
        seen_paths.add(path)

        # Get link text
        label = anchor.get_text(strip=True)
        if not label:
            # Try aria-label or title
            label = anchor.get("aria-label", "") or anchor.get("title", "") or path.split("/")[-1]

        # Classify page type
        page_type = _classify_page(path, label)

        pages.append(PageInfo(
            url=abs_url.split("?")[0].split("#")[0],  # strip query/fragment
            path=path,
            nav_label=label[:100],
            page_type=page_type,
        ))

    logger.info("Discovered %d nav links from %s", len(pages), base_url)
    return pages[:MAX_SUBPAGES]


def _classify_page(path: str, label: str) -> str:
    """Classify a page type based on its URL path and nav label."""
    search_text = f"{path.lower()} {label.lower()}"

    for page_type, patterns in _PAGE_TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern in search_text:
                return page_type

    return "other"


# --- Subpage crawling --------------------------------------------------------

async def crawl_subpages(
    pages: list[PageInfo],
    base_url: str,
) -> list[PageInfo]:
    """Fetch and extract content from discovered subpages in parallel.

    Modifies PageInfo objects in-place with extracted content and images.
    """
    if not pages:
        return pages

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _crawl_one(page: PageInfo) -> None:
        async with sem:
            try:
                html, final_url = await fetch_page(page.url, timeout=FETCH_TIMEOUT)
                soup = BeautifulSoup(html, "lxml")

                # Remove noise
                for tag in soup.find_all(["script", "style", "noscript"]):
                    tag.decompose()

                # Extract texts
                page.content = _extract_texts(soup)

                # Extract images with page context
                raw_images = _extract_images(soup, final_url)
                page.images = _annotate_images(raw_images, page, soup)

                # Detect blog posts on this page
                if page.page_type == "blog":
                    page.has_blog_posts = True
                    page.blog_post_count = _count_blog_posts(soup)

                logger.info(
                    "Crawled %s (%s): %d headings, %d images",
                    page.path, page.page_type,
                    len(page.content.get("headings", [])),
                    len(page.images),
                )
            except Exception as e:
                logger.warning("Failed to crawl %s: %s", page.url, e)
                page.content = None

    await asyncio.gather(*[_crawl_one(p) for p in pages])
    return pages


def _annotate_images(
    images: list[dict],
    page: PageInfo,
    soup: BeautifulSoup,
) -> list[dict]:
    """Add source_page context and nearby heading to each image."""
    for img_dict in images:
        img_dict["source_page"] = page.path
        img_dict["source_page_type"] = page.page_type
        img_dict["source_page_label"] = page.nav_label

    # Try to find nearby headings for context
    for img_tag in soup.find_all("img"):
        src = img_tag.get("src") or img_tag.get("data-src") or ""
        # Find matching image dict
        for img_dict in images:
            if src and src in img_dict.get("url", ""):
                # Find closest preceding heading
                heading = _find_nearest_heading(img_tag)
                if heading:
                    img_dict["context_heading"] = heading
                break

    return images


def _find_nearest_heading(element: Tag) -> str | None:
    """Walk up and backwards from element to find the nearest heading."""
    # Check parent sections for headings
    for parent in element.parents:
        if parent.name in ("section", "div", "article", "main"):
            heading = parent.find(["h1", "h2", "h3", "h4"])
            if heading:
                text = heading.get_text(strip=True)
                if text:
                    return text[:150]
        if parent.name == "body":
            break
    return None


def _count_blog_posts(soup: BeautifulSoup) -> int:
    """Estimate number of blog posts on a page."""
    # Common blog post patterns: <article> tags, post-class elements
    articles = soup.find_all("article")
    if articles:
        return len(articles)

    # Look for repeated card/post patterns
    for class_pattern in ["post", "blog-item", "entry", "article-card", "news-item"]:
        items = soup.find_all(class_=re.compile(class_pattern, re.IGNORECASE))
        if len(items) >= 2:
            return len(items)

    return 0


# --- CrawlReport builder ----------------------------------------------------

def build_crawl_report(
    homepage_url: str,
    homepage_soup: BeautifulSoup,
    pages: list[PageInfo],
) -> CrawlReport:
    """Build a comprehensive CrawlReport from discovered and crawled pages."""
    report = CrawlReport(
        homepage_url=homepage_url,
        pages_discovered=len(pages),
        pages_crawled=sum(1 for p in pages if p.content is not None),
        site_map=pages,
    )

    # Aggregate flags
    page_types = {p.page_type for p in pages}
    report.has_blog = "blog" in page_types
    report.has_booking = "booking" in page_types
    report.has_pricing = "pricing" in page_types
    report.has_portfolio = "portfolio" in page_types

    # Blog post count
    for p in pages:
        if p.has_blog_posts:
            report.blog_post_count += p.blog_post_count

    # Collect all images with context from all pages
    for p in pages:
        report.all_images.extend(p.images)

    # Generate AI generation notes
    report.generation_notes = _build_generation_notes(report, pages)

    return report


def _build_generation_notes(report: CrawlReport, pages: list[PageInfo]) -> list[str]:
    """Build actionable notes for the AI generator based on crawl findings."""
    notes: list[str] = []

    # Site structure overview
    type_counts: dict[str, int] = {}
    for p in pages:
        type_counts[p.page_type] = type_counts.get(p.page_type, 0) + 1

    if type_counts:
        structure_parts = [f"{count}x {ptype}" for ptype, count in type_counts.items()]
        notes.append(f"Sidstruktur: {', '.join(structure_parts)}")

    # Blog detection
    if report.has_blog:
        count = report.blog_post_count
        if count > 0:
            notes.append(
                f"Bloggsida hittad med ~{count} inlägg. "
                "Rekommendation: installera blog-appen (install_apps: ['blog'])."
            )
        else:
            notes.append(
                "Bloggsida/nyhetssida hittad. "
                "Rekommendation: installera blog-appen (install_apps: ['blog'])."
            )

    # Booking
    if report.has_booking:
        notes.append(
            "Bokningssida hittad. Den nya sidan bör ha en tydlig 'Boka tid'-CTA "
            "och möjligen en kontaktsida med bokningsfokus."
        )

    # Pricing
    if report.has_pricing:
        notes.append(
            "Prissida hittad. Inkludera pricing-sektionen med tiers "
            "baserat på befintliga priser om möjligt."
        )

    # Portfolio/references
    if report.has_portfolio:
        notes.append(
            "Portfolio/referenssida hittad. Använd gallerisektion med bilder "
            "från den befintliga portfolio-sidan."
        )

    # About page content enrichment
    about_pages = [p for p in pages if p.page_type == "about" and p.content]
    if about_pages:
        about = about_pages[0]
        about_text = about.content.get("about") or ""
        paragraphs = about.content.get("paragraphs", [])
        if about_text or len(paragraphs) > 2:
            notes.append(
                f"Detaljerad om-oss-sida hittad ('{about.nav_label}'). "
                "Använd detta innehåll för en rikare about-sektion och egen /om-oss undersida."
            )

    # Services page
    services_pages = [p for p in pages if p.page_type == "services" and p.content]
    if services_pages:
        svc = services_pages[0]
        svc_items = svc.content.get("services", [])
        headings = svc.content.get("headings", [])
        note = f"Tjänstesida hittad ('{svc.nav_label}')."
        if svc_items:
            note += f" {len(svc_items)} tjänster extraherade."
        elif headings:
            note += f" {len(headings)} rubriker hittade som kan vara tjänster."
        notes.append(note)

    # Contact page
    contact_pages = [p for p in pages if p.page_type == "contact" and p.content]
    if contact_pages:
        notes.append(
            "Kontaktsida hittad. Skapa en egen /kontakt undersida med fullständig kontaktinfo."
        )

    # FAQ page
    faq_pages = [p for p in pages if p.page_type == "faq" and p.content]
    if faq_pages:
        faq = faq_pages[0]
        faq_items = faq.content.get("faq_items", [])
        if faq_items:
            notes.append(f"FAQ-sida hittad med {len(faq_items)} frågor. Använd dessa i FAQ-sektionen.")

    # Team page
    team_pages = [p for p in pages if p.page_type == "team" and p.content]
    if team_pages:
        team = team_pages[0]
        members = team.content.get("team_members", [])
        if members:
            notes.append(f"Teamsida hittad med {len(members)} medlemmar. Inkludera team-sektion.")

    # Image context summary
    page_images = {p.page_type: len(p.images) for p in pages if p.images}
    if page_images:
        img_parts = [f"{ptype}: {count} bilder" for ptype, count in page_images.items()]
        notes.append(f"Bilder per sidtyp — {', '.join(img_parts)}")

    # General recommendation
    if len(pages) >= 5:
        notes.append(
            "Ursprungssidan har många undersidor — den nya sidan bör ha "
            "3-4 undersidor för att spegla djupet i innehållet."
        )
    elif len(pages) <= 2:
        notes.append(
            "Ursprungssidan är enkel med få undersidor — "
            "håll den nya sidan kompakt med 2-3 sidor."
        )

    return notes


def _summarize_page_content(content: dict) -> dict | None:
    """Create a compact summary of a page's content for storage."""
    if not content:
        return None

    summary: dict = {}

    if content.get("title"):
        summary["title"] = content["title"][:200]

    if content.get("hero_text"):
        summary["hero_text"] = content["hero_text"][:200]

    if content.get("about"):
        summary["about"] = content["about"][:500]

    if content.get("paragraphs"):
        # First 5 paragraphs, truncated
        summary["paragraphs"] = [p[:300] for p in content["paragraphs"][:5]]

    if content.get("services"):
        summary["services"] = content["services"][:10]

    if content.get("faq_items"):
        summary["faq_items"] = content["faq_items"][:10]

    if content.get("team_members"):
        summary["team_members"] = content["team_members"][:10]

    if content.get("features"):
        summary["features"] = content["features"][:8]

    if content.get("headings"):
        summary["headings"] = content["headings"][:15]

    return summary if summary else None
