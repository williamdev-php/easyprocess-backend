from __future__ import annotations

from datetime import datetime
from typing import Optional

import strawberry


@strawberry.type
class SubscriptionType:
    id: str
    status: str
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    trial_start: Optional[datetime]
    trial_end: Optional[datetime]
    created_at: datetime


@strawberry.type
class PaymentType:
    id: str
    amount_sek: int
    currency: str
    status: str
    invoice_url: Optional[str]
    created_at: datetime


@strawberry.type
class PaymentListType:
    items: list[PaymentType]
    total: int


@strawberry.type
class BillingDetailsType:
    id: str
    billing_name: Optional[str]
    billing_company: Optional[str]
    billing_org_number: Optional[str]
    billing_vat_number: Optional[str]
    billing_email: Optional[str]
    billing_phone: Optional[str]
    address_line1: Optional[str]
    address_line2: Optional[str]
    zip: Optional[str]
    city: Optional[str]
    country: Optional[str]


@strawberry.type
class PlanType:
    key: str
    name: str
    price_sek: int
    trial_days: int
    features: list[str]


@strawberry.type
class PaymentMethodType:
    id: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int


@strawberry.input
class UpdateBillingDetailsInput:
    billing_name: Optional[str] = None
    billing_company: Optional[str] = None
    billing_org_number: Optional[str] = None
    billing_vat_number: Optional[str] = None
    billing_email: Optional[str] = None
    billing_phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    zip: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
