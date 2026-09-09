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
from app.exceptions import InvalidOrderItems, InvalidStatusTransition  # noqa: F401
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
    """Создаёт заказ, посчитав сумму по ценам из каталога.

    ЗАГОТОВКА - реализовать самостоятельно.

    Что должно произойти по шагам:

    1. Собрать список menu_item_id из data.order_items и запросить позиции
       у каталога ОДНИМ вызовом: await fetch_menu_items([...]).
       Именно одним, а не по вызову на позицию: N запросов по сети гораздо
       дороже, чем N запросов к своей базе.

       Если каталог недоступен, fetch_menu_items сам бросит CatalogUnavailable,
       перехватывать не нужно - роут вернёт 503.

    2. Проверить каждую запрошенную позицию. Бросить InvalidOrderItems, если:
       - позиции нет в ответе каталога (её удалили или id выдуман);
       - её restaurant_id не совпадает с data.restaurant_id, иначе можно
         собрать заказ из блюд разных ресторанов и его некому готовить;
       - is_available == False, блюдо снято с продажи.

    3. Посчитать сумму на сервере: сумма по всем позициям цена * количество.
       Цены брать ТОЛЬКО из ответа каталога: клиент цены не присылает,
       иначе заказ можно оформить за рубль.
       Оборачивать в Decimal(str(price)) - float здесь испортит копейки.

    4. Создать Order (status по умолчанию CREATED, courier_id пока None)
       и для каждой позиции OrderItem, зафиксировав снимки:
       product_name_snapshot - название из каталога на этот момент,
       price_at_order - цена на этот момент.
       Позиции складывать в order.items, SQLAlchemy сохранит их каскадом.

    5. Один db.add(order), один await db.commit(), затем db.refresh(order).
       Одна транзакция на весь заказ: либо сохранится заказ со всеми
       позициями, либо не сохранится ничего. Заказ без позиций недопустим.

    6. Вернуть order.

    Под рукой уже есть: fetch_menu_items, InvalidOrderItems, Decimal, Order,
    OrderItem - всё импортировано выше. Ответ каталога - список словарей
    с ключами id, restaurant_id, name, price, is_available.
    """
    raise NotImplementedError("create_order: реализовать по описанию выше")


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
