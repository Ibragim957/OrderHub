"""Точка входа service-2 — Catalog & Delivery Service.

Отвечает за каталог (рестораны, меню) и курьеров. Собственная база данных,
никаких прямых обращений к БД service-1: связь между сервисами идёт по HTTP
и через события RabbitMQ.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import engine
from app.routes import router


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


@app.get("/health", tags=["system"])
async def health():
    """Проверка живости сервиса.

    Используется healthcheck'ом Docker Compose и мониторингом.
    """
    return {"status": "ok", "service": "catalog-delivery"}
