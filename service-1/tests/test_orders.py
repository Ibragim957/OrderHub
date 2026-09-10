from decimal import Decimal

import pytest

from app.exceptions import InvalidOrderItems
from app.models import OrderStatus
from app.schemas import OrderCreate
from app.services import ALLOWED_TRANSITIONS, create_order

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# Пользователи и аутентификация
# --------------------------------------------------------------------------


async def test_register_returns_user_without_password(client):
    response = await client.post(
        "/users",
        json={"full_name": "Ivan", "email": "ivan@test.com", "password": "secret12345"},
    )
    assert response.status_code == 201
    body = response.json()
    assert "password" not in body
    assert "hashed_password" not in body
    assert body["role"] == "user"


async def test_duplicate_email_conflicts(client):
    payload = {"full_name": "Ivan", "email": "dup@test.com", "password": "secret12345"}
    await client.post("/users", json=payload)
    response = await client.post("/users", json=payload)
    assert response.status_code == 409


async def test_login_returns_token_and_wrong_password_does_not(client):
    await client.post(
        "/users",
        json={"full_name": "Ivan", "email": "login@test.com", "password": "secret12345"},
    )

    good = await client.post(
        "/auth/login", json={"email": "login@test.com", "password": "secret12345"}
    )
    assert good.status_code == 200
    assert good.json()["token_type"] == "bearer"

    bad = await client.post(
        "/auth/login", json={"email": "login@test.com", "password": "wrongpassword"}
    )
    assert bad.status_code == 401
    assert "email or password" in bad.json()["detail"]


async def test_orders_require_authentication(client):
    response = await client.get("/orders")
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Создание заказа
# --------------------------------------------------------------------------


async def test_total_price_is_computed_from_catalog(client, user_headers, fake_catalog):
    response = await client.post(
        "/orders",
        json={
            "restaurant_id": 1,
            "order_items": [
                {"menu_item_id": 1, "quantity": 2},
                {"menu_item_id": 3, "quantity": 1},
            ],
        },
        headers=user_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert Decimal(body["total_price"]) == Decimal("1250.00")
    assert body["status"] == "created"
    assert body["courier_id"] is None


async def test_order_items_store_snapshots(client, user_headers, fake_catalog):
    response = await client.post(
        "/orders",
        json={"restaurant_id": 1, "order_items": [{"menu_item_id": 1, "quantity": 2}]},
        headers=user_headers,
    )
    item = response.json()["items"][0]
    assert item["product_name_snapshot"] == "Pizza"
    assert Decimal(item["price_at_order"]) == Decimal("550.00")


async def test_unavailable_item_is_rejected(client, user_headers, fake_catalog):
    response = await client.post(
        "/orders",
        json={"restaurant_id": 1, "order_items": [{"menu_item_id": 2, "quantity": 1}]},
        headers=user_headers,
    )
    assert response.status_code == 400
    assert "not available" in response.json()["detail"]


async def test_item_from_another_restaurant_is_rejected(client, user_headers, fake_catalog):
    response = await client.post(
        "/orders",
        json={"restaurant_id": 42, "order_items": [{"menu_item_id": 1, "quantity": 1}]},
        headers=user_headers,
    )
    assert response.status_code == 400
    assert "another restaurant" in response.json()["detail"]


async def test_bad_item_anywhere_in_list_rejects_whole_order(
    client, user_headers, fake_catalog, db_session
):
    response = await client.post(
        "/orders",
        json={
            "restaurant_id": 1,
            "order_items": [
                {"menu_item_id": 1, "quantity": 1},
                {"menu_item_id": 999, "quantity": 1},
            ],
        },
        headers=user_headers,
    )
    assert response.status_code == 400

    listed = await client.get("/orders", headers=user_headers)
    assert listed.json() == []


async def test_catalog_failure_returns_503_not_500(client, user_headers, broken_catalog):
    response = await client.post(
        "/orders",
        json={"restaurant_id": 1, "order_items": [{"menu_item_id": 1, "quantity": 1}]},
        headers=user_headers,
    )
    assert response.status_code == 503


async def test_empty_order_is_rejected_by_schema(client, user_headers, fake_catalog):
    response = await client.post(
        "/orders", json={"restaurant_id": 1, "order_items": []}, headers=user_headers
    )
    assert response.status_code == 422


async def test_client_cannot_dictate_price(client, user_headers, fake_catalog):
    response = await client.post(
        "/orders",
        json={
            "restaurant_id": 1,
            "order_items": [{"menu_item_id": 1, "quantity": 1}],
            "total_price": "1.00",
        },
        headers=user_headers,
    )
    assert response.status_code == 201
    assert Decimal(response.json()["total_price"]) == Decimal("550.00")


# --------------------------------------------------------------------------
# Доступ к заказам
# --------------------------------------------------------------------------


async def test_user_cannot_read_someone_elses_order(
    client, user_headers, admin_headers, fake_catalog
):
    created = await client.post(
        "/orders",
        json={"restaurant_id": 1, "order_items": [{"menu_item_id": 1, "quantity": 1}]},
        headers=user_headers,
    )
    order_id = created.json()["id"]

    stranger = {
        "Authorization": "Bearer "
        + __import__("app.auth", fromlist=["create_access_token"]).create_access_token(
            user_id=777, full_name="Stranger", role="user"
        )
    }
    denied = await client.get(f"/orders/{order_id}", headers=stranger)
    assert denied.status_code == 403

    allowed = await client.get(f"/orders/{order_id}", headers=admin_headers)
    assert allowed.status_code == 200


# --------------------------------------------------------------------------
# Статусы
# --------------------------------------------------------------------------


async def test_delivered_order_cannot_be_cancelled(
    client, user_headers, admin_headers, fake_catalog
):
    created = await client.post(
        "/orders",
        json={"restaurant_id": 1, "order_items": [{"menu_item_id": 1, "quantity": 1}]},
        headers=user_headers,
    )
    order_id = created.json()["id"]

    for status_value in ("confirmed", "cooking", "delivering", "delivered"):
        step = await client.patch(
            f"/orders/{order_id}/status?new_status={status_value}", headers=admin_headers
        )
        assert step.status_code == 200, status_value

    cancelled = await client.post(f"/orders/{order_id}/cancel", headers=user_headers)
    assert cancelled.status_code == 409


async def test_fresh_order_can_be_cancelled(client, user_headers, fake_catalog):
    created = await client.post(
        "/orders",
        json={"restaurant_id": 1, "order_items": [{"menu_item_id": 1, "quantity": 1}]},
        headers=user_headers,
    )
    order_id = created.json()["id"]

    response = await client.post(f"/orders/{order_id}/cancel", headers=user_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_terminal_statuses_have_no_exits():
    assert ALLOWED_TRANSITIONS[OrderStatus.DELIVERED] == set()
    assert ALLOWED_TRANSITIONS[OrderStatus.CANCELLED] == set()


async def test_create_order_raises_domain_error_not_http(db_session, fake_catalog):
    data = OrderCreate(restaurant_id=1, order_items=[{"menu_item_id": 2, "quantity": 1}])
    with pytest.raises(InvalidOrderItems):
        await create_order(db_session, data, user_id=1, customer_name="Ivan")
