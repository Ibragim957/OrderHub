import json
import logging
import os

import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))

RESTAURANTS_PREFIX = "catalog:restaurants"

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
            retry_on_timeout=False,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def restaurants_key(skip: int, limit: int) -> str:
    return f"{RESTAURANTS_PREFIX}:list:{skip}:{limit}"


async def get_cached(key: str) -> list | dict | None:
    try:
        raw = await get_client().get(key)
    except (RedisError, OSError, RuntimeError) as exc:
        logger.warning("Redis unavailable on read, falling back to database: %s", exc)
        return None

    if raw is None:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def set_cached(key: str, value: list | dict, ttl: int = CACHE_TTL_SECONDS) -> None:
    try:
        await get_client().set(key, json.dumps(value, default=str), ex=ttl)
    except (RedisError, OSError, RuntimeError) as exc:
        logger.warning("Redis unavailable on write, skipping cache: %s", exc)


async def invalidate_restaurants() -> None:
    try:
        client = get_client()
        keys = [key async for key in client.scan_iter(f"{RESTAURANTS_PREFIX}:*")]
        if keys:
            await client.delete(*keys)
            logger.info("Invalidated %d cached restaurant entries", len(keys))
    except (RedisError, OSError, RuntimeError) as exc:
        logger.warning("Redis unavailable on invalidation: %s", exc)


async def ping() -> bool:
    try:
        return bool(await get_client().ping())
    except (RedisError, OSError, RuntimeError):
        return False
