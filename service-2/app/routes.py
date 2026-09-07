"""HTTP-слой: маршруты, коды ответов, проверка прав.

Роуты намеренно тонкие — вся работа делегируется в services.py. Здесь решается
только то, что относится к вебу: какой URL, какой код вернуть, кто имеет доступ.
"""

from app import services
from app.database import get_db
from app.deps import CurrentUser, UserRole, get_current_user, require_admin
from app.metrics import (
    couriers_available,
    menu_items_created_total,
    restaurants_created_total,
)
from app.models import CourierStatus
from app.schemas import (
    CourierCreate,
    CourierRead,
    CourierUpdate,
    MenuItemCreate,
    MenuItemRead,
    MenuItemUpdate,
    RestaurantCreate,
    RestaurantRead,
    RestaurantUpdate,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ------------------ Рестораны --------------------------


@router.get("/restaurants", response_model=list[RestaurantRead], tags=["restaurants"])
async def list_restaurants(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Публичный список ресторанов — именно его будем кэшировать в Redis."""
    return await services.list_restaurants(db, skip=skip, limit=limit)


@router.get("/restaurants/{restaurant_id}", response_model=RestaurantRead, tags=["restaurants"])
async def get_restaurant(restaurant_id: int, db: AsyncSession = Depends(get_db)):
    restaurant = await services.get_restaurant(db, restaurant_id)
    if restaurant is None:
        # Сервис вернул None; решение отдать 404 принимается здесь, в HTTP-слое.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
    return restaurant


@router.post(
    "/restaurants",
    response_model=RestaurantRead,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurants"],
)
async def create_restaurant(
    data: RestaurantCreate,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    restaurant = await services.create_restaurant(db, data, owner_id=admin.id)
    restaurants_created_total.inc()
    return restaurant


@router.patch("/restaurants/{restaurant_id}", response_model=RestaurantRead, tags=["restaurants"])
async def update_restaurant(
    restaurant_id: int,
    data: RestaurantUpdate,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    restaurant = await services.update_restaurant(db, restaurant_id, data)
    if restaurant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
    return restaurant


@router.delete(
    "/restaurants/{restaurant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["restaurants"],
)
async def delete_restaurant(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    if not await services.delete_restaurant(db, restaurant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")


# ------------------ Меню --------------------------


@router.get(
    "/restaurants/{restaurant_id}/menu-items",
    response_model=list[MenuItemRead],
    tags=["menu"],
)
async def list_menu_items(
    restaurant_id: int,
    only_available: bool = False,
    db: AsyncSession = Depends(get_db),
):
    if await services.get_restaurant(db, restaurant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
    return await services.list_menu_items(db, restaurant_id, only_available=only_available)


@router.get("/menu-items", response_model=list[MenuItemRead], tags=["menu"])
async def get_menu_items_by_ids(
    ids: list[int] = Query(..., description="Идентификаторы позиций меню"),
    db: AsyncSession = Depends(get_db),
):
    """Пакетная выборка для service-1: цены всех позиций заказа одним запросом."""
    return await services.get_menu_items_by_ids(db, ids)


@router.get("/menu-items/{menu_item_id}", response_model=MenuItemRead, tags=["menu"])
async def get_menu_item(menu_item_id: int, db: AsyncSession = Depends(get_db)):
    menu_item = await services.get_menu_item(db, menu_item_id)
    if menu_item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    return menu_item


@router.post(
    "/menu-items",
    response_model=MenuItemRead,
    status_code=status.HTTP_201_CREATED,
    tags=["menu"],
)
async def create_menu_item(
    data: MenuItemCreate,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    menu_item = await services.create_menu_item(db, data)
    if menu_item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Restaurant not found")
    menu_items_created_total.labels(restaurant_id=str(data.restaurant_id)).inc()
    return menu_item


@router.patch("/menu-items/{menu_item_id}", response_model=MenuItemRead, tags=["menu"])
async def update_menu_item(
    menu_item_id: int,
    data: MenuItemUpdate,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    menu_item = await services.update_menu_item(db, menu_item_id, data)
    if menu_item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    return menu_item


@router.delete(
    "/menu-items/{menu_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["menu"],
)
async def delete_menu_item(
    menu_item_id: int,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    if not await services.delete_menu_item(db, menu_item_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")


# ------------------ Курьеры --------------------------


@router.post(
    "/couriers",
    response_model=CourierRead,
    status_code=status.HTTP_201_CREATED,
    tags=["couriers"],
)
async def create_courier(
    data: CourierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    courier = await services.create_courier(
        db, data, user_id=current_user.id, full_name=current_user.full_name
    )
    if courier is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Courier profile already exists")
    return courier


@router.get("/couriers", response_model=list[CourierRead], tags=["couriers"])
async def list_couriers(
    status_filter: CourierStatus | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    return await services.list_couriers(db, status=status_filter)


@router.get("/couriers/{courier_id}", response_model=CourierRead, tags=["couriers"])
async def get_courier(
    courier_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    courier = await services.get_courier(db, courier_id)
    if courier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Courier not found")
    return courier


@router.patch("/couriers/{courier_id}", response_model=CourierRead, tags=["couriers"])
async def update_courier(
    courier_id: int,
    data: CourierUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    courier = await services.get_courier(db, courier_id)
    if courier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Courier not found")

    # Свой профиль курьер меняет сам; чужой — только админ.
    # Роли всего две, принадлежность ресурса проверяется отдельно от роли.
    if courier.user_id != current_user.id and current_user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your courier profile")

    updated = await services.update_courier(db, courier_id, data)

    # Пересчитываем метрику по факту, а не инкрементом: статус может меняться
    # в обе стороны, и счётчик рассинхронизировался бы с реальностью.
    available = await services.list_couriers(db, status=CourierStatus.AVAILABLE)
    couriers_available.set(len(available))

    return updated
