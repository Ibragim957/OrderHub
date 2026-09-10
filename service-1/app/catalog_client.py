import os

import httpx

from app.exceptions import CatalogUnavailable

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8002")

_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


async def fetch_menu_items(menu_item_ids: list[int]) -> list[dict]:
    if not menu_item_ids:
        return []

    params = [("ids", str(i)) for i in menu_item_ids]
    try:
        async with httpx.AsyncClient(base_url=CATALOG_SERVICE_URL, timeout=_TIMEOUT) as client:
            response = await client.get("/menu-items", params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CatalogUnavailable(f"Catalog service request failed: {exc}") from exc
