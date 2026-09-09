"""Точка входа service-1 — Order Service.

Отвечает за пользователей и заказы. Цены и данные каталога берёт у service-2
по HTTP; прямого доступа к его базе нет.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import messaging
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

INSTANCE_NAME = os.getenv("INSTANCE_NAME", "service-1-local")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await messaging.connect()
    # Потребитель живёт фоновой задачей: он слушает очередь бесконечно,
    # и запускать его синхронно значило бы заблокировать старт приложения.
    consumer = messaging.start_consumer()

    yield

    if consumer is not None:
        consumer.cancel()
    await messaging.close()
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
