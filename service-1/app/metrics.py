from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

orders_created_total = Counter(
    "orders_created_total",
    "Количество созданных заказов",
    ["restaurant_id"],
)

order_status_transitions_total = Counter(
    "orders_status_transitions_total",
    "Смены статуса заказа",
    ["from_status", "to_status"],
)

order_value = Histogram(
    "orders_value_rubles",
    "Сумма заказа в рублях",
    buckets=[100, 250, 500, 1000, 2000, 5000],
)

catalog_requests_total = Counter(
    "orders_catalog_requests_total",
    "Запросы к сервису каталога",
    ["result"],
)

orders_awaiting_courier = Gauge(
    "orders_awaiting_courier",
    "Заказы без назначенного курьера",
)


def setup_metrics(app) -> None:
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["system"])
