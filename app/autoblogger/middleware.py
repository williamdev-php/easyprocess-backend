"""AutoBlogger middleware — request ID tracking for observability."""
from __future__ import annotations

import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add X-Request-ID header to all requests/responses for tracing."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Use client-provided ID or generate one
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

        # Store on request state for use in handlers
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
