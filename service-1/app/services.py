"""Слой бизнес-логики Order Service.

Функции не знают про HTTP: принимают сессию БД и данные, возвращают ORM-объекты
или None, а о проблемах сообщают доменными исключениями из exceptions.py.
Перевод в коды ответа — задача routes.py.
"""

from decimal import Decimal  # noqa: F401  -- нужен в create_order

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# fetch_menu_items, InvalidOrderItems и OrderItem пока не используются:
# они подготовлены для create_order, которая ещё не реализована.
from app.catalog_client import fetch_menu_items  # noqa: F401
from app.exceptions import CatalogUnavailable, InvalidOrderItems, InvalidStatusTransition  # noqa: F401
from app.models import Order, OrderItem, OrderStatus, User, UserRole  # noqa: F401
from app.schemas import OrderCreate, UserCreate, UserUpdate
from app.security import hash_password, verify_password

# --------------------------------------------------------------------------
# Пользователи
# --------------------------------------------------------------------------


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, data: UserCreate) -> User | None:
    """Регистрирует пользователя. Возвращает None, если email уже занят."""
    if await get_user_by_email(db, data.email) is not None:
        return None

    user = User(
        email=data.email,
        full_name=data.full_name,
        # Пароль в базу не попадает никогда — только его хеш.
        hashed_password=hash_password(data.password),
        # Роль назначает сервер, а не клиент: иначе любой при регистрации
        # объявил бы себя админом.
        role=UserRole.USER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    """Проверяет пару email/пароль. Понадобится эндпоинту выдачи JWT."""
    user = await get_user_by_email(db, email)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def update_user(db: AsyncSession, user_id: int, data: UserUpdate) -> User | None:
    user = await db.get(User, user_id)
    if user is None:
        return None

    payload = data.model_dump(exclude_unset=True)
    # Пароль приходит в открытом виде и требует отдельной обработки:
    # в модели поле называется иначе и хранит хеш.
    if "password" in payload:
        user.hashed_password = hash_password(payload.pop("password"))

    for field, value in payload.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user


# --------------------------------------------------------------------------
# Заказы
# --------------------------------------------------------------------------

# Допустимые переходы между статусами. Без такой таблицы enum остаётся
# декоративным: в базу можно записать любой статус в любой момент, и заказ
# съедет, например, из delivered обратно в created.
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.COOKING, OrderStatus.CANCELLED},
    OrderStatus.COOKING: {OrderStatus.DELIVERING, OrderStatus.CANCELLED},
    # После передачи курьеру отмена невозможна: еда приготовлена и уже в пути.
    OrderStatus.DELIVERING: {OrderStatus.DELIVERED},
    # Терминальные состояния: выхода из них нет.
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


async def create_order(
    db: AsyncSession, data: OrderCreate, user_id: int, customer_name: str
) -> Order:
    """Создаёт заказ, посчитав сумму по ценам из каталога"""
    list_of_menu_item_ids = [item.menu_item_id for item in data.order_items]
    menu_items = await fetch_menu_items(list_of_menu_item_ids)
    catalog = {item["id"]: item for item in menu_items}
    total = Decimal("0")
    order_items = []

    for requested in data.order_items:
        item = catalog.get(requested.menu_item_id)
        if item is None:
            raise InvalidOrderItems(f"Menu item {requested.menu_item_id} is Invalid")
        if item["restaurant_id"] != data.restaurant_id:
            raise InvalidOrderItems(f"Menu item {requested.menu_item_id} is from another restaurant")
        if item["is_available"] is False:
            raise InvalidOrderItems(f"Menu item {requested.menu_item_id} is not available")
        price = Decimal(str(item["price"]))
        total += price * requested.quantity
        order_items.append(OrderItem(
            menu_item_id=requested.menu_item_id,
            quantity=requested.quantity,
            product_name_snapshot=item["name"],
            price_at_order=Decimal(str(item["price"]))
        ))    

    order = Order(
        user_id=user_id,
        restaurant_id=data.restaurant_id,
        customer_name_snapshot=customer_name,
        total_price=total,
        items=order_items
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    return await get_order(db, order.id)
    


async def get_order(db: AsyncSession, order_id: int) -> Order | None:
    """Возвращает заказ вместе с позициями.

    selectinload обязателен: OrderRead включает вложенный список items, а в
    асинхронном режиме ленивая подгрузка связи вне await-вызова падает
    с MissingGreenlet. Здесь связь загружается сразу, отдельным запросом.
    """
    result = await db.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    return result.scalar_one_or_none()


async def list_orders(
    db: AsyncSession,
    user_id: int | None = None,
    skip: int = 0,
    limit: int = 20,
) -> list[Order]:
    """Список заказов. user_id=None означает "все" - так их видит админ.

    Тот же selectinload, и здесь он решает проблему N+1: без него на список
    из 50 заказов ушёл бы 1 запрос за заказами плюс 50 за позициями.
    С ним - ровно 2 запроса независимо от количества заказов.
    """
    query = select(Order).options(selectinload(Order.items))
    if user_id is not None:
        query = query.where(Order.user_id == user_id)

    result = await db.execute(query.order_by(Order.id.desc()).offset(skip).limit(limit))
    return list(result.scalars().all())


async def update_order_status(
    db: AsyncSession, order_id: int, new_status: OrderStatus
) -> Order | None:
    """Меняет статус заказа с проверкой допустимости перехода.

    Возвращает None, если заказа нет; бросает InvalidStatusTransition,
    если переход запрещён.
    """
    order = await get_order(db, order_id)
    if order is None:
        return None

    if new_status not in ALLOWED_TRANSITIONS[order.status]:
        raise InvalidStatusTransition(
            f"Cannot change status from {order.status.value} to {new_status.value}"
        )

    order.status = new_status
    await db.commit()
    await db.refresh(order)
    return order


async def assign_courier(db: AsyncSession, order_id: int, courier_id: int) -> Order | None:
    """Привязывает курьера к заказу.

    Вызывается не только из роута, но и из обработчика события RabbitMQ,
    когда service-2 сообщает о назначении курьера. Ради таких случаев
    сервисный слой и не знает про HTTP.
    """
    order = await get_order(db, order_id)
    if order is None:
        return None

    order.courier_id = courier_id
    await db.commit()
    await db.refresh(order)
    return order
