"""Shared pagination types for consistent offset/limit pagination across all
GraphQL list endpoints.

Usage in filter inputs::

    @strawberry.input
    class LeadFilterInput(PaginationInput):
        status: str | None = None
        ...

Usage in list response types::

    @strawberry.type
    class LeadListType(PaginatedListType):
        items: list[LeadType]
"""

from __future__ import annotations

import strawberry


DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@strawberry.input
class PaginationInput:
    """Shared base for all paginated filter inputs.

    All list queries use **offset/limit** (page-based) pagination:
    - ``page``: 1-indexed page number (default 1)
    - ``page_size``: items per page (default 20, max 100)
    """

    page: int = DEFAULT_PAGE
    page_size: int = DEFAULT_PAGE_SIZE

    def validated_page_size(self, max_size: int = MAX_PAGE_SIZE) -> int:
        """Return page_size clamped to *max_size*."""
        return max(1, min(self.page_size, max_size))

    def offset(self, max_size: int = MAX_PAGE_SIZE) -> int:
        """Return the SQL OFFSET derived from page and page_size."""
        return (max(1, self.page) - 1) * self.validated_page_size(max_size)


@strawberry.type
class PaginatedListType:
    """Shared base fields for all paginated list responses."""

    total: int
    page: int
    page_size: int
