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
    await engine.dispose()


app = FastAPI(
    title="OrderHub — Catalog & Delivery Service",
    description="Рестораны, меню и курьеры",
    version="0.1.0",
    lifespan=lifespan,
    root_path=os.getenv("ROOT_PATH", ""),
)

app.include_router(router)
setup_metrics(app)


@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "service": "catalog-delivery",
        "instance": INSTANCE_NAME,
        "redis": "up" if await redis_ping() else "down",
    }
