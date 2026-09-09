"""Кэширование в Redis.

Кэшируем список ресторанов: его читают все клиенты постоянно, а меняется он
редко — именно тот случай, когда кэш оправдан.

Главный принцип модуля: **кэш не должен ронять сервис**. Redis — ускоритель,
а не источник данных. Если он недоступен, приложение обязано продолжить
работать, просто медленнее, читая из PostgreSQL. Это и называется graceful
degradation, и ради него каждая операция обёрнута в try/except.
"""

import json
import logging
import os

import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")

# Время жизни записи. Даже при идеальной инвалидации TTL нужен как страховка:
# если мы где-то забудем сбросить кэш, запись протухнет сама и не будет
# показывать устаревшие данные вечно.
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))

# Префикс ключей: позволяет сбросить только наш кэш, не задев чужие данные
# в той же базе Redis.
RESTAURANTS_PREFIX = "catalog:restaurants"

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    """Одно подключение на процесс, создаётся при первом обращении.

    redis-py сам держит пул соединений внутри, поэтому создавать клиента
    на каждый запрос не нужно.
    """
    global _client
    if _client is None:
        _client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            # Короткие таймауты обязательны. С настройками по умолчанию клиент
            # ждёт подключения секундами и ещё повторяет попытки — при лежащем
            # Redis каждый запрос к API замедлялся бы на 8 секунд вместо
            # мгновенного отката к базе. Кэш должен либо помочь быстро,
            # либо мгновенно уйти с дороги.
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
            retry_on_timeout=False,
        )
    return _client


async def close_client() -> None:
    """Закрывает подключение при остановке сервиса."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def restaurants_key(skip: int, limit: int) -> str:
    """Ключ зависит от параметров пагинации.

    Без skip/limit в ключе первая же страница затёрла бы вторую, и клиент
    получал бы чужие данные.
    """
    return f"{RESTAURANTS_PREFIX}:list:{skip}:{limit}"


async def get_cached(key: str) -> list | dict | None:
    """Читает значение из кэша. None означает "нет данных" ИЛИ "Redis недоступен".

    Для вызывающего это одно и то же: в обоих случаях нужно идти в базу.
    """
    try:
        raw = await get_client().get(key)
    except (RedisError, OSError) as exc:
        # OSError покрывает случай, когда Redis вообще не поднят.
        logger.warning("Redis unavailable on read, falling back to database: %s", exc)
        return None

    if raw is None:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # В кэше мусор (например, формат данных изменился после деплоя).
        # Считаем, что кэша нет — данные всё равно возьмём из базы.
        return None


async def set_cached(key: str, value: list | dict, ttl: int = CACHE_TTL_SECONDS) -> None:
    """Кладёт значение в кэш. Ошибка Redis не должна прерывать запрос."""
    try:
        # default=str нужен для Decimal и datetime: json их не умеет,
        # а в ответах каталога есть и то, и другое.
        await get_client().set(key, json.dumps(value, default=str), ex=ttl)
    except (RedisError, OSError) as exc:
        logger.warning("Redis unavailable on write, skipping cache: %s", exc)


async def invalidate_restaurants() -> None:
    """Сбрасывает весь кэш списков ресторанов.

    Вызывается при любом изменении ресторанов. Удаляем все страницы разом:
    после добавления ресторана съезжает вся пагинация, а не одна страница.

    scan_iter, а не keys(): keys() блокирует Redis на время обхода всех ключей,
    что на нагруженной базе останавливает обслуживание. scan_iter идёт
    порциями и никого не блокирует.
    """
    try:
        client = get_client()
        keys = [key async for key in client.scan_iter(f"{RESTAURANTS_PREFIX}:*")]
        if keys:
            await client.delete(*keys)
            logger.info("Invalidated %d cached restaurant entries", len(keys))
    except (RedisError, OSError) as exc:
        # Сброс не удался — данные в кэше устареют максимум на TTL.
        # Это неприятно, но не повод отменять уже выполненное изменение.
        logger.warning("Redis unavailable on invalidation: %s", exc)


async def ping() -> bool:
    """Доступен ли Redis. Используется в /health."""
    try:
        return bool(await get_client().ping())
    except (RedisError, OSError):
        return False
