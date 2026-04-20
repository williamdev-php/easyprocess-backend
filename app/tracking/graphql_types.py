import strawberry


@strawberry.type
class FunnelStepType:
    name: str
    count: int
    conversion_rate: float | None


@strawberry.type
class FunnelStatsType:
    steps: list[FunnelStepType]
    start_date: str
    end_date: str


@strawberry.type
class DailyVisitorPointType:
    date: str
    count: int


@strawberry.type
class VisitorStatsType:
    points: list[DailyVisitorPointType]
    total: int


@strawberry.type
class UtmEntryType:
    source: str | None
    medium: str | None
    campaign: str | None
    count: int


@strawberry.type
class TopPageType:
    path: str
    count: int


@strawberry.type
class AnalyticsOverviewType:
    unique_visitors: int
    total_signups: int
    total_trials: int
    total_subscriptions: int
    trial_start_rate: float
    trial_conversion_rate: float
    total_revenue_sek: int
    avg_session_duration_seconds: float
