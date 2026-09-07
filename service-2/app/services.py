"""Слой бизнес-логики.

Функции этого модуля ничего не знают про HTTP: они принимают сессию БД и данные,
возвращают ORM-объекты, None или bool. Превращать результат в HTTP-ответ
(404, 403, коды статуса) — задача routes.py. Благодаря этому их можно вызывать
не только из роутов, но и из обработчиков событий RabbitMQ или из тестов.
"""

from app.models import Courier, CourierStatus, MenuItem, Restaurant
from app.schemas import (
    CourierCreate,
    CourierUpdate,
    MenuItemCreate,
    MenuItemUpdate,
    RestaurantCreate,
    RestaurantUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ------------------ Рестораны --------------------------


async def create_restaurant(
    db: AsyncSession, data: RestaurantCreate, owner_id: int
) -> Restaurant:
    # owner_id приходит отдельным аргументом, а не в data: его источник — JWT,
    # клиент не может назначить владельцем кого-то другого.
    restaurant = Restaurant(**data.model_dump(), owner_id=owner_id)
    db.add(restaurant)
    await db.commit()
    await db.refresh(restaurant)  # подтягиваем id и created_at, проставленные БД
    return restaurant


async def get_restaurant(db: AsyncSession, restaurant_id: int) -> Restaurant | None:
    return await db.get(Restaurant, restaurant_id)


async def list_restaurants(
    db: AsyncSession, skip: int = 0, limit: int = 20
) -> list[Restaurant]:
    result = await db.execute(
        select(Restaurant).order_by(Restaurant.id).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def update_restaurant(
    db: AsyncSession, restaurant_id: int, data: RestaurantUpdate
) -> Restaurant | None:
    restaurant = await db.get(Restaurant, restaurant_id)
    if restaurant is None:
        return None

    # exclude_unset=True оставляет только поля, реально присланные клиентом.
    # Без него PATCH с одним полем затёр бы остальные значениями None.
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(restaurant, field, value)

    await db.commit()
    await db.refresh(restaurant)
    return restaurant


async def delete_restaurant(db: AsyncSession, restaurant_id: int) -> bool:
    restaurant = await db.get(Restaurant, restaurant_id)
    if restaurant is None:
        return False

    await db.delete(restaurant)
    await db.commit()
    return True


# ------------------ Меню --------------------------


async def create_menu_item(db: AsyncSession, data: MenuItemCreate) -> MenuItem | None:
    # Ресторан лежит в этой же БД, поэтому проверяем существование напрямую.
    # Возвращаем None, если его нет — роут превратит это в 404.
    restaurant = await db.get(Restaurant, data.restaurant_id)
    if restaurant is None:
        return None

    menu_item = MenuItem(**data.model_dump())
    db.add(menu_item)
    await db.commit()
    await db.refresh(menu_item)
    return menu_item


async def get_menu_item(db: AsyncSession, menu_item_id: int) -> MenuItem | None:
    return await db.get(MenuItem, menu_item_id)


async def list_menu_items(
    db: AsyncSession, restaurant_id: int, only_available: bool = False
) -> list[MenuItem]:
    query = select(MenuItem).where(MenuItem.restaurant_id == restaurant_id)
    if only_available:
        query = query.where(MenuItem.is_available.is_(True))

    result = await db.execute(query.order_by(MenuItem.id))
    return list(result.scalars().all())


async def get_menu_items_by_ids(
    db: AsyncSession, menu_item_ids: list[int]
) -> list[MenuItem]:
    """Пакетная выборка по списку id.

    Нужна service-1: при создании заказа он одним запросом получает цены всех
    позиций сразу, вместо отдельного запроса на каждую (это и есть защита от N+1).
    """
    if not menu_item_ids:
        return []

    result = await db.execute(select(MenuItem).where(MenuItem.id.in_(menu_item_ids)))
    return list(result.scalars().all())


async def update_menu_item(
    db: AsyncSession, menu_item_id: int, data: MenuItemUpdate
) -> MenuItem | None:
    menu_item = await db.get(MenuItem, menu_item_id)
    if menu_item is None:
        return None

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(menu_item, field, value)

    await db.commit()
    await db.refresh(menu_item)
    return menu_item


async def delete_menu_item(db: AsyncSession, menu_item_id: int) -> bool:
    menu_item = await db.get(MenuItem, menu_item_id)
    if menu_item is None:
        return False

    await db.delete(menu_item)
    await db.commit()
    return True


# ------------------ Курьеры --------------------------


async def create_courier(
    db: AsyncSession, data: CourierCreate, user_id: int, full_name: str
) -> Courier | None:
    # user_id и имя берутся из JWT, а не из тела запроса.
    # full_name сохраняется снимком: имя в service-1 может измениться позже.
    existing = await get_courier_by_user_id(db, user_id)
    if existing is not None:
        return None  # один пользователь — один профиль курьера

    courier = Courier(
        **data.model_dump(),
        user_id=user_id,
        full_name_snapshot=full_name,
        status=CourierStatus.OFFLINE,  # на смену курьер выходит явным действием
    )
    db.add(courier)
    await db.commit()
    await db.refresh(courier)
    return courier


async def get_courier(db: AsyncSession, courier_id: int) -> Courier | None:
    return await db.get(Courier, courier_id)


async def get_courier_by_user_id(db: AsyncSession, user_id: int) -> Courier | None:
    result = await db.execute(select(Courier).where(Courier.user_id == user_id))
    return result.scalar_one_or_none()


async def list_couriers(
    db: AsyncSession, status: CourierStatus | None = None
) -> list[Courier]:
    query = select(Courier)
    if status is not None:
        query = query.where(Courier.status == status)

    result = await db.execute(query.order_by(Courier.id))
    return list(result.scalars().all())


async def update_courier(
    db: AsyncSession, courier_id: int, data: CourierUpdate
) -> Courier | None:
    courier = await db.get(Courier, courier_id)
    if courier is None:
        return None

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(courier, field, value)

    await db.commit()
    await db.refresh(courier)
    return courier
