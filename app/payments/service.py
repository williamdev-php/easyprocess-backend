"""
Stripe Connect service for marketplace payments.

Handles connected account creation, onboarding, and payment processing
with platform fees.
"""
import logging
import stripe
from app.config import settings
from app.database import get_db_session

logger = logging.getLogger(__name__)

def _init_stripe():
    stripe.api_key = settings.STRIPE_SECRET_KEY


async def create_connect_account(site_id: str, user_id: str, email: str, country: str = "SE") -> dict:
    """Create a Stripe Connect Express account and return the account ID + onboarding URL."""
    _init_stripe()

    account = stripe.Account.create(
        type="express",
        country=country,
        email=email,
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
            "klarna_payments": {"requested": True},
        },
        business_type="individual",
        metadata={
            "site_id": site_id,
            "user_id": user_id,
            "platform": "qvicko",
        },
    )

    return {
        "account_id": account.id,
        "details_submitted": account.details_submitted,
    }


async def create_account_link(stripe_account_id: str, refresh_url: str, return_url: str) -> str:
    """Generate an onboarding link for a Connect account."""
    _init_stripe()

    link = stripe.AccountLink.create(
        account=stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link.url


async def get_account_status(stripe_account_id: str) -> dict:
    """Get the current status of a Connect account."""
    _init_stripe()

    account = stripe.Account.retrieve(stripe_account_id)
    return {
        "charges_enabled": account.charges_enabled,
        "payouts_enabled": account.payouts_enabled,
        "details_submitted": account.details_submitted,
        "requirements": {
            "currently_due": account.requirements.currently_due if account.requirements else [],
            "past_due": account.requirements.past_due if account.requirements else [],
        },
    }


async def create_payment_intent(
    amount_cents: int,
    currency: str,
    connected_account_id: str,
    platform_fee_cents: int,
    metadata: dict | None = None,
) -> dict:
    """Create a PaymentIntent on a connected account with platform fee."""
    _init_stripe()

    payment_methods = ["card"]
    # Klarna only available for certain currencies/countries
    if currency.upper() in ("SEK", "EUR", "NOK", "DKK", "GBP", "USD"):
        payment_methods.append("klarna")

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency=currency.lower(),
        payment_method_types=payment_methods,
        application_fee_amount=platform_fee_cents,
        transfer_data={
            "destination": connected_account_id,
        },
        metadata=metadata or {},
    )

    return {
        "payment_intent_id": intent.id,
        "client_secret": intent.client_secret,
        "status": intent.status,
    }


async def create_refund(payment_intent_id: str, amount_cents: int | None = None) -> dict:
    """Refund a payment. If amount_cents is None, full refund."""
    _init_stripe()

    params = {"payment_intent": payment_intent_id}
    if amount_cents is not None:
        params["amount"] = amount_cents
    # Reverse the transfer to debit the connected account
    params["reverse_transfer"] = True

    refund = stripe.Refund.create(**params)
    return {
        "refund_id": refund.id,
        "status": refund.status,
        "amount": refund.amount,
    }


async def get_account_balance(stripe_account_id: str) -> dict:
    """Get balance for a connected account."""
    _init_stripe()

    balance = stripe.Balance.retrieve(stripe_account_id=stripe_account_id)
    available = balance.available[0] if balance.available else {"amount": 0, "currency": "sek"}
    pending = balance.pending[0] if balance.pending else {"amount": 0, "currency": "sek"}

    return {
        "available_amount": available.get("amount", 0),
        "pending_amount": pending.get("amount", 0),
        "currency": available.get("currency", "sek"),
    }
