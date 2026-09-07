"""Точка входа service-2 — Catalog & Delivery Service.

Отвечает за каталог (рестораны, меню) и курьеров. Собственная база данных,
никаких прямых обращений к БД service-1: связь между сервисами идёт по HTTP
и через события RabbitMQ.
"""

import os
from contextlib import asynccontextmanager

from app.database import engine
from app.metrics import setup_metrics
from app.routes import router
from fastapi import FastAPI

INSTANCE_NAME = os.getenv("INSTANCE_NAME", "service-2-local")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Здесь позже поднимаются подключения к RabbitMQ и Redis.
    yield
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
    return {"status": "ok", "service": "catalog-delivery", "instance": INSTANCE_NAME}
