"""Обмен событиями через RabbitMQ со стороны каталога.

Этот сервис:
  - слушает order.* от service-1 и назначает курьера на новый заказ;
  - публикует courier.assigned, чтобы service-1 записал курьера в свой заказ.

Обратите внимание, что получается настоящий двусторонний обмен: ни один сервис
не вызывает другой напрямую, но оба остаются согласованными.
"""

import asyncio
import json
import logging
import os
from typing import Any

import aio_pika

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
EXCHANGE_NAME = "orderhub.events"

COURIER_ASSIGNED = "courier.assigned"

_connection: aio_pika.abc.AbstractRobustConnection | None = None
_exchange: aio_pika.abc.AbstractExchange | None = None


async def connect() -> None:
    global _connection, _exchange
    try:
        _connection = await aio_pika.connect_robust(RABBITMQ_URL, timeout=5)
        channel = await _connection.channel()
        _exchange = await channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        logger.info("Connected to RabbitMQ")
    except Exception as exc:
        logger.warning("RabbitMQ unavailable at startup: %s", exc)
        _connection = None
        _exchange = None


async def close() -> None:
    global _connection, _exchange
    if _connection is not None:
        await _connection.close()
        _connection = None
        _exchange = None


async def publish(routing_key: str, payload: dict[str, Any]) -> bool:
    if _exchange is None:
        logger.warning("Skipping event %s: no RabbitMQ connection", routing_key)
        return False
    try:
        await _exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload, default=str).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
        )
        logger.info("Published %s: %s", routing_key, payload)
        return True
    except Exception as exc:
        logger.warning("Failed to publish %s: %s", routing_key, exc)
        return False


async def publish_courier_assigned(order_id: int, courier_id: int) -> bool:
    return await publish(
        COURIER_ASSIGNED, {"order_id": order_id, "courier_id": courier_id}
    )


async def consume_order_events() -> None:
    """Слушает order.* и на новый заказ подбирает свободного курьера.

    Это и есть польза от событий: подбор курьера может занять время и
    сорваться, но клиент не должен ждать его при оформлении заказа. Заказ
    создаётся мгновенно, а курьер назначается фоном.
    """
    if _connection is None:
        logger.warning("Order consumer not started: no RabbitMQ connection")
        return

    from app.database import AsyncSessionLocal
    from app.models import CourierStatus
    from app.schemas import CourierUpdate
    from app.services import list_couriers, update_courier

    channel = await _connection.channel()
    # prefetch_count=1: брокер не выдаст следующее сообщение, пока не
    # подтверждено текущее. Иначе два заказа могли бы одновременно получить
    # одного и того же свободного курьера.
    await channel.set_qos(prefetch_count=1)

    queue = await channel.declare_queue("service-2.order-events", durable=True)
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    await queue.bind(exchange, routing_key="order.*")

    async with queue.iterator() as messages:
        async for message in messages:
            async with message.process():
                try:
                    event = json.loads(message.body)
                except json.JSONDecodeError as exc:
                    logger.error("Malformed order event: %s", exc)
                    continue

                # Курьера ищем только для новых заказов; события о смене
                # статуса просто логируем.
                if message.routing_key != "order.created":
                    logger.info("Order event %s: %s", message.routing_key, event)
                    continue

                order_id = event.get("order_id")
                if order_id is None:
                    continue

                async with AsyncSessionLocal() as db:
                    available = await list_couriers(db, status=CourierStatus.AVAILABLE)
                    if not available:
                        logger.info("No available courier for order %s", order_id)
                        continue

                    courier = available[0]
                    await update_courier(
                        db, courier.id, CourierUpdate(status=CourierStatus.BUSY)
                    )

                await publish_courier_assigned(order_id, courier.id)


def start_consumer() -> asyncio.Task | None:
    if _connection is None:
        return None
    return asyncio.create_task(consume_order_events())
