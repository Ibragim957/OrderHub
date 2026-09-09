"""Метрики Prometheus для Order Service.

Стандартные HTTP-метрики и эндпоинт /metrics добавляет instrumentator.
Ниже — метрики предметной области: они отвечают на вопросы бизнеса,
а не инфраструктуры.
"""

from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

# 1. Созданные заказы с разбивкой по ресторану.
orders_created_total = Counter(
    "orders_created_total",
    "Количество созданных заказов",
    ["restaurant_id"],
)

# 2. Переходы между статусами. По этой метрике видно воронку:
# сколько заказов дошло до доставки, а сколько отменили и на каком шаге.
order_status_transitions_total = Counter(
    "orders_status_transitions_total",
    "Смены статуса заказа",
    ["from_status", "to_status"],
)

# 3. Стоимость заказов. Histogram, а не Counter: интересна не сумма,
# а распределение — какие чеки типичны, есть ли выбросы.
order_value = Histogram(
    "orders_value_rubles",
    "Сумма заказа в рублях",
    buckets=[100, 250, 500, 1000, 2000, 5000],
)

# 4. Обращения к каталогу. result=error растёт, когда service-2 недоступен —
# по этой метрике настраивается алерт на отказ соседнего сервиса.
catalog_requests_total = Counter(
    "orders_catalog_requests_total",
    "Запросы к сервису каталога",
    ["result"],
)

# 5. Заказы, ожидающие назначения курьера, прямо сейчас.
orders_awaiting_courier = Gauge(
    "orders_awaiting_courier",
    "Заказы без назначенного курьера",
)


def setup_metrics(app) -> None:
    """Подключает стандартные метрики и открывает /metrics."""
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["system"])
