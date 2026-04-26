"""AutoBlogger custom exception classes and exception handlers."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


class AutoBloggerError(Exception):
    """Base exception for all AutoBlogger errors."""

    def __init__(self, message: str = "An AutoBlogger error occurred", detail: object = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class InsufficientCreditsError(AutoBloggerError):
    """Raised when a user does not have enough credits for an operation."""

    def __init__(self, message: str = "Insufficient credits", detail: object = None):
        super().__init__(message=message, detail=detail)


class PostGenerationError(AutoBloggerError):
    """Raised when blog post generation fails."""

    def __init__(self, message: str = "Post generation failed", detail: object = None):
        super().__init__(message=message, detail=detail)


class PublishError(AutoBloggerError):
    """Raised when publishing a post to a platform fails."""

    def __init__(self, message: str = "Publishing failed", detail: object = None):
        super().__init__(message=message, detail=detail)


class IntegrationError(AutoBloggerError):
    """Raised when a platform integration (Shopify, WordPress, etc.) encounters an error."""

    def __init__(self, message: str = "Integration error", detail: object = None):
        super().__init__(message=message, detail=detail)


class InvalidSourceError(AutoBloggerError):
    """Raised when a source configuration is invalid or missing."""

    def __init__(self, message: str = "Invalid source", detail: object = None):
        super().__init__(message=message, detail=detail)


# ---------------------------------------------------------------------------
# HTTP status code mapping
# ---------------------------------------------------------------------------

_STATUS_CODES: dict[type[AutoBloggerError], int] = {
    InsufficientCreditsError: 402,
    PostGenerationError: 500,
    PublishError: 502,
    IntegrationError: 502,
    InvalidSourceError: 422,
    AutoBloggerError: 500,
}

_ERROR_CODES: dict[type[AutoBloggerError], str] = {
    InsufficientCreditsError: "INSUFFICIENT_CREDITS",
    PostGenerationError: "POST_GENERATION_ERROR",
    PublishError: "PUBLISH_ERROR",
    IntegrationError: "INTEGRATION_ERROR",
    InvalidSourceError: "INVALID_SOURCE",
    AutoBloggerError: "AUTOBLOGGER_ERROR",
}


# ---------------------------------------------------------------------------
# Exception handler
# ---------------------------------------------------------------------------


async def autoblogger_exception_handler(request: Request, exc: AutoBloggerError) -> JSONResponse:
    """Return structured JSON for AutoBloggerError subclasses."""
    # Walk MRO to find the most specific registered status code
    status_code = 500
    error_code = "AUTOBLOGGER_ERROR"
    for cls in type(exc).__mro__:
        if cls in _STATUS_CODES:
            status_code = _STATUS_CODES[cls]
            error_code = _ERROR_CODES.get(cls, "AUTOBLOGGER_ERROR")
            break

    body: dict = {
        "error": {
            "code": error_code,
            "message": exc.message,
        }
    }
    if exc.detail is not None:
        body["error"]["detail"] = exc.detail

    return JSONResponse(status_code=status_code, content=body)
