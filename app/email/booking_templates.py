"""
Booking email templates.

Templates for the booking system lifecycle:
  - New booking notification (to site owner)
  - Booking confirmation (to customer)
  - Booking confirmed by owner (to customer)
  - Booking cancelled (to customer)
  - Booking completed (to customer)
  - Payment received (to customer)
  - Payment failed (to customer)
"""

from __future__ import annotations

from html import escape as html_escape

from app.email.i18n import DEFAULT_LOCALE, t
from app.email.templates import (
    _body_text,
    _cta_button,
    _greeting,
    _heading,
    _info_box,
    _muted_text,
    _spacer,
    _warning_box,
    _wrap_layout,
)


def _detail_row(label: str, value: str) -> str:
    """Render a single key-value detail row."""
    return (
        f'<tr>'
        f'<td style="padding:4px 12px 4px 0; color:#7A9BAD; font-size:14px; white-space:nowrap; vertical-align:top;">{label}</td>'
        f'<td style="padding:4px 0; color:#1A3A50; font-size:14px;">{value}</td>'
        f'</tr>'
    )


def _details_table(rows: list[tuple[str, str]]) -> str:
    """Render a detail table with label-value pairs inside an info box."""
    row_html = "\n".join(_detail_row(label, value) for label, value in rows)
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#F4E9D4; border-radius:12px; padding:20px 24px; border:1px solid #E0D8CB;">
              <table cellpadding="0" cellspacing="0" role="presentation">
{row_html}
              </table>
            </td></tr>
          </table>"""


# ---------------------------------------------------------------------------
# 1. New booking — notification to site owner
# ---------------------------------------------------------------------------

def build_booking_owner_notification_email(
    owner_name: str,
    site_name: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None,
    service_name: str | None,
    booking_date: str,
    amount: float,
    currency: str,
    payment_method: str | None,
    dashboard_url: str,
    form_data: dict | None = None,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_owner = html_escape(owner_name)
    safe_site = html_escape(site_name)
    safe_customer = html_escape(customer_name)
    safe_email = html_escape(customer_email)
    safe_dash = html_escape(dashboard_url)

    subject = t("booking_owner.subject", locale, customer_name=customer_name, site_name=site_name)

    details: list[tuple[str, str]] = [
        (t("booking_common.customer", locale), f"{safe_customer} ({safe_email})"),
    ]
    if customer_phone:
        details.append((t("booking_common.phone", locale), html_escape(customer_phone)))
    if service_name:
        details.append((t("booking_common.service", locale), html_escape(service_name)))
    details.append((t("booking_common.date", locale), html_escape(booking_date)))
    details.append((t("booking_common.amount", locale), f"{amount} {html_escape(currency)}"))
    if payment_method:
        pm_labels = t("booking_common.payment_methods", locale)
        pm_label = pm_labels.get(payment_method, payment_method) if isinstance(pm_labels, dict) else payment_method
        details.append((t("booking_common.payment_method", locale), html_escape(str(pm_label))))

    if form_data:
        for key, value in form_data.items():
            details.append((html_escape(str(key)), html_escape(str(value))))

    inner = "\n\n".join([
        _heading(t("booking_owner.heading", locale)),
        _greeting(t("booking_owner.greeting", locale, name=safe_owner)),
        _body_text(
            t("booking_owner.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _details_table(details),
        _spacer(),
        _cta_button(safe_dash, t("booking_owner.cta", locale)),
        _muted_text(t("booking_owner.manage_note", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_details = "\n".join(f"  {label}: {value}" for label, value in details)
    plain_text = (
        f"{t('booking_owner.greeting', locale, name=owner_name)}\n\n"
        f"{t('booking_owner.body', locale, site_name=site_name)}\n\n"
        f"{plain_details}\n\n"
        f"{t('booking_owner.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 2. Booking confirmation — sent to customer
# ---------------------------------------------------------------------------

def build_booking_customer_confirmation_email(
    customer_name: str,
    site_name: str,
    service_name: str | None,
    booking_date: str,
    amount: float,
    currency: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(customer_name)
    safe_site = html_escape(site_name)

    subject = t("booking_customer_confirm.subject", locale, site_name=site_name)

    details: list[tuple[str, str]] = []
    if service_name:
        details.append((t("booking_common.service", locale), html_escape(service_name)))
    details.append((t("booking_common.date", locale), html_escape(booking_date)))
    details.append((t("booking_common.amount", locale), f"{amount} {html_escape(currency)}"))

    inner = "\n\n".join([
        _heading(t("booking_customer_confirm.heading", locale)),
        _greeting(t("booking_customer_confirm.greeting", locale, name=safe_name)),
        _body_text(
            t("booking_customer_confirm.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _details_table(details),
        _spacer(),
        _info_box(t("booking_customer_confirm.info", locale)),
        _muted_text(
            t("booking_customer_confirm.footer", locale, site_name=safe_site),
            margin="28px 0 0",
        ),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_details = "\n".join(f"  {label}: {value}" for label, value in details)
    plain_text = (
        f"{t('booking_customer_confirm.greeting', locale, name=customer_name)}\n\n"
        f"{t('booking_customer_confirm.body', locale, site_name=site_name)}\n\n"
        f"{plain_details}\n\n"
        f"{t('booking_customer_confirm.info', locale)}\n\n"
        f"{t('booking_customer_confirm.footer', locale, site_name=site_name)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 3. Booking confirmed by owner — sent to customer
# ---------------------------------------------------------------------------

def build_booking_confirmed_email(
    customer_name: str,
    site_name: str,
    service_name: str | None,
    booking_date: str,
    amount: float,
    currency: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(customer_name)
    safe_site = html_escape(site_name)

    subject = t("booking_confirmed.subject", locale, site_name=site_name)

    details: list[tuple[str, str]] = []
    if service_name:
        details.append((t("booking_common.service", locale), html_escape(service_name)))
    details.append((t("booking_common.date", locale), html_escape(booking_date)))
    details.append((t("booking_common.amount", locale), f"{amount} {html_escape(currency)}"))

    inner = "\n\n".join([
        _heading(t("booking_confirmed.heading", locale)),
        _greeting(t("booking_confirmed.greeting", locale, name=safe_name)),
        _body_text(
            t("booking_confirmed.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _details_table(details),
        _spacer(),
        _info_box(t("booking_confirmed.info", locale)),
        _muted_text(
            t("booking_confirmed.footer", locale, site_name=safe_site),
            margin="28px 0 0",
        ),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_details = "\n".join(f"  {label}: {value}" for label, value in details)
    plain_text = (
        f"{t('booking_confirmed.greeting', locale, name=customer_name)}\n\n"
        f"{t('booking_confirmed.body', locale, site_name=site_name)}\n\n"
        f"{plain_details}\n\n"
        f"{t('booking_confirmed.info', locale)}\n\n"
        f"{t('booking_confirmed.footer', locale, site_name=site_name)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 4. Booking cancelled — sent to customer
# ---------------------------------------------------------------------------

def build_booking_cancelled_email(
    customer_name: str,
    site_name: str,
    service_name: str | None,
    booking_date: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(customer_name)
    safe_site = html_escape(site_name)

    subject = t("booking_cancelled.subject", locale, site_name=site_name)

    details: list[tuple[str, str]] = []
    if service_name:
        details.append((t("booking_common.service", locale), html_escape(service_name)))
    details.append((t("booking_common.date", locale), html_escape(booking_date)))

    inner = "\n\n".join([
        _heading(t("booking_cancelled.heading", locale)),
        _greeting(t("booking_cancelled.greeting", locale, name=safe_name)),
        _body_text(
            t("booking_cancelled.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _details_table(details),
        _spacer(),
        _body_text(t("booking_cancelled.contact_note", locale, site_name=safe_site), margin="0"),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_details = "\n".join(f"  {label}: {value}" for label, value in details)
    plain_text = (
        f"{t('booking_cancelled.greeting', locale, name=customer_name)}\n\n"
        f"{t('booking_cancelled.body', locale, site_name=site_name)}\n\n"
        f"{plain_details}\n\n"
        f"{t('booking_cancelled.contact_note', locale, site_name=site_name)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 5. Booking completed — sent to customer
# ---------------------------------------------------------------------------

def build_booking_completed_email(
    customer_name: str,
    site_name: str,
    service_name: str | None,
    booking_date: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(customer_name)
    safe_site = html_escape(site_name)

    subject = t("booking_completed.subject", locale, site_name=site_name)

    details: list[tuple[str, str]] = []
    if service_name:
        details.append((t("booking_common.service", locale), html_escape(service_name)))
    details.append((t("booking_common.date", locale), html_escape(booking_date)))

    inner = "\n\n".join([
        _heading(t("booking_completed.heading", locale)),
        _greeting(t("booking_completed.greeting", locale, name=safe_name)),
        _body_text(
            t("booking_completed.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _details_table(details),
        _spacer(),
        _body_text(t("booking_completed.thanks", locale, site_name=safe_site), margin="0"),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_details = "\n".join(f"  {label}: {value}" for label, value in details)
    plain_text = (
        f"{t('booking_completed.greeting', locale, name=customer_name)}\n\n"
        f"{t('booking_completed.body', locale, site_name=site_name)}\n\n"
        f"{plain_details}\n\n"
        f"{t('booking_completed.thanks', locale, site_name=site_name)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 6. Payment received — sent to customer
# ---------------------------------------------------------------------------

def build_booking_payment_received_email(
    customer_name: str,
    site_name: str,
    service_name: str | None,
    booking_date: str,
    amount: float,
    currency: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(customer_name)
    safe_site = html_escape(site_name)

    subject = t("booking_payment_received.subject", locale, site_name=site_name)

    details: list[tuple[str, str]] = []
    if service_name:
        details.append((t("booking_common.service", locale), html_escape(service_name)))
    details.append((t("booking_common.date", locale), html_escape(booking_date)))
    details.append((t("booking_common.amount", locale), f"{amount} {html_escape(currency)}"))

    inner = "\n\n".join([
        _heading(t("booking_payment_received.heading", locale)),
        _greeting(t("booking_payment_received.greeting", locale, name=safe_name)),
        _body_text(
            t("booking_payment_received.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _details_table(details),
        _spacer(),
        _info_box(t("booking_payment_received.info", locale)),
        _muted_text(
            t("booking_payment_received.footer", locale, site_name=safe_site),
            margin="28px 0 0",
        ),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_details = "\n".join(f"  {label}: {value}" for label, value in details)
    plain_text = (
        f"{t('booking_payment_received.greeting', locale, name=customer_name)}\n\n"
        f"{t('booking_payment_received.body', locale, site_name=site_name)}\n\n"
        f"{plain_details}\n\n"
        f"{t('booking_payment_received.info', locale)}\n\n"
        f"{t('booking_payment_received.footer', locale, site_name=site_name)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 7. Payment failed — sent to customer
# ---------------------------------------------------------------------------

def build_booking_payment_failed_email(
    customer_name: str,
    site_name: str,
    service_name: str | None,
    booking_date: str,
    amount: float,
    currency: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(customer_name)
    safe_site = html_escape(site_name)

    subject = t("booking_payment_failed.subject", locale, site_name=site_name)

    details: list[tuple[str, str]] = []
    if service_name:
        details.append((t("booking_common.service", locale), html_escape(service_name)))
    details.append((t("booking_common.date", locale), html_escape(booking_date)))
    details.append((t("booking_common.amount", locale), f"{amount} {html_escape(currency)}"))

    inner = "\n\n".join([
        _heading(t("booking_payment_failed.heading", locale)),
        _greeting(t("booking_payment_failed.greeting", locale, name=safe_name)),
        _body_text(
            t("booking_payment_failed.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _warning_box(t("booking_payment_failed.warning", locale)),
        _spacer(),
        _details_table(details),
        _spacer(),
        _body_text(t("booking_payment_failed.contact_note", locale, site_name=safe_site), margin="0"),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_details = "\n".join(f"  {label}: {value}" for label, value in details)
    plain_text = (
        f"{t('booking_payment_failed.greeting', locale, name=customer_name)}\n\n"
        f"{t('booking_payment_failed.body', locale, site_name=site_name)}\n\n"
        f"{t('booking_payment_failed.warning', locale)}\n\n"
        f"{plain_details}\n\n"
        f"{t('booking_payment_failed.contact_note', locale, site_name=site_name)}"
    )

    return subject, html_body, plain_text
