import logging
import time
from collections import defaultdict

import strawberry
from strawberry.extensions import SchemaExtension, QueryDepthLimiter
from strawberry.fastapi import GraphQLRouter

from app.auth.resolvers import Mutation as AuthMutation, Query as AuthQuery
from app.billing.admin_subscriptions_resolvers import AdminSubscriptionQuery
from app.billing.resolvers import BillingMutation, BillingQuery
from app.billing.revenue_resolvers import RevenueQuery
from app.media.resolvers import MediaMutation, MediaQuery
from app.sites.resolvers import SiteMutation, SiteQuery
from app.support.resolvers import SupportMutation, SupportQuery
from app.tracking.resolvers import AnalyticsQuery
from app.apps.resolvers import Mutation as AppMutation, Query as AppQuery
from app.platform_settings.resolvers import PlatformSettingsMutation, PlatformSettingsQuery

logger = logging.getLogger(__name__)


class GraphQLRateLimitExtension(SchemaExtension):
    """In-memory rate limiter for GraphQL mutations.

    General limit: MAX_MUTATIONS mutations per WINDOW_SECONDS window per IP.
    Heavy mutations (site generation): stricter per-IP limits.
    """

    WINDOW_SECONDS = 60
    MAX_MUTATIONS = 30

    # Stricter limits for expensive mutations (per IP, per window)
    _HEAVY_MUTATIONS = {
        "createLead": 5,
        "scrapeLead": 5,
        "create_lead": 5,
        "scrape_lead": 5,
    }
    _HEAVY_WINDOW_SECONDS = 60

    # {ip: [(timestamp, ...), ...]}
    _buckets: dict[str, list[float]] = defaultdict(list)
    _heavy_buckets: dict[str, list[float]] = defaultdict(list)

    def on_operation(self):
        request = self.execution_context.context.get("request")
        if not request:
            yield
            return

        # Only rate-limit mutations
        from graphql import OperationType

        doc = self.execution_context.graphql_document
        is_mutation = (
            doc is not None
            and doc.definitions
            and getattr(doc.definitions[0], "operation", None)
            == OperationType.MUTATION
        )

        rate_limit_info: dict = {}

        if is_mutation:
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()

            # --- General mutation rate limit ---
            bucket = self._buckets[ip]
            cutoff = now - self.WINDOW_SECONDS
            self._buckets[ip] = bucket = [t for t in bucket if t > cutoff]

            remaining = max(0, self.MAX_MUTATIONS - len(bucket))
            rate_limit_info = {
                "rateLimit": {
                    "limit": self.MAX_MUTATIONS,
                    "remaining": remaining,
                    "resetInSeconds": self.WINDOW_SECONDS,
                }
            }

            if len(bucket) >= self.MAX_MUTATIONS:
                logger.warning("GraphQL rate limit exceeded for IP %s", ip)
                from graphql import GraphQLError
                raise GraphQLError(
                    f"Rate limit exceeded. Max {self.MAX_MUTATIONS} mutations per minute.",
                    extensions=rate_limit_info,
                )

            bucket.append(now)
            # Update remaining after recording this request
            rate_limit_info["rateLimit"]["remaining"] = max(0, self.MAX_MUTATIONS - len(bucket))

            # --- Per-mutation type rate limit for heavy operations ---
            selections = getattr(doc.definitions[0], "selection_set", None)
            if selections:
                for sel in selections.selections:
                    mutation_name = getattr(sel, "name", None)
                    if mutation_name:
                        name_str = mutation_name.value
                        max_allowed = self._HEAVY_MUTATIONS.get(name_str)
                        if max_allowed is not None:
                            heavy_key = f"{ip}:{name_str}"
                            h_bucket = self._heavy_buckets[heavy_key]
                            h_cutoff = now - self._HEAVY_WINDOW_SECONDS
                            self._heavy_buckets[heavy_key] = h_bucket = [
                                t for t in h_bucket if t > h_cutoff
                            ]
                            heavy_remaining = max(0, max_allowed - len(h_bucket))
                            rate_limit_info["rateLimit"][name_str] = {
                                "limit": max_allowed,
                                "remaining": heavy_remaining,
                                "resetInSeconds": self._HEAVY_WINDOW_SECONDS,
                            }
                            if len(h_bucket) >= max_allowed:
                                logger.warning(
                                    "Heavy mutation rate limit exceeded: %s for IP %s",
                                    name_str, ip,
                                )
                                from graphql import GraphQLError
                                raise GraphQLError(
                                    f"Rate limit exceeded for {name_str}. "
                                    f"Max {max_allowed} per minute.",
                                    extensions=rate_limit_info,
                                )
                            h_bucket.append(now)
                            rate_limit_info["rateLimit"][name_str]["remaining"] = max(
                                0, max_allowed - len(h_bucket)
                            )

        yield

        # Attach rate limit info to response extensions so clients can see usage
        if rate_limit_info:
            result = self.execution_context.result
            if result is not None:
                if result.extensions is None:
                    result.extensions = {}
                result.extensions.update(rate_limit_info)


@strawberry.type
class Query(AuthQuery, SiteQuery, BillingQuery, MediaQuery, AnalyticsQuery, RevenueQuery, AdminSubscriptionQuery, SupportQuery, AppQuery, PlatformSettingsQuery):
    pass


@strawberry.type
class Mutation(AuthMutation, SiteMutation, BillingMutation, MediaMutation, SupportMutation, AppMutation, PlatformSettingsMutation):
    pass


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[GraphQLRateLimitExtension, QueryDepthLimiter(max_depth=10)],
)

graphql_app = GraphQLRouter(schema)
