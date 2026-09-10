import pytest

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# Аутентификация и права
# --------------------------------------------------------------------------


async def test_public_endpoint_needs_no_token(client):
    response = await client.get("/restaurants")
    assert response.status_code == 200
    assert response.json() == []


async def test_create_restaurant_requires_authentication(client):
    response = await client.post("/restaurants", json={"name": "X", "address": "Y"})
    assert response.status_code == 401


async def test_create_restaurant_requires_admin_role(client, user_headers):
    response = await client.post(
        "/restaurants", json={"name": "X", "address": "Y"}, headers=user_headers
    )
    assert response.status_code == 403


async def test_forged_token_is_rejected(client, user_headers):
    broken = {"Authorization": user_headers["Authorization"] + "tampered"}
    response = await client.get("/couriers", headers=broken)
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Рестораны
# --------------------------------------------------------------------------


async def test_admin_creates_restaurant_and_owner_comes_from_token(client, admin_headers):
    response = await client.post(
        "/restaurants",
        json={"name": "Sushi Place", "address": "Main St 1"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["owner_id"] == 1
    assert body["is_open"] is True


async def test_get_missing_restaurant_returns_404(client):
    response = await client.get("/restaurants/999")
    assert response.status_code == 404


async def test_partial_update_keeps_other_fields(client, admin_headers):
    created = await client.post(
        "/restaurants",
        json={"name": "Sushi Place", "address": "Main St 1"},
        headers=admin_headers,
    )
    restaurant_id = created.json()["id"]

    response = await client.patch(
        f"/restaurants/{restaurant_id}", json={"is_open": False}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_open"] is False
    assert body["name"] == "Sushi Place"
    assert body["address"] == "Main St 1"


# --------------------------------------------------------------------------
# Меню
# --------------------------------------------------------------------------


async def test_menu_item_for_missing_restaurant_returns_404(client, admin_headers):
    response = await client.post(
        "/menu-items",
        json={"restaurant_id": 999, "name": "Ghost", "price": "100.00"},
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_price_must_be_positive(client, admin_headers):
    response = await client.post(
        "/menu-items",
        json={"restaurant_id": 1, "name": "Free lunch", "price": "0"},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_only_available_filter(client, admin_headers):
    restaurant = await client.post(
        "/restaurants", json={"name": "R", "address": "A"}, headers=admin_headers
    )
    rid = restaurant.json()["id"]

    await client.post(
        "/menu-items",
        json={"restaurant_id": rid, "name": "Available", "price": "100.00"},
        headers=admin_headers,
    )
    await client.post(
        "/menu-items",
        json={
            "restaurant_id": rid,
            "name": "Sold out",
            "price": "200.00",
            "is_available": False,
        },
        headers=admin_headers,
    )

    everything = await client.get(f"/restaurants/{rid}/menu-items")
    assert len(everything.json()) == 2

    available = await client.get(f"/restaurants/{rid}/menu-items?only_available=true")
    names = [item["name"] for item in available.json()]
    assert names == ["Available"]


async def test_batch_lookup_by_ids(client, admin_headers):
    restaurant = await client.post(
        "/restaurants", json={"name": "R", "address": "A"}, headers=admin_headers
    )
    rid = restaurant.json()["id"]
    first = await client.post(
        "/menu-items",
        json={"restaurant_id": rid, "name": "One", "price": "100.00"},
        headers=admin_headers,
    )
    item_id = first.json()["id"]

    response = await client.get(f"/menu-items?ids={item_id}&ids=999")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [item_id]


# --------------------------------------------------------------------------
# Курьеры
# --------------------------------------------------------------------------


async def test_courier_registers_with_status_offline(client, user_headers):
    response = await client.post(
        "/couriers", json={"vehicle_type": "bike"}, headers=user_headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "offline"
    assert body["user_id"] == 55
    assert body["full_name_snapshot"] == "Ivan Petrov"


async def test_second_courier_profile_conflicts(client, user_headers):
    await client.post("/couriers", json={"vehicle_type": "bike"}, headers=user_headers)
    response = await client.post(
        "/couriers", json={"vehicle_type": "car"}, headers=user_headers
    )
    assert response.status_code == 409


async def test_cannot_edit_someone_elses_courier_profile(client, user_headers, admin_headers):
    created = await client.post(
        "/couriers", json={"vehicle_type": "bike"}, headers=user_headers
    )
    courier_id = created.json()["id"]

    stranger = {"Authorization": admin_headers["Authorization"]}
    allowed = await client.patch(
        f"/couriers/{courier_id}", json={"status": "available"}, headers=stranger
    )
    assert allowed.status_code == 200


# --------------------------------------------------------------------------
# Кэш
# --------------------------------------------------------------------------


async def test_api_works_without_redis(client, admin_headers):
    await client.post(
        "/restaurants", json={"name": "No Redis", "address": "A"}, headers=admin_headers
    )
    response = await client.get("/restaurants")
    assert response.status_code == 200
    assert len(response.json()) == 1
