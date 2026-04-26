"""Crawl service — web crawling, email extraction, lead scoring, CSV import."""

import asyncio
import csv
import io
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import anthropic
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.feyra.models import (
    CrawlJob,
    CrawlJobStatus,
    CrawlResult,
    CrawlResultStatus,
    EmailVerificationStatus,
    Lead,
    LeadSource,
    LeadStatus,
)

logger = logging.getLogger(__name__)

_ai_client = anthropic.AsyncAnthropic()

# Generic email addresses to filter out
_GENERIC_EMAILS = {
    "info", "contact", "support", "admin", "sales", "hello", "help",
    "noreply", "no-reply", "webmaster", "postmaster", "abuse",
    "office", "team", "mail", "enquiries", "marketing",
}

_EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Rate-limit tracker: domain -> last request time
_domain_last_request: dict[str, float] = {}
_RATE_LIMIT_SECONDS = 1.0


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

_robots_cache: dict[str, set[str]] = {}


async def _check_robots_txt(url: str, session: httpx.AsyncClient) -> bool:
    """Check if crawling the URL is allowed by robots.txt. Returns True if allowed."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    if base not in _robots_cache:
        try:
            resp = await session.get(f"{base}/robots.txt", timeout=10)
            disallowed: set[str] = set()
            if resp.status_code == 200:
                user_agent_applies = False
                for line in resp.text.splitlines():
                    line = line.strip()
                    if line.lower().startswith("user-agent:"):
                        agent = line.split(":", 1)[1].strip()
                        user_agent_applies = agent == "*"
                    elif line.lower().startswith("disallow:") and user_agent_applies:
                        path = line.split(":", 1)[1].strip()
                        if path:
                            disallowed.add(path)
            _robots_cache[base] = disallowed
        except Exception:
            _robots_cache[base] = set()

    for disallowed_path in _robots_cache.get(base, set()):
        if parsed.path.startswith(disallowed_path):
            return False
    return True


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def _rate_limit_domain(url: str) -> None:
    """Enforce a minimum delay of 1 second between requests to the same domain."""
    domain = urlparse(url).netloc
    now = asyncio.get_event_loop().time()
    last = _domain_last_request.get(domain, 0)
    wait = _RATE_LIMIT_SECONDS - (now - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _domain_last_request[domain] = asyncio.get_event_loop().time()


# ---------------------------------------------------------------------------
# Page crawling
# ---------------------------------------------------------------------------


async def crawl_page(url: str, session: httpx.AsyncClient) -> dict:
    """Fetch a page and extract its content.

    Returns a dict with keys: url, status_code, title, html, text, links, error.
    """
    result = {
        "url": url,
        "status_code": None,
        "title": "",
        "html": "",
        "text": "",
        "links": [],
        "error": None,
    }

    try:
        allowed = await _check_robots_txt(url, session)
        if not allowed:
            result["error"] = "Blocked by robots.txt"
            return result

        await _rate_limit_domain(url)

        resp = await session.get(
            url,
            timeout=20,
            follow_redirects=True,
            headers={
                "User-Agent": "FeyraBot/1.0 (compatible; lead-generation crawler)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        result["status_code"] = resp.status_code

        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        html = resp.text
        result["html"] = html

        soup = BeautifulSoup(html, "lxml")

        # Title
        title_tag = soup.find("title")
        result["title"] = title_tag.get_text(strip=True) if title_tag else ""

        # Text content
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        result["text"] = soup.get_text(separator=" ", strip=True)[:10000]

        # Extract links
        base_domain = urlparse(url).netloc
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            absolute = urljoin(url, href)
            parsed = urlparse(absolute)
            if parsed.scheme in ("http", "https") and parsed.netloc == base_domain:
                links.append(absolute)
        result["links"] = list(set(links))[:100]

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Email extraction
# ---------------------------------------------------------------------------


def extract_emails_from_content(html: str, url: str) -> list[str]:
    """Extract email addresses from HTML content.

    Uses regex pattern matching and mailto: link extraction.
    Filters out generic addresses like info@, support@, etc.
    """
    emails: set[str] = set()

    # Extract from mailto: links
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip().lower()
            if _EMAIL_REGEX.match(email):
                emails.add(email)

    # Extract from text content
    text = soup.get_text(separator=" ")
    for match in _EMAIL_REGEX.findall(text):
        emails.add(match.lower())

    # Also check raw HTML for obfuscated emails
    for match in _EMAIL_REGEX.findall(html):
        emails.add(match.lower())

    # Filter out generic emails and image file false positives
    filtered = []
    for email in emails:
        local_part = email.split("@")[0].lower()
        domain = email.split("@")[1].lower() if "@" in email else ""
        if local_part in _GENERIC_EMAILS:
            continue
        # Filter out common false positives (image files, CSS, etc.)
        if domain.endswith((".png", ".jpg", ".gif", ".css", ".js")):
            continue
        filtered.append(email)

    return filtered


# ---------------------------------------------------------------------------
# Contact extraction
# ---------------------------------------------------------------------------


def extract_contacts_from_page(html: str, url: str) -> list[dict]:
    """Extract contact information (names, titles, phones, LinkedIn) near email addresses.

    Returns a list of dicts with keys: email, name, title, phone, linkedin_url.
    """
    soup = BeautifulSoup(html, "lxml")
    emails = extract_emails_from_content(html, url)

    if not emails:
        return []

    contacts = []
    phone_pattern = re.compile(
        r"[\+]?[(]?[0-9]{1,4}[)]?[-\s\./0-9]{7,15}"
    )
    linkedin_pattern = re.compile(
        r"https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-_%]+"
    )

    for email_addr in emails:
        contact: dict = {
            "email": email_addr,
            "name": None,
            "title": None,
            "phone": None,
            "linkedin_url": None,
            "source_url": url,
        }

        # Find surrounding context for this email
        text = soup.get_text(separator="\n")
        email_positions = [m.start() for m in re.finditer(re.escape(email_addr), text, re.IGNORECASE)]

        for pos in email_positions:
            # Get text window around the email (500 chars before and after)
            start = max(0, pos - 500)
            end = min(len(text), pos + 500)
            context = text[start:end]

            # Try to extract phone
            phone_matches = phone_pattern.findall(context)
            if phone_matches:
                contact["phone"] = phone_matches[0].strip()

            # Try to extract LinkedIn URL
            html_context = html[max(0, html.lower().find(email_addr.lower()) - 1000):
                                html.lower().find(email_addr.lower()) + 1000]
            linkedin_matches = linkedin_pattern.findall(html_context)
            if linkedin_matches:
                contact["linkedin_url"] = linkedin_matches[0]

        # Try to find name from structured data (team pages, about pages)
        for tag in soup.find_all(["div", "li", "article", "section", "tr"]):
            tag_text = tag.get_text(separator=" ", strip=True)
            if email_addr.lower() in tag_text.lower():
                # Look for common name patterns: names are often in h2/h3/strong/b tags
                name_tag = tag.find(["h2", "h3", "h4", "strong", "b"])
                if name_tag:
                    name_text = name_tag.get_text(strip=True)
                    # Basic validation: name should be 2-5 words, start with uppercase
                    words = name_text.split()
                    if 2 <= len(words) <= 5 and words[0][0].isupper() and len(name_text) < 60:
                        contact["name"] = name_text

                # Look for job titles in common patterns
                for child in tag.find_all(["span", "p", "small", "em"]):
                    child_text = child.get_text(strip=True)
                    title_keywords = [
                        "ceo", "cto", "cfo", "coo", "founder", "director",
                        "manager", "head of", "vp ", "vice president",
                        "engineer", "developer", "designer", "analyst",
                        "consultant", "specialist", "coordinator",
                    ]
                    if any(kw in child_text.lower() for kw in title_keywords):
                        if len(child_text) < 80:
                            contact["title"] = child_text
                            break
                break

        contacts.append(contact)

    return contacts


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


async def verify_email(email: str) -> dict:
    """Verify an email address using MX record check and SMTP RCPT TO.

    Returns {"email": str, "status": str, "mx_host": str|None, "message": str}.
    """
    import dns.resolver

    result = {
        "email": email,
        "status": EmailVerificationStatus.PENDING.value,
        "mx_host": None,
        "message": "",
    }

    domain = email.split("@")[1]

    # Step 1: MX record check
    try:
        loop = asyncio.get_event_loop()
        mx_records = await loop.run_in_executor(
            None, lambda: dns.resolver.resolve(domain, "MX")
        )
        if not mx_records:
            result["status"] = EmailVerificationStatus.INVALID.value
            result["message"] = "No MX records found"
            return result
        mx_host = str(mx_records[0].exchange).rstrip(".")
        result["mx_host"] = mx_host
    except Exception as exc:
        result["status"] = EmailVerificationStatus.INVALID.value
        result["message"] = f"DNS lookup failed: {exc}"
        return result

    # Step 2: SMTP RCPT TO check
    import smtplib

    def _smtp_verify() -> tuple[str, str]:
        try:
            server = smtplib.SMTP(mx_host, 25, timeout=10)
            server.ehlo("feyra.com")
            server.mail("verify@feyra.com")
            code, message = server.rcpt(email)
            server.quit()

            if code == 250:
                return EmailVerificationStatus.VALID.value, "Email address is valid"
            elif code == 550:
                return EmailVerificationStatus.INVALID.value, "Mailbox does not exist"
            else:
                # Many servers return catch-all responses
                return EmailVerificationStatus.CATCH_ALL.value, f"Server returned code {code}"
        except smtplib.SMTPServerDisconnected:
            return EmailVerificationStatus.CATCH_ALL.value, "Server disconnected (possible greylisting)"
        except Exception as e:
            return EmailVerificationStatus.CATCH_ALL.value, f"SMTP check failed: {e}"

    status_val, message = await loop.run_in_executor(None, _smtp_verify)
    result["status"] = status_val
    result["message"] = message
    return result


# ---------------------------------------------------------------------------
# Lead scoring with AI
# ---------------------------------------------------------------------------


async def score_lead_against_icp(lead_data: dict, icp_description: str) -> int:
    """Use Claude to score a lead 0-100 against an ideal customer profile.

    Higher scores indicate a better match.
    """
    prompt = (
        f"Score this lead against the Ideal Customer Profile on a scale of 0-100.\n\n"
        f"Ideal Customer Profile:\n{icp_description}\n\n"
        f"Lead Data:\n"
        f"- Name: {lead_data.get('name', 'Unknown')}\n"
        f"- Email: {lead_data.get('email', 'Unknown')}\n"
        f"- Company: {lead_data.get('company', 'Unknown')}\n"
        f"- Job Title: {lead_data.get('job_title', 'Unknown')}\n"
        f"- Industry: {lead_data.get('industry', 'Unknown')}\n"
        f"- Company Size: {lead_data.get('company_size', 'Unknown')}\n"
        f"- Location: {lead_data.get('location', 'Unknown')}\n"
        f"- Website: {lead_data.get('website', 'Unknown')}\n\n"
        "Return ONLY a single integer between 0 and 100. Nothing else."
    )

    response = await _ai_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    try:
        score = int(re.search(r"\d+", text).group())
        return max(0, min(100, score))
    except (ValueError, AttributeError):
        logger.warning("Failed to parse ICP score from AI response: %s", text)
        return 50


# ---------------------------------------------------------------------------
# Main crawl execution
# ---------------------------------------------------------------------------


async def start_crawl(db: AsyncSession, crawl_job_id: str) -> None:
    """Execute a crawl job: fetch pages, extract contacts, score leads."""
    job_result = await db.execute(
        select(CrawlJob).where(CrawlJob.id == crawl_job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        logger.error("Crawl job %s not found", crawl_job_id)
        return

    # Mark as running
    await db.execute(
        update(CrawlJob)
        .where(CrawlJob.id == crawl_job_id)
        .values(status=CrawlJobStatus.RUNNING, started_at=datetime.now(timezone.utc))
    )
    await db.flush()

    visited: set[str] = set()
    to_visit: list[str] = []
    max_pages = job.max_pages or 50

    # Seed URLs from the job config
    if job.seed_urls:
        to_visit.extend(job.seed_urls)
    elif job.target_domains:
        # Use target domains as seed if no seed_urls provided
        for domain in job.target_domains:
            if not domain.startswith("http"):
                domain = f"https://{domain}"
            to_visit.append(domain)

    total_contacts = 0

    try:
        async with httpx.AsyncClient() as client:
            while to_visit and len(visited) < max_pages:
                url = to_visit.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                # Check if job was paused/cancelled
                job_check = await db.execute(
                    select(CrawlJob.status).where(CrawlJob.id == crawl_job_id)
                )
                current_status = job_check.scalar()
                if current_status in (CrawlJobStatus.PAUSED, CrawlJobStatus.FAILED):
                    logger.info("Crawl job %s was stopped", crawl_job_id)
                    return

                page_data = await crawl_page(url, client)

                # Create CrawlResult record
                crawl_result = CrawlResult(
                    crawl_job_id=crawl_job_id,
                    url=url,
                    status=CrawlResultStatus.SCRAPED if not page_data["error"] else CrawlResultStatus.ERROR,
                    page_title=page_data.get("title", ""),
                    http_status_code=page_data.get("status_code"),
                    error_message=page_data.get("error"),
                    crawled_at=datetime.now(timezone.utc),
                )
                db.add(crawl_result)
                await db.flush()

                if page_data["error"]:
                    continue

                # Extract contacts
                contacts = extract_contacts_from_page(page_data["html"], url)
                emails = extract_emails_from_content(page_data["html"], url)

                for contact in contacts:
                    # Check for duplicate leads
                    existing = await db.execute(
                        select(func.count()).select_from(Lead).where(
                            and_(
                                Lead.user_id == job.user_id,
                                Lead.email == contact["email"],
                            )
                        )
                    )
                    if existing.scalar() > 0:
                        continue

                    lead = Lead(
                        user_id=job.user_id,
                        email=contact["email"],
                        first_name=contact.get("name", "").split()[0] if contact.get("name") else None,
                        last_name=" ".join(contact.get("name", "").split()[1:]) if contact.get("name") else None,
                        job_title=contact.get("title"),
                        phone=contact.get("phone"),
                        linkedin_url=contact.get("linkedin_url"),
                        website_url=url,
                        source_url=url,
                        source=LeadSource.CRAWL,
                        status=LeadStatus.NEW,
                    )
                    db.add(lead)
                    total_contacts += 1

                # Update crawl result status
                await db.execute(
                    update(CrawlResult)
                    .where(CrawlResult.id == crawl_result.id)
                    .values(
                        status=CrawlResultStatus.PROCESSED,
                        emails_found=emails,
                        contacts_extracted=[c["email"] for c in contacts],
                    )
                )
                await db.flush()

                # Add discovered links to queue
                for link in page_data.get("links", []):
                    if link not in visited:
                        to_visit.append(link)

                # Update progress
                await db.execute(
                    update(CrawlJob)
                    .where(CrawlJob.id == crawl_job_id)
                    .values(
                        pages_crawled=len(visited),
                        leads_found=total_contacts,
                        emails_found=CrawlJob.emails_found + len(emails),
                    )
                )
                await db.flush()

        # Mark job as completed
        await db.execute(
            update(CrawlJob)
            .where(CrawlJob.id == crawl_job_id)
            .values(
                status=CrawlJobStatus.COMPLETED,
                completed_at=datetime.now(timezone.utc),
                pages_crawled=len(visited),
                leads_found=total_contacts,
            )
        )
        await db.flush()
        logger.info(
            "Crawl job %s completed: %d pages, %d contacts",
            crawl_job_id, len(visited), total_contacts,
        )

    except Exception as exc:
        logger.exception("Crawl job %s failed", crawl_job_id)
        await db.execute(
            update(CrawlJob)
            .where(CrawlJob.id == crawl_job_id)
            .values(
                status=CrawlJobStatus.FAILED,
                completed_at=datetime.now(timezone.utc),
                error_message=str(exc)[:500],
            )
        )
        await db.flush()


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


async def import_leads_from_csv(
    db: AsyncSession,
    user_id: str,
    file_content: bytes,
    column_mapping: dict,
    tags: list[str] | None = None,
) -> dict:
    """Parse a CSV file and create Lead records, deduplicating by email.

    column_mapping maps CSV column names to Lead field names, e.g.:
    {"Email Address": "email", "First Name": "first_name", ...}

    Returns {"imported": int, "duplicates": int, "errors": int, "total": int}.
    """
    tags = tags or []
    text = file_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    imported = 0
    duplicates = 0
    errors = 0
    total = 0

    # Reverse mapping: lead_field -> csv_column
    field_map = {v: k for k, v in column_mapping.items()}

    for row in reader:
        total += 1
        try:
            # Extract email (required)
            email_col = field_map.get("email")
            if not email_col or not row.get(email_col):
                errors += 1
                continue

            email_val = row[email_col].strip().lower()
            if not _EMAIL_REGEX.match(email_val):
                errors += 1
                continue

            # Check for duplicates
            existing = await db.execute(
                select(func.count()).select_from(Lead).where(
                    and_(Lead.user_id == user_id, Lead.email == email_val)
                )
            )
            if existing.scalar() > 0:
                duplicates += 1
                continue

            # Build lead data from column mapping
            lead_kwargs: dict = {
                "user_id": user_id,
                "email": email_val,
                "source": LeadSource.CSV_IMPORT,
                "status": LeadStatus.NEW,
            }

            # Map user-facing field names to actual model field names
            _csv_field_to_model = {
                "company": "company_name",
                "website": "website_url",
                "city": "location",
            }
            optional_fields = [
                "first_name", "last_name", "company_name", "job_title",
                "phone", "linkedin_url", "website_url", "location", "country",
                "industry",
            ]
            for field in optional_fields:
                csv_col = field_map.get(field)
                if not csv_col:
                    # Also check the user-facing alias (e.g. "company" -> "company_name")
                    for alias, model_field in _csv_field_to_model.items():
                        if model_field == field:
                            csv_col = field_map.get(alias)
                            break
                if csv_col and row.get(csv_col):
                    lead_kwargs[field] = row[csv_col].strip()

            if tags:
                lead_kwargs["tags"] = tags

            lead = Lead(**lead_kwargs)
            db.add(lead)
            imported += 1

            # Flush every 100 records for memory efficiency
            if imported % 100 == 0:
                await db.flush()

        except Exception:
            logger.exception("Error importing CSV row %d", total)
            errors += 1

    await db.flush()

    logger.info(
        "CSV import complete: %d imported, %d duplicates, %d errors out of %d rows",
        imported, duplicates, errors, total,
    )
    return {
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
        "total": total,
    }
