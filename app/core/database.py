from collections.abc import AsyncIterator
from functools import lru_cache
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    # Lazy: importar la aplicación o generar OpenAPI no abre conexiones ni requiere cargar el driver hasta usar BD.
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        # No dependemos del search_path configurado globalmente en PostgreSQL.
        # Alembic crea el esquema si no existe y las conexiones normales lo usan
        # explícitamente desde el primer handshake de asyncpg.
        connect_args={"server_settings": {"search_path": settings.db_schema}},
    )


SessionLocal = async_sessionmaker(expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal(bind=get_engine()) as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
