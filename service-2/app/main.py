"""Точка входа service-2 — Catalog & Delivery Service.

Отвечает за каталог (рестораны, меню) и курьеров. Собственная база данных,
никаких прямых обращений к БД service-1: связь между сервисами идёт по HTTP
и через события RabbitMQ.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import messaging
from app.cache import close_client
from app.cache import ping as redis_ping
from app.database import engine
from app.metrics import setup_metrics
from app.routes import router

# Без явной настройки сообщения logging из наших модулей никуда не выводятся:
# uvicorn настраивает только свои логгеры. Без этого события RabbitMQ и
# предупреждения о недоступном Redis работали бы "втихую".
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)

INSTANCE_NAME = os.getenv("INSTANCE_NAME", "service-2-local")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await messaging.connect()
    consumer = messaging.start_consumer()

    yield

    if consumer is not None:
        consumer.cancel()
    await messaging.close()
    await close_client()
    # Корректно закрываем пул подключений к БД при остановке сервиса,
    # иначе Postgres будет какое-то время держать осиротевшие соединения.
    await engine.dispose()


app = FastAPI(
    title="OrderHub — Catalog & Delivery Service",
    description="Рестораны, меню и курьеры",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
setup_metrics(app)


@app.get("/health", tags=["system"])
async def health():
    """Проверка живости сервиса.

    Используется healthcheck'ом Docker Compose и мониторингом.
    """
    # instance попадает в ответ, чтобы через nginx было видно,
    # какой из двух контейнеров обслужил запрос — наглядное доказательство
    # того, что балансировка действительно работает.
    # Redis показываем отдельным полем, но общий статус от него НЕ зависит:
    # сервис исправен и без кэша, просто работает медленнее.
    return {
        "status": "ok",
        "service": "catalog-delivery",
        "instance": INSTANCE_NAME,
        "redis": "up" if await redis_ping() else "down",
    }
