import logging

from starlette.requests import Request
from slowapi import Limiter

from app.config import settings

logger = logging.getLogger(__name__)

# Use Redis for rate limit storage when available (required for multi-instance
# deployments), otherwise fall back to in-memory.
_storage_uri = settings.effective_redis_url or "memory://"

if _storage_uri != "memory://":
    logger.info("Rate limiter using Redis storage")
else:
    logger.info("Rate limiter using in-memory storage (single instance only)")


def _get_real_client_ip(request: Request) -> str:
    """Extract the real client IP, correctly handling X-Forwarded-For behind a
    trusted reverse proxy in production.

    Takes the leftmost (first) IP from X-Forwarded-For, which is the original
    client IP set by the first proxy in the chain. Only trusted in production
    where we know traffic comes through a reverse proxy (Railway, Vercel, etc.).
    In development, falls back to the direct connection IP.
    """
    if settings.ENVIRONMENT == "production":
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The first IP is the original client; subsequent IPs are proxies.
            return forwarded.split(",")[0].strip()
    # Development or no proxy header — use direct connection IP.
    if request.client:
        return request.client.host
    return "127.0.0.1"


limiter = Limiter(
    key_func=_get_real_client_ip,
    storage_uri=_storage_uri,
)
