"""Redis caching utilities for AutoBlogger.

All keys use the 'autoblogger:' prefix to avoid collisions with other apps.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "autoblogger:"

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    """Return the shared async Redis client."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Close Redis connection (call on app shutdown)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def cache_get(key: str) -> Any | None:
    """Get a cached value by key. Returns None on miss or error."""
    try:
        r = _get_redis()
        raw = await r.get(f"{_PREFIX}{key}")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.debug("Cache miss/error for key=%s", key)
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Set a cached value with TTL in seconds (default 5 minutes)."""
    try:
        r = _get_redis()
        await r.set(f"{_PREFIX}{key}", json.dumps(value, default=str), ex=ttl)
    except Exception:
        logger.debug("Cache set failed for key=%s", key)


async def cache_delete(key: str) -> None:
    """Delete a cached key."""
    try:
        r = _get_redis()
        await r.delete(f"{_PREFIX}{key}")
    except Exception:
        logger.debug("Cache delete failed for key=%s", key)


async def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching a pattern (e.g., 'user:abc:*')."""
    try:
        r = _get_redis()
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=f"{_PREFIX}{pattern}", count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        logger.debug("Cache delete pattern failed for pattern=%s", pattern)
