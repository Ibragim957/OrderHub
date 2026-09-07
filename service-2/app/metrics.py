"""Метрики Prometheus.

prometheus-fastapi-instrumentator сам добавляет стандартные HTTP-метрики
(количество запросов, длительность, размеры) и эндпоинт /metrics.
Ниже — кастомные метрики предметной области, их значение в том, что они
отвечают на вопросы бизнеса, а не инфраструктуры.
"""

from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

# 1. Сколько ресторанов завели за всё время работы сервиса.
restaurants_created_total = Counter(
    "catalog_restaurants_created_total",
    "Количество созданных ресторанов",
)

# 2. Сколько позиций меню добавлено, с разбивкой по ресторану.
# Метки позволяют строить графики в разрезе: какой ресторан активнее пополняет меню.
menu_items_created_total = Counter(
    "catalog_menu_items_created_total",
    "Количество добавленных позиций меню",
    ["restaurant_id"],
)

# 3. Попадания и промахи кэша. Отношение hit/miss показывает,
# оправдывает ли себя Redis: при низком hit rate кэш только мешает.
cache_operations_total = Counter(
    "catalog_cache_operations_total",
    "Обращения к кэшу каталога",
    ["operation", "result"],
)

# 4. Курьеры, готовые принять заказ, прямо сейчас.
# Gauge, а не Counter: значение растёт и падает, а не только накапливается.
couriers_available = Gauge(
    "catalog_couriers_available",
    "Курьеры со статусом available",
)


def setup_metrics(app) -> None:
    """Подключает стандартные метрики и открывает /metrics."""
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["system"])
