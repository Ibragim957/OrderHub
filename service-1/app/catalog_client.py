"""HTTP-клиент к service-2 (каталог).

Единственная точка, где Order Service обращается к чужому сервису. Прямого
доступа к его базе нет и быть не должно: у каждого сервиса своя БД, а связь
идёт через API и события.
"""

import os

import httpx

from app.exceptions import CatalogUnavailable

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8002")

# Таймаут обязателен. Без него зависший каталог удерживал бы наши воркеры
# до бесконечности, и через несколько минут лёг бы уже Order Service —
# это называется каскадным отказом.
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


async def fetch_menu_items(menu_item_ids: list[int]) -> list[dict]:
    """Забирает позиции меню по списку id — одним запросом на весь заказ.

    Возвращает список словарей с полями id, restaurant_id, name, price,
    is_available. Порядок и полнота не гарантируются: если позиции нет
    в каталоге, её просто не будет в ответе — проверять это должен вызывающий.

    Бросает CatalogUnavailable, если каталог недоступен или ответил ошибкой.
    """
    if not menu_item_ids:
        return []

    params = [("ids", str(i)) for i in menu_item_ids]
    try:
        async with httpx.AsyncClient(base_url=CATALOG_SERVICE_URL, timeout=_TIMEOUT) as client:
            response = await client.get("/menu-items", params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # httpx.HTTPError покрывает и таймауты, и отказ в соединении, и коды 4xx/5xx;
        # ValueError — невалидный JSON в ответе.
        raise CatalogUnavailable(f"Catalog service request failed: {exc}") from exc
