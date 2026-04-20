import logging
import time
from collections import defaultdict

import strawberry
from strawberry.extensions import SchemaExtension
from strawberry.fastapi import GraphQLRouter

from app.auth.resolvers import Mutation as AuthMutation, Query as AuthQuery
from app.billing.resolvers import BillingMutation, BillingQuery
from app.media.resolvers import MediaMutation, MediaQuery
from app.sites.resolvers import SiteMutation, SiteQuery
from app.tracking.resolvers import AnalyticsQuery

logger = logging.getLogger(__name__)


class GraphQLRateLimitExtension(SchemaExtension):
    """Simple in-memory rate limiter for GraphQL mutations.

    Limits each IP to MAX_MUTATIONS mutations per WINDOW_SECONDS window.
    Queries are not rate-limited here (they are read-only).
    """

    WINDOW_SECONDS = 60
    MAX_MUTATIONS = 30

    # {ip: [(timestamp, ...), ...]}
    _buckets: dict[str, list[float]] = defaultdict(list)

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
        if is_mutation:
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            bucket = self._buckets[ip]

            # Prune expired entries
            cutoff = now - self.WINDOW_SECONDS
            self._buckets[ip] = bucket = [t for t in bucket if t > cutoff]

            if len(bucket) >= self.MAX_MUTATIONS:
                logger.warning("GraphQL rate limit exceeded for IP %s", ip)
                from graphql import GraphQLError
                raise GraphQLError(
                    f"Rate limit exceeded. Max {self.MAX_MUTATIONS} mutations per minute."
                )

            bucket.append(now)

        yield


@strawberry.type
class Query(AuthQuery, SiteQuery, BillingQuery, MediaQuery, AnalyticsQuery):
    pass


@strawberry.type
class Mutation(AuthMutation, SiteMutation, BillingMutation, MediaMutation):
    pass


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[GraphQLRateLimitExtension],
)

graphql_app = GraphQLRouter(schema)
