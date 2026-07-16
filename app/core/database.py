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

# Optimisé pour un VPS 8 Go / 4 vCPU, avec PgBouncer en amont
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_size=150,               # connexions par worker
    max_overflow=150,            # total max ~300 par worker (si 4 workers → 1200)
    pool_timeout=3,
    pool_recycle=600,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db() -> None:
    async with engine.begin() as conn:
        from app.models import user, conversation, message
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized.")

async def close_db() -> None:
    try:
        await engine.dispose()
        logger.info("Database engine disposed.")
    except Exception as e:
        logger.exception("Error disposing database engine: %s", e)
        raise