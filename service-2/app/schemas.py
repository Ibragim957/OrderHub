from datetime import datetime
from decimal import Decimal

from app.models import CourierStatus
from pydantic import BaseModel, ConfigDict, Field

# ------------------Ресторан--------------------------

class RestaurantCreate(BaseModel):
    name: str = Field(..., max_length=150)
    description: str | None = Field(None, max_length=500)
    address: str = Field(..., max_length=255)
    is_open: bool = True


class RestaurantUpdate(BaseModel):
    name: str | None = Field(None, max_length=150)
    description: str | None = Field(None, max_length=500)
    address: str | None = Field(None, max_length=255)
    is_open: bool | None = None


class RestaurantRead(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str | None
    address: str
    is_open: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ------------------Меню--------------------------

class MenuItemCreate(BaseModel):
    restaurant_id: int
    name: str = Field(..., max_length=150)
    description: str | None = Field(None, max_length=500)
    price: Decimal = Field(..., gt=0)
    is_available: bool = True


class MenuItemUpdate(BaseModel):
    name: str | None = Field(None, max_length=150)
    description: str | None = Field(None, max_length=500)
    price: Decimal | None = Field(None, gt=0)
    is_available: bool | None = None


class MenuItemRead(BaseModel):
    id: int
    restaurant_id: int
    name: str
    description: str | None
    price: Decimal
    is_available: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)



# ------------------Курьер--------------------------

class CourierCreate(BaseModel):
    vehicle_type: str = Field(..., max_length=50)


class CourierUpdate(BaseModel):
    full_name_snapshot: str | None = Field(None, max_length=100)
    status: CourierStatus | None = None
    vehicle_type: str | None = Field(None, max_length=50)


class CourierRead(BaseModel):
    id: int
    user_id: int
    full_name_snapshot: str
    status: CourierStatus
    vehicle_type: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


