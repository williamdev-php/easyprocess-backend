"""
Contact form email templates.

Templates for the public contact form on viewer sites:
  - Contact form notification (to site owner)
  - Contact form confirmation (to visitor)
"""

from __future__ import annotations

from html import escape as html_escape

from app.email.i18n import DEFAULT_LOCALE, t
from app.email.templates import (
    _body_text,
    _greeting,
    _heading,
    _info_box,
    _muted_text,
    _spacer,
    _wrap_layout,
)


# ---------------------------------------------------------------------------
# 1. Contact form notification — sent to site owner
# ---------------------------------------------------------------------------

def build_contact_form_owner_email(
    owner_name: str,
    site_name: str,
    visitor_name: str,
    visitor_email: str,
    message: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_owner = html_escape(owner_name)
    safe_site = html_escape(site_name)
    safe_visitor = html_escape(visitor_name)
    safe_email = html_escape(visitor_email)
    safe_message = html_escape(message)

    subject = t("contact_owner.subject", locale, visitor_name=visitor_name, site_name=site_name)

    message_box = f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#F4E9D4; border-radius:12px; padding:20px 24px; border:1px solid #E0D8CB;">
              <p style="color:#7A9BAD; font-size:12px; margin:0 0 8px; text-transform:uppercase; letter-spacing:0.5px;">
                {t("contact_owner.from_label", locale)}
              </p>
              <p style="color:#1A3A50; font-size:14px; margin:0 0 4px;">
                <strong>{safe_visitor}</strong> &mdash; <a href="mailto:{safe_email}" style="color:#326586; text-decoration:underline;">{safe_email}</a>
              </p>
              <hr style="border:none; border-top:1px solid #E0D8CB; margin:12px 0;" />
              <p style="color:#1A3A50; font-size:14px; line-height:1.6; margin:0; white-space:pre-wrap;">{safe_message}</p>
            </td></tr>
          </table>"""

    inner = "\n\n".join([
        _heading(t("contact_owner.heading", locale)),
        _greeting(t("contact_owner.greeting", locale, name=safe_owner)),
        _body_text(
            t("contact_owner.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        message_box,
        _spacer(),
        _muted_text(
            t("contact_owner.reply_note", locale, email=f'<a href="mailto:{safe_email}" style="color:#326586; text-decoration:underline;">{safe_email}</a>'),
        ),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('contact_owner.greeting', locale, name=owner_name)}\n\n"
        f"{t('contact_owner.body', locale, site_name=site_name)}\n\n"
        f"{t('contact_owner.from_label', locale)}\n"
        f"  {visitor_name} — {visitor_email}\n\n"
        f"{message}\n\n"
        f"{t('contact_owner.reply_note', locale, email=visitor_email)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 2. Contact form confirmation — sent to visitor
# ---------------------------------------------------------------------------

def build_contact_form_visitor_email(
    visitor_name: str,
    site_name: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(visitor_name)
    safe_site = html_escape(site_name)

    subject = t("contact_visitor.subject", locale, site_name=site_name)

    inner = "\n\n".join([
        _heading(t("contact_visitor.heading", locale)),
        _greeting(t("contact_visitor.greeting", locale, name=safe_name)),
        _body_text(
            t("contact_visitor.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(t("contact_visitor.info", locale)),
        _spacer(),
        _muted_text(
            t("contact_visitor.footer", locale, site_name=safe_site),
            margin="0",
        ),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('contact_visitor.greeting', locale, name=visitor_name)}\n\n"
        f"{t('contact_visitor.body', locale, site_name=site_name)}\n\n"
        f"{t('contact_visitor.info', locale)}\n\n"
        f"{t('contact_visitor.footer', locale, site_name=site_name)}"
    )

    return subject, html_body, plain_text
