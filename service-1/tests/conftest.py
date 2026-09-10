import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import create_access_token
from app.database import get_db
from app.main import app
from app.models import Base


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def user_headers():
    token = create_access_token(user_id=1, full_name="Ivan Petrov", role="user")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    token = create_access_token(user_id=2, full_name="Admin", role="admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_catalog(monkeypatch):
    from app import services

    items = [
        {"id": 1, "restaurant_id": 1, "name": "Pizza", "price": "550.00", "is_available": True},
        {"id": 2, "restaurant_id": 1, "name": "Sold out", "price": "480.00", "is_available": False},
        {"id": 3, "restaurant_id": 1, "name": "Cola", "price": "150.00", "is_available": True},
    ]

    async def fake_fetch(menu_item_ids):
        return [i for i in items if i["id"] in menu_item_ids]

    monkeypatch.setattr(services, "fetch_menu_items", fake_fetch)
    return items


@pytest.fixture
def broken_catalog(monkeypatch):
    from app import services
    from app.exceptions import CatalogUnavailable

    async def fail(menu_item_ids):
        raise CatalogUnavailable("Catalog service request failed")

    monkeypatch.setattr(services, "fetch_menu_items", fail)


@pytest.fixture(autouse=True)
def no_events(monkeypatch):
    from app import messaging

    async def noop(*args, **kwargs):
        return False

    monkeypatch.setattr(messaging, "publish_order_created", noop)
    monkeypatch.setattr(messaging, "publish_order_status_changed", noop)
