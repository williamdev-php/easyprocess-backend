"""
Email templates for AutoBlogger.

Uses AutoBlogger's own colour palette (Deep Indigo + Electric Lime)
and branding in the header.  All translatable strings live in
app/email/translations/autoblogger_{locale}.json.

Colour palette (from autoblogger frontend globals.css):
  Background:       #F8F7FF
  Primary (indigo):  #4F46E5
  Primary dark:      #3730A3
  Primary deep:      #1E1B4B
  Surface:           #FFFFFF
  Border:            #D4D0E8
  Border light:      #E8E5F5
  Text:              #1E1B4B
  Text secondary:    #5B51D8
  Text muted:        #8B83B8
  Accent (lime):     #BEF264
"""

from __future__ import annotations

import json
from functools import lru_cache
from html import escape as html_escape
from pathlib import Path

from app.email.i18n import DEFAULT_LOCALE, FALLBACK_LOCALE, SUPPORTED_LOCALES
from app.email.templates import (
    _body_text as _qvicko_body_text,
    _heading as _qvicko_heading,
    _greeting as _qvicko_greeting,
    _muted_text as _qvicko_muted_text,
    _spacer,
)

# ---------------------------------------------------------------------------
# AutoBlogger translation helpers
# ---------------------------------------------------------------------------

_TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "email" / "translations"


@lru_cache(maxsize=None)
def _load_ab(locale: str) -> dict:
    path = _TRANSLATIONS_DIR / f"autoblogger_{locale}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _t(key: str, locale: str = DEFAULT_LOCALE, **kwargs: object) -> str:
    """Look up a translated AutoBlogger string by dotted key."""
    if locale not in SUPPORTED_LOCALES:
        locale = FALLBACK_LOCALE

    data = _load_ab(locale)
    value: dict | str = data
    for part in key.split("."):
        value = value[part]  # type: ignore[index]

    if kwargs and isinstance(value, str):
        return value.format(**kwargs)
    return value  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# AutoBlogger-branded component helpers
# ---------------------------------------------------------------------------

def _heading(text: str) -> str:
    return f'          <h2 style="color:#1E1B4B; margin:0 0 16px; font-size:22px;">{text}</h2>'


def _greeting(text: str) -> str:
    return f"""          <p style="color:#1E1B4B; font-size:15px; line-height:1.6; margin:0 0 12px;">
            {text}
          </p>"""


def _body_text(text: str, margin: str = "0 0 28px") -> str:
    return f"""          <p style="color:#5B51D8; font-size:15px; line-height:1.6; margin:{margin};">
            {text}
          </p>"""


def _muted_text(text: str, size: str = "13px", margin: str = "28px 0 0") -> str:
    return f"""          <p style="color:#8B83B8; font-size:{size}; line-height:1.5; margin:{margin};">
            {text}
          </p>"""


def _cta_button(url: str, label: str) -> str:
    """Render a centred CTA button in AutoBlogger indigo."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td align="center" style="padding:8px 0;">
              <a href="{url}" style="display:inline-block; background:#4F46E5; color:#FFFFFF; text-decoration:none; padding:14px 36px; border-radius:12px; font-size:15px; font-weight:600;">
                {label}
              </a>
            </td></tr>
          </table>"""


def _info_box(text: str) -> str:
    """Render an info box with AutoBlogger accent tones."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#E8E5F5; border-radius:12px; padding:20px 24px; border:1px solid #D4D0E8;">
              <p style="color:#1E1B4B; font-size:14px; line-height:1.6; margin:0;">
                {text}
              </p>
            </td></tr>
          </table>"""


def _warning_box(text: str) -> str:
    """Render a red warning box."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#FEF2F2; border-radius:12px; padding:20px 24px; border:1px solid #D4D0E8;">
              <p style="color:#DC2626; font-size:14px; line-height:1.6; margin:0;">
                {text}
              </p>
            </td></tr>
          </table>"""


# ---------------------------------------------------------------------------
# AutoBlogger layout wrapper
# ---------------------------------------------------------------------------

def _wrap_autoblogger_layout(inner_html: str, locale: str = DEFAULT_LOCALE) -> str:
    """Wrap content in the AutoBlogger email layout."""
    footer = html_escape(_t("common.footer_rights", locale))
    return f"""<!DOCTYPE html>
<html lang="{locale}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#F8F7FF; font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif; -webkit-font-smoothing:antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background-color:#F8F7FF; padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px; width:100%; background:#FFFFFF; border-radius:16px; border:1px solid #D4D0E8; overflow:hidden;">

        <!-- Header -->
        <tr><td style="background:#4F46E5; padding:28px 40px; text-align:center;">
          <span style="color:#FFFFFF; font-size:24px; font-weight:700; letter-spacing:0.5px;">AutoBlogger</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:40px;">
{inner_html}
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 40px; border-top:1px solid #E8E5F5; text-align:center;">
          <p style="color:#8B83B8; font-size:12px; margin:0;">
            {footer}
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Helper: stats table for weekly summary
# ---------------------------------------------------------------------------

def _stats_table(rows: list[tuple[str, str | int]]) -> str:
    """Render a simple two-column stats table."""
    row_html = ""
    for label, value in rows:
        row_html += (
            f'<tr>'
            f'<td style="padding:8px 12px; color:#5B51D8; font-size:14px; border-bottom:1px solid #E8E5F5;">{label}</td>'
            f'<td style="padding:8px 12px; color:#1E1B4B; font-size:14px; font-weight:600; text-align:right; border-bottom:1px solid #E8E5F5;">{value}</td>'
            f'</tr>'
        )
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="border:1px solid #D4D0E8; border-radius:12px; overflow:hidden;">
{row_html}
          </table>"""


# ---------------------------------------------------------------------------
# 1. Post generated successfully
# ---------------------------------------------------------------------------

def build_post_generated_email(
    post_title: str,
    post_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_title = html_escape(post_title)
    safe_url = html_escape(post_url)

    subject = _t("post_generated.subject", locale, post_title=post_title)

    inner = "\n\n".join([
        _heading(_t("post_generated.heading", locale)),
        _greeting(_t("post_generated.greeting", locale)),
        _body_text(
            _t("post_generated.body", locale, post_title=f"<strong>{safe_title}</strong>"),
            margin="0 0 24px",
        ),
        _cta_button(safe_url, _t("post_generated.cta", locale)),
        _muted_text(_t("post_generated.note", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('post_generated.greeting', locale)}\n\n"
        f"{_t('post_generated.body', locale, post_title=post_title)}\n\n"
        f"{_t('post_generated.cta', locale)}: {post_url}\n\n"
        f"{_t('post_generated.note', locale)}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 2. Post generation failed
# ---------------------------------------------------------------------------

def build_post_failed_email(
    post_title: str,
    error_message: str,
    retry_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_title = html_escape(post_title)
    safe_error = html_escape(error_message)
    safe_url = html_escape(retry_url)

    subject = _t("post_failed.subject", locale, post_title=post_title)

    inner = "\n\n".join([
        _heading(_t("post_failed.heading", locale)),
        _greeting(_t("post_failed.greeting", locale)),
        _body_text(
            _t("post_failed.body", locale, post_title=f"<strong>{safe_title}</strong>"),
            margin="0 0 24px",
        ),
        _warning_box(
            f"<strong>{_t('post_failed.error_label', locale)}</strong> {safe_error}"
        ),
        _spacer(),
        _cta_button(safe_url, _t("post_failed.cta", locale)),
        _muted_text(_t("post_failed.note", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('post_failed.greeting', locale)}\n\n"
        f"{_t('post_failed.body', locale, post_title=post_title)}\n\n"
        f"{_t('post_failed.error_label', locale)} {error_message}\n\n"
        f"{_t('post_failed.cta', locale)}: {retry_url}\n\n"
        f"{_t('post_failed.note', locale)}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 3. Post awaiting review
# ---------------------------------------------------------------------------

def build_post_review_email(
    post_title: str,
    approve_url: str,
    decline_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_title = html_escape(post_title)
    safe_approve = html_escape(approve_url)
    safe_decline = html_escape(decline_url)

    subject = _t("post_review.subject", locale, post_title=post_title)

    inner = "\n\n".join([
        _heading(_t("post_review.heading", locale)),
        _greeting(_t("post_review.greeting", locale)),
        _body_text(
            _t("post_review.body", locale, post_title=f"<strong>{safe_title}</strong>"),
            margin="0 0 24px",
        ),
        _cta_button(safe_approve, _t("post_review.cta_approve", locale)),
        _muted_text(
            f'<a href="{safe_decline}" style="color:#8B83B8; text-decoration:underline;">'
            f'{_t("post_review.cta_decline", locale)}</a>',
            margin="12px 0 0",
        ),
        _muted_text(_t("post_review.note", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('post_review.greeting', locale)}\n\n"
        f"{_t('post_review.body', locale, post_title=post_title)}\n\n"
        f"{_t('post_review.cta_approve', locale)}: {approve_url}\n"
        f"{_t('post_review.cta_decline', locale)}: {decline_url}\n\n"
        f"{_t('post_review.note', locale)}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 4. Weekly summary
# ---------------------------------------------------------------------------

def build_weekly_summary_email(
    posts_generated: int,
    posts_published: int,
    credits_used: int,
    credits_remaining: int,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    subject = _t("weekly_summary.subject", locale)

    stats_rows = [
        (_t("weekly_summary.posts_generated_label", locale), str(posts_generated)),
        (_t("weekly_summary.posts_published_label", locale), str(posts_published)),
        (_t("weekly_summary.credits_used_label", locale), str(credits_used)),
        (_t("weekly_summary.credits_remaining_label", locale), str(credits_remaining)),
    ]

    unsubscribe_html = _t(
        "common.unsubscribe", locale,
        link_start='<a href="{{unsubscribe_url}}" style="color:#8B83B8; text-decoration:underline;">',
        link_end="</a>",
    )

    inner = "\n\n".join([
        _heading(_t("weekly_summary.heading", locale)),
        _greeting(_t("weekly_summary.greeting", locale)),
        _body_text(_t("weekly_summary.body", locale), margin="0 0 24px"),
        _stats_table(stats_rows),
        _spacer(),
        _cta_button("{{dashboard_url}}", _t("weekly_summary.cta", locale)),
        _muted_text(unsubscribe_html, size="12px", margin="28px 0 0"),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('weekly_summary.greeting', locale)}\n\n"
        f"{_t('weekly_summary.body', locale)}\n\n"
        f"{_t('weekly_summary.posts_generated_label', locale)}: {posts_generated}\n"
        f"{_t('weekly_summary.posts_published_label', locale)}: {posts_published}\n"
        f"{_t('weekly_summary.credits_used_label', locale)}: {credits_used}\n"
        f"{_t('weekly_summary.credits_remaining_label', locale)}: {credits_remaining}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 5. Credits running low
# ---------------------------------------------------------------------------

def build_credits_low_email(
    credits_remaining: int,
    total_credits: int,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    subject = _t("credits_low.subject", locale)

    inner = "\n\n".join([
        _heading(_t("credits_low.heading", locale)),
        _greeting(_t("credits_low.greeting", locale)),
        _body_text(
            _t("credits_low.body", locale,
               credits_remaining=f"<strong>{credits_remaining}</strong>",
               total_credits=f"<strong>{total_credits}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(_t("credits_low.info", locale)),
        _spacer(),
        _cta_button("{{credits_url}}", _t("credits_low.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('credits_low.greeting', locale)}\n\n"
        f"{_t('credits_low.body', locale, credits_remaining=credits_remaining, total_credits=total_credits)}\n\n"
        f"{_t('credits_low.info', locale)}\n\n"
        f"{_t('common.questions_reply', locale)}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 6. Credits exhausted
# ---------------------------------------------------------------------------

def build_credits_exhausted_email(
    upgrade_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_url = html_escape(upgrade_url)

    subject = _t("credits_exhausted.subject", locale)

    inner = "\n\n".join([
        _heading(_t("credits_exhausted.heading", locale)),
        _greeting(_t("credits_exhausted.greeting", locale)),
        _body_text(_t("credits_exhausted.body", locale), margin="0 0 24px"),
        _warning_box(_t("credits_exhausted.warning", locale)),
        _spacer(),
        _cta_button(safe_url, _t("credits_exhausted.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('credits_exhausted.greeting', locale)}\n\n"
        f"{_t('credits_exhausted.body', locale)}\n\n"
        f"{_t('credits_exhausted.warning', locale)}\n\n"
        f"{_t('credits_exhausted.cta', locale)}: {upgrade_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 7. Trial ending in 3 days
# ---------------------------------------------------------------------------

def build_trial_ending_email(
    trial_end_date: str,
    upgrade_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_date = html_escape(trial_end_date)
    safe_url = html_escape(upgrade_url)

    subject = _t("ab_trial_ending.subject", locale)

    inner = "\n\n".join([
        _heading(_t("ab_trial_ending.heading", locale)),
        _greeting(_t("ab_trial_ending.greeting", locale)),
        _body_text(
            _t("ab_trial_ending.body", locale, trial_end_date=f"<strong>{safe_date}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(_t("ab_trial_ending.info", locale)),
        _spacer(),
        _cta_button(safe_url, _t("ab_trial_ending.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('ab_trial_ending.greeting', locale)}\n\n"
        f"{_t('ab_trial_ending.body', locale, trial_end_date=trial_end_date)}\n\n"
        f"{_t('ab_trial_ending.info', locale)}\n\n"
        f"{_t('ab_trial_ending.cta', locale)}: {upgrade_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 8. Payment failed
# ---------------------------------------------------------------------------

def build_payment_failed_email(
    invoice_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_url = html_escape(invoice_url)

    subject = _t("ab_payment_failed.subject", locale)

    inner = "\n\n".join([
        _heading(_t("ab_payment_failed.heading", locale)),
        _greeting(_t("ab_payment_failed.greeting", locale)),
        _body_text(_t("ab_payment_failed.body", locale), margin="0 0 24px"),
        _warning_box(_t("ab_payment_failed.warning", locale)),
        _spacer(),
        _cta_button(safe_url, _t("ab_payment_failed.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('ab_payment_failed.greeting', locale)}\n\n"
        f"{_t('ab_payment_failed.body', locale)}\n\n"
        f"{_t('ab_payment_failed.warning', locale)}\n\n"
        f"{_t('ab_payment_failed.cta', locale)}: {invoice_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 9. Welcome after registration
# ---------------------------------------------------------------------------

def build_welcome_email(
    user_name: str,
    getting_started_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_url = html_escape(getting_started_url)

    subject = _t("ab_welcome.subject", locale)

    inner = "\n\n".join([
        _heading(_t("ab_welcome.heading", locale)),
        _greeting(_t("ab_welcome.greeting", locale, user_name=safe_name)),
        _body_text(_t("ab_welcome.body", locale), margin="0 0 24px"),
        _info_box(_t("ab_welcome.info", locale)),
        _spacer(),
        _cta_button(safe_url, _t("ab_welcome.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('ab_welcome.greeting', locale, user_name=user_name)}\n\n"
        f"{_t('ab_welcome.body', locale)}\n\n"
        f"{_t('ab_welcome.info', locale)}\n\n"
        f"{_t('ab_welcome.cta', locale)}: {getting_started_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 10. Email verification
# ---------------------------------------------------------------------------

def build_verification_email(
    verify_url: str,
    user_name: str | None = None,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    name = user_name or _t("common.default_user_name", locale)
    safe_name = html_escape(name)
    safe_url = html_escape(verify_url)

    subject = _t("verification.subject", locale)

    inner = "\n\n".join([
        _heading(_t("verification.heading", locale)),
        _greeting(_t("verification.greeting", locale, name=safe_name)),
        _body_text(_t("verification.body", locale)),
        _cta_button(safe_url, _t("verification.cta", locale)),
        _muted_text(_t("verification.ignore", locale)),
        _muted_text(
            f'{_t("common.copy_link_prefix", locale)} {safe_url}',
            size="12px", margin="16px 0 0",
        ),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('verification.greeting', locale, name=name)}\n\n"
        f"{_t('verification.body', locale)}\n\n"
        f"{_t('verification.cta', locale)}: {verify_url}\n\n"
        f"{_t('verification.ignore', locale)}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 11. Password reset
# ---------------------------------------------------------------------------

def build_password_reset_email(
    reset_url: str,
    user_name: str | None = None,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    name = user_name or _t("common.default_user_name", locale)
    safe_name = html_escape(name)
    safe_url = html_escape(reset_url)

    subject = _t("password_reset.subject", locale)

    inner = "\n\n".join([
        _heading(_t("password_reset.heading", locale)),
        _greeting(_t("password_reset.greeting", locale, name=safe_name)),
        _body_text(_t("password_reset.body", locale)),
        _cta_button(safe_url, _t("password_reset.cta", locale)),
        _muted_text(_t("common.ignore_if_not_requested", locale)),
        _muted_text(
            f'{_t("common.copy_link_prefix", locale)} {safe_url}',
            size="12px", margin="16px 0 0",
        ),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('password_reset.greeting', locale, name=name)}\n\n"
        f"{_t('password_reset.body', locale)}\n\n"
        f"{_t('password_reset.cta', locale)}: {reset_url}\n\n"
        f"{_t('common.ignore_if_not_requested', locale)}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 12. Payment confirmation
# ---------------------------------------------------------------------------

def build_payment_confirmation_email(
    amount: str,
    next_billing_date: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_url = html_escape(dashboard_url)

    subject = _t("payment_confirmation.subject", locale)

    inner = "\n\n".join([
        _heading(_t("payment_confirmation.heading", locale)),
        _greeting(_t("payment_confirmation.greeting", locale)),
        _body_text(
            _t("payment_confirmation.body", locale, amount=f"<strong>{html_escape(amount)}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(_t("payment_confirmation.info", locale, next_billing_date=html_escape(next_billing_date))),
        _spacer(),
        _cta_button(safe_url, _t("payment_confirmation.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('payment_confirmation.greeting', locale)}\n\n"
        f"{_t('payment_confirmation.body', locale, amount=amount)}\n\n"
        f"{_t('payment_confirmation.info', locale, next_billing_date=next_billing_date)}\n\n"
        f"{_t('payment_confirmation.cta', locale)}: {dashboard_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 13. Plan change confirmation
# ---------------------------------------------------------------------------

def build_plan_change_email(
    old_plan: str,
    new_plan: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_url = html_escape(dashboard_url)

    subject = _t("plan_change.subject", locale)

    inner = "\n\n".join([
        _heading(_t("plan_change.heading", locale)),
        _greeting(_t("plan_change.greeting", locale)),
        _body_text(
            _t("plan_change.body", locale,
               old_plan=f"<strong>{html_escape(old_plan)}</strong>",
               new_plan=f"<strong>{html_escape(new_plan)}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(_t("plan_change.info", locale)),
        _spacer(),
        _cta_button(safe_url, _t("plan_change.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_autoblogger_layout(inner, locale)

    plain_text = (
        f"{_t('plan_change.greeting', locale)}\n\n"
        f"{_t('plan_change.body', locale, old_plan=old_plan, new_plan=new_plan)}\n\n"
        f"{_t('plan_change.info', locale)}\n\n"
        f"{_t('plan_change.cta', locale)}: {dashboard_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text
