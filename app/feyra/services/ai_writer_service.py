"""AI writer service — cold email generation, rewriting, spam checking."""

import logging
import re

import anthropic

logger = logging.getLogger(__name__)

_ai_client = anthropic.AsyncAnthropic()

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Template personalization (no AI needed)
# ---------------------------------------------------------------------------


def personalize_template(template: str, lead_data: dict) -> str:
    """Replace template variables like {{first_name}}, {{company}}, etc.

    Supported variables: first_name, last_name, full_name, company, job_title,
    email, phone, city, country, website, industry, custom_1..custom_5.
    Falls back to empty string for missing values.
    """
    replacements = {
        "first_name": lead_data.get("first_name", ""),
        "last_name": lead_data.get("last_name", ""),
        "full_name": f"{lead_data.get('first_name', '')} {lead_data.get('last_name', '')}".strip(),
        "company": lead_data.get("company", ""),
        "job_title": lead_data.get("job_title", ""),
        "email": lead_data.get("email", ""),
        "phone": lead_data.get("phone", ""),
        "city": lead_data.get("city", ""),
        "country": lead_data.get("country", ""),
        "website": lead_data.get("website", ""),
        "industry": lead_data.get("industry", ""),
    }
    # Support custom fields
    for i in range(1, 6):
        replacements[f"custom_{i}"] = lead_data.get(f"custom_{i}", "")

    result = template
    for key, value in replacements.items():
        result = result.replace(f"{{{{{key}}}}}", value)

    return result


# ---------------------------------------------------------------------------
# Cold email generation
# ---------------------------------------------------------------------------


async def generate_cold_email(
    lead_data: dict,
    campaign_tone: str,
    product_description: str,
    language: str = "en",
) -> dict:
    """Generate a cold outreach email using Claude.

    Returns {"subject": str, "body_html": str, "body_text": str}.
    """
    lead_context = (
        f"Recipient: {lead_data.get('first_name', '')} {lead_data.get('last_name', '')}\n"
        f"Company: {lead_data.get('company', 'Unknown')}\n"
        f"Job Title: {lead_data.get('job_title', 'Unknown')}\n"
        f"Industry: {lead_data.get('industry', 'Unknown')}\n"
    )

    lang_instruction = f"Write the email in {language}." if language != "en" else ""

    prompt = (
        f"Write a cold outreach email with a {campaign_tone} tone.\n\n"
        f"Product/Service:\n{product_description}\n\n"
        f"Lead Information:\n{lead_context}\n\n"
        f"Requirements:\n"
        f"- Keep it concise (under 150 words for the body)\n"
        f"- Personalize based on the lead's role and company\n"
        f"- Include a clear but soft call-to-action\n"
        f"- Do NOT use spam trigger words (free, guarantee, act now, etc.)\n"
        f"- Sound human and genuine, not salesy\n"
        f"- Do NOT include any unsubscribe link (handled separately)\n"
        f"{lang_instruction}\n\n"
        f"Return the email in this exact format:\n"
        f"SUBJECT: <subject line>\n"
        f"---\n"
        f"<email body in plain text>"
    )

    response = await _ai_client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Parse subject and body
    subject = ""
    body_text = text

    if "SUBJECT:" in text:
        parts = text.split("---", 1)
        subject_line = parts[0].strip()
        subject = subject_line.replace("SUBJECT:", "").strip()
        body_text = parts[1].strip() if len(parts) > 1 else ""
    else:
        # Fallback: first line is subject
        lines = text.split("\n", 1)
        subject = lines[0].strip()
        body_text = lines[1].strip() if len(lines) > 1 else ""

    # Convert plain text to simple HTML
    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
    body_html = "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)

    return {
        "subject": subject,
        "body_html": body_html,
        "body_text": body_text,
    }


# ---------------------------------------------------------------------------
# Subject line generation
# ---------------------------------------------------------------------------


async def generate_subject_lines(
    product_description: str,
    target_audience: str,
    count: int = 5,
) -> list[str]:
    """Generate multiple cold email subject line options.

    Returns a list of subject lines.
    """
    prompt = (
        f"Generate {count} cold email subject lines for the following:\n\n"
        f"Product/Service: {product_description}\n"
        f"Target Audience: {target_audience}\n\n"
        f"Requirements:\n"
        f"- Keep each under 60 characters\n"
        f"- Avoid spam trigger words\n"
        f"- Use curiosity, relevance, or personalization\n"
        f"- Vary the style (question, statement, personalized)\n"
        f"- Do NOT use all caps or excessive punctuation\n\n"
        f"Return ONLY the subject lines, one per line, numbered 1-{count}."
    )

    response = await _ai_client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Remove numbering like "1.", "1)", "1:"
        cleaned = re.sub(r"^\d+[\.\)\:]\s*", "", line).strip()
        if cleaned:
            lines.append(cleaned)

    return lines[:count]


# ---------------------------------------------------------------------------
# Email rewriting
# ---------------------------------------------------------------------------


async def rewrite_email(
    body: str,
    tone: str,
    language: str = "en",
) -> dict:
    """Rewrite an email body with a different tone.

    Returns {"body_html": str, "body_text": str}.
    """
    lang_instruction = f"Write in {language}." if language != "en" else ""

    prompt = (
        f"Rewrite the following email with a {tone} tone. "
        f"Keep the same core message and intent, but adjust the style. "
        f"Keep it concise. {lang_instruction}\n\n"
        f"Original email:\n{body}\n\n"
        f"Return ONLY the rewritten email body in plain text."
    )

    response = await _ai_client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    body_text = response.content[0].text.strip()
    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
    body_html = "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)

    return {
        "body_html": body_html,
        "body_text": body_text,
    }


# ---------------------------------------------------------------------------
# Follow-up generation
# ---------------------------------------------------------------------------


async def generate_follow_up(
    previous_email: str,
    step_number: int,
    language: str = "en",
) -> dict:
    """Generate a follow-up email based on the previous email.

    Returns {"subject": str, "body_html": str, "body_text": str}.
    """
    lang_instruction = f"Write in {language}." if language != "en" else ""

    step_guidance = {
        2: "This is the first follow-up. Gently reference your previous email and add new value.",
        3: "This is the second follow-up. Try a different angle or share a quick insight.",
        4: "This is the third follow-up. Keep it very short. Ask a simple yes/no question.",
        5: "This is the final follow-up. Be brief and give a graceful exit (breakup email).",
    }
    guidance = step_guidance.get(step_number, f"This is follow-up #{step_number}. Keep it brief and add value.")

    prompt = (
        f"Write a follow-up email based on this previous email:\n\n"
        f"{previous_email}\n\n"
        f"{guidance}\n\n"
        f"Requirements:\n"
        f"- Keep it under 100 words\n"
        f"- Do NOT repeat the original pitch verbatim\n"
        f"- Sound natural and human\n"
        f"- Include a soft call-to-action\n"
        f"{lang_instruction}\n\n"
        f"Return in this format:\n"
        f"SUBJECT: <subject line>\n"
        f"---\n"
        f"<email body in plain text>"
    )

    response = await _ai_client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    subject = ""
    body_text = text

    if "SUBJECT:" in text:
        parts = text.split("---", 1)
        subject_line = parts[0].strip()
        subject = subject_line.replace("SUBJECT:", "").strip()
        body_text = parts[1].strip() if len(parts) > 1 else ""
    else:
        lines = text.split("\n", 1)
        subject = lines[0].strip()
        body_text = lines[1].strip() if len(lines) > 1 else ""

    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
    body_html = "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)

    return {
        "subject": subject,
        "body_html": body_html,
        "body_text": body_text,
    }


# ---------------------------------------------------------------------------
# Spam score analysis
# ---------------------------------------------------------------------------

_SPAM_TRIGGERS = [
    ("free", 5), ("guarantee", 5), ("act now", 8), ("limited time", 7),
    ("click here", 6), ("buy now", 8), ("no obligation", 5), ("winner", 7),
    ("congratulations", 6), ("urgent", 6), ("100%", 5), ("lowest price", 6),
    ("order now", 7), ("risk free", 5), ("special promotion", 6),
    ("you have been selected", 8), ("dear friend", 7), ("amazing", 4),
    ("incredible", 4), ("once in a lifetime", 7), ("double your", 7),
    ("earn money", 7), ("make money", 7), ("cash bonus", 8),
    ("no cost", 5), ("no fees", 5), ("apply now", 5), ("call now", 6),
    ("offer expires", 6), ("while supplies last", 6), ("subscribe", 3),
    ("unsubscribe", 2),
]


async def check_spam_score(subject: str, body: str) -> dict:
    """Analyze an email for spam triggers.

    Returns {"score": int (0-100, lower is better), "issues": list[str]}.
    """
    issues: list[str] = []
    total_penalty = 0
    combined = f"{subject} {body}".lower()

    # Check trigger words
    for trigger, penalty in _SPAM_TRIGGERS:
        if trigger in combined:
            issues.append(f'Contains spam trigger word: "{trigger}"')
            total_penalty += penalty

    # Check for excessive capitalization
    words = body.split()
    if words:
        caps_words = sum(1 for w in words if w.isupper() and len(w) > 1)
        caps_ratio = caps_words / len(words)
        if caps_ratio > 0.2:
            issues.append(f"Excessive capitalization: {caps_ratio:.0%} of words are ALL CAPS")
            total_penalty += 10

    # Check for excessive punctuation
    exclamation_count = combined.count("!")
    if exclamation_count > 2:
        issues.append(f"Too many exclamation marks: {exclamation_count}")
        total_penalty += exclamation_count * 2

    question_mark_count = combined.count("?")
    if question_mark_count > 3:
        issues.append(f"Excessive question marks: {question_mark_count}")
        total_penalty += 3

    # Check for all-caps subject
    if subject.isupper() and len(subject) > 3:
        issues.append("Subject line is ALL CAPS")
        total_penalty += 15

    # Check for very short or very long subject
    if len(subject) < 5:
        issues.append("Subject line is too short")
        total_penalty += 5
    elif len(subject) > 80:
        issues.append("Subject line is too long (over 80 characters)")
        total_penalty += 5

    # Check for too many links
    link_count = len(re.findall(r"https?://", body))
    if link_count > 3:
        issues.append(f"Too many links in body: {link_count}")
        total_penalty += link_count * 3

    # Check for image-heavy content
    img_count = body.lower().count("<img")
    if img_count > 2:
        issues.append(f"Too many images: {img_count}")
        total_penalty += img_count * 3

    score = min(100, total_penalty)

    if not issues:
        issues.append("No spam issues detected")

    return {
        "score": score,
        "issues": issues,
    }
