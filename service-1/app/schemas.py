from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import OrderStatus, UserRole

# ------------------Пользователь--------------------------

class UserCreate(BaseModel):
    full_name: str = Field(..., max_length=100)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    email: str | None = Field(None, max_length=255)
    password: str | None = Field(None, min_length=8)
    is_active: bool | None = None


class UserRead(BaseModel):
    id: int
    email: str
    full_name: str
    phone: str | None
    role: UserRole
    created_at: datetime
    is_active: bool
    model_config = ConfigDict(from_attributes=True) 


# ------------------Заказ--------------------------

class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = Field(..., ge=1)


class OrderCreate(BaseModel):
    restaurant_id: int
    order_items: list[OrderItemCreate] = Field(..., min_length=1)


class OrderItemRead(BaseModel):
    id: int
    order_id: int
    menu_item_id: int
    product_name_snapshot: str
    quantity: int = Field(..., ge=1)
    price_at_order: Decimal = Field(..., gt=0)
    model_config = ConfigDict(from_attributes=True)


class OrderRead(BaseModel):
    id: int
    user_id: int
    restaurant_id: int
    courier_id: int | None = None
    status: OrderStatus
    total_price: Decimal = Field(..., gt=0)
    customer_name_snapshot: str = Field(..., max_length=100)
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]
    model_config = ConfigDict(from_attributes=True)

# ------------------Аутентификация--------------------------

class LoginRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
