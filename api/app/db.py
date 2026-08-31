from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from .models import Base

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # lightweight dev migration: add columns that create_all won't add to existing tables
        from sqlalchemy import text
        for ddl in ("ALTER TABLE pr_candidate ADD COLUMN evidence_urls JSON",
                    "ALTER TABLE use_case ADD COLUMN definition TEXT DEFAULT ''",
                    "ALTER TABLE use_case ADD COLUMN doc_url TEXT DEFAULT ''"):
            try:
                await conn.execute(text(ddl))
            except Exception:
                pass  # already exists


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
