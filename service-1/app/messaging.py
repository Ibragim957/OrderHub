import asyncio
import json
import logging
import os
from typing import Any

import aio_pika

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
EXCHANGE_NAME = "orderhub.events"

ORDER_CREATED = "order.created"
ORDER_STATUS_CHANGED = "order.status_changed"

_connection: aio_pika.abc.AbstractRobustConnection | None = None
_exchange: aio_pika.abc.AbstractExchange | None = None


async def connect() -> None:
    global _connection, _exchange
    try:
        _connection = await aio_pika.connect_robust(RABBITMQ_URL, timeout=5)
        channel = await _connection.channel()
        _exchange = await channel.declare_exchange(
            EXCHANGE_NAME,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
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


async def publish_order_created(order) -> bool:
    return await publish(
        ORDER_CREATED,
        {
            "order_id": order.id,
            "user_id": order.user_id,
            "restaurant_id": order.restaurant_id,
            "total_price": str(order.total_price),
            "items": [
                {"menu_item_id": i.menu_item_id, "quantity": i.quantity} for i in order.items
            ],
        },
    )


async def publish_order_status_changed(order, previous_status: str) -> bool:
    return await publish(
        ORDER_STATUS_CHANGED,
        {
            "order_id": order.id,
            "user_id": order.user_id,
            "from_status": previous_status,
            "to_status": order.status.value,
        },
    )


async def consume_courier_events() -> None:
    if _connection is None:
        logger.warning("Courier consumer not started: no RabbitMQ connection")
        return

    from app.database import AsyncSessionLocal
    from app.services import assign_courier

    channel = await _connection.channel()
    queue = await channel.declare_queue("service-1.courier-events", durable=True)
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    await queue.bind(exchange, routing_key="courier.*")

    async with queue.iterator() as messages:
        async for message in messages:
            async with message.process():
                try:
                    event = json.loads(message.body)
                    order_id = event["order_id"]
                    courier_id = event["courier_id"]
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.error("Malformed courier event: %s", exc)
                    continue

                async with AsyncSessionLocal() as db:
                    order = await assign_courier(db, order_id, courier_id)

                if order is None:
                    logger.warning("Courier event for unknown order %s", order_id)
                else:
                    logger.info("Assigned courier %s to order %s", courier_id, order_id)


def start_consumer() -> asyncio.Task | None:
    if _connection is None:
        return None
    return asyncio.create_task(consume_courier_events())
