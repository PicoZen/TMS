from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.common.config import settings


class Base(DeclarativeBase):
    pass


def _get_engine_args(database_url: str) -> dict:
    """Get engine arguments for the async Postgres engine."""
    return {
        "echo": settings.debug,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    }


engine = create_async_engine(
    settings.database_url,
    **_get_engine_args(settings.database_url),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Verify the database is reachable at startup.

    This deliberately does NOT call Base.metadata.create_all(). Schema is
    owned entirely by Alembic migrations (see alembic/versions/) - running
    create_all() here as well means two different code paths can create or
    check the same tables, which is both redundant (it re-ran a has_table()
    reflection query for every table on every single app startup/reload)
    and a real source of the
    'InterfaceError: cannot perform operation: another operation is in
    progress' errors seen under uvicorn --reload: a restart mid-reflection
    could leave a pooled connection in a half-finished state that then gets
    handed back out to a real request.
    Run `alembic upgrade head` before starting the app instead - see SETUP.md.
    """
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    await engine.dispose()