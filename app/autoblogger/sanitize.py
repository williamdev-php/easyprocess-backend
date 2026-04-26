"""Input sanitization utilities for AutoBlogger.

Uses only the Python stdlib (html module + re) — no external dependencies.
"""
from __future__ import annotations

import html
import re

# Tags that are safe to keep in user-supplied HTML content.
SAFE_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "img",
    "ul", "ol", "li",
    "strong", "em", "b", "i",
    "blockquote", "code", "pre", "br",
    "table", "thead", "tbody", "tr", "td", "th",
    "span", "div", "sub", "sup",
})

# Attributes that are safe on specific tags.
SAFE_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title", "target", "rel"}),
    "img": frozenset({"src", "alt", "title", "width", "height"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan", "scope"}),
}

# Dangerous tags that must always be stripped (content included).
DANGEROUS_TAGS = frozenset({"script", "iframe", "object", "embed", "form", "style"})

# Regex patterns
_DANGEROUS_TAG_RE = re.compile(
    r"<\s*/?\s*(?:" + "|".join(DANGEROUS_TAGS) + r")\b[^>]*>",
    re.IGNORECASE,
)
_DANGEROUS_BLOCK_RE = re.compile(
    r"<\s*(?P<tag>" + "|".join(DANGEROUS_TAGS) + r")\b[^>]*>.*?<\s*/\s*(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ON_EVENT_ATTR_RE = re.compile(
    r"""\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""",
    re.IGNORECASE,
)
_JAVASCRIPT_URI_RE = re.compile(
    r"""(href|src|action)\s*=\s*["']?\s*javascript\s*:""",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<(/?)(\w+)(\s[^>]*)?>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(
    r"""(\w[\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""",
    re.IGNORECASE,
)
_STRIP_ALL_TAGS_RE = re.compile(r"<[^>]+>")


def sanitize_html(content: str) -> str:
    """Strip dangerous tags/attributes while preserving safe formatting HTML.

    - Removes <script>, <iframe>, <object>, <embed>, <form>, <style> and their content.
    - Removes all on* event handler attributes (onclick, onerror, etc.).
    - Removes javascript: URIs.
    - Keeps safe tags listed in SAFE_TAGS with allowed attributes.
    - Strips unknown tags but keeps their inner text.
    """
    if not content:
        return content

    # 1. Remove dangerous tag blocks (with content)
    result = _DANGEROUS_BLOCK_RE.sub("", content)
    # Catch any remaining orphaned dangerous tags
    result = _DANGEROUS_TAG_RE.sub("", result)

    # 2. Remove on* event handler attributes
    result = _ON_EVENT_ATTR_RE.sub("", result)

    # 3. Remove javascript: URIs
    result = _JAVASCRIPT_URI_RE.sub("", result)

    # 4. Filter tags and attributes
    def _filter_tag(match: re.Match) -> str:
        slash = match.group(1)
        tag_name = match.group(2).lower()
        attrs_str = match.group(3) or ""

        if tag_name not in SAFE_TAGS:
            # Strip the tag but keep content (tag is removed, inner text stays)
            return ""

        if slash:
            return f"</{tag_name}>"

        # Filter attributes
        allowed = SAFE_ATTRS.get(tag_name, frozenset())
        safe_attrs: list[str] = []
        for attr_match in _ATTR_RE.finditer(attrs_str):
            attr_name = attr_match.group(1).lower()
            if attr_name in allowed:
                attr_value = attr_match.group(2) or attr_match.group(3) or attr_match.group(4) or ""
                # Double-check no javascript: in attribute values
                if not re.match(r"\s*javascript\s*:", attr_value, re.IGNORECASE):
                    safe_attrs.append(f'{attr_name}="{html.escape(attr_value, quote=True)}"')

        if safe_attrs:
            return f"<{tag_name} {' '.join(safe_attrs)}>"
        return f"<{tag_name}>"

    result = _TAG_RE.sub(_filter_tag, result)
    return result


def sanitize_text(text: str) -> str:
    """Strip all HTML tags and unescape HTML entities.

    Returns plain text suitable for fields that should contain no markup.
    """
    if not text:
        return text

    # Remove all HTML tags
    result = _STRIP_ALL_TAGS_RE.sub("", text)
    # Unescape HTML entities
    result = html.unescape(result)
    return result.strip()
