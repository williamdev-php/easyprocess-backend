"""
Email templates for Feyra.

Uses Feyra's own colour palette (Deep Navy + Coral) and branding in
the header.  All translatable strings live in
app/email/translations/feyra_{locale}.json.

Colour palette (from feyra frontend globals.css):
  Background:       #FAFAF8
  Primary (navy):    #1E3A5F
  Primary dark:      #152C4A
  Primary deep:      #0F1F35
  Accent (coral):    #F06543
  Accent hover:      #D9553A
  Warm:              #FFB347
  Surface:           #FFFFFF
  Border:            #E2E0DB
  Border light:      #EDEBE6
  Text:              #0F1F35
  Text secondary:    #4A6A8A
  Text muted:        #8A9EB5
"""

from __future__ import annotations

import json
from functools import lru_cache
from html import escape as html_escape
from pathlib import Path

from app.email.i18n import DEFAULT_LOCALE, FALLBACK_LOCALE, SUPPORTED_LOCALES
from app.email.templates import _spacer


# ---------------------------------------------------------------------------
# Feyra translation helpers
# ---------------------------------------------------------------------------

_TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "email" / "translations"


@lru_cache(maxsize=None)
def _load_feyra(locale: str) -> dict:
    path = _TRANSLATIONS_DIR / f"feyra_{locale}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _t(key: str, locale: str = DEFAULT_LOCALE, **kwargs: object) -> str:
    """Look up a translated Feyra string by dotted key."""
    if locale not in SUPPORTED_LOCALES:
        locale = FALLBACK_LOCALE

    data = _load_feyra(locale)
    value: dict | str = data
    for part in key.split("."):
        value = value[part]  # type: ignore[index]

    if kwargs and isinstance(value, str):
        return value.format(**kwargs)
    return value  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Feyra-branded component helpers
# ---------------------------------------------------------------------------

def _heading(text: str) -> str:
    return f'          <h2 style="color:#0F1F35; margin:0 0 16px; font-size:22px;">{text}</h2>'


def _greeting(text: str) -> str:
    return f"""          <p style="color:#0F1F35; font-size:15px; line-height:1.6; margin:0 0 12px;">
            {text}
          </p>"""


def _body_text(text: str, margin: str = "0 0 28px") -> str:
    return f"""          <p style="color:#4A6A8A; font-size:15px; line-height:1.6; margin:{margin};">
            {text}
          </p>"""


def _muted_text(text: str, size: str = "13px", margin: str = "28px 0 0") -> str:
    return f"""          <p style="color:#8A9EB5; font-size:{size}; line-height:1.5; margin:{margin};">
            {text}
          </p>"""


def _cta_button(url: str, label: str) -> str:
    """Render a centred CTA button in Feyra coral."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td align="center" style="padding:8px 0;">
              <a href="{url}" style="display:inline-block; background:#F06543; color:#FFFFFF; text-decoration:none; padding:14px 36px; border-radius:12px; font-size:15px; font-weight:600;">
                {label}
              </a>
            </td></tr>
          </table>"""


def _info_box(text: str) -> str:
    """Render an info box with Feyra warm tones."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#FFF4E0; border-radius:12px; padding:20px 24px; border:1px solid #E2E0DB;">
              <p style="color:#0F1F35; font-size:14px; line-height:1.6; margin:0;">
                {text}
              </p>
            </td></tr>
          </table>"""


def _warning_box(text: str) -> str:
    """Render a red warning box."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#FDF0F0; border-radius:12px; padding:20px 24px; border:1px solid #E2E0DB;">
              <p style="color:#C44D4D; font-size:14px; line-height:1.6; margin:0;">
                {text}
              </p>
            </td></tr>
          </table>"""


# ---------------------------------------------------------------------------
# Feyra layout wrapper
# ---------------------------------------------------------------------------

def _wrap_feyra_layout(inner_html: str, locale: str = DEFAULT_LOCALE) -> str:
    """Wrap content in the Feyra email layout."""
    footer = html_escape(_t("common.footer_rights", locale))
    return f"""<!DOCTYPE html>
<html lang="{locale}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#FAFAF8; font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif; -webkit-font-smoothing:antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background-color:#FAFAF8; padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px; width:100%; background:#FFFFFF; border-radius:16px; border:1px solid #E2E0DB; overflow:hidden;">

        <!-- Header -->
        <tr><td style="background:#1E3A5F; padding:28px 40px; text-align:center;">
          <span style="color:#FFFFFF; font-size:24px; font-weight:700; letter-spacing:0.5px;">Feyra</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:40px;">
{inner_html}
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 40px; border-top:1px solid #EDEBE6; text-align:center;">
          <p style="color:#8A9EB5; font-size:12px; margin:0;">
            {footer}
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 1. Email verification
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

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('verification.greeting', locale, name=name)}\n\n"
        f"{_t('verification.body', locale)}\n\n"
        f"{_t('verification.cta', locale)}: {verify_url}\n\n"
        f"{_t('verification.ignore', locale)}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 2. Password reset
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

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('password_reset.greeting', locale, name=name)}\n\n"
        f"{_t('password_reset.body', locale)}\n\n"
        f"{_t('password_reset.cta', locale)}: {reset_url}\n\n"
        f"{_t('common.ignore_if_not_requested', locale)}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 3. Welcome after registration
# ---------------------------------------------------------------------------

def build_welcome_email(
    user_name: str,
    getting_started_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_url = html_escape(getting_started_url)

    subject = _t("welcome.subject", locale)

    inner = "\n\n".join([
        _heading(_t("welcome.heading", locale)),
        _greeting(_t("welcome.greeting", locale, user_name=safe_name)),
        _body_text(_t("welcome.body", locale), margin="0 0 24px"),
        _info_box(_t("welcome.info", locale)),
        _spacer(),
        _cta_button(safe_url, _t("welcome.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('welcome.greeting', locale, user_name=user_name)}\n\n"
        f"{_t('welcome.body', locale)}\n\n"
        f"{_t('welcome.info', locale)}\n\n"
        f"{_t('welcome.cta', locale)}: {getting_started_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 4. Campaign sent
# ---------------------------------------------------------------------------

def build_campaign_sent_email(
    campaign_name: str,
    recipient_count: int,
    campaign_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(campaign_name)
    safe_url = html_escape(campaign_url)

    subject = _t("campaign_sent.subject", locale)

    inner = "\n\n".join([
        _heading(_t("campaign_sent.heading", locale)),
        _greeting(_t("campaign_sent.greeting", locale)),
        _body_text(
            _t("campaign_sent.body", locale,
               campaign_name=f"<strong>{safe_name}</strong>",
               recipient_count=f"<strong>{recipient_count}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(_t("campaign_sent.info", locale)),
        _spacer(),
        _cta_button(safe_url, _t("campaign_sent.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('campaign_sent.greeting', locale)}\n\n"
        f"{_t('campaign_sent.body', locale, campaign_name=campaign_name, recipient_count=recipient_count)}\n\n"
        f"{_t('campaign_sent.info', locale)}\n\n"
        f"{_t('campaign_sent.cta', locale)}: {campaign_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 5. Lead import complete
# ---------------------------------------------------------------------------

def build_lead_import_complete_email(
    imported_count: int,
    leads_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_url = html_escape(leads_url)

    subject = _t("lead_import_complete.subject", locale)

    inner = "\n\n".join([
        _heading(_t("lead_import_complete.heading", locale)),
        _greeting(_t("lead_import_complete.greeting", locale)),
        _body_text(
            _t("lead_import_complete.body", locale,
               imported_count=f"<strong>{imported_count}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(_t("lead_import_complete.info", locale)),
        _spacer(),
        _cta_button(safe_url, _t("lead_import_complete.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('lead_import_complete.greeting', locale)}\n\n"
        f"{_t('lead_import_complete.body', locale, imported_count=imported_count)}\n\n"
        f"{_t('lead_import_complete.info', locale)}\n\n"
        f"{_t('lead_import_complete.cta', locale)}: {leads_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 6. Warmup status update
# ---------------------------------------------------------------------------

def build_warmup_status_email(
    email_account: str,
    warmup_status: str,
    warmup_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_account = html_escape(email_account)
    safe_url = html_escape(warmup_url)

    subject = _t("warmup_status.subject", locale)

    # Pick the right info message based on status
    info_key = {
        "active": "warmup_status.info_active",
        "complete": "warmup_status.info_complete",
    }.get(warmup_status, "warmup_status.info_issue")

    inner = "\n\n".join([
        _heading(_t("warmup_status.heading", locale)),
        _greeting(_t("warmup_status.greeting", locale)),
        _body_text(
            _t("warmup_status.body", locale,
               email_account=f"<strong>{safe_account}</strong>",
               status=f"<strong>{html_escape(warmup_status)}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(_t(info_key, locale)),
        _spacer(),
        _cta_button(safe_url, _t("warmup_status.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('warmup_status.greeting', locale)}\n\n"
        f"{_t('warmup_status.body', locale, email_account=email_account, status=warmup_status)}\n\n"
        f"{_t(info_key, locale)}\n\n"
        f"{_t('warmup_status.cta', locale)}: {warmup_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 7. Payment confirmation
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

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('payment_confirmation.greeting', locale)}\n\n"
        f"{_t('payment_confirmation.body', locale, amount=amount)}\n\n"
        f"{_t('payment_confirmation.info', locale, next_billing_date=next_billing_date)}\n\n"
        f"{_t('payment_confirmation.cta', locale)}: {dashboard_url}\n\n"
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

    subject = _t("payment_failed.subject", locale)

    inner = "\n\n".join([
        _heading(_t("payment_failed.heading", locale)),
        _greeting(_t("payment_failed.greeting", locale)),
        _body_text(_t("payment_failed.body", locale), margin="0 0 24px"),
        _warning_box(_t("payment_failed.warning", locale)),
        _spacer(),
        _cta_button(safe_url, _t("payment_failed.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('payment_failed.greeting', locale)}\n\n"
        f"{_t('payment_failed.body', locale)}\n\n"
        f"{_t('payment_failed.warning', locale)}\n\n"
        f"{_t('payment_failed.cta', locale)}: {invoice_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 9. Trial ending
# ---------------------------------------------------------------------------

def build_trial_ending_email(
    trial_end_date: str,
    upgrade_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_date = html_escape(trial_end_date)
    safe_url = html_escape(upgrade_url)

    subject = _t("trial_ending.subject", locale)

    inner = "\n\n".join([
        _heading(_t("trial_ending.heading", locale)),
        _greeting(_t("trial_ending.greeting", locale)),
        _body_text(
            _t("trial_ending.body", locale, trial_end_date=f"<strong>{safe_date}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(_t("trial_ending.info", locale)),
        _spacer(),
        _cta_button(safe_url, _t("trial_ending.cta", locale)),
        _muted_text(_t("common.questions_reply", locale)),
    ])

    html_body = _wrap_feyra_layout(inner, locale)

    plain_text = (
        f"{_t('trial_ending.greeting', locale)}\n\n"
        f"{_t('trial_ending.body', locale, trial_end_date=trial_end_date)}\n\n"
        f"{_t('trial_ending.info', locale)}\n\n"
        f"{_t('trial_ending.cta', locale)}: {upgrade_url}\n\n"
        f"{_t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text
