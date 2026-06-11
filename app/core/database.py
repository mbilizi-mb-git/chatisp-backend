import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,  # verify connections before using
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create database tables if they don't exist."""
    async with engine.begin() as conn:
        # Import all models here to ensure they are registered with Base
        from app.models import user, conversation, message  # noqa

        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized (if not existed).")


async def close_db() -> None:
    """
    Close the database engine and release all connections.
    Should be called during application shutdown.
    """
    try:
        await engine.dispose()
        logger.info("Database engine disposed successfully")
    except Exception as e:
        logger.exception("Error while disposing database engine: %s", e)
        # Re-raise to ensure the application knows shutdown may be incomplete
        raise