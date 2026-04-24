"""
Payment email templates for Stripe Connect.

Templates for payment lifecycle events sent to site owners:
  - Payout initiated (money leaving Stripe → bank)
  - Payout completed
  - Payout failed
  - Chargeback / dispute received
  - Negative balance warning
  - Negative balance overdue
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


def _amount_display(amount: float, currency: str) -> str:
    """Format amount with currency for display."""
    return f"{amount:.2f} {html_escape(currency.upper())}"


# ---------------------------------------------------------------------------
# 1. Payout initiated — money on its way to bank
# ---------------------------------------------------------------------------

def build_payout_initiated_email(
    owner_name: str,
    site_name: str,
    amount: float,
    currency: str,
    estimated_arrival: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(owner_name)
    safe_site = html_escape(site_name)
    safe_dash = html_escape(dashboard_url)
    amt = _amount_display(amount, currency)

    subject = t("payout_initiated.subject", locale, amount=amt)

    inner = "\n\n".join([
        _heading(t("payout_initiated.heading", locale)),
        _greeting(t("payout_initiated.greeting", locale, name=safe_name)),
        _body_text(
            t("payout_initiated.body", locale,
              amount=f"<strong>{amt}</strong>",
              site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(
            t("payout_initiated.arrival_info", locale,
              estimated_arrival=f"<strong>{html_escape(estimated_arrival)}</strong>")
        ),
        _spacer(),
        _cta_button(safe_dash, t("payout_initiated.cta", locale)),
        _muted_text(t("payout_initiated.note", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('payout_initiated.greeting', locale, name=owner_name)}\n\n"
        f"{t('payout_initiated.body', locale, amount=amt, site_name=site_name)}\n\n"
        f"{t('payout_initiated.arrival_info', locale, estimated_arrival=estimated_arrival)}\n\n"
        f"{t('payout_initiated.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 2. Payout completed
# ---------------------------------------------------------------------------

def build_payout_completed_email(
    owner_name: str,
    site_name: str,
    amount: float,
    currency: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(owner_name)
    safe_site = html_escape(site_name)
    safe_dash = html_escape(dashboard_url)
    amt = _amount_display(amount, currency)

    subject = t("payout_completed.subject", locale, amount=amt)

    inner = "\n\n".join([
        _heading(t("payout_completed.heading", locale)),
        _greeting(t("payout_completed.greeting", locale, name=safe_name)),
        _body_text(
            t("payout_completed.body", locale,
              amount=f"<strong>{amt}</strong>",
              site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _info_box(t("payout_completed.info", locale)),
        _spacer(),
        _cta_button(safe_dash, t("payout_completed.cta", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('payout_completed.greeting', locale, name=owner_name)}\n\n"
        f"{t('payout_completed.body', locale, amount=amt, site_name=site_name)}\n\n"
        f"{t('payout_completed.info', locale)}\n\n"
        f"{t('payout_completed.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 3. Payout failed
# ---------------------------------------------------------------------------

def build_payout_failed_email(
    owner_name: str,
    site_name: str,
    amount: float,
    currency: str,
    failure_reason: str | None,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(owner_name)
    safe_site = html_escape(site_name)
    safe_dash = html_escape(dashboard_url)
    amt = _amount_display(amount, currency)

    subject = t("payout_failed.subject", locale, amount=amt)

    warning_text = t("payout_failed.warning", locale)
    if failure_reason:
        warning_text += f"<br><br><strong>{t('payout_failed.reason_label', locale)}</strong> {html_escape(failure_reason)}"

    inner = "\n\n".join([
        _heading(t("payout_failed.heading", locale)),
        _greeting(t("payout_failed.greeting", locale, name=safe_name)),
        _body_text(
            t("payout_failed.body", locale,
              amount=f"<strong>{amt}</strong>",
              site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _warning_box(warning_text),
        _spacer(),
        _cta_button(safe_dash, t("payout_failed.cta", locale)),
        _muted_text(t("common.questions_reply", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('payout_failed.greeting', locale, name=owner_name)}\n\n"
        f"{t('payout_failed.body', locale, amount=amt, site_name=site_name)}\n\n"
        f"{t('payout_failed.warning', locale)}\n"
        f"{(t('payout_failed.reason_label', locale) + ' ' + failure_reason) if failure_reason else ''}\n\n"
        f"{t('payout_failed.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 4. Chargeback / dispute received
# ---------------------------------------------------------------------------

def build_chargeback_received_email(
    owner_name: str,
    site_name: str,
    amount: float,
    currency: str,
    customer_name: str,
    reason: str | None,
    respond_by: str | None,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(owner_name)
    safe_site = html_escape(site_name)
    safe_customer = html_escape(customer_name)
    safe_dash = html_escape(dashboard_url)
    amt = _amount_display(amount, currency)

    subject = t("chargeback_received.subject", locale, amount=amt)

    warning_parts = [t("chargeback_received.warning", locale, amount=f"<strong>{amt}</strong>", customer_name=safe_customer)]
    if reason:
        warning_parts.append(f"<br><strong>{t('chargeback_received.reason_label', locale)}</strong> {html_escape(reason)}")
    if respond_by:
        warning_parts.append(f"<br><strong>{t('chargeback_received.respond_by_label', locale)}</strong> {html_escape(respond_by)}")

    inner = "\n\n".join([
        _heading(t("chargeback_received.heading", locale)),
        _greeting(t("chargeback_received.greeting", locale, name=safe_name)),
        _body_text(
            t("chargeback_received.body", locale, site_name=f"<strong>{safe_site}</strong>"),
            margin="0 0 24px",
        ),
        _warning_box("".join(warning_parts)),
        _spacer(),
        _info_box(t("chargeback_received.action_info", locale)),
        _spacer(),
        _cta_button(safe_dash, t("chargeback_received.cta", locale)),
        _muted_text(t("common.questions_reply", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('chargeback_received.greeting', locale, name=owner_name)}\n\n"
        f"{t('chargeback_received.body', locale, site_name=site_name)}\n\n"
        f"{t('chargeback_received.warning', locale, amount=amt, customer_name=customer_name)}\n"
        f"{(t('chargeback_received.reason_label', locale) + ' ' + reason) if reason else ''}\n"
        f"{(t('chargeback_received.respond_by_label', locale) + ' ' + respond_by) if respond_by else ''}\n\n"
        f"{t('chargeback_received.action_info', locale)}\n\n"
        f"{t('chargeback_received.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 5. Negative balance warning
# ---------------------------------------------------------------------------

def build_negative_balance_warning_email(
    owner_name: str,
    site_name: str,
    balance: float,
    currency: str,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(owner_name)
    safe_site = html_escape(site_name)
    safe_dash = html_escape(dashboard_url)
    bal = _amount_display(abs(balance), currency)

    subject = t("negative_balance_warning.subject", locale)

    inner = "\n\n".join([
        _heading(t("negative_balance_warning.heading", locale)),
        _greeting(t("negative_balance_warning.greeting", locale, name=safe_name)),
        _body_text(
            t("negative_balance_warning.body", locale,
              site_name=f"<strong>{safe_site}</strong>",
              balance=f"<strong>-{bal}</strong>"),
            margin="0 0 24px",
        ),
        _warning_box(t("negative_balance_warning.warning", locale)),
        _spacer(),
        _info_box(t("negative_balance_warning.info", locale)),
        _spacer(),
        _cta_button(safe_dash, t("negative_balance_warning.cta", locale)),
        _muted_text(t("common.questions_reply", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('negative_balance_warning.greeting', locale, name=owner_name)}\n\n"
        f"{t('negative_balance_warning.body', locale, site_name=site_name, balance=f'-{bal}')}\n\n"
        f"{t('negative_balance_warning.warning', locale)}\n\n"
        f"{t('negative_balance_warning.info', locale)}\n\n"
        f"{t('negative_balance_warning.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 6. Negative balance overdue — persistent negative balance
# ---------------------------------------------------------------------------

def build_negative_balance_overdue_email(
    owner_name: str,
    site_name: str,
    balance: float,
    currency: str,
    days_negative: int,
    dashboard_url: str,
    locale: str = DEFAULT_LOCALE,
) -> tuple[str, str, str]:
    safe_name = html_escape(owner_name)
    safe_site = html_escape(site_name)
    safe_dash = html_escape(dashboard_url)
    bal = _amount_display(abs(balance), currency)

    subject = t("negative_balance_overdue.subject", locale, balance=f"-{bal}")

    inner = "\n\n".join([
        _heading(t("negative_balance_overdue.heading", locale)),
        _greeting(t("negative_balance_overdue.greeting", locale, name=safe_name)),
        _body_text(
            t("negative_balance_overdue.body", locale,
              site_name=f"<strong>{safe_site}</strong>",
              balance=f"<strong>-{bal}</strong>",
              days_negative=f"<strong>{days_negative}</strong>"),
            margin="0 0 24px",
        ),
        _warning_box(f"<strong>{t('negative_balance_overdue.warning', locale)}</strong>"),
        _spacer(),
        _info_box(t("negative_balance_overdue.action_info", locale)),
        _spacer(),
        _cta_button(safe_dash, t("negative_balance_overdue.cta", locale)),
        _muted_text(t("common.questions_reply", locale)),
    ])

    html_body = _wrap_layout(inner, locale)

    plain_text = (
        f"{t('negative_balance_overdue.greeting', locale, name=owner_name)}\n\n"
        f"{t('negative_balance_overdue.body', locale, site_name=site_name, balance=f'-{bal}', days_negative=days_negative)}\n\n"
        f"{t('negative_balance_overdue.warning', locale)}\n\n"
        f"{t('negative_balance_overdue.action_info', locale)}\n\n"
        f"{t('negative_balance_overdue.cta', locale)}: {dashboard_url}\n\n"
        f"{t('common.sign_off', locale)}"
    )

    return subject, html_body, plain_text
