import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

logger = logging.getLogger(__name__)

# Use Redis for rate limit storage when available (required for multi-instance
# deployments), otherwise fall back to in-memory.
_storage_uri = settings.effective_redis_url or "memory://"

if _storage_uri != "memory://":
    logger.info("Rate limiter using Redis storage")
else:
    logger.info("Rate limiter using in-memory storage (single instance only)")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri,
)
