"""HTTP-слой Order Service.

Роуты тонкие: разбирают запрос, зовут services.py, переводят его ответ
в код HTTP. Доменные исключения превращаются в статусы здесь и только здесь.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import services
from app.auth import JWT_EXPIRE_MINUTES, create_access_token
from app.database import get_db
from app.deps import CurrentUser, get_current_user, require_admin
from app.exceptions import CatalogUnavailable, InvalidOrderItems, InvalidStatusTransition
from app.metrics import (
    catalog_requests_total,
    order_status_transitions_total,
    order_value,
    orders_created_total,
)
from app.models import OrderStatus, UserRole
from app.schemas import (
    LoginRequest,
    OrderCreate,
    OrderRead,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)

router = APIRouter()


# ------------------ Пользователи --------------------------


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
)
async def register_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    user = await services.create_user(db, data)
    if user is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    return user


@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Выдаёт JWT в обмен на email и пароль."""
    user = await services.authenticate_user(db, data.email, data.password)
    if user is None:
        # Намеренно не уточняем, что именно не подошло — email или пароль.
        # Иначе по разнице ответов можно перебором выяснить, какие адреса
        # зарегистрированы в системе.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id, user.full_name, user.role.value)
    return TokenResponse(access_token=token, expires_in_minutes=JWT_EXPIRE_MINUTES)


@router.get("/users/me", response_model=UserRead, tags=["users"])
async def read_me(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    user = await services.get_user(db, current_user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.patch("/users/me", response_model=UserRead, tags=["users"])
async def update_me(
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    user = await services.update_user(db, current_user.id, data)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/users/{user_id}", response_model=UserRead, tags=["users"])
async def read_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    user = await services.get_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


# ------------------ Заказы --------------------------


@router.post(
    "/orders",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    tags=["orders"],
)
async def create_order(
    data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        order = await services.create_order(
            db, data, user_id=current_user.id, customer_name=current_user.full_name
        )
    except CatalogUnavailable as exc:
        # 503, а не 500: проблема временная и на нашей стороне всё исправно,
        # клиенту имеет смысл повторить запрос позже.
        catalog_requests_total.labels(result="error").inc()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except InvalidOrderItems as exc:
        # 400: запрос сформирован неверно, повторять его бессмысленно.
        catalog_requests_total.labels(result="ok").inc()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    catalog_requests_total.labels(result="ok").inc()
    orders_created_total.labels(restaurant_id=str(order.restaurant_id)).inc()
    order_value.observe(float(order.total_price))
    return order


@router.get("/orders", response_model=list[OrderRead], tags=["orders"])
async def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Свои заказы; админ видит все."""
    # Фильтр по пользователю решается здесь, а не в сервисе: сервис просто
    # умеет отдавать заказы с фильтром или без, а кто что вправе видеть —
    # это вопрос доступа, то есть HTTP-слоя.
    user_filter = None if current_user.role is UserRole.ADMIN else current_user.id
    return await services.list_orders(db, user_id=user_filter, skip=skip, limit=limit)


@router.get("/orders/{order_id}", response_model=OrderRead, tags=["orders"])
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    order = await services.get_order(db, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    if order.user_id != current_user.id and current_user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your order")

    return order


@router.patch("/orders/{order_id}/status", response_model=OrderRead, tags=["orders"])
async def change_order_status(
    order_id: int,
    new_status: OrderStatus,
    db: AsyncSession = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    """Смена статуса заказа. Доступна администратору (кухня, диспетчер)."""
    order = await services.get_order(db, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    previous_status = order.status
    try:
        order = await services.update_order_status(db, order_id, new_status)
    except InvalidStatusTransition as exc:
        # 409 Conflict: запрос корректен, но противоречит текущему состоянию
        # ресурса — например, попытка отменить уже доставленный заказ.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    order_status_transitions_total.labels(
        from_status=previous_status.value, to_status=new_status.value
    ).inc()
    return order


@router.post("/orders/{order_id}/cancel", response_model=OrderRead, tags=["orders"])
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Отмена заказа самим клиентом — пока он не передан курьеру."""
    order = await services.get_order(db, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    if order.user_id != current_user.id and current_user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your order")

    previous_status = order.status
    try:
        order = await services.update_order_status(db, order_id, OrderStatus.CANCELLED)
    except InvalidStatusTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    order_status_transitions_total.labels(
        from_status=previous_status.value, to_status=OrderStatus.CANCELLED.value
    ).inc()
    return order
