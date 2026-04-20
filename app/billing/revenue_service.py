"""
Stripe revenue stats for super-admin dashboard.

Fetches live data from Stripe API: charges, subscriptions, MRR.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe

from app.config import settings

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


async def get_revenue_stats(limit: int = 30) -> dict:
    """Fetch revenue metrics and recent charges from Stripe."""

    # --- Active & trialing subscriptions ---
    active_subs = stripe.Subscription.list(status="active", limit=100)
    trialing_subs = stripe.Subscription.list(status="trialing", limit=100)

    active_count = len(active_subs.data)
    trialing_count = len(trialing_subs.data)

    # --- MRR (sum of active subscription amounts) ---
    mrr = 0
    for sub in active_subs.data:
        for item in sub["items"]["data"]:
            # amount in öre (SEK cents)
            mrr += item["price"]["unit_amount"] * item["quantity"]

    # --- Recent charges ---
    charges = stripe.Charge.list(limit=limit, expand=["data.customer"])

    total_revenue = 0
    total_refunded = 0
    recent_charges = []

    for ch in charges.data:
        if ch.status == "succeeded":
            total_revenue += ch.amount
        if ch.amount_refunded:
            total_refunded += ch.amount_refunded

        # Extract card info
        card_brand = None
        card_last4 = None
        if ch.payment_method_details and ch.payment_method_details.get("card"):
            card = ch.payment_method_details["card"]
            card_brand = card.get("brand")
            card_last4 = card.get("last4")

        # Extract customer info
        customer_email = None
        customer_name = None
        if ch.customer and isinstance(ch.customer, stripe.Customer):
            customer_email = ch.customer.email
            customer_name = ch.customer.name
        elif ch.billing_details:
            customer_email = ch.billing_details.get("email")
            customer_name = ch.billing_details.get("name")

        recent_charges.append({
            "id": ch.id,
            "amount_sek": ch.amount,
            "currency": ch.currency,
            "status": ch.status,
            "description": ch.description,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "card_brand": card_brand,
            "card_last4": card_last4,
            "created_at": datetime.fromtimestamp(ch.created, tz=timezone.utc),
        })

    return {
        "mrr_sek": mrr,
        "total_revenue_sek": total_revenue,
        "active_subscriptions": active_count,
        "trialing_subscriptions": trialing_count,
        "charges_count": len(charges.data),
        "refunded_sek": total_refunded,
        "recent_charges": recent_charges,
    }
