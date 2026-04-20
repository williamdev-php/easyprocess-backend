"""
Email templates for Qvicko.

Outreach emails are plain text only (to appear hand-written).
All other templates share a unified HTML design based on the frontend palette:
  Background (sand mist): #FDFAF5
  Primary (petrol blue):  #326586
  Primary dark:           #24506E
  Text (primary deep):    #1A3A50
  Accent:                 #F4E9D4
  Surface:                #FFFFFF
  Border:                 #E0D8CB
  Border light:           #EDE7DC
  Text secondary:         #4A7A96
  Text muted:             #7A9BAD
"""

from __future__ import annotations

from html import escape as html_escape

from app.email.i18n import DEFAULT_LOCALE, t


# ---------------------------------------------------------------------------
# Shared layout helpers
# ---------------------------------------------------------------------------

def _wrap_layout(inner_html: str, locale: str = DEFAULT_LOCALE) -> str:
    """Wrap content in the shared email layout."""
    footer = html_escape(t("common.footer_rights", locale))
    return f"""<!DOCTYPE html>
<html lang="{locale}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#FDFAF5; font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif; -webkit-font-smoothing:antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background-color:#FDFAF5; padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px; width:100%; background:#FFFFFF; border-radius:16px; border:1px solid #E0D8CB; overflow:hidden;">

        <!-- Header -->
        <tr><td style="background:#326586; padding:28px 40px; text-align:center;">
          <img src="https://qvicko.com/logo-sand-mist.png" alt="Qvicko" width="140" style="display:inline-block; height:auto; max-width:140px;" />
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:40px;">
{inner_html}
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 40px; border-top:1px solid #EDE7DC; text-align:center;">
          <p style="color:#7A9BAD; font-size:12px; margin:0;">
            {footer}
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _cta_button(url: str, label: str) -> str:
    """Render a centred CTA button in petrol blue."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td align="center" style="padding:8px 0;">
              <a href="{url}" style="display:inline-block; background:#326586; color:#FFFFFF; text-decoration:none; padding:14px 36px; border-radius:12px; font-size:15px; font-weight:600;">
                {label}
              </a>
            </td></tr>
          </table>"""


def _info_box(text: str) -> str:
    """Render a sand-mist info box with accent background."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#F4E9D4; border-radius:12px; padding:20px 24px; border:1px solid #E0D8CB;">
              <p style="color:#1A3A50; font-size:14px; line-height:1.6; margin:0;">
                {text}
              </p>
            </td></tr>
          </table>"""


def _warning_box(text: str) -> str:
    """Render a red warning box."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#FDF0F0; border-radius:12px; padding:20px 24px; border:1px solid #E0D8CB;">
              <p style="color:#C44D4D; font-size:14px; line-height:1.6; margin:0;">
                {text}
              </p>
            </td></tr>
          </table>"""


def _heading(text: str) -> str:
    return f'          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">{text}</h2>'


def _greeting(text: str) -> str:
    return f"""          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            {text}
          </p>"""


def _body_text(text: str, margin: str = "0 0 28px") -> str:
    return f"""          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:{margin};">
            {text}
          </p>"""


def _muted_text(text: str, size: str = "13px", margin: str = "28px 0 0") -> str:
    return f"""          <p style="color:#7A9BAD; font-size:{size}; line-height:1.5; margin:{margin};">
            {text}
          </p>"""


def _spacer() -> str:
    return '          <div style="height:24px;"></div>'


# ---------------------------------------------------------------------------
# 1. Outreach email (plain text only — looks hand-written)
#    NOTE: Outreach is marketing, not transactional. Swedish only.
# ---------------------------------------------------------------------------

def build_outreach_email(
    business_name: str,
    demo_url: str,
    from_name: str = "Qvicko",
) -> tuple[str, str, str]:
    """
    Build subject, html_body, and plain_text for an outreach email.
    Returns (subject, html_body, plain_text).

    NOTE: html_body is intentionally minimal — plain text is the primary
    format so the email looks personally written, not templated.
    """
    subject = f"{business_name} — vi har skapat ett förslag på en ny hemsida åt er"
    subject = subject.replace("\n", "").replace("\r", "")

    plain_text = (
        f"Hej {business_name}!\n"
        f"\n"
        f"Jag hittade er hemsida och såg att det finns potential att modernisera den.\n"
        f"Därför tog jag mig friheten att skapa ett förslag på hur en ny, modern\n"
        f"hemsida skulle kunna se ut för er.\n"
        f"\n"
        f"Jag har utgått från ert befintliga innehåll, era färger och er profil\n"
        f"för att skapa något som känns rätt för just ert företag.\n"
        f"\n"
        f"Kolla in förslaget här: {demo_url}\n"
        f"\n"
        f"Förslaget är helt kostnadsfritt och utan förpliktelser. Om ni gillar det\n"
        f"kan vi prata vidare om hur jag kan hjälpa er att komma igång.\n"
        f"\n"
        f"Hör gärna av er om ni har frågor!\n"
        f"\n"
        f"Vänliga hälsningar,\n"
        f"{from_name}"
    )

    html_body = (
        f"<div style=\"font-family:sans-serif; font-size:14px; color:#222; line-height:1.6;\">"
        f"<p>Hej {html_escape(business_name)}!</p>"
        f"<p>Jag hittade er hemsida och såg att det finns potential att modernisera den. "
        f"Därför tog jag mig friheten att skapa ett förslag på hur en ny, modern "
        f"hemsida skulle kunna se ut för er.</p>"
        f"<p>Jag har utgått från ert befintliga innehåll, era färger och er profil "
        f"för att skapa något som känns rätt för just ert företag.</p>"
        f"<p>Kolla in förslaget här: <a href=\"{html_escape(demo_url)}\">{html_escape(demo_url)}</a></p>"
        f"<p>Förslaget är helt kostnadsfritt och utan förpliktelser. Om ni gillar det "
        f"kan vi prata vidare om hur jag kan hjälpa er att komma igång.</p>"
        f"<p>Hör gärna av er om ni har frågor!</p>"
        f"<p>Vänliga hälsningar,<br>{html_escape(from_name)}</p>"
        f"</div>"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 2. Password reset email
# ---------------------------------------------------------------------------

def build_password_reset_email(
    reset_url: str,
    user_name: str | None = None,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    name = user_name or t("common.default_user_name", locale)
    safe_name = html_escape(name)
    safe_url = html_escape(reset_url)

    subject = t("password_reset.subject", locale)

    inner = "\n\n".join([
        _heading(t("password_reset.heading", locale)),
        _greeting(t("password_reset.greeting", locale, name=safe_name)),
        _body_text(t("password_reset.body", locale)),
        _cta_button(safe_url, t("password_reset.cta", locale)),
        _muted_text(t("common.ignore_if_not_requested", locale)),
        _muted_text(
            f'{t("common.copy_link_prefix", locale)} {safe_url}',
            size="12px", margin="16px 0 0",
        ),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('password_reset.greeting', locale, name=name)}\n\n"
        f"{t('password_reset.body', locale)}\n\n"
        f"{t('password_reset.cta', locale)}: {reset_url}\n\n"
        f"{t('common.ignore_if_not_requested', locale)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 3. Email verification
# ---------------------------------------------------------------------------

def build_verification_email(
    verify_url: str,
    user_name: str | None = None,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    name = user_name or t("common.default_user_name", locale)
    safe_name = html_escape(name)
    safe_url = html_escape(verify_url)

    subject = t("verification.subject", locale)

    inner = "\n\n".join([
        _heading(t("verification.heading", locale)),
        _greeting(t("verification.greeting", locale, name=safe_name)),
        _body_text(t("verification.body", locale)),
        _cta_button(safe_url, t("verification.cta", locale)),
        _muted_text(t("verification.ignore", locale)),
        _muted_text(
            f'{t("common.copy_link_prefix", locale)} {safe_url}',
            size="12px", margin="16px 0 0",
        ),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('verification.greeting', locale, name=name)}\n\n"
        f"{t('verification.body', locale)}\n\n"
        f"{t('verification.cta', locale)}: {verify_url}\n\n"
        f"{t('verification.ignore', locale)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 4. Site published — welcome (day 0)
# ---------------------------------------------------------------------------

def build_site_published_email(
    user_name: str,
    business_name: str,
    site_url: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_site = html_escape(site_url)
    safe_dash = html_escape(dashboard_url)

    subject = t("site_published.subject", locale, business_name=business_name)

    dashboard_text = t(
        "site_published.dashboard_text", locale,
        link_start=f'<a href="{safe_dash}" style="color:#326586; text-decoration:underline;">',
        link_end="</a>",
    )

    inner = "\n\n".join([
        _heading(t("site_published.heading", locale)),
        _greeting(t("site_published.greeting", locale, name=safe_name)),
        _body_text(
            t("site_published.body", locale, business_name=f"<strong>{safe_biz}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(t("site_published.trial_info", locale)),
        _spacer(),
        _cta_button(safe_site, t("site_published.cta", locale)),
        _body_text(dashboard_text, margin="28px 0 0"),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('site_published.greeting', locale, name=user_name)}\n\n"
        f"{t('site_published.body', locale, business_name=business_name)}\n\n"
        f"{t('site_published.cta', locale)}: {site_url}\n\n"
        f"{t('site_published.trial_info', locale)}\n\n"
        f"{t('site_published.dashboard_text', locale, link_start='', link_end='')}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 5. Free trial ending soon (day ~25)
# ---------------------------------------------------------------------------

def build_trial_ending_email(
    user_name: str,
    business_name: str,
    days_left: int,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_dash = html_escape(dashboard_url)

    subject = t("trial_ending.subject", locale, business_name=business_name, days_left=days_left)

    inner = "\n\n".join([
        _heading(t("trial_ending.heading", locale)),
        _greeting(t("trial_ending.greeting", locale, name=safe_name)),
        _body_text(
            t("trial_ending.body", locale, business_name=f"<strong>{safe_biz}</strong>", days_left=f"<strong>{days_left}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(t("trial_ending.info", locale)),
        _spacer(),
        _cta_button(safe_dash, t("trial_ending.cta", locale)),
        _muted_text(t("common.questions_reply", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('trial_ending.greeting', locale, name=user_name)}\n\n"
        f"{t('trial_ending.body', locale, business_name=business_name, days_left=days_left)}\n\n"
        f"{t('trial_ending.info', locale)}\n\n"
        f"{t('trial_ending.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.questions_reply', locale)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 6. Site paused — free period expired (day 30)
# ---------------------------------------------------------------------------

def build_site_paused_email(
    user_name: str,
    business_name: str,
    days_until_deletion: int,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_dash = html_escape(dashboard_url)

    subject = t("site_paused.subject", locale, business_name=business_name)

    inner = "\n\n".join([
        _heading(t("site_paused.heading", locale)),
        _greeting(t("site_paused.greeting", locale, name=safe_name)),
        _body_text(
            t("site_paused.body", locale, business_name=f"<strong>{safe_biz}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(
            f"<strong>{t('site_paused.info', locale, days_until_deletion=days_until_deletion)}</strong>"
        ),
        _spacer(),
        _cta_button(safe_dash, t("site_paused.cta", locale)),
        _muted_text(t("common.questions_reply", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('site_paused.greeting', locale, name=user_name)}\n\n"
        f"{t('site_paused.body', locale, business_name=business_name)}\n\n"
        f"{t('site_paused.info', locale, days_until_deletion=days_until_deletion)}\n\n"
        f"{t('site_paused.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.questions_reply', locale)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 7. Final warning — site about to be deleted (day ~42)
# ---------------------------------------------------------------------------

def build_site_deletion_warning_email(
    user_name: str,
    business_name: str,
    days_until_deletion: int,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_dash = html_escape(dashboard_url)

    subject = t("site_deletion_warning.subject", locale, days_until_deletion=days_until_deletion)

    inner = "\n\n".join([
        _heading(t("site_deletion_warning.heading", locale)),
        _greeting(t("site_deletion_warning.greeting", locale, name=safe_name)),
        _body_text(
            t("site_deletion_warning.body", locale,
              business_name=f"<strong>{safe_biz}</strong>",
              days_until_deletion=f"<strong>{days_until_deletion}</strong>"),
            margin="0 0 24px",
        ),
        _warning_box(f"<strong>{t('site_deletion_warning.warning', locale)}</strong>"),
        _spacer(),
        _cta_button(safe_dash, t("site_deletion_warning.cta", locale)),
        _muted_text(t("common.questions_reply", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('site_deletion_warning.greeting', locale, name=user_name)}\n\n"
        f"{t('site_deletion_warning.body', locale, business_name=business_name, days_until_deletion=days_until_deletion)}\n\n"
        f"{t('site_deletion_warning.warning', locale)}\n\n"
        f"{t('site_deletion_warning.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.questions_reply', locale)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 8. Site deleted (day 45)
# ---------------------------------------------------------------------------

def build_site_deleted_email(
    user_name: str,
    business_name: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)

    subject = t("site_deleted.subject", locale, business_name=business_name)

    inner = "\n\n".join([
        _heading(t("site_deleted.heading", locale)),
        _greeting(t("site_deleted.greeting", locale, name=safe_name)),
        _body_text(
            t("site_deleted.body", locale, business_name=f"<strong>{safe_biz}</strong>"),
            margin="0 0 24px",
        ),
        _body_text(t("site_deleted.content_removed", locale), margin="0 0 16px"),
        _body_text(t("site_deleted.welcome_back", locale), margin="0"),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('site_deleted.greeting', locale, name=user_name)}\n\n"
        f"{t('site_deleted.body', locale, business_name=business_name)}\n\n"
        f"{t('site_deleted.content_removed', locale)}\n\n"
        f"{t('site_deleted.welcome_back', locale)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 9. Payment method added confirmation
# ---------------------------------------------------------------------------

def build_payment_method_added_email(
    user_name: str,
    business_name: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_dash = html_escape(dashboard_url)

    subject = t("payment_method_added.subject", locale, business_name=business_name)

    inner = "\n\n".join([
        _heading(t("payment_method_added.heading", locale)),
        _greeting(t("payment_method_added.greeting", locale, name=safe_name)),
        _body_text(
            t("payment_method_added.body", locale, business_name=f"<strong>{safe_biz}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(t("payment_method_added.info", locale)),
        _spacer(),
        _cta_button(safe_dash, t("payment_method_added.cta", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('payment_method_added.greeting', locale, name=user_name)}\n\n"
        f"{t('payment_method_added.body', locale, business_name=business_name)}\n\n"
        f"{t('payment_method_added.info', locale)}\n\n"
        f"{t('payment_method_added.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 10. Support ticket: confirmation
# ---------------------------------------------------------------------------

def build_ticket_created_email(
    user_name: str,
    ticket_subject: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_subj = html_escape(ticket_subject)
    safe_dash = html_escape(dashboard_url)

    subject = t("ticket_created.subject", locale)

    inner = "\n\n".join([
        _heading(t("ticket_created.heading", locale)),
        _greeting(t("ticket_created.greeting", locale, name=safe_name)),
        _body_text(t("ticket_created.body", locale), margin="0 0 24px"),
        _info_box(f"<strong>{t('ticket_created.subject_label', locale)}</strong> {safe_subj}"),
        _spacer(),
        _body_text(t("ticket_created.follow_status", locale), margin="0 0 24px"),
        _cta_button(safe_dash, t("ticket_created.cta", locale)),
        _muted_text(t("ticket_created.response_time", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('ticket_created.greeting', locale, name=user_name)}\n\n"
        f"{t('ticket_created.body', locale)}\n\n"
        f"{t('ticket_created.subject_label', locale)} {ticket_subject}\n\n"
        f"{t('ticket_created.follow_status', locale)}: {dashboard_url}\n\n"
        f"{t('ticket_created.response_time', locale)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 11. Support ticket: admin replied
# ---------------------------------------------------------------------------

def build_ticket_replied_email(
    user_name: str,
    ticket_subject: str,
    admin_reply: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_subj = html_escape(ticket_subject)
    safe_reply = html_escape(admin_reply)
    safe_dash = html_escape(dashboard_url)

    subject = t("ticket_replied.subject", locale, ticket_subject=ticket_subject)

    inner = "\n\n".join([
        _heading(t("ticket_replied.heading", locale)),
        _greeting(t("ticket_replied.greeting", locale, name=safe_name)),
        _body_text(
            t("ticket_replied.body", locale, ticket_subject=f"<strong>&ldquo;{safe_subj}&rdquo;</strong>"),
            margin="0 0 24px",
        ),
        _info_box(safe_reply.replace("\n", "<br>")),
        _spacer(),
        _cta_button(safe_dash, t("ticket_replied.cta", locale)),
        _muted_text(t("ticket_replied.conversation_note", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('ticket_replied.greeting', locale, name=user_name)}\n\n"
        f"{t('ticket_replied.body', locale, ticket_subject=ticket_subject)}\n\n"
        f"{admin_reply}\n\n"
        f"{t('ticket_replied.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 12. Support ticket: status changed
# ---------------------------------------------------------------------------

def build_ticket_status_email(
    user_name: str,
    ticket_subject: str,
    new_status: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_subj = html_escape(ticket_subject)
    safe_dash = html_escape(dashboard_url)

    status_labels: dict = t("ticket_status.status_labels", locale)  # type: ignore[assignment]
    status_text = status_labels.get(new_status, new_status)

    subject = t("ticket_status.subject", locale, ticket_subject=ticket_subject)

    inner = "\n\n".join([
        _heading(t("ticket_status.heading", locale)),
        _greeting(t("ticket_status.greeting", locale, name=safe_name)),
        _body_text(
            t("ticket_status.body", locale,
              ticket_subject=f"<strong>&ldquo;{safe_subj}&rdquo;</strong>",
              status_text=status_text),
            margin="0 0 24px",
        ),
        _cta_button(safe_dash, t("ticket_status.cta", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('ticket_status.greeting', locale, name=user_name)}\n\n"
        f"{t('ticket_status.body', locale, ticket_subject=ticket_subject, status_text=status_text)}\n\n"
        f"{t('ticket_status.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 13. Site deletion confirmation email
# ---------------------------------------------------------------------------

def build_site_deletion_email(
    site_name: str,
    token: str,
    frontend_url: str = "https://qvicko.com",
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    """Build subject, html_body, and plain_text for site deletion confirmation."""
    safe_name = html_escape(site_name)
    confirm_url = f"{frontend_url}/{locale}/dashboard/pages?confirm_delete={token}"
    safe_url = html_escape(confirm_url)

    subject = t("site_deletion_confirm.subject", locale, site_name=site_name)

    inner = "\n\n".join([
        _heading(t("site_deletion_confirm.heading", locale)),
        _body_text(
            t("site_deletion_confirm.body", locale, site_name=f"<strong>{safe_name}</strong>"),
            margin="0 0 12px",
        ),
        _body_text(t("site_deletion_confirm.warning", locale), margin="0 0 24px"),
        _cta_button(safe_url, t("site_deletion_confirm.cta", locale)),
        _muted_text(t("site_deletion_confirm.ignore", locale)),
        _muted_text(
            f'{t("common.copy_link_prefix", locale)} {safe_url}',
            size="12px", margin="16px 0 0",
        ),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('site_deletion_confirm.body', locale, site_name=site_name)}\n\n"
        f"{t('site_deletion_confirm.warning', locale)}\n\n"
        f"{t('site_deletion_confirm.cta', locale)}: {confirm_url}\n\n"
        f"{t('site_deletion_confirm.ignore', locale)}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text
