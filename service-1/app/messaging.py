"""Асинхронный обмен событиями через RabbitMQ.

Зачем это нужно помимо HTTP. Прямой вызов service-1 -> service-2 связывает
сервисы жёстко: если каталог лежит, заказ не создать. События работают иначе —
сервис публикует факт "заказ создан" и продолжает работу, не зная и не
интересуясь, кто и когда это прочитает. Если подписчик недоступен, сообщение
подождёт его в очереди.

Схема обмена:

    service-1  --order.created---------->  [orderhub.events]  -->  service-2
    service-1  --order.status_changed-->   [orderhub.events]  -->  service-2
    service-2  --courier.assigned------>   [orderhub.events]  -->  service-1

Обмен типа topic: отправитель помечает сообщение ключом ("order.created"),
получатель подписывается на шаблон ("order.*"). Отправитель не знает о
получателях ничего — их может быть ноль, один или десять.
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

# Типы событий, которые публикует этот сервис.
ORDER_CREATED = "order.created"
ORDER_STATUS_CHANGED = "order.status_changed"

_connection: aio_pika.abc.AbstractRobustConnection | None = None
_exchange: aio_pika.abc.AbstractExchange | None = None


async def connect() -> None:
    """Подключается к брокеру и объявляет обмен.

    connect_robust, а не connect: он сам переподключается после обрыва связи.
    Без этого одна перезагрузка RabbitMQ навсегда оставила бы сервис без
    событий до перезапуска.
    """
    global _connection, _exchange
    try:
        _connection = await aio_pika.connect_robust(RABBITMQ_URL, timeout=5)
        channel = await _connection.channel()
        _exchange = await channel.declare_exchange(
            EXCHANGE_NAME,
            aio_pika.ExchangeType.TOPIC,
            # durable=True: обмен переживёт перезапуск брокера.
            durable=True,
        )
        logger.info("Connected to RabbitMQ")
    except Exception as exc:
        # Брокер недоступен — сервис всё равно должен подняться и обслуживать
        # HTTP. События подождут: это дополнительная возможность, а не условие
        # работоспособности API.
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
    """Публикует событие. Возвращает False, если брокер недоступен.

    Публикация никогда не бросает исключение наружу: заказ уже сохранён
    в базе, и провал отправки уведомления не повод отвечать клиенту ошибкой.
    """
    if _exchange is None:
        logger.warning("Skipping event %s: no RabbitMQ connection", routing_key)
        return False

    try:
        await _exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload, default=str).encode(),
                content_type="application/json",
                # PERSISTENT: сообщение записывается на диск и переживает
                # перезапуск брокера. Для событий о заказах это обязательно —
                # потерянное событие означает несогласованность между сервисами.
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
    """Событие о новом заказе: каталог узнаёт, что пора искать курьера."""
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
    """Событие о смене статуса: по нему строится трекинг и уведомления."""
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
    """Слушает courier.assigned от service-2 и проставляет курьера в заказе.

    Это обратное направление: каталог назначил курьера и сообщил об этом,
    а мы обновляем свой заказ. Через HTTP так не сделать — service-2 не
    должен знать внутреннее устройство чужих заказов.
    """
    if _connection is None:
        logger.warning("Courier consumer not started: no RabbitMQ connection")
        return

    from app.database import AsyncSessionLocal
    from app.services import assign_courier

    channel = await _connection.channel()
    # Очередь именованная и durable: сообщения копятся в ней, даже когда
    # сервис выключен, и не теряются при перезапуске брокера.
    queue = await channel.declare_queue("service-1.courier-events", durable=True)
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    await queue.bind(exchange, routing_key="courier.*")

    async with queue.iterator() as messages:
        async for message in messages:
            # async with message.process() подтверждает обработку при выходе
            # из блока. Если внутри случится исключение, подтверждения не будет
            # и брокер вернёт сообщение в очередь — оно не потеряется.
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
    """Запускает потребителя фоновой задачей, чтобы не блокировать старт API."""
    if _connection is None:
        return None
    return asyncio.create_task(consume_courier_events())
