"""Tests for the scraper/extractor module."""
from __future__ import annotations

import pytest

from app.scraper.extractor import extract_all, fetch_page


# ---------------------------------------------------------------------------
# extract_all — unit tests (no network)
# ---------------------------------------------------------------------------

SAMPLE_HTML = """\
<!DOCTYPE html>
<html lang="sv">
<head>
  <title>X Nails - Nagelstudio i Stockholm</title>
  <meta name="description" content="Vi erbjuder gelenagelbehandlingar och manikyr.">
  <meta property="og:image" content="https://xnails.se/og.jpg">
  <meta name="keywords" content="naglar, gelénaglar, manikyr">
  <style>
    body { color: #111827; background: #ffffff; }
    .brand { color: #e91e63; }
    .accent { color: #ff9800; }
  </style>
</head>
<body>
  <header>
    <nav>
      <img src="/logo.png" alt="X Nails Logo" class="logo">
    </nav>
  </header>

  <section class="hero">
    <h1>Välkommen till X Nails</h1>
    <p>Vi är Stockholms bästa nagelstudio med över 10 års erfarenhet inom nagelvård och skönhet.</p>
  </section>

  <section>
    <h2>Om oss</h2>
    <p>X Nails grundades 2014 och har sedan dess vuxit till ett av de mest populära nagelstudiona.</p>
  </section>

  <section>
    <h2>Tjänster</h2>
    <h3>Gelénaglar</h3>
    <p>Hållbara och vackra gelénaglar som håller i veckor.</p>
    <h3>Manikyr</h3>
    <p>Klassisk manikyr med lyxig handmassage.</p>
  </section>

  <section>
    <h2>Kontakt</h2>
    <p>Email: <a href="mailto:info@xnails.se">info@xnails.se</a></p>
    <p>Telefon: <a href="tel:+46701234567">070-123 45 67</a></p>
    <address>Storgatan 1, 111 22 Stockholm</address>
    <a href="https://instagram.com/xnails">Instagram</a>
    <a href="https://facebook.com/xnails">Facebook</a>
  </section>

  <img src="/hero.jpg" alt="Nagelbehandling" width="800" height="600">
  <img src="/team.jpg" alt="Vårt team" width="400" height="400">
  <img src="/icon-small.png" alt="ikon" width="16" height="16">
</body>
</html>
"""


class TestExtractAll:
    @pytest.mark.asyncio
    async def test_extracts_emails(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        emails = data["contact_info"]["emails"]
        assert "info@xnails.se" in emails

    @pytest.mark.asyncio
    async def test_extracts_phones(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        phones = data["contact_info"]["phones"]
        assert any("46701234567" in p or "0701234567" in p for p in phones)

    @pytest.mark.asyncio
    async def test_extracts_address(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        address = data["contact_info"]["address"]
        assert address is not None
        assert "Stockholm" in address or "Storgatan" in address

    @pytest.mark.asyncio
    async def test_extracts_social_links(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        social = data["contact_info"]["social_links"]
        assert "instagram" in social
        assert "facebook" in social

    @pytest.mark.asyncio
    async def test_extracts_title(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        assert "X Nails" in data["texts"]["title"]

    @pytest.mark.asyncio
    async def test_extracts_description(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        assert "gelenagelbehandlingar" in data["texts"]["description"]

    @pytest.mark.asyncio
    async def test_extracts_headings(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        heading_texts = [h["text"] for h in data["texts"]["headings"]]
        assert any("Välkommen" in t for t in heading_texts)

    @pytest.mark.asyncio
    async def test_extracts_hero_text(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        assert "Välkommen" in data["texts"]["hero_text"]

    @pytest.mark.asyncio
    async def test_extracts_about(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        assert data["texts"]["about"] is not None
        assert "grundades" in data["texts"]["about"]

    @pytest.mark.asyncio
    async def test_extracts_services(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        services = data["texts"]["services"]
        titles = [s["title"] for s in services]
        assert any("Gelénaglar" in t for t in titles)
        assert any("Manikyr" in t for t in titles)

    @pytest.mark.asyncio
    async def test_extracts_colors(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        colors = data["colors"]
        assert "primary" in colors
        assert colors["primary"].startswith("#")

    @pytest.mark.asyncio
    async def test_extracts_logo(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        assert data["logo_url"] is not None
        assert "logo" in data["logo_url"]

    @pytest.mark.asyncio
    async def test_extracts_images_skips_small(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        urls = [img["url"] for img in data["images"]]
        # Should include hero.jpg but not icon-small.png (16x16)
        assert any("hero.jpg" in u for u in urls)
        assert not any("icon-small" in u for u in urls)

    @pytest.mark.asyncio
    async def test_extracts_meta(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        meta = data["meta_info"]
        assert "X Nails" in meta["title"]
        assert meta["og_image"] == "https://xnails.se/og.jpg"
        assert "naglar" in meta["keywords"]

    @pytest.mark.asyncio
    async def test_html_hash(self):
        data = await extract_all(SAMPLE_HTML, "https://xnails.se/")
        assert len(data["html_hash"]) == 64  # sha256 hex


class TestExtractAllNoContacts:
    """Page with no contact info should still return valid structure."""

    BARE_HTML = """\
    <html><head><title>Empty</title></head>
    <body><h1>Hello</h1><p>No contact info here.</p></body></html>
    """

    @pytest.mark.asyncio
    async def test_empty_contacts(self):
        data = await extract_all(self.BARE_HTML, "https://example.com")
        assert data["contact_info"]["emails"] == []
        assert data["contact_info"]["phones"] == []


# ---------------------------------------------------------------------------
# fetch_page — SSRF protection
# ---------------------------------------------------------------------------

class TestFetchPageSSRF:
    @pytest.mark.asyncio
    async def test_blocks_localhost(self):
        with pytest.raises(ValueError, match="SSRF"):
            await fetch_page("http://localhost/admin")

    @pytest.mark.asyncio
    async def test_blocks_internal_ip(self):
        with pytest.raises(ValueError, match="SSRF"):
            await fetch_page("http://127.0.0.1/admin")

    @pytest.mark.asyncio
    async def test_blocks_metadata(self):
        with pytest.raises(ValueError, match="SSRF"):
            await fetch_page("http://metadata.google.internal/")
