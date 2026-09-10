from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

restaurants_created_total = Counter(
    "catalog_restaurants_created_total",
    "Количество созданных ресторанов",
)

menu_items_created_total = Counter(
    "catalog_menu_items_created_total",
    "Количество добавленных позиций меню",
    ["restaurant_id"],
)

cache_operations_total = Counter(
    "catalog_cache_operations_total",
    "Обращения к кэшу каталога",
    ["operation", "result"],
)

couriers_available = Gauge(
    "catalog_couriers_available",
    "Курьеры со статусом available",
)


def setup_metrics(app) -> None:
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["system"])
