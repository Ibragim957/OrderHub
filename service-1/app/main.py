import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import messaging
from app.database import engine
from app.metrics import setup_metrics
from app.routes import router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)

INSTANCE_NAME = os.getenv("INSTANCE_NAME", "service-1-local")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await messaging.connect()
    consumer = messaging.start_consumer()

    yield

    if consumer is not None:
        consumer.cancel()
    await messaging.close()
    await engine.dispose()


app = FastAPI(
    title="OrderHub — Order Service",
    description="Пользователи и заказы",
    version="0.1.0",
    lifespan=lifespan,
    root_path=os.getenv("ROOT_PATH", ""),
)

app.include_router(router)
setup_metrics(app)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "order", "instance": INSTANCE_NAME}
