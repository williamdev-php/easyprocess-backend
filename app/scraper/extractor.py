"""
Content extractor: scrapes a website for logos, colors, texts, images, and contact info.

Uses httpx + BeautifulSoup. All image downloads are uploaded to R2.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


def _is_safe_url(url: str) -> bool:
    """Block requests to private/internal networks (SSRF protection)."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return False
    # Block common dangerous hostnames
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"}
    if hostname in blocked_hosts:
        return False
    try:
        # Resolve hostname and check if IP is private
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}

# Swedish phone patterns
_PHONE_RE = re.compile(
    r"(?:\+46|0)\s*(?:\(?\d{1,3}\)?[\s\-]*){1,4}\d{2,4}[\s\-]*\d{2,4}"
)
# Email pattern
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Ignore list for emails
_EMAIL_IGNORE = {"noreply", "no-reply", "info@example", "test@", "wix.com", "wordpress"}

# Patterns to strip resize parameters from image URLs
_RESIZE_PARAMS = re.compile(r"[?&](w|width|h|height|resize|size|fit|crop|quality|q)=[^&]*", re.IGNORECASE)


async def _ssrf_event_hook(request: httpx.Request) -> None:
    """Validate every request (including redirects) against SSRF rules."""
    if not _is_safe_url(str(request.url)):
        raise ValueError(f"URL blocked by SSRF protection (redirect): {request.url}")


async def fetch_page(url: str, timeout: float = 15.0) -> tuple[str, str]:
    """Fetch a page and return (html, final_url) after redirects."""
    if not _is_safe_url(url):
        raise ValueError(f"URL blocked by SSRF protection: {url}")

    max_size = 10 * 1024 * 1024  # 10MB

    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=timeout,
        max_redirects=5,
        event_hooks={"request": [_ssrf_event_hook]},
    ) as client:
        # Stream to enforce size limit before reading entire body
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()

            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > max_size:
                raise ValueError(f"Response too large: {content_length} bytes")

            content_type = resp.headers.get("content-type", "")
            if not any(ct in content_type for ct in ("text/html", "text/plain", "application/xhtml")):
                raise ValueError(f"Unexpected content type: {content_type}")

            # Read with size limit
            chunks = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_size:
                    raise ValueError(f"Response body exceeds {max_size} bytes limit")
                chunks.append(chunk)

            body = b"".join(chunks)
            return body.decode(resp.encoding or "utf-8", errors="replace"), str(resp.url)


async def extract_all(html: str, base_url: str) -> dict:
    """
    Extract everything from an HTML page. Returns a dict with:
    - contact_info: {emails, phones, address, social_links}
    - texts: {title, description, headings, paragraphs, hero_text, about, services}
    - colors: {primary, secondary, accent, background, text}
    - images: [{url, alt, category, width, height}]
    - logo_url: str | None
    - meta_info: {title, description, keywords, og_image}
    - html_hash: str
    """
    soup = BeautifulSoup(html, "lxml")
    domain = urlparse(base_url).netloc

    # Fetch external CSS for better color extraction
    external_css = await _fetch_external_css(soup, base_url)

    return {
        "contact_info": _extract_contacts(soup, html, domain),
        "texts": _extract_texts(soup),
        "colors": _extract_colors(soup, html, external_css),
        "images": _extract_images(soup, base_url),
        "logo_url": _extract_logo(soup, base_url),
        "favicon_url": _extract_favicon(soup, base_url),
        "meta_info": _extract_meta(soup),
        "html_hash": hashlib.sha256(html.encode()).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Contact info
# ---------------------------------------------------------------------------

def _extract_contacts(soup: BeautifulSoup, html: str, domain: str) -> dict:
    emails = set()
    phones = set()
    social_links: dict[str, str] = {}

    # Emails from mailto links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0].strip().lower()
            if email and not any(ig in email for ig in _EMAIL_IGNORE):
                emails.add(email)
        elif href.startswith("tel:"):
            phone = href[4:].strip()
            if phone:
                phones.add(_normalize_phone(phone))

    # Emails from visible page text (not raw HTML — avoids JS/CSS matches)
    visible_text = soup.get_text(separator=" ", strip=True)
    for match in _EMAIL_RE.findall(visible_text):
        email = match.lower()
        if not any(ig in email for ig in _EMAIL_IGNORE):
            emails.add(email)

    # Phones from visible page text (not raw HTML — avoids JS/CSS number matches)
    for match in _PHONE_RE.findall(visible_text):
        phone = _normalize_phone(match)
        if _is_valid_phone(phone):
            phones.add(phone)

    # Social links
    social_patterns = {
        "facebook": "facebook.com",
        "instagram": "instagram.com",
        "linkedin": "linkedin.com",
        "twitter": "twitter.com",
        "youtube": "youtube.com",
        "tiktok": "tiktok.com",
    }
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        for platform, pattern in social_patterns.items():
            if pattern in href and domain not in href:
                social_links[platform] = a["href"]

    # Address — look for common patterns in Swedish
    address = _extract_address(soup)

    return {
        "emails": sorted(emails),
        "phones": sorted(phones),
        "address": address,
        "social_links": social_links,
    }


def _normalize_phone(phone: str) -> str:
    return re.sub(r"[^\d+]", "", phone)


def _is_valid_phone(phone: str) -> bool:
    """Validate a normalised phone number (digits and optional leading +)."""
    digits = phone.lstrip("+")
    if not digits.isdigit():
        return False
    # Must be 8-13 digits (Swedish numbers: 8-10 without country code, 10-12 with +46)
    if not (8 <= len(digits) <= 13):
        return False
    # Reject all-zeros
    if digits == "0" * len(digits):
        return False
    # Reject +460... (invalid — leading 0 is dropped after +46)
    if phone.startswith("+460"):
        return False
    return True


def _extract_address(soup: BeautifulSoup) -> str | None:
    """Try to find a street address on the page."""
    # Look for structured address
    addr_tag = soup.find(["address"])
    if addr_tag:
        text = addr_tag.get_text(separator=" ", strip=True)
        if len(text) > 10:
            return text[:300]

    # Look for Swedish postal code pattern in text blocks
    postal_re = re.compile(r"\d{3}\s?\d{2}\s+\w+")
    for tag in soup.find_all(["p", "div", "span", "li"]):
        text = tag.get_text(strip=True)
        if postal_re.search(text) and len(text) < 200:
            return text

    return None


# ---------------------------------------------------------------------------
# Texts (expanded — extract much more content)
# ---------------------------------------------------------------------------

def _extract_texts(soup: BeautifulSoup) -> dict:
    # Remove script/style/noscript noise
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)

    # Meta description
    desc_tag = soup.find("meta", attrs={"name": "description"})
    description = desc_tag["content"].strip() if desc_tag and desc_tag.get("content") else ""

    # Headings — grab all h1-h4
    headings = []
    for level in ["h1", "h2", "h3", "h4"]:
        for h in soup.find_all(level):
            text = h.get_text(strip=True)
            if text and len(text) > 2:
                headings.append({"level": level, "text": text[:300]})

    # Hero text (first h1 + sibling/parent p)
    hero_text = ""
    hero_subtitle = ""
    h1 = soup.find("h1")
    if h1:
        hero_text = h1.get_text(strip=True)
        # Try to find subtitle near h1
        next_el = h1.find_next_sibling(["p", "h2", "span", "div"])
        if next_el:
            sub = next_el.get_text(strip=True)
            if sub and len(sub) > 10 and len(sub) < 500:
                hero_subtitle = sub

    # Paragraphs — get many more meaningful ones
    paragraphs = []
    seen = set()
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if text and len(text) > 20 and text not in seen:
            seen.add(text)
            paragraphs.append(text[:800])
            if len(paragraphs) >= 30:
                break

    # Try to identify "about us" section
    about_text = _find_section_text(soup, ["om oss", "om företaget", "about us", "about", "vi är", "vår historia"])

    # Try to find services
    services = _find_services(soup)

    # Try to find FAQ content
    faq_items = _find_faq(soup)

    # Try to find team members
    team_members = _find_team(soup)

    # Extract all list items that could be features/benefits
    features = _find_features(soup)

    return {
        "title": title,
        "description": description,
        "headings": headings,
        "hero_text": hero_text,
        "hero_subtitle": hero_subtitle,
        "paragraphs": paragraphs,
        "about": about_text,
        "services": services,
        "faq_items": faq_items,
        "team_members": team_members,
        "features": features,
    }


def _find_section_text(soup: BeautifulSoup, keywords: list[str]) -> str | None:
    """Find a section whose heading matches one of the keywords."""
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        heading_text = h.get_text(strip=True).lower()
        if any(kw in heading_text for kw in keywords):
            # Grab following paragraphs
            texts = []
            for sib in h.find_next_siblings():
                if isinstance(sib, Tag) and sib.name in ["h1", "h2", "h3"]:
                    break
                if isinstance(sib, Tag):
                    t = sib.get_text(strip=True)
                    if t and len(t) > 10:
                        texts.append(t)
                    if len(texts) >= 5:
                        break
            if texts:
                return " ".join(texts)[:2000]
    return None


def _find_services(soup: BeautifulSoup) -> list[dict]:
    """Try to extract a list of services."""
    services = []

    for h in soup.find_all(["h2", "h3"]):
        heading_text = h.get_text(strip=True).lower()
        if any(kw in heading_text for kw in ["tjänster", "services", "vad vi gör", "erbjudanden", "våra tjänster"]):
            # Look for list items or cards after this heading
            container = h.find_parent(["section", "div"])
            if container:
                for item in container.find_all(["h3", "h4", "li"]):
                    title = item.get_text(strip=True)
                    if title and len(title) > 3 and title.lower() != heading_text:
                        desc = ""
                        next_p = item.find_next_sibling("p")
                        if next_p:
                            desc = next_p.get_text(strip=True)[:300]
                        services.append({"title": title[:150], "description": desc})
                        if len(services) >= 12:
                            return services
            break

    return services


def _find_faq(soup: BeautifulSoup) -> list[dict]:
    """Try to extract FAQ items."""
    faq_items = []

    # Look for FAQ section by heading
    for h in soup.find_all(["h2", "h3"]):
        heading_text = h.get_text(strip=True).lower()
        if any(kw in heading_text for kw in ["faq", "vanliga frågor", "frågor och svar", "frequently asked"]):
            container = h.find_parent(["section", "div"])
            if container:
                # Look for details/summary (common FAQ pattern)
                for details in container.find_all("details"):
                    summary = details.find("summary")
                    if summary:
                        question = summary.get_text(strip=True)
                        answer_parts = []
                        for child in details.children:
                            if child != summary and hasattr(child, "get_text"):
                                answer_parts.append(child.get_text(strip=True))
                        answer = " ".join(answer_parts).strip()
                        if question and answer:
                            faq_items.append({"question": question[:200], "answer": answer[:500]})

                # Also look for accordion-style patterns (h3/h4 + p)
                if not faq_items:
                    for item_h in container.find_all(["h3", "h4", "h5"]):
                        q = item_h.get_text(strip=True)
                        if q and q.lower() != heading_text:
                            a_el = item_h.find_next_sibling(["p", "div"])
                            if a_el:
                                a = a_el.get_text(strip=True)
                                if a:
                                    faq_items.append({"question": q[:200], "answer": a[:500]})
                        if len(faq_items) >= 10:
                            break
            break

    return faq_items


def _find_team(soup: BeautifulSoup) -> list[dict]:
    """Try to extract team member info."""
    members = []

    for h in soup.find_all(["h2", "h3"]):
        heading_text = h.get_text(strip=True).lower()
        if any(kw in heading_text for kw in ["team", "vårt team", "personal", "medarbetare", "vi som jobbar"]):
            container = h.find_parent(["section", "div"])
            if container:
                # Look for cards with name + role
                for card in container.find_all(["div", "li", "article"]):
                    name_el = card.find(["h3", "h4", "h5"])
                    if name_el:
                        name = name_el.get_text(strip=True)
                        if name and name.lower() != heading_text and len(name) < 100:
                            role = ""
                            role_el = name_el.find_next_sibling(["p", "span"])
                            if role_el:
                                role = role_el.get_text(strip=True)[:100]
                            img = card.find("img")
                            img_url = None
                            if img:
                                img_url = img.get("src") or img.get("data-src")
                            members.append({
                                "name": name,
                                "role": role,
                                "image": img_url,
                            })
                    if len(members) >= 8:
                        break
            break

    return members


def _find_features(soup: BeautifulSoup) -> list[dict]:
    """Try to extract feature/benefit items."""
    features = []

    for h in soup.find_all(["h2", "h3"]):
        heading_text = h.get_text(strip=True).lower()
        if any(kw in heading_text for kw in [
            "varför", "fördelar", "features", "why", "benefits",
            "det som gör oss", "vad vi erbjuder", "våra styrkor",
        ]):
            container = h.find_parent(["section", "div"])
            if container:
                for item in container.find_all(["h3", "h4", "li"]):
                    title = item.get_text(strip=True)
                    if title and len(title) > 3 and title.lower() != heading_text:
                        desc = ""
                        next_p = item.find_next_sibling("p")
                        if next_p:
                            desc = next_p.get_text(strip=True)[:300]
                        features.append({"title": title[:150], "description": desc})
                        if len(features) >= 8:
                            return features
            break

    return features


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
_RGB_RE = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_CSS_VAR_COLOR_RE = re.compile(
    r"--([\w-]*(?:color|primary|secondary|accent|brand|theme)[\w-]*)\s*:\s*([^;]+)",
    re.IGNORECASE,
)

# Colors to ignore — too generic / neutral
_IGNORE_COLORS = {
    "#fff", "#ffffff", "#000", "#000000",
    "#333", "#333333", "#666", "#666666", "#999", "#999999",
    "#ccc", "#cccccc", "#ddd", "#dddddd", "#eee", "#eeeeee",
    "#f5f5f5", "#fafafa", "#e5e5e5", "#d4d4d4",
}


async def _fetch_external_css(soup: BeautifulSoup, base_url: str) -> str:
    """Fetch the first few external CSS files for color extraction."""
    css_text = ""
    links = soup.find_all("link", rel="stylesheet", href=True)
    urls = [urljoin(base_url, link["href"]) for link in links[:3]]

    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True, timeout=5.0, max_redirects=3
    ) as client:
        for url in urls:
            try:
                if not _is_safe_url(url):
                    continue
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.text) < 500_000:
                    css_text += resp.text + "\n"
            except Exception:
                continue
    return css_text


def _extract_colors(soup: BeautifulSoup, html: str, external_css: str = "") -> dict:
    """Extract the dominant color palette from CSS (inline, <style>, and external)."""
    color_counts: dict[str, int] = {}
    # Higher-weight colors from CSS custom properties
    brand_colors: list[str] = []

    # Collect from inline styles and <style> blocks
    style_text = ""
    for style_tag in soup.find_all("style"):
        style_text += style_tag.get_text()

    for tag in soup.find_all(style=True):
        style_text += tag.get("style", "")

    # Add external CSS
    all_css = style_text + "\n" + external_css

    # Extract CSS custom properties that look like brand colors (high priority)
    for var_name, var_value in _CSS_VAR_COLOR_RE.findall(all_css):
        val = var_value.strip()
        hex_match = _HEX_RE.search(val)
        if hex_match:
            hex_color = _normalize_hex(hex_match.group(1))
            if hex_color and hex_color not in _IGNORE_COLORS:
                brand_colors.append(hex_color)
        rgb_match = _RGB_RE.search(val)
        if rgb_match:
            r, g, b = rgb_match.groups()
            hex_color = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
            if hex_color not in _IGNORE_COLORS:
                brand_colors.append(hex_color)

    # Hex colors from all CSS
    for match in _HEX_RE.findall(all_css):
        hex_color = _normalize_hex(match)
        if hex_color and hex_color not in _IGNORE_COLORS:
            color_counts[hex_color] = color_counts.get(hex_color, 0) + 1

    # RGB colors
    for r, g, b in _RGB_RE.findall(all_css):
        hex_color = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
        if hex_color not in _IGNORE_COLORS:
            color_counts[hex_color] = color_counts.get(hex_color, 0) + 1

    # Brand colors from CSS variables get top priority
    if brand_colors:
        # Deduplicate while preserving order
        seen = set()
        unique_brand = []
        for c in brand_colors:
            if c not in seen:
                seen.add(c)
                unique_brand.append(c)
        top = unique_brand[:5]
    else:
        # Fall back to frequency-based
        sorted_colors = sorted(color_counts.items(), key=lambda x: -x[1])
        top = [c for c, _ in sorted_colors[:5]]

    return {
        "primary": top[0] if len(top) > 0 else "#2563eb",
        "secondary": top[1] if len(top) > 1 else "#1e40af",
        "accent": top[2] if len(top) > 2 else "#f59e0b",
        "background": "#ffffff",
        "text": "#111827",
    }


def _normalize_hex(h: str) -> str | None:
    if len(h) == 3:
        return f"#{h[0]*2}{h[1]*2}{h[2]*2}".lower()
    if len(h) == 6:
        return f"#{h}".lower()
    return None


# ---------------------------------------------------------------------------
# Images (expanded — srcset, picture, background-image support)
# ---------------------------------------------------------------------------

_SMALL_IMAGE_KEYWORDS = {"icon", "logo", "favicon", "sprite", "pixel", "tracking", "spacer"}


def _get_best_srcset_url(srcset: str, base_url: str) -> str | None:
    """Parse srcset and return the highest resolution URL."""
    if not srcset:
        return None

    candidates = []
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if not tokens:
            continue
        url = tokens[0]
        # Parse width descriptor (e.g., "800w") or pixel density (e.g., "2x")
        width = 0
        if len(tokens) > 1:
            desc = tokens[1].lower()
            if desc.endswith("w"):
                try:
                    width = int(desc[:-1])
                except ValueError:
                    logger.warning("Malformed srcset width descriptor: %s", desc)
            elif desc.endswith("x"):
                try:
                    width = int(float(desc[:-1]) * 1000)
                except ValueError:
                    logger.warning("Malformed srcset density descriptor: %s", desc)
        candidates.append((url, width))

    if not candidates:
        return None

    # Sort by width descending and return the largest
    candidates.sort(key=lambda x: x[1], reverse=True)
    return urljoin(base_url, candidates[0][0])


def _strip_resize_params(url: str) -> str:
    """Remove common resize/crop parameters from image URLs to get full-size version."""
    cleaned = _RESIZE_PARAMS.sub("", url)
    # Clean up dangling ? if all params were removed
    if cleaned.endswith("?"):
        cleaned = cleaned[:-1]
    return cleaned


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Extract meaningful images (skip tiny icons, tracking pixels).

    Supports: <img src>, <img srcset>, <picture><source>, CSS background-image.
    Prioritizes highest resolution versions.
    """
    images = []
    seen_urls = set()

    def _add_image(url: str, alt: str, category: str, width: int | None = None, height: int | None = None):
        if url in seen_urls:
            return
        seen_urls.add(url)
        # Also try without resize params
        clean_url = _strip_resize_params(url)
        img_data = {"url": clean_url, "alt": alt, "category": category}
        if width:
            img_data["width"] = width
        if height:
            img_data["height"] = height
        images.append(img_data)

    # 1. <picture> elements — get highest quality source
    for picture in soup.find_all("picture"):
        sources = picture.find_all("source")
        img = picture.find("img")
        alt = img.get("alt", "").strip() if img else ""

        best_url = None
        best_width = 0

        for source in sources:
            srcset = source.get("srcset", "")
            candidate = _get_best_srcset_url(srcset, base_url)
            if candidate:
                # Estimate width from media query or srcset
                media = source.get("media", "")
                w = 9999 if "min-width" in media else best_width + 1
                if w > best_width:
                    best_width = w
                    best_url = candidate

        if not best_url and img:
            srcset = img.get("srcset", "")
            best_url = _get_best_srcset_url(srcset, base_url)
            if not best_url:
                src = img.get("src") or img.get("data-src")
                if src:
                    best_url = urljoin(base_url, src)

        if best_url:
            src_lower = best_url.lower()
            if not any(kw in src_lower for kw in _SMALL_IMAGE_KEYWORDS):
                category = _categorize_image(picture, "general")
                _add_image(best_url, alt, category)

    # 2. <img> tags — prefer srcset for higher resolution
    for img in soup.find_all("img"):
        # Skip if already covered by <picture>
        if img.find_parent("picture"):
            continue

        srcset = img.get("srcset", "")
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")

        # Prefer highest srcset URL
        best_url = _get_best_srcset_url(srcset, base_url) if srcset else None
        if not best_url and src:
            best_url = urljoin(base_url, src)

        if not best_url:
            continue

        alt = img.get("alt", "").strip()
        src_lower = best_url.lower()

        # Skip tracking pixels and tiny images
        if any(kw in src_lower for kw in _SMALL_IMAGE_KEYWORDS):
            continue

        # Check dimensions if available
        width = _parse_dim(img.get("width"))
        height = _parse_dim(img.get("height"))
        if width and width < 80:
            continue
        if height and height < 80:
            continue

        category = _categorize_image(img, "general")
        _add_image(best_url, alt, category, width, height)

        if len(images) >= 30:
            break

    # 3. CSS background-image — extract from inline styles
    bg_re = re.compile(r"background(?:-image)?\s*:\s*url\(['\"]?([^'\")\s]+)['\"]?\)", re.IGNORECASE)
    for tag in soup.find_all(style=True):
        style = tag.get("style", "")
        for match in bg_re.findall(style):
            url = urljoin(base_url, match)
            if any(kw in url.lower() for kw in _SMALL_IMAGE_KEYWORDS):
                continue
            # Background images are often hero/banner images
            category = _categorize_image(tag, "hero")
            _add_image(url, "", category)

        if len(images) >= 30:
            break

    logger.info("Extracted %d images (with srcset/picture/bg-image support)", len(images))
    return images


def _categorize_image(element, default: str = "general") -> str:
    """Categorize an image based on its parent elements."""
    parent = element
    if hasattr(element, 'find_parent'):
        parent = element.find_parent(["section", "div", "header", "main"])
    if parent:
        classes = " ".join(parent.get("class", [])).lower() if parent.get("class") else ""
        parent_id = (parent.get("id") or "").lower()
        ctx = classes + " " + parent_id
        if any(k in ctx for k in ["hero", "banner", "slider", "jumbotron", "cover"]):
            return "hero"
        elif any(k in ctx for k in ["gallery", "portfolio", "projekt", "work", "showcase"]):
            return "gallery"
        elif any(k in ctx for k in ["team", "personal", "staff", "medarbetare"]):
            return "team"
    return default


def _parse_dim(val: str | None) -> int | None:
    if not val:
        return None
    try:
        return int(str(val).replace("px", "").strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

def _extract_logo(soup: BeautifulSoup, base_url: str) -> str | None:
    """Find the site logo. Prioritises real logo images over favicons."""
    # 1. Look for img in header/nav with "logo" in class/alt/src
    for container in [soup.find("header"), soup.find("nav")]:
        if container:
            for img in container.find_all("img"):
                attrs_text = " ".join([
                    img.get("alt", ""),
                    img.get("src", ""),
                    " ".join(img.get("class", [])),
                    img.get("id", ""),
                ]).lower()
                if "logo" in attrs_text:
                    src = img.get("src") or img.get("data-src")
                    if src:
                        return urljoin(base_url, src)

    # 2. Any img with "logo" in attributes
    for img in soup.find_all("img"):
        attrs_text = " ".join([
            img.get("alt", ""),
            img.get("src", ""),
            " ".join(img.get("class", [])),
        ]).lower()
        if "logo" in attrs_text:
            src = img.get("src") or img.get("data-src")
            if src:
                return urljoin(base_url, src)

    # 3. SVG logo in header/nav (common on modern sites)
    for container in [soup.find("header"), soup.find("nav")]:
        if container:
            for svg in container.find_all("svg"):
                attrs_text = " ".join([
                    " ".join(svg.get("class", [])),
                    svg.get("id", ""),
                    svg.get("aria-label", ""),
                ]).lower()
                if "logo" in attrs_text:
                    return None  # SVG logo found but can't extract URL; skip to avoid favicon

    # 4. OG image as fallback
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return urljoin(base_url, og["content"])

    # 5. Favicon / apple-touch-icon (last resort)
    for rel in ["apple-touch-icon", "icon", "shortcut icon"]:
        link = soup.find("link", rel=rel)
        if link and link.get("href"):
            return urljoin(base_url, link["href"])

    return None


# ---------------------------------------------------------------------------
# Favicon
# ---------------------------------------------------------------------------

def _extract_favicon(soup: BeautifulSoup, base_url: str) -> str | None:
    """Extract the favicon URL from the page, preferring high-resolution versions."""
    # 1. apple-touch-icon (highest quality, typically 180x180)
    for rel in ["apple-touch-icon", "apple-touch-icon-precomposed"]:
        link = soup.find("link", rel=rel)
        if link and link.get("href"):
            return urljoin(base_url, link["href"])

    # 2. Explicit icon links — prefer largest size
    icon_links = soup.find_all("link", rel=lambda r: r and "icon" in r if isinstance(r, list) else r == "icon")
    if not icon_links:
        icon_links = soup.find_all("link", rel="shortcut icon")

    best_url = None
    best_size = 0
    for link in icon_links:
        href = link.get("href")
        if not href:
            continue
        sizes = link.get("sizes", "")
        size = 0
        if sizes and "x" in sizes.lower():
            try:
                size = int(sizes.lower().split("x")[0])
            except (ValueError, IndexError):
                pass
        if size > best_size or best_url is None:
            best_size = size
            best_url = urljoin(base_url, href)

    if best_url:
        return best_url

    # 3. Fallback: /favicon.ico at root
    return urljoin(base_url, "/favicon.ico")


# ---------------------------------------------------------------------------
# Meta info
# ---------------------------------------------------------------------------

def _extract_meta(soup: BeautifulSoup) -> dict:
    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)

    desc = ""
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag and desc_tag.get("content"):
        desc = desc_tag["content"].strip()

    keywords = []
    kw_tag = soup.find("meta", attrs={"name": "keywords"})
    if kw_tag and kw_tag.get("content"):
        keywords = [k.strip() for k in kw_tag["content"].split(",") if k.strip()]

    og_image = None
    og_tag = soup.find("meta", property="og:image")
    if og_tag and og_tag.get("content"):
        og_image = og_tag["content"]

    return {
        "title": title,
        "description": desc,
        "keywords": keywords,
        "og_image": og_image,
    }
