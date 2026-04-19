from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import strawberry
from sqlalchemy import func, select, or_
from sqlalchemy.orm import selectinload
from strawberry.scalars import JSON
from strawberry.types import Info

from pydantic import ValidationError

from app.auth.models import AuditEventType, User
from app.auth.resolvers import _get_user_from_info, _require_user
from app.auth.service import log_settings_change
from app.billing.service import get_active_subscription
from app.cache import cache
from app.database import get_db_session
from app.sites.site_schema import SiteSchema
from app.sites.graphql_types import (
    AddDomainInput,
    AssignDomainInput,
    CreateLeadInput,
    CustomDomainType,
    DailyVisitorPoint,
    DashboardStatsType,
    DomainPurchaseType,
    DomainSearchResult,
    DomainTransferInfoType,
    DraftType,
    GeneratedSiteType,
    InboundEmailFilterInput,
    InboundEmailListType,
    InboundEmailType,
    LeadFilterInput,
    LeadListType,
    LeadType,
    OutreachEmailType,
    PublishResult,
    SaveDraftInput,
    ScrapedDataType,
    SiteAnalyticsType,
    SubdomainInfoType,
    SiteVersionType,
    UpdateSiteDataInput,
)
from app.sites.models import (
    BLACKLISTED_SUBDOMAINS,
    CustomDomain,
    DomainPurchase,
    DomainStatus,
    GeneratedSite,
    InboundEmail,
    Lead,
    LeadStatus,
    OutreachEmail,
    PageView,
    ScrapedData,
    SiteDeletionToken,
    SiteDraft,
    SiteStatus,
    SiteVersion,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Free plan helpers
# ---------------------------------------------------------------------------

_SUB_CHECK_TTL = 600  # 10 minutes


async def _has_active_subscription(db, user: User) -> bool:
    """Check if user has an active (or trialing) subscription (cached)."""
    cache_key = f"sub_active:{user.id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    sub = await get_active_subscription(db, user.id)
    has_sub = sub is not None
    await cache.set(cache_key, has_sub, ttl=_SUB_CHECK_TTL)
    return has_sub


async def _require_subscription(db, user: User, action: str = "This action") -> None:
    """Raise if user has no active subscription (free plan)."""
    if user.is_superuser:
        return
    if not await _has_active_subscription(db, user):
        raise ValueError(
            f"{action} kräver ett aktivt abonnemang. "
            "Uppgradera din plan under Betalning."
        )


async def _check_site_limit(db, user: User) -> None:
    """Free plan: max 1 site. Raise if user already has one and has no subscription."""
    if user.is_superuser:
        return
    if await _has_active_subscription(db, user):
        return
    count_result = await db.execute(
        select(func.count(GeneratedSite.id))
        .join(Lead, GeneratedSite.lead_id == Lead.id)
        .where(Lead.created_by == str(user.id))
    )
    count = count_result.scalar() or 0
    if count >= 1:
        raise ValueError(
            "Free-planen tillåter max 1 hemsida. "
            "Uppgradera din plan för att skapa fler."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scraped_to_gql(s: ScrapedData) -> ScrapedDataType:
    return ScrapedDataType(
        id=s.id,
        logo_url=s.logo_url,
        colors=s.colors,
        texts=s.texts,
        images=s.images,
        contact_info=s.contact_info,
        meta_info=s.meta_info,
        created_at=s.created_at,
    )


def _site_to_gql(s: GeneratedSite, lead: Lead | None = None) -> GeneratedSiteType:
    return GeneratedSiteType(
        id=s.id,
        site_data=s.site_data,
        template=s.template,
        status=s.status.value,
        subdomain=s.subdomain,
        custom_domain=s.custom_domain,
        views=s.views,
        tokens_used=s.tokens_used,
        ai_model=s.ai_model,
        generation_cost_usd=s.generation_cost_usd,
        published_at=s.published_at,
        purchased_at=s.purchased_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
        lead_id=s.lead_id,
        business_name=lead.business_name if lead else None,
        website_url=lead.website_url if lead else None,
    )


def _email_to_gql(e: OutreachEmail) -> OutreachEmailType:
    return OutreachEmailType(
        id=e.id,
        to_email=e.to_email,
        subject=e.subject,
        status=e.status.value,
        resend_id=e.resend_id,
        sent_at=e.sent_at,
        opened_at=e.opened_at,
        clicked_at=e.clicked_at,
        created_at=e.created_at,
    )


def _lead_to_gql(lead: Lead) -> LeadType:
    inbound = lead.inbound_emails if lead.inbound_emails else []
    return LeadType(
        id=lead.id,
        business_name=lead.business_name,
        website_url=lead.website_url,
        email=lead.email,
        phone=lead.phone,
        address=lead.address,
        industry=lead.industry,
        source=lead.source,
        status=lead.status.value,
        quality_score=lead.quality_score,
        error_message=lead.error_message,
        scraped_at=lead.scraped_at,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        scraped_data=_scraped_to_gql(lead.scraped_data) if lead.scraped_data else None,
        generated_site=_site_to_gql(lead.generated_site) if lead.generated_site else None,
        outreach_emails=[_email_to_gql(e) for e in lead.outreach_emails] if lead.outreach_emails else [],
        inbound_emails=[_inbound_to_gql(e) for e in inbound],
        inbound_emails_count=len(inbound),
    )


def _inbound_to_gql(email: InboundEmail) -> InboundEmailType:
    return InboundEmailType(
        id=email.id,
        from_email=email.from_email,
        from_name=email.from_name,
        to_email=email.to_email,
        subject=email.subject,
        body_text=email.body_text,
        body_html=email.body_html,
        category=email.category if isinstance(email.category, str) else email.category.value,
        spam_score=email.spam_score,
        ai_summary=email.ai_summary,
        matched_lead_id=email.matched_lead_id,
        is_read=email.is_read,
        is_archived=email.is_archived,
        created_at=email.created_at.isoformat() if email.created_at else "",
    )


def _calc_performance_score(
    avg_lcp_ms: int | None,
    avg_fcp_ms: int | None,
    avg_cls: float | None,
) -> int:
    """Compute a 0-100 performance score from Web Vitals averages.

    Scoring based on Google's Core Web Vitals thresholds:
    - LCP: <=2500ms good, <=4000ms needs improvement
    - FCP: <=1800ms good, <=3000ms needs improvement
    - CLS: <=0.1 good, <=0.25 needs improvement
    """
    scores = []

    if avg_lcp_ms is not None:
        if avg_lcp_ms <= 2500:
            scores.append(100)
        elif avg_lcp_ms <= 4000:
            scores.append(50 + int(50 * (4000 - avg_lcp_ms) / 1500))
        else:
            scores.append(max(0, int(50 * (8000 - avg_lcp_ms) / 4000)))

    if avg_fcp_ms is not None:
        if avg_fcp_ms <= 1800:
            scores.append(100)
        elif avg_fcp_ms <= 3000:
            scores.append(50 + int(50 * (3000 - avg_fcp_ms) / 1200))
        else:
            scores.append(max(0, int(50 * (6000 - avg_fcp_ms) / 3000)))

    if avg_cls is not None:
        if avg_cls <= 0.1:
            scores.append(100)
        elif avg_cls <= 0.25:
            scores.append(50 + int(50 * (0.25 - avg_cls) / 0.15))
        else:
            scores.append(max(0, int(50 * (0.5 - avg_cls) / 0.25)))

    if not scores:
        return 0
    return int(sum(scores) / len(scores))


def _require_superuser(user: User) -> User:
    if not user.is_superuser:
        raise PermissionError("Superuser access required")
    return user


def _extract_vercel_verification(vercel_data: dict) -> dict:
    """Extract user-facing verification info from Vercel's domain response.

    Returns a dict with:
    - verified: whether the domain is verified
    - verification: list of TXT records needed (if any)
    - configured: whether DNS is properly configured
    - instructions: human-readable DNS instructions
    """
    result: dict = {
        "verified": vercel_data.get("verified", False),
    }

    # Verification TXT records (needed before DNS config)
    if vercel_data.get("verification"):
        result["verification"] = vercel_data["verification"]

    # DNS config info
    dns_config = vercel_data.get("dnsConfig")
    if dns_config:
        result["configured"] = dns_config.get("configured", False)
        result["misconfigured"] = dns_config.get("misconfigured", False)

    # Build user-friendly instructions
    if not result.get("verified"):
        verification_records = vercel_data.get("verification", [])
        if verification_records:
            result["instructions"] = (
                "Lägg till följande TXT-post i din DNS för att verifiera domänen: "
                f"Typ: TXT, Namn: _vercel, Värde: {verification_records[0].get('value', '')}"
            )
        else:
            result["instructions"] = (
                "Peka din domän till Vercel genom att lägga till en CNAME-post: "
                "Typ: CNAME, Namn: @ (eller www), Värde: cname.vercel-dns.com"
            )
    else:
        result["instructions"] = "Domänen är verifierad och aktiv!"

    return result


def _domain_to_gql(d: CustomDomain, vercel_verification: dict | None = None) -> CustomDomainType:
    return CustomDomainType(
        id=d.id,
        domain=d.domain,
        site_id=d.site_id,
        status=d.status.value,
        site_subdomain=d.site.subdomain if d.site else None,
        site_business_name=d.site.lead.business_name if d.site and d.site.lead else None,
        verified_at=d.verified_at,
        created_at=d.created_at,
        updated_at=d.updated_at,
        vercel_verification=vercel_verification,
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@strawberry.type
class SiteQuery:

    @strawberry.field
    async def my_sites(self, info: Info) -> list[GeneratedSiteType]:
        """Get all sites belonging to the current user (via lead.created_by).
        Excludes soft-deleted sites."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    Lead.created_by == str(user.id),
                    GeneratedSite.deleted_at.is_(None),
                )
                .options(selectinload(GeneratedSite.lead))
                .order_by(GeneratedSite.created_at.desc())
            )
            sites = result.scalars().all()
            return [_site_to_gql(s, s.lead) for s in sites]

    @strawberry.field
    async def my_site(self, info: Info, id: str) -> GeneratedSiteType | None:
        """Get a single site owned by the current user (for editing)."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    GeneratedSite.id == id,
                    Lead.created_by == str(user.id),
                )
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                return None
            return _site_to_gql(site, site.lead)

    @strawberry.field
    async def site_analytics(
        self, info: Info, site_id: str, days: int = 7
    ) -> SiteAnalyticsType:
        """Get analytics for a site owned by the current user.

        Uses database aggregation instead of loading all PageView rows into memory.
        """
        from datetime import timedelta
        from sqlalchemy import cast, Date

        user = _require_user(await _get_user_from_info(info))
        days = min(days, 90)

        async with get_db_session() as db:
            # Verify ownership (superadmins can access any site)
            query = (
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(GeneratedSite.id == site_id)
            )
            if not user.is_superuser:
                query = query.where(Lead.created_by == str(user.id))

            result = await db.execute(query)
            site = result.scalar_one_or_none()
            if not site:
                raise PermissionError("Site not found or access denied")

            now = datetime.now(timezone.utc)
            period_start = now - timedelta(days=days)
            prev_period_start = period_start - timedelta(days=days)

            # --- Aggregate current period in database ---
            cur_agg = await db.execute(
                select(
                    func.count().label("total_views"),
                    func.count(func.distinct(PageView.visitor_id)).label("unique_visitors"),
                    func.count(func.distinct(PageView.session_id)).label("unique_sessions"),
                    func.avg(PageView.load_time_ms).label("avg_load"),
                    func.avg(PageView.fcp_ms).label("avg_fcp"),
                    func.avg(PageView.lcp_ms).label("avg_lcp"),
                    func.avg(PageView.cls).label("avg_cls"),
                ).where(
                    PageView.site_id == site_id,
                    PageView.created_at >= period_start,
                )
            )
            cur = cur_agg.one()

            total_page_views = cur.total_views or 0
            total_visitors = cur.unique_visitors or 0
            total_sessions = cur.unique_sessions or 0
            pages_per_session = round(total_page_views / total_sessions, 1) if total_sessions else 0.0

            avg_load = int(cur.avg_load) if cur.avg_load is not None else None
            avg_fcp = int(cur.avg_fcp) if cur.avg_fcp is not None else None
            avg_lcp = int(cur.avg_lcp) if cur.avg_lcp is not None else None
            avg_cls = round(float(cur.avg_cls), 3) if cur.avg_cls is not None else None

            perf_score = _calc_performance_score(avg_lcp, avg_fcp, avg_cls)

            # --- Aggregate previous period in database ---
            prev_agg = await db.execute(
                select(
                    func.count().label("total_views"),
                    func.count(func.distinct(PageView.visitor_id)).label("unique_visitors"),
                    func.count(func.distinct(PageView.session_id)).label("unique_sessions"),
                    func.avg(PageView.lcp_ms).label("avg_lcp"),
                    func.avg(PageView.fcp_ms).label("avg_fcp"),
                    func.avg(PageView.cls).label("avg_cls"),
                ).where(
                    PageView.site_id == site_id,
                    PageView.created_at >= prev_period_start,
                    PageView.created_at < period_start,
                )
            )
            prev = prev_agg.one()

            prev_visitors = prev.unique_visitors or 0
            prev_sessions = prev.unique_sessions or 0
            prev_pps = round((prev.total_views or 0) / prev_sessions, 1) if prev_sessions else 0.0

            prev_avg_lcp = int(prev.avg_lcp) if prev.avg_lcp is not None else None
            prev_avg_fcp = int(prev.avg_fcp) if prev.avg_fcp is not None else None
            prev_avg_cls = round(float(prev.avg_cls), 3) if prev.avg_cls is not None else None
            prev_perf = _calc_performance_score(prev_avg_lcp, prev_avg_fcp, prev_avg_cls)

            visitors_change = 0.0
            if prev_visitors > 0:
                visitors_change = round(((total_visitors - prev_visitors) / prev_visitors) * 100, 1)

            # --- Daily breakdown (aggregated in DB) ---
            daily_agg = await db.execute(
                select(
                    cast(PageView.created_at, Date).label("day"),
                    func.count(func.distinct(PageView.visitor_id)).label("visitors"),
                    func.count().label("page_views"),
                ).where(
                    PageView.site_id == site_id,
                    PageView.created_at >= period_start,
                ).group_by(
                    cast(PageView.created_at, Date)
                )
            )
            daily_map = {str(row.day): row for row in daily_agg.all()}

            daily_points = []
            for i in range(days):
                day = (period_start + timedelta(days=i + 1)).strftime("%Y-%m-%d")
                row = daily_map.get(day)
                daily_points.append(DailyVisitorPoint(
                    date=day,
                    visitors=row.visitors if row else 0,
                    page_views=row.page_views if row else 0,
                ))

            return SiteAnalyticsType(
                total_visitors=total_visitors,
                total_sessions=total_sessions,
                total_page_views=total_page_views,
                pages_per_session=pages_per_session,
                avg_load_time_ms=avg_load,
                avg_fcp_ms=avg_fcp,
                avg_lcp_ms=avg_lcp,
                avg_cls=avg_cls,
                performance_score=perf_score,
                visitors_change_pct=visitors_change,
                pages_per_session_prev=prev_pps,
                performance_score_prev=prev_perf,
                daily=daily_points,
            )

    @strawberry.field
    async def my_domains(self, info: Info) -> list[CustomDomainType]:
        """Get all domains belonging to the current user.

        Includes both:
        - Custom domains from the custom_domains table
        - Auto-generated subdomain entries from the user's sites
        """
        from app.config import settings as _settings
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            # 1. Custom domains
            result = await db.execute(
                select(CustomDomain)
                .where(CustomDomain.user_id == str(user.id))
                .options(selectinload(CustomDomain.site).selectinload(GeneratedSite.lead))
                .order_by(CustomDomain.created_at.desc())
            )
            domains = [_domain_to_gql(d) for d in result.scalars().all()]

            # 2. Subdomain entries from the user's sites
            # These are platform subdomains (e.g. acme.qvickosite.com) that
            # are always active and don't need DNS verification.
            site_result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    Lead.created_by == str(user.id),
                    GeneratedSite.deleted_at.is_(None),
                    GeneratedSite.subdomain.isnot(None),
                )
                .options(selectinload(GeneratedSite.lead))
            )
            # Collect custom-domain domains already in the list to avoid dupes
            custom_domain_set = {d.domain for d in domains}
            for site in site_result.scalars().all():
                full = f"{site.subdomain}.{_settings.BASE_DOMAIN}"
                if full in custom_domain_set:
                    continue
                domains.append(CustomDomainType(
                    id=f"sub-{site.id}",
                    domain=full,
                    site_id=site.id,
                    status="ACTIVE",
                    site_subdomain=site.subdomain,
                    site_business_name=site.lead.business_name if site.lead else None,
                    verified_at=site.created_at,
                    created_at=site.created_at,
                    updated_at=site.updated_at,
                    vercel_verification=None,
                ))

            return domains

    @strawberry.field
    async def search_domain(self, info: Info, domain: str) -> DomainSearchResult:
        """Search for a domain's availability and price."""
        _require_user(await _get_user_from_info(info))

        from app.sites.vercel import check_domain_availability
        result = await check_domain_availability(domain.strip().lower())
        if not result:
            raise ValueError("Kunde inte kontrollera domäntillgänglighet")

        return DomainSearchResult(
            available=result.get("available", False),
            domain=result.get("domain", domain),
            price_sek=result.get("price_sek", 0),
            price_sek_display=result.get("price_sek_display", 0),
            price_usd=result.get("price_usd", 0.0),
            period=result.get("period", 1),
        )

    @strawberry.field
    async def my_purchased_domains(self, info: Info) -> list[DomainPurchaseType]:
        """Get all domains purchased by the current user."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(DomainPurchase)
                .where(DomainPurchase.user_id == str(user.id))
                .order_by(DomainPurchase.created_at.desc())
            )
            purchases = result.scalars().all()
            return [
                DomainPurchaseType(
                    id=p.id,
                    domain=p.domain,
                    price_sek=p.price_sek,
                    status=p.status.value,
                    period_years=p.period_years,
                    auto_renew=p.auto_renew,
                    is_locked=p.is_locked,
                    expires_at=p.expires_at,
                    purchased_at=p.purchased_at,
                    created_at=p.created_at,
                )
                for p in purchases
            ]

    @strawberry.field
    async def subdomain_info(self, info: Info, site_id: str) -> SubdomainInfoType:
        """Get subdomain info for a site."""
        user = _require_user(await _get_user_from_info(info))
        from app.config import settings as _settings

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(GeneratedSite.id == site_id)
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            full_url = None
            if site.subdomain:
                full_url = f"https://{site.subdomain}.{_settings.BASE_DOMAIN}"

            return SubdomainInfoType(
                subdomain=site.subdomain,
                full_url=full_url,
                base_domain=_settings.BASE_DOMAIN,
            )

    @strawberry.field
    async def lead(self, info: Info, id: str) -> LeadType | None:
        """Get a single lead by ID (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))
        async with get_db_session() as db:
            result = await db.execute(
                select(Lead)
                .where(Lead.id == id)
                .options(
                    selectinload(Lead.scraped_data),
                    selectinload(Lead.generated_site),
                    selectinload(Lead.outreach_emails),
                    selectinload(Lead.inbound_emails),
                )
            )
            lead = result.scalar_one_or_none()
            return _lead_to_gql(lead) if lead else None

    @strawberry.field
    async def leads(self, info: Info, filter: LeadFilterInput | None = None) -> LeadListType:
        """List leads with filtering and pagination (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))
        f = filter or LeadFilterInput()
        page_size = min(f.page_size, 100)

        async with get_db_session() as db:
            query = select(Lead).options(
                selectinload(Lead.scraped_data),
                selectinload(Lead.generated_site),
                selectinload(Lead.outreach_emails),
                selectinload(Lead.inbound_emails),
            )

            if f.status:
                query = query.where(Lead.status == LeadStatus(f.status))
            if f.industry:
                query = query.where(Lead.industry == f.industry)
            if f.search:
                search = f"%{f.search}%"
                query = query.where(
                    or_(
                        Lead.business_name.ilike(search),
                        Lead.website_url.ilike(search),
                        Lead.email.ilike(search),
                    )
                )

            # Count
            count_result = await db.execute(
                select(func.count()).select_from(query.subquery())
            )
            total = count_result.scalar() or 0

            # Paginate
            offset = (f.page - 1) * page_size
            query = query.order_by(Lead.created_at.desc()).offset(offset).limit(page_size)

            result = await db.execute(query)
            leads = result.scalars().all()

            return LeadListType(
                items=[_lead_to_gql(l) for l in leads],
                total=total,
                page=f.page,
                page_size=page_size,
            )

    @strawberry.field
    async def dashboard_stats(self, info: Info) -> DashboardStatsType:
        """Dashboard statistics (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        # Try cache first
        cached = await cache.get("admin:dashboard_stats")
        if cached:
            return DashboardStatsType(**cached)

        async with get_db_session() as db:
            # Lead counts by status (single GROUP BY instead of N queries)
            result = await db.execute(
                select(Lead.status, func.count()).group_by(Lead.status)
            )
            lead_counts = {s.value: 0 for s in LeadStatus}
            for row_status, count in result:
                lead_counts[row_status.value] = count

            total_leads = sum(lead_counts.values())

            # Site count
            site_count_result = await db.execute(select(func.count()).select_from(GeneratedSite))
            total_sites = site_count_result.scalar() or 0

            # Email count
            email_count_result = await db.execute(
                select(func.count()).where(OutreachEmail.status != "PENDING")
            )
            total_emails = email_count_result.scalar() or 0

            # Total views
            views_result = await db.execute(select(func.sum(GeneratedSite.views)))
            total_views = views_result.scalar() or 0

            # Total AI cost
            cost_result = await db.execute(select(func.sum(GeneratedSite.generation_cost_usd)))
            total_cost = cost_result.scalar() or 0.0

            stats = DashboardStatsType(
                total_leads=total_leads,
                leads_new=lead_counts.get("NEW", 0),
                leads_scraped=lead_counts.get("SCRAPED", 0),
                leads_generated=lead_counts.get("GENERATED", 0),
                leads_email_sent=lead_counts.get("EMAIL_SENT", 0),
                leads_converted=lead_counts.get("CONVERTED", 0),
                leads_failed=lead_counts.get("FAILED", 0),
                total_sites=total_sites,
                total_emails_sent=total_emails,
                total_views=total_views,
                total_ai_cost_usd=round(total_cost, 4),
            )

            # Cache for 60 seconds
            await cache.set("admin:dashboard_stats", {
                "total_leads": stats.total_leads,
                "leads_new": stats.leads_new,
                "leads_scraped": stats.leads_scraped,
                "leads_generated": stats.leads_generated,
                "leads_email_sent": stats.leads_email_sent,
                "leads_converted": stats.leads_converted,
                "leads_failed": stats.leads_failed,
                "total_sites": stats.total_sites,
                "total_emails_sent": stats.total_emails_sent,
                "total_views": stats.total_views,
                "total_ai_cost_usd": stats.total_ai_cost_usd,
            }, ttl=60)

            return stats

    @strawberry.field
    async def site(self, info: Info, id: str) -> GeneratedSiteType | None:
        """Get a generated site by ID (public — for rendering)."""
        # Try cache
        cached = await cache.get(f"site:{id}")
        if cached:
            return GeneratedSiteType(**cached)

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite).where(
                    GeneratedSite.id == id,
                    GeneratedSite.status == SiteStatus.PUBLISHED,
                    GeneratedSite.deleted_at.is_(None),
                )
            )
            site = result.scalar_one_or_none()
            if not site:
                return None

            gql = _site_to_gql(site)
            # Hide sensitive business metrics from public queries
            gql.tokens_used = None
            gql.ai_model = None
            gql.generation_cost_usd = None

            # Cache published sites
            if site.status == SiteStatus.PUBLISHED:
                await cache.set(f"site:{id}", {
                    "id": gql.id,
                    "site_data": gql.site_data,
                    "template": gql.template,
                    "status": gql.status,
                    "subdomain": gql.subdomain,
                    "custom_domain": gql.custom_domain,
                    "views": gql.views,
                    "tokens_used": gql.tokens_used,
                    "ai_model": gql.ai_model,
                    "generation_cost_usd": gql.generation_cost_usd,
                    "published_at": gql.published_at.isoformat() if gql.published_at else None,
                    "purchased_at": gql.purchased_at.isoformat() if gql.purchased_at else None,
                    "created_at": gql.created_at.isoformat(),
                    "updated_at": gql.updated_at.isoformat(),
                }, ttl=3600)

            return gql

    @strawberry.field
    async def inbox(
        self, info: Info, filter: InboundEmailFilterInput | None = None
    ) -> InboundEmailListType:
        """List inbound emails (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            f = filter or InboundEmailFilterInput()
            page_size = min(f.page_size, 100)

            query = select(InboundEmail)
            count_query = select(func.count()).select_from(InboundEmail)

            if f.category:
                query = query.where(InboundEmail.category == f.category)
                count_query = count_query.where(InboundEmail.category == f.category)
            if f.to_email:
                query = query.where(InboundEmail.to_email == f.to_email)
                count_query = count_query.where(InboundEmail.to_email == f.to_email)
            if f.is_read is not None:
                query = query.where(InboundEmail.is_read == f.is_read)
                count_query = count_query.where(InboundEmail.is_read == f.is_read)
            if f.is_archived is not None:
                query = query.where(InboundEmail.is_archived == f.is_archived)
                count_query = count_query.where(InboundEmail.is_archived == f.is_archived)
            if f.search:
                search = f"%{f.search}%"
                query = query.where(
                    (InboundEmail.from_email.ilike(search))
                    | (InboundEmail.subject.ilike(search))
                    | (InboundEmail.from_name.ilike(search))
                )
                count_query = count_query.where(
                    (InboundEmail.from_email.ilike(search))
                    | (InboundEmail.subject.ilike(search))
                    | (InboundEmail.from_name.ilike(search))
                )

            total = (await db.execute(count_query)).scalar() or 0

            query = query.order_by(InboundEmail.created_at.desc())
            query = query.offset((f.page - 1) * page_size).limit(page_size)

            result = await db.execute(query)
            emails = result.scalars().all()

            return InboundEmailListType(
                items=[_inbound_to_gql(e) for e in emails],
                total=total,
                page=f.page,
                page_size=page_size,
            )

    @strawberry.field
    async def inbound_email(self, info: Info, id: str) -> InboundEmailType | None:
        """Get single inbound email (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            result = await db.execute(
                select(InboundEmail).where(InboundEmail.id == id)
            )
            email = result.scalar_one_or_none()
            if not email:
                return None

            # Mark as read
            if not email.is_read:
                email.is_read = True
                await db.commit()

            return _inbound_to_gql(email)

    @strawberry.field
    async def site_versions(self, info: Info, site_id: str) -> list[SiteVersionType]:
        """Get version history for a site (newest first)."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            # Verify ownership
            site_result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = site_result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            is_owner = site.lead and site.lead.created_by == str(user.id)
            if not user.is_superuser and not is_owner:
                raise PermissionError("Access denied")

            result = await db.execute(
                select(SiteVersion)
                .where(SiteVersion.site_id == site_id)
                .order_by(SiteVersion.version_number.desc())
                .limit(20)
            )
            versions = result.scalars().all()

        return [
            SiteVersionType(
                id=v.id,
                site_id=v.site_id,
                version_number=v.version_number,
                site_data=v.site_data,
                label=v.label,
                created_at=v.created_at,
            )
            for v in versions
        ]


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

@strawberry.type
class SiteMutation:

    @strawberry.mutation
    async def create_lead(self, info: Info, input: CreateLeadInput) -> LeadType:
        """Create a new lead from a URL and trigger pipeline (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        # Normalize URL
        url = input.website_url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        async with get_db_session() as db:
            # Check for duplicate
            existing = await db.execute(
                select(Lead).where(Lead.website_url == url)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Lead with URL {url} already exists")

            lead = Lead(
                website_url=url,
                business_name=input.business_name,
                industry=input.industry,
                source="manual",
                status=LeadStatus.NEW,
                created_by=user.id,
            )
            db.add(lead)
            await db.commit()
            await db.refresh(lead)
            lead_id = lead.id

            # Invalidate dashboard cache
            await cache.delete("admin:dashboard_stats")

            # Trigger pipeline in background
            asyncio.create_task(_run_pipeline_bg(lead_id))

            # Return directly — lead was just created so relationships are empty;
            # accessing them would trigger lazy loads outside the session.
            return LeadType(
                id=lead.id,
                business_name=lead.business_name,
                website_url=lead.website_url,
                email=lead.email,
                phone=lead.phone,
                address=lead.address,
                industry=lead.industry,
                source=lead.source,
                status=lead.status.value,
                quality_score=lead.quality_score,
                error_message=lead.error_message,
                scraped_at=lead.scraped_at,
                created_at=lead.created_at,
                updated_at=lead.updated_at,
                scraped_data=None,
                generated_site=None,
                outreach_emails=[],
                inbound_emails=[],
                inbound_emails_count=0,
            )

    @strawberry.mutation
    async def scrape_lead(self, info: Info, lead_id: str) -> bool:
        """Re-run the scrape+generate pipeline for a lead (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            result = await db.execute(select(Lead).where(Lead.id == lead_id))
            lead = result.scalar_one_or_none()
            if not lead:
                raise ValueError("Lead not found")

        asyncio.create_task(_run_pipeline_bg(lead_id))
        return True

    @strawberry.mutation
    async def send_outreach_email(self, info: Info, lead_id: str) -> OutreachEmailType:
        """Send outreach email for a lead (superadmin only). Lead must have a generated site."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            result = await db.execute(
                select(Lead)
                .where(Lead.id == lead_id)
                .options(selectinload(Lead.generated_site))
            )
            lead = result.scalar_one_or_none()
            if not lead:
                raise ValueError("Lead not found")
            if not lead.email:
                raise ValueError("Lead has no email address")
            if not lead.generated_site:
                raise ValueError("Lead has no generated site yet")

            from app.email.service import send_outreach_email as send_email
            outreach = await send_email(db, lead, lead.generated_site)
            lead.status = LeadStatus.EMAIL_SENT
            await db.commit()
            await cache.delete("admin:dashboard_stats")
            return _email_to_gql(outreach)

    @strawberry.mutation
    async def update_lead_status(self, info: Info, lead_id: str, status: str) -> LeadType:
        """Update a lead's status (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            result = await db.execute(
                select(Lead)
                .where(Lead.id == lead_id)
                .options(
                    selectinload(Lead.scraped_data),
                    selectinload(Lead.generated_site),
                    selectinload(Lead.outreach_emails),
                    selectinload(Lead.inbound_emails),
                )
            )
            lead = result.scalar_one_or_none()
            if not lead:
                raise ValueError("Lead not found")

            lead.status = LeadStatus(status)
            lead.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(lead, attribute_names=["status", "updated_at"])

            await cache.delete("admin:dashboard_stats")
            return _lead_to_gql(lead)

    @strawberry.mutation
    async def delete_lead(self, info: Info, lead_id: str) -> bool:
        """Delete a lead and all related data (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            result = await db.execute(
                select(Lead)
                .where(Lead.id == lead_id)
                .options(selectinload(Lead.generated_site))
            )
            lead = result.scalar_one_or_none()
            if not lead:
                raise ValueError("Lead not found")

            # Invalidate site cache if exists
            if lead.generated_site:
                await cache.delete(f"site:{lead.generated_site.id}")
                await cache.delete(f"site:data:{lead.generated_site.id}")
                await cache.delete(f"site:meta:{lead.generated_site.id}")
                if lead.generated_site.subdomain:
                    await cache.delete(f"resolve:sub:{lead.generated_site.subdomain}")
                if lead.generated_site.custom_domain:
                    await cache.delete(f"resolve:dom:{lead.generated_site.custom_domain}")

            await db.delete(lead)
            await db.commit()

            await cache.delete("admin:dashboard_stats")
            await cache.delete("sites:published")
            return True

    @strawberry.mutation
    async def update_site_data(self, info: Info, input: UpdateSiteDataInput) -> GeneratedSiteType:
        """Update a site's JSON data (superadmin or site owner)."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == input.site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            # Allow superadmin or site owner (via lead.created_by)
            is_owner = site.lead and site.lead.created_by == str(user.id)
            if not user.is_superuser and not is_owner:
                raise PermissionError("You do not have permission to edit this site")

            # Validate site_data against schema
            try:
                SiteSchema.model_validate(input.site_data)
            except ValidationError as e:
                raise ValueError(f"Invalid site data: {e}")

            site.site_data = input.site_data
            site.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(site)

            # Invalidate cache
            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            if site.subdomain:
                await cache.delete(f"resolve:sub:{site.subdomain}")
            if site.custom_domain:
                await cache.delete(f"resolve:dom:{site.custom_domain}")

            return _site_to_gql(site, site.lead)

    # ------------------------------------------------------------------
    # Draft management
    # ------------------------------------------------------------------

    @strawberry.mutation
    async def save_draft(self, info: Info, input: SaveDraftInput) -> DraftType:
        """Auto-save editor draft. No cache invalidation — draft only."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == input.site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            is_owner = site.lead and site.lead.created_by == str(user.id)
            if not user.is_superuser and not is_owner:
                raise PermissionError("You do not have permission to edit this site")

            # Upsert draft
            draft_result = await db.execute(
                select(SiteDraft).where(SiteDraft.site_id == input.site_id)
            )
            draft = draft_result.scalar_one_or_none()

            if draft:
                draft.draft_data = input.draft_data
                draft.updated_at = datetime.now(timezone.utc)
            else:
                draft = SiteDraft(
                    site_id=input.site_id,
                    draft_data=input.draft_data,
                )
                db.add(draft)

            await db.commit()
            await db.refresh(draft)

            return DraftType(
                site_id=draft.site_id,
                draft_data=draft.draft_data,
                updated_at=draft.updated_at,
            )

    @strawberry.mutation
    async def load_draft(self, info: Info, site_id: str) -> DraftType | None:
        """Load the current draft for a site, if one exists."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            is_owner = site.lead and site.lead.created_by == str(user.id)
            if not user.is_superuser and not is_owner:
                raise PermissionError("You do not have permission to view this site")

            draft_result = await db.execute(
                select(SiteDraft).where(SiteDraft.site_id == site_id)
            )
            draft = draft_result.scalar_one_or_none()
            if not draft:
                return None

            return DraftType(
                site_id=draft.site_id,
                draft_data=draft.draft_data,
                updated_at=draft.updated_at,
            )

    @strawberry.mutation
    async def publish_site_data(self, info: Info, input: UpdateSiteDataInput) -> PublishResult:
        """Publish site data: save to site_data, delete draft, invalidate all caches."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == input.site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            is_owner = site.lead and site.lead.created_by == str(user.id)
            if not user.is_superuser and not is_owner:
                raise PermissionError("You do not have permission to edit this site")

            # Validate
            try:
                SiteSchema.model_validate(input.site_data)
            except ValidationError as e:
                raise ValueError(f"Invalid site data: {e}")

            # Create version snapshot before overwriting
            version_count_result = await db.execute(
                select(func.coalesce(func.max(SiteVersion.version_number), 0)).where(
                    SiteVersion.site_id == input.site_id
                )
            )
            next_version = version_count_result.scalar_one() + 1
            version = SiteVersion(
                site_id=input.site_id,
                version_number=next_version,
                site_data=input.site_data,
            )
            db.add(version)

            # Keep only last 20 versions per site
            old_versions_result = await db.execute(
                select(SiteVersion.id)
                .where(SiteVersion.site_id == input.site_id)
                .order_by(SiteVersion.version_number.desc())
                .offset(20)
            )
            old_ids = [row[0] for row in old_versions_result.all()]
            if old_ids:
                from sqlalchemy import delete
                await db.execute(
                    delete(SiteVersion).where(SiteVersion.id.in_(old_ids))
                )

            # Save to published site_data
            site.site_data = input.site_data
            site.updated_at = datetime.now(timezone.utc)

            # Delete draft
            draft_result = await db.execute(
                select(SiteDraft).where(SiteDraft.site_id == input.site_id)
            )
            draft = draft_result.scalar_one_or_none()
            if draft:
                await db.delete(draft)

            await db.commit()
            await db.refresh(site)

            # Invalidate ALL viewer caches for this site
            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            await cache.delete("sites:published")
            if site.subdomain:
                await cache.delete(f"resolve:sub:{site.subdomain}")
            if site.custom_domain:
                await cache.delete(f"resolve:dom:{site.custom_domain}")

            # Trigger viewer ISR revalidation
            asyncio.ensure_future(_revalidate_viewer(site.id, site.subdomain))

            return PublishResult(
                success=True,
                site=_site_to_gql(site, site.lead),
            )

    @strawberry.mutation
    async def discard_draft(self, info: Info, site_id: str) -> bool:
        """Discard draft and revert to published version."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            is_owner = site.lead and site.lead.created_by == str(user.id)
            if not user.is_superuser and not is_owner:
                raise PermissionError("You do not have permission to edit this site")

            draft_result = await db.execute(
                select(SiteDraft).where(SiteDraft.site_id == site_id)
            )
            draft = draft_result.scalar_one_or_none()
            if draft:
                await db.delete(draft)
                await db.commit()

            return True

    @strawberry.mutation
    async def publish_site(self, info: Info, site_id: str) -> GeneratedSiteType:
        """Publish a site. Requires active subscription (or superadmin)."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            # Require subscription for non-superusers
            await _require_subscription(db, user, "Publicering av hemsida")

            result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            # Verify ownership (non-superusers)
            if not user.is_superuser:
                is_owner = site.lead and site.lead.created_by == str(user.id)
                if not is_owner:
                    raise PermissionError("You do not have permission to publish this site")

            site.status = SiteStatus.PUBLISHED
            site.published_at = datetime.now(timezone.utc)
            site.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(site)

            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            await cache.delete("sites:published")
            return _site_to_gql(site, site.lead)

    @strawberry.mutation
    async def track_site_view(self, info: Info, site_id: str) -> bool:
        """Increment view count for a site (public).

        Uses a cache counter to buffer increments and flushes to DB every
        _VIEW_FLUSH_THRESHOLD views, avoiding a DB write per page view.
        """
        _VIEW_FLUSH_THRESHOLD = 10
        counter_key = f"site:views_buffer:{site_id}"

        # Increment counter in cache
        current = await cache.get(counter_key)
        count = (int(current) if current else 0) + 1
        await cache.set(counter_key, count, ttl=300)

        if count >= _VIEW_FLUSH_THRESHOLD:
            # Flush buffered views to DB
            async with get_db_session() as db:
                result = await db.execute(
                    select(GeneratedSite).where(GeneratedSite.id == site_id)
                )
                site = result.scalar_one_or_none()
                if not site:
                    return False

                site.views += count
                await db.commit()

            await cache.delete(counter_key)
            await cache.delete(f"site:{site_id}")

        return True

    @strawberry.mutation
    async def mark_email_read(
        self, info: Info, id: str, is_read: bool = True
    ) -> InboundEmailType:
        """Mark inbound email as read/unread (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            result = await db.execute(
                select(InboundEmail).where(InboundEmail.id == id)
            )
            email = result.scalar_one_or_none()
            if not email:
                raise ValueError("Email not found")

            email.is_read = is_read
            await db.commit()
            return _inbound_to_gql(email)

    @strawberry.mutation
    async def archive_email(
        self, info: Info, id: str, is_archived: bool = True
    ) -> InboundEmailType:
        """Archive/unarchive inbound email (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            result = await db.execute(
                select(InboundEmail).where(InboundEmail.id == id)
            )
            email = result.scalar_one_or_none()
            if not email:
                raise ValueError("Email not found")

            email.is_archived = is_archived
            await db.commit()
            return _inbound_to_gql(email)

    @strawberry.mutation
    async def update_site_domain(
        self,
        info: Info,
        site_id: str,
        subdomain: str | None = None,
        custom_domain: str | None = None,
    ) -> GeneratedSiteType:
        """Update a site's subdomain and/or custom domain. Logs changes to settings audit."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            is_owner = site.lead and site.lead.created_by == str(user.id)
            if not user.is_superuser and not is_owner:
                raise PermissionError("You do not have permission to edit this site")

            changes: dict[str, tuple[str | None, str | None]] = {}
            if subdomain is not None and subdomain != site.subdomain:
                changes["subdomain"] = (site.subdomain, subdomain)
                site.subdomain = subdomain
            if custom_domain is not None and custom_domain != site.custom_domain:
                changes["custom_domain"] = (site.custom_domain, custom_domain)
                site.custom_domain = custom_domain

            if changes:
                site.updated_at = datetime.now(timezone.utc)
                await log_settings_change(
                    db, str(user.id), AuditEventType.DOMAIN_CHANGE,
                    "generated_site", site.id, changes,
                )
                await db.commit()
                await cache.delete(f"site:{site.id}")
                await cache.delete(f"site:data:{site.id}")
                await cache.delete(f"site:meta:{site.id}")
                await cache.delete("sites:published")
                # Invalidate old and new resolve keys
                for field, (old_val, new_val) in changes.items():
                    if field == "subdomain":
                        if old_val:
                            await cache.delete(f"resolve:sub:{old_val}")
                        if new_val:
                            await cache.delete(f"resolve:sub:{new_val}")
                    elif field == "custom_domain":
                        if old_val:
                            await cache.delete(f"resolve:dom:{old_val}")
                        if new_val:
                            await cache.delete(f"resolve:dom:{new_val}")

            return _site_to_gql(site, site.lead)


    @strawberry.mutation
    async def add_domain(self, info: Info, input: AddDomainInput) -> CustomDomainType:
        """Add a custom domain for the current user.

        Registers the domain with Vercel so it can serve the viewer app
        and issue TLS certificates. Returns verification info so the user
        knows which DNS records to configure.
        """
        user = _require_user(await _get_user_from_info(info))

        # Normalize domain
        domain = input.domain.strip().lower()
        domain = domain.removeprefix("http://").removeprefix("https://")
        domain = domain.removeprefix("www.")
        domain = domain.rstrip("/")

        if not domain or "." not in domain:
            raise ValueError("Invalid domain format")

        async with get_db_session() as db:
            # Free plan: no custom domains
            await _require_subscription(db, user, "Egen domän")

            # Check if domain already exists
            existing = await db.execute(
                select(CustomDomain).where(CustomDomain.domain == domain)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Domain {domain} is already registered")

            # If site_id provided, verify ownership
            if input.site_id:
                site_result = await db.execute(
                    select(GeneratedSite)
                    .join(Lead, GeneratedSite.lead_id == Lead.id)
                    .where(
                        GeneratedSite.id == input.site_id,
                        Lead.created_by == str(user.id),
                    )
                )
                if not site_result.scalar_one_or_none():
                    raise PermissionError("Site not found or not owned by you")

            custom_domain = CustomDomain(
                user_id=str(user.id),
                domain=domain,
                site_id=input.site_id,
                status=DomainStatus.PENDING,
            )
            db.add(custom_domain)
            await db.commit()

            # Re-fetch with site relationship eagerly loaded
            result = await db.execute(
                select(CustomDomain)
                .where(CustomDomain.id == custom_domain.id)
                .options(selectinload(CustomDomain.site).selectinload(GeneratedSite.lead))
            )
            custom_domain = result.scalar_one()

            # Register domain with Vercel (best-effort)
            vercel_info = None
            try:
                from app.sites.vercel import add_domain as vercel_add_domain
                vercel_result = await vercel_add_domain(domain)
                if vercel_result:
                    vercel_info = _extract_vercel_verification(vercel_result)
            except Exception:
                logger.warning("Failed to register domain %s with Vercel", domain)

            # Log the change
            await log_settings_change(
                db, str(user.id), AuditEventType.DOMAIN_CHANGE,
                "custom_domain", custom_domain.id,
                {"domain": (None, domain)},
            )
            await db.commit()

            return _domain_to_gql(custom_domain, vercel_verification=vercel_info)

    @strawberry.mutation
    async def remove_domain(self, info: Info, domain_id: str) -> bool:
        """Remove a custom domain. Also removes it from Vercel."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(CustomDomain).where(
                    CustomDomain.id == domain_id,
                    CustomDomain.user_id == str(user.id),
                )
            )
            domain = result.scalar_one_or_none()
            if not domain:
                raise ValueError("Domain not found")

            domain_name = domain.domain

            # Remove from Vercel (best-effort)
            try:
                from app.sites.vercel import remove_domain as vercel_remove_domain
                await vercel_remove_domain(domain_name)
            except Exception:
                logger.warning("Failed to remove domain %s from Vercel", domain_name)

            # Also clear custom_domain on the linked site
            if domain.site_id:
                site_result = await db.execute(
                    select(GeneratedSite).where(GeneratedSite.id == domain.site_id)
                )
                site = site_result.scalar_one_or_none()
                if site and site.custom_domain == domain_name:
                    site.custom_domain = None
                    await cache.delete(f"site:{site.id}")
                    await cache.delete(f"site:data:{site.id}")
                    await cache.delete(f"site:meta:{site.id}")

            await cache.delete(f"resolve:dom:{domain_name}")
            await db.delete(domain)
            await db.commit()

            await log_settings_change(
                db, str(user.id), AuditEventType.DOMAIN_CHANGE,
                "custom_domain", domain_id,
                {"domain": (domain_name, None)},
            )
            await db.commit()

            return True

    @strawberry.mutation
    async def assign_domain_to_site(self, info: Info, input: AssignDomainInput) -> CustomDomainType:
        """Assign a custom domain to a site."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            # Verify domain ownership
            domain_result = await db.execute(
                select(CustomDomain).where(
                    CustomDomain.id == input.domain_id,
                    CustomDomain.user_id == str(user.id),
                )
            )
            domain = domain_result.scalar_one_or_none()
            if not domain:
                raise ValueError("Domain not found")

            # Verify site ownership
            site_result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    GeneratedSite.id == input.site_id,
                    Lead.created_by == str(user.id),
                )
            )
            site = site_result.scalar_one_or_none()
            if not site:
                raise PermissionError("Site not found or not owned by you")

            old_site_id = domain.site_id
            domain.site_id = input.site_id
            await db.commit()

            # Also update the site's custom_domain field
            site.custom_domain = domain.domain
            await db.commit()

            await log_settings_change(
                db, str(user.id), AuditEventType.DOMAIN_CHANGE,
                "custom_domain", domain.id,
                {"site_id": (old_site_id, input.site_id)},
            )
            await db.commit()

            # Re-fetch with site relationship eagerly loaded
            result = await db.execute(
                select(CustomDomain)
                .where(CustomDomain.id == domain.id)
                .options(selectinload(CustomDomain.site).selectinload(GeneratedSite.lead))
            )
            domain = result.scalar_one()
            return _domain_to_gql(domain)

    @strawberry.mutation
    async def verify_domain(self, info: Info, domain_id: str) -> CustomDomainType:
        """Verify a custom domain's DNS configuration via Vercel.

        Checks Vercel's domain verification status. If verified, Vercel
        will automatically issue TLS certificates and route traffic.
        """
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(CustomDomain).where(
                    CustomDomain.id == domain_id,
                    CustomDomain.user_id == str(user.id),
                ).options(selectinload(CustomDomain.site).selectinload(GeneratedSite.lead))
            )
            domain = result.scalar_one_or_none()
            if not domain:
                raise ValueError("Domain not found")

            vercel_info = None
            verified = False

            # Primary: check via Vercel API
            try:
                from app.sites.vercel import check_domain_status
                verified, vercel_data = await check_domain_status(domain.domain)
                if vercel_data:
                    vercel_info = _extract_vercel_verification(vercel_data)
            except Exception:
                logger.warning("Vercel verification failed for %s", domain.domain)

            if verified:
                domain.status = DomainStatus.ACTIVE
                domain.verified_at = datetime.now(timezone.utc)
            else:
                domain.status = DomainStatus.FAILED

            await db.commit()
            # Re-fetch with site relationship to avoid lazy-load in _domain_to_gql
            result = await db.execute(
                select(CustomDomain)
                .where(CustomDomain.id == domain.id)
                .options(selectinload(CustomDomain.site).selectinload(GeneratedSite.lead))
            )
            domain = result.scalar_one()
            return _domain_to_gql(domain, vercel_verification=vercel_info)

    @strawberry.mutation
    async def set_site_subdomain(
        self, info: Info, site_id: str, subdomain: str
    ) -> GeneratedSiteType:
        """Set a subdomain slug for a site. Validates against blacklist and uniqueness."""
        import re
        user = _require_user(await _get_user_from_info(info))

        # Normalize subdomain
        subdomain = subdomain.strip().lower()
        subdomain = re.sub(r"[^a-z0-9-]", "", subdomain)
        subdomain = re.sub(r"-+", "-", subdomain).strip("-")

        if not subdomain or len(subdomain) < 3:
            raise ValueError("Subdomain must be at least 3 characters")
        if len(subdomain) > 63:
            raise ValueError("Subdomain must be 63 characters or less")
        if subdomain in BLACKLISTED_SUBDOMAINS:
            raise ValueError(f"Subdomain '{subdomain}' is reserved and cannot be used")

        async with get_db_session() as db:
            # Verify site ownership
            result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    GeneratedSite.id == site_id,
                    Lead.created_by == str(user.id),
                )
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise PermissionError("Site not found or not owned by you")

            # Check uniqueness
            existing = await db.execute(
                select(GeneratedSite).where(
                    GeneratedSite.subdomain == subdomain,
                    GeneratedSite.id != site_id,
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Subdomain '{subdomain}' is already taken")

            old_subdomain = site.subdomain
            site.subdomain = subdomain
            site.updated_at = datetime.now(timezone.utc)
            await db.commit()

            # Log the change
            await log_settings_change(
                db, str(user.id), AuditEventType.DOMAIN_CHANGE,
                "generated_site", site.id,
                {"subdomain": (old_subdomain, subdomain)},
            )
            await db.commit()

            # Invalidate cache
            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            await cache.delete("sites:published")
            if old_subdomain:
                await cache.delete(f"resolve:sub:{old_subdomain}")
            await cache.delete(f"resolve:sub:{subdomain}")

            return _site_to_gql(site, site.lead)

    # -------------------------------------------------------------------
    # Domain transfer & management (not promoted, available on request)
    # -------------------------------------------------------------------

    @strawberry.mutation
    async def prepare_domain_transfer(self, info: Info, domain_id: str) -> DomainTransferInfoType:
        """Unlock a purchased domain and retrieve the auth/EPP code for transfer.

        The customer needs this code to transfer the domain to another registrar.
        """
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(DomainPurchase).where(
                    DomainPurchase.id == domain_id,
                    DomainPurchase.user_id == str(user.id),
                )
            )
            purchase = result.scalar_one_or_none()
            if not purchase:
                raise ValueError("Köpt domän hittades inte")
            if purchase.status.value != "PURCHASED":
                raise ValueError("Domänen måste ha status PURCHASED för att kunna överföras")

            from app.sites.vercel import get_transfer_auth_code

            # Get auth code (unlocking is implicit in the new API)
            auth_code = await get_transfer_auth_code(purchase.domain)

            purchase.is_locked = False
            await db.commit()

            return DomainTransferInfoType(
                domain=purchase.domain,
                is_locked=False,
                auth_code=auth_code,
                instructions=(
                    "Domänen är nu upplåst för överföring. "
                    "Använd auktoriseringskoden hos din nya domänregistrar för att initiera flytten. "
                    "Överföringen tar vanligtvis 5-7 dagar. "
                    "Domänen låses automatiskt igen efter 14 dagar om ingen överföring sker."
                ),
            )

    @strawberry.mutation
    async def lock_domain(self, info: Info, domain_id: str) -> DomainPurchaseType:
        """Re-lock a domain to prevent unauthorized transfers."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(DomainPurchase).where(
                    DomainPurchase.id == domain_id,
                    DomainPurchase.user_id == str(user.id),
                )
            )
            purchase = result.scalar_one_or_none()
            if not purchase:
                raise ValueError("Köpt domän hittades inte")

            # Re-locking is not exposed in the new Registrar API;
            # the domain is implicitly locked when no transfer is active.

            purchase.is_locked = True
            await db.commit()

            return DomainPurchaseType(
                id=purchase.id,
                domain=purchase.domain,
                price_sek=purchase.price_sek,
                status=purchase.status.value,
                period_years=purchase.period_years,
                auto_renew=purchase.auto_renew,
                is_locked=purchase.is_locked,
                expires_at=purchase.expires_at,
                purchased_at=purchase.purchased_at,
                created_at=purchase.created_at,
            )

    @strawberry.mutation
    async def toggle_domain_auto_renew(self, info: Info, domain_id: str, auto_renew: bool) -> DomainPurchaseType:
        """Enable or disable auto-renewal for a purchased domain."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(DomainPurchase).where(
                    DomainPurchase.id == domain_id,
                    DomainPurchase.user_id == str(user.id),
                )
            )
            purchase = result.scalar_one_or_none()
            if not purchase:
                raise ValueError("Köpt domän hittades inte")

            purchase.auto_renew = auto_renew
            await db.commit()

            return DomainPurchaseType(
                id=purchase.id,
                domain=purchase.domain,
                price_sek=purchase.price_sek,
                status=purchase.status.value,
                period_years=purchase.period_years,
                auto_renew=purchase.auto_renew,
                is_locked=purchase.is_locked,
                expires_at=purchase.expires_at,
                purchased_at=purchase.purchased_at,
                created_at=purchase.created_at,
            )

    @strawberry.mutation
    async def renew_purchased_domain(self, info: Info, domain_id: str) -> DomainPurchaseType:
        """Manually renew a purchased domain. Charges the user's default payment method."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(DomainPurchase).where(
                    DomainPurchase.id == domain_id,
                    DomainPurchase.user_id == str(user.id),
                )
            )
            purchase = result.scalar_one_or_none()
            if not purchase:
                raise ValueError("Köpt domän hittades inte")
            if purchase.status.value != "PURCHASED":
                raise ValueError("Kan bara förnya aktiva domäner")

            # Get renewal price
            from app.sites.vercel import check_domain_price, renew_domain as vercel_renew
            price_info = await check_domain_price(purchase.domain)
            if not price_info:
                raise ValueError("Kunde inte hämta förnyelsepris")

            # Create PaymentIntent for renewal
            import stripe
            from app.billing.service import get_or_create_stripe_customer

            customer_id = await get_or_create_stripe_customer(db, user)
            price_sek_ore = price_info["price_sek"]

            payment_intent = stripe.PaymentIntent.create(
                amount=price_sek_ore,
                currency="sek",
                customer=customer_id,
                metadata={
                    "qvicko_user_id": str(user.id),
                    "qvicko_domain": purchase.domain,
                    "qvicko_type": "domain_renewal",
                    "qvicko_purchase_id": purchase.id,
                },
                description=f"Domänförnyelse: {purchase.domain}",
                confirm=True,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            )

            if payment_intent.status == "succeeded":
                # Renew on Vercel (new API requires expected price)
                renew_result = await vercel_renew(
                    purchase.domain,
                    expected_price=price_info["price_usd"],
                )
                if renew_result:
                    from dateutil.relativedelta import relativedelta
                    purchase.expires_at = (purchase.expires_at or datetime.now(timezone.utc)) + relativedelta(years=1)
                    purchase.price_sek = price_sek_ore
                    await db.commit()
                else:
                    raise ValueError("Vercel-förnyelse misslyckades. Betalning återbetalas.")
            else:
                raise ValueError("Betalningen kunde inte genomföras. Kontrollera ditt betalkort.")

            return DomainPurchaseType(
                id=purchase.id,
                domain=purchase.domain,
                price_sek=purchase.price_sek,
                status=purchase.status.value,
                period_years=purchase.period_years,
                auto_renew=purchase.auto_renew,
                is_locked=purchase.is_locked,
                expires_at=purchase.expires_at,
                purchased_at=purchase.purchased_at,
                created_at=purchase.created_at,
            )


    # -------------------------------------------------------------------
    # Soft-delete & Pause
    # -------------------------------------------------------------------

    @strawberry.mutation
    async def request_site_deletion(self, info: Info, site_id: str, slug: str) -> bool:
        """Request site deletion. Requires matching slug. Sends confirmation email."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    GeneratedSite.id == site_id,
                    Lead.created_by == str(user.id),
                    GeneratedSite.deleted_at.is_(None),
                )
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Hemsida hittades inte")

            # Verify slug matches
            expected_slug = site.subdomain or site.id[:8]
            if slug.strip().lower() != expected_slug.lower():
                raise ValueError("Slug matchar inte. Skriv korrekt slug för att bekräfta radering.")

            # Generate deletion token
            import secrets
            from app.auth.service import _hash_token
            from datetime import timedelta

            raw_token = secrets.token_urlsafe(32)
            token_hash = _hash_token(raw_token)
            expires = datetime.now(timezone.utc) + timedelta(hours=24)

            deletion_token = SiteDeletionToken(
                site_id=site_id,
                user_id=str(user.id),
                token_hash=token_hash,
                expires_at=expires,
            )
            db.add(deletion_token)
            await db.commit()

            # Send confirmation email
            try:
                from app.email.service import _send_via_resend
                from app.email.templates import build_site_deletion_email
                site_name = site.lead.business_name if site.lead else "Din hemsida"
                html = build_site_deletion_email(site_name, raw_token)
                await _send_via_resend(
                    to=user.email,
                    subject=f"Bekräfta radering av {site_name}",
                    html=html,
                    text=f"Bekräfta radering av {site_name}. Klicka på länken i HTML-versionen av detta e-postmeddelande.",
                )
            except Exception:
                logger.warning("Failed to send deletion confirmation email to %s", user.email)

            return True

    @strawberry.mutation
    async def confirm_site_deletion(self, info: Info, token: str) -> bool:
        """Confirm site deletion via email token. Performs soft-delete."""
        user = _require_user(await _get_user_from_info(info))

        from app.auth.service import _hash_token

        token_hash = _hash_token(token)

        async with get_db_session() as db:
            result = await db.execute(
                select(SiteDeletionToken).where(
                    SiteDeletionToken.token_hash == token_hash,
                    SiteDeletionToken.user_id == str(user.id),
                    SiteDeletionToken.used_at.is_(None),
                )
            )
            deletion_token = result.scalar_one_or_none()
            if not deletion_token:
                raise ValueError("Ogiltig eller redan använd raderingstoken")

            if deletion_token.expires_at < datetime.now(timezone.utc):
                raise ValueError("Raderingstoken har gått ut. Begär en ny radering.")

            # Mark token as used
            deletion_token.used_at = datetime.now(timezone.utc)

            # Soft-delete the site
            site_result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == deletion_token.site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = site_result.scalar_one_or_none()
            if not site:
                raise ValueError("Hemsida hittades inte")

            site.deleted_at = datetime.now(timezone.utc)
            site.previous_status = site.status.value
            site.status = SiteStatus.ARCHIVED

            # Remove subdomain and custom domain from Vercel
            old_subdomain = site.subdomain
            old_custom_domain = site.custom_domain

            if old_subdomain:
                try:
                    from app.sites.vercel import remove_domain as vercel_remove
                    from app.config import settings as _settings
                    await vercel_remove(f"{old_subdomain}.{_settings.BASE_DOMAIN}")
                except Exception:
                    logger.warning("Failed to remove subdomain %s from Vercel", old_subdomain)
                site.subdomain = None

            if old_custom_domain:
                try:
                    from app.sites.vercel import remove_domain as vercel_remove
                    await vercel_remove(old_custom_domain)
                except Exception:
                    logger.warning("Failed to remove custom domain %s from Vercel", old_custom_domain)
                site.custom_domain = None

            # Unlink custom domains from this site
            domain_result = await db.execute(
                select(CustomDomain).where(CustomDomain.site_id == site.id)
            )
            for domain in domain_result.scalars().all():
                domain.site_id = None

            await db.commit()

            # Invalidate caches
            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            await cache.delete("sites:published")
            if old_subdomain:
                await cache.delete(f"resolve:sub:{old_subdomain}")
            if old_custom_domain:
                await cache.delete(f"resolve:dom:{old_custom_domain}")

            return True

    @strawberry.mutation
    async def pause_site(self, info: Info, site_id: str) -> GeneratedSiteType:
        """Pause a site. Removes it from public access but keeps data."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    GeneratedSite.id == site_id,
                    Lead.created_by == str(user.id),
                    GeneratedSite.deleted_at.is_(None),
                )
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Hemsida hittades inte")

            if site.status == SiteStatus.PAUSED:
                raise ValueError("Hemsidan är redan pausad")

            site.previous_status = site.status.value
            site.status = SiteStatus.PAUSED
            site.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(site)

            # Invalidate caches
            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            if site.subdomain:
                await cache.delete(f"resolve:sub:{site.subdomain}")
            if site.custom_domain:
                await cache.delete(f"resolve:dom:{site.custom_domain}")

            return _site_to_gql(site, site.lead)

    @strawberry.mutation
    async def unpause_site(self, info: Info, site_id: str) -> GeneratedSiteType:
        """Unpause a site. Restores previous status."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    GeneratedSite.id == site_id,
                    Lead.created_by == str(user.id),
                    GeneratedSite.deleted_at.is_(None),
                )
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Hemsida hittades inte")

            if site.status != SiteStatus.PAUSED:
                raise ValueError("Hemsidan är inte pausad")

            prev = site.previous_status
            site.status = SiteStatus(prev) if prev and prev != "PAUSED" else SiteStatus.PUBLISHED
            site.previous_status = None
            site.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(site)

            # Invalidate caches
            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            if site.subdomain:
                await cache.delete(f"resolve:sub:{site.subdomain}")
            if site.custom_domain:
                await cache.delete(f"resolve:dom:{site.custom_domain}")

            return _site_to_gql(site, site.lead)

    @strawberry.mutation
    async def update_site_settings(
        self, info: Info, site_id: str, settings: JSON
    ) -> GeneratedSiteType:
        """Update site settings (meta/SEO, language, business email).

        Accepts a JSON object with keys: meta, business, seo.
        Only provided keys are merged into site_data.
        """
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            result = await db.execute(
                select(GeneratedSite)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    GeneratedSite.id == site_id,
                    Lead.created_by == str(user.id),
                    GeneratedSite.deleted_at.is_(None),
                )
                .options(selectinload(GeneratedSite.lead))
            )
            site = result.scalar_one_or_none()
            if not site:
                raise ValueError("Hemsida hittades inte")

            # Merge settings into site_data
            site_data = dict(site.site_data) if site.site_data else {}
            allowed_keys = {"meta", "business", "seo"}
            for key in allowed_keys:
                if key in settings:
                    if isinstance(settings[key], dict):
                        existing = site_data.get(key, {})
                        if isinstance(existing, dict):
                            existing.update(settings[key])
                            site_data[key] = existing
                        else:
                            site_data[key] = settings[key]
                    else:
                        site_data[key] = settings[key]

            # Validate merged data
            try:
                SiteSchema.model_validate(site_data)
            except ValidationError as e:
                raise ValueError(f"Invalid site data: {e}")

            site.site_data = site_data
            site.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(site)

            # Invalidate caches
            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            if site.subdomain:
                await cache.delete(f"resolve:sub:{site.subdomain}")
            if site.custom_domain:
                await cache.delete(f"resolve:dom:{site.custom_domain}")

            return _site_to_gql(site, site.lead)

    @strawberry.mutation
    async def restore_site_version(
        self, info: Info, site_id: str, version_id: str
    ) -> GeneratedSiteType:
        """Restore a site to a previous version."""
        user = _require_user(await _get_user_from_info(info))

        async with get_db_session() as db:
            # Verify ownership
            site_result = await db.execute(
                select(GeneratedSite)
                .where(GeneratedSite.id == site_id)
                .options(selectinload(GeneratedSite.lead))
            )
            site = site_result.scalar_one_or_none()
            if not site:
                raise ValueError("Site not found")

            is_owner = site.lead and site.lead.created_by == str(user.id)
            if not user.is_superuser and not is_owner:
                raise PermissionError("Access denied")

            # Get the version
            version_result = await db.execute(
                select(SiteVersion).where(
                    SiteVersion.id == version_id,
                    SiteVersion.site_id == site_id,
                )
            )
            version = version_result.scalar_one_or_none()
            if not version:
                raise ValueError("Version not found")

            # Validate restored data
            try:
                SiteSchema.model_validate(version.site_data)
            except ValidationError as e:
                raise ValueError(f"Invalid version data: {e}")

            # Create a new version snapshot of current state before restoring
            max_result = await db.execute(
                select(func.coalesce(func.max(SiteVersion.version_number), 0)).where(
                    SiteVersion.site_id == site_id
                )
            )
            next_num = max_result.scalar_one() + 1
            snapshot = SiteVersion(
                site_id=site_id,
                version_number=next_num,
                site_data=version.site_data,
                label=f"Återställd från v{version.version_number}",
            )
            db.add(snapshot)

            site.site_data = version.site_data
            site.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(site)

            # Invalidate caches
            await cache.delete(f"site:{site.id}")
            await cache.delete(f"site:data:{site.id}")
            await cache.delete(f"site:meta:{site.id}")
            if site.subdomain:
                await cache.delete(f"resolve:sub:{site.subdomain}")
            if site.custom_domain:
                await cache.delete(f"resolve:dom:{site.custom_domain}")

            asyncio.ensure_future(_revalidate_viewer(site.id, site.subdomain))

            return _site_to_gql(site, site.lead)


# ---------------------------------------------------------------------------
# Background pipeline runner
# ---------------------------------------------------------------------------

async def _run_pipeline_bg(lead_id: str) -> None:
    """Run the scraper+generator pipeline in the background."""
    from app.scraper.pipeline import run_pipeline
    try:
        async with get_db_session() as db:
            await run_pipeline(db, lead_id)
            await db.commit()
    except Exception:
        logger.exception("Background pipeline failed for lead %s", lead_id)


async def _revalidate_viewer(site_id: str, subdomain: str | None) -> None:
    """Trigger ISR on-demand revalidation in the viewer app."""
    import httpx
    from app.config import settings

    viewer_url = getattr(settings, "VIEWER_URL", None) or "http://localhost:3001"
    paths = [f"/preview/{site_id}", f"/{site_id}"]

    async with httpx.AsyncClient(timeout=5) as client:
        for path in paths:
            try:
                await client.get(f"{viewer_url}/api/revalidate", params={"path": path})
            except Exception:
                pass  # Best effort — viewer cache has TTL fallback
