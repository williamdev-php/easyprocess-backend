"""
Redis cache with automatic in-memory (dict) fallback.

Usage:
    from app.cache import cache

    await cache.set("key", "value", ttl=300)
    value = await cache.get("key")
    await cache.delete("key")
    await cache.delete_pattern("site:*")
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_MAX_CACHE_SIZE = 1000

# Try to import redis; fall back gracefully
try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class _InMemoryCache:
    """Simple dict-based cache for development / when Redis is unavailable."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires is not None and time.time() > expires:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        # Evict oldest entries if cache is full
        while len(self._store) >= _MAX_CACHE_SIZE:
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]
        expires = (time.time() + ttl) if ttl else None
        self._store[key] = (value, expires)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_pattern(self, pattern: str) -> int:
        prefix = pattern.rstrip("*")
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]
        return len(keys)

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def flush(self) -> None:
        self._store.clear()

    async def close(self) -> None:
        pass

    @property
    def backend(self) -> str:
        return "memory"


class _RedisCache:
    """Async Redis cache wrapper."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: aioredis.Redis | None = None

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                self._url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return self._client

    async def get(self, key: str) -> Any | None:
        client = await self._get_client()
        raw = await client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        client = await self._get_client()
        serialized = json.dumps(value) if not isinstance(value, str) else value
        if ttl:
            await client.setex(key, ttl, serialized)
        else:
            await client.set(key, serialized)

    async def delete(self, key: str) -> None:
        client = await self._get_client()
        await client.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        client = await self._get_client()
        count = 0
        async for key in client.scan_iter(match=pattern, count=100):
            await client.delete(key)
            count += 1
        return count

    async def exists(self, key: str) -> bool:
        client = await self._get_client()
        return bool(await client.exists(key))

    async def flush(self) -> None:
        client = await self._get_client()
        await client.flushdb()

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def backend(self) -> str:
        return "redis"


class Cache:
    """
    Auto-selecting cache: tries Redis first, falls back to in-memory.
    """

    def __init__(self) -> None:
        self._impl: _RedisCache | _InMemoryCache | None = None

    async def _get_impl(self) -> _RedisCache | _InMemoryCache:
        if self._impl is not None:
            return self._impl

        if HAS_REDIS and settings.REDIS_URL:
            try:
                r = _RedisCache(settings.REDIS_URL)
                client = await r._get_client()
                await client.ping()
                self._impl = r
                logger.info("Cache backend: Redis (%s)", settings.REDIS_URL)
                return self._impl
            except Exception as e:
                logger.warning("Redis unavailable (%s), using in-memory cache", e)

        self._impl = _InMemoryCache()
        logger.info("Cache backend: in-memory")
        return self._impl

    async def get(self, key: str) -> Any | None:
        impl = await self._get_impl()
        return await impl.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        impl = await self._get_impl()
        await impl.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        impl = await self._get_impl()
        await impl.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        impl = await self._get_impl()
        return await impl.delete_pattern(pattern)

    async def exists(self, key: str) -> bool:
        impl = await self._get_impl()
        return await impl.exists(key)

    async def flush(self) -> None:
        impl = await self._get_impl()
        await impl.flush()

    async def close(self) -> None:
        if self._impl:
            await self._impl.close()
            self._impl = None

    @property
    def backend(self) -> str:
        if self._impl:
            return self._impl.backend
        return "not initialized"


# Global singleton
cache = Cache()
