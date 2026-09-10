import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import cache
from app.auth import create_access_token
from app.database import get_db
from app.main import app
from app.models import Base


@pytest.fixture(autouse=True)
def reset_redis_client():
    cache._client = None
    yield
    cache._client = None


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
def admin_headers():
    token = create_access_token(user_id=1, full_name="Admin", role="admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers():
    token = create_access_token(user_id=55, full_name="Ivan Petrov", role="user")
    return {"Authorization": f"Bearer {token}"}
