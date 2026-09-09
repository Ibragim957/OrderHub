"""Точка входа service-1 — Order Service.

Отвечает за пользователей и заказы. Цены и данные каталога берёт у service-2
по HTTP; прямого доступа к его базе нет.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import engine
from app.metrics import setup_metrics
from app.routes import router

INSTANCE_NAME = os.getenv("INSTANCE_NAME", "service-1-local")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Здесь позже поднимаются подключения к RabbitMQ и Redis.
    yield
    # Закрываем пул подключений к БД при остановке, иначе Postgres какое-то
    # время держит осиротевшие соединения.
    await engine.dispose()


app = FastAPI(
    title="OrderHub — Order Service",
    description="Пользователи и заказы",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
setup_metrics(app)


@app.get("/health", tags=["system"])
async def health():
    """Проверка живости сервиса — для healthcheck Docker и мониторинга."""
    return {"status": "ok", "service": "order", "instance": INSTANCE_NAME}
