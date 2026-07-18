import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Set test environment BEFORE importing anything
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# SQLite, in-process - no external database service required to run the
# suite. Ticket.search_vector is declared with .with_variant(Text(),
# "sqlite") (see src/common/models.py) so schema creation succeeds here,
# and TicketRepository.search() falls back to a plain ILIKE match on any
# non-Postgres dialect instead of the real tsvector/websearch_to_tsquery
# path - see DECISIONS.md "Ticket search & filtering".
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("LLM_PROVIDER", "mock")  # Use mock LLM for tests
os.environ.setdefault("TESTING", "true")  # Mark as test environment

# Configure Celery for testing BEFORE importing tasks
from src.celery_app import celery_app
celery_app.conf.update(
    task_always_eager=True,
    task_eager_propagates=True,
    broker_url="memory://",
    result_backend="rpc://",
)

from src.auth.dependencies import get_current_active_user
from src.auth.schemas import UserCreate
from src.auth.service import AuthService
from src.common.database import get_db
from src.common.models import Base, User
from src.common.security import hash_password
from src.main import app

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
# ^ Honors an explicitly-exported DATABASE_URL if you want to point the
# suite at something else instead of the default SQLite file above.

# NullPool: every checkout opens a fresh connection and every checkin closes
# it, rather than a connection being reused across test functions. This
# matters because pytest-asyncio 1.x scopes its event loop per
# `asyncio_default_fixture_loop_scope` in pytest.ini (currently "session"),
# and a pooled connection tied to a closed event loop can't be reused - see
# pytest.ini for the full story. Cheap to keep even for SQLite.
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        email="test@example.com",
        password_hash=hash_password("testpassword"),
        role="AGENT",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin@example.com",
        password_hash=hash_password("adminpassword"),
        role="ADMIN",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict:
    from src.common.security import create_token_pair

    token_pair = create_token_pair(str(test_user.id), test_user.email, test_user.role.value)
    return {"Authorization": f"Bearer {token_pair.access_token}"}


@pytest.fixture
def admin_headers(admin_user: User) -> dict:
    from src.common.security import create_token_pair

    token_pair = create_token_pair(str(admin_user.id), admin_user.email, admin_user.role.value)
    return {"Authorization": f"Bearer {token_pair.access_token}"}
