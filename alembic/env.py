from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _quoted_schema(connection) -> str:
    # Usa el preparador del dialecto para citar el identificador de forma segura.
    return connection.dialect.identifier_preparer.quote(settings.db_schema)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_schemas=True,
        version_table_schema=settings.db_schema,
    )
    with context.begin_transaction():
        # En modo offline dejamos explícito el esquema en el SQL generado.
        schema = settings.db_schema.replace('"', '""')
        context.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        context.execute(f'SET search_path TO "{schema}"')
        context.run_migrations()


def do_run_migrations(connection):
    # PostgreSQL puede tener search_path vacío o personalizado. Primero
    # garantizamos el esquema y fijamos el search_path.
    #
    # IMPORTANTE: SQLAlchemy 2 inicia una transacción implícita (autobegin)
    # en el primer execute(). Si no la cerramos aquí, Alembic puede ejecutar
    # las revisiones dentro de esa transacción externa y al cerrar la conexión
    # terminar haciendo rollback aunque el log muestre "Running upgrade".
    # Por eso confirmamos explícitamente esta preparación ANTES de entregar
    # el control transaccional a Alembic.
    quoted_schema = _quoted_schema(connection)
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema}"))
    connection.execute(text(f"SET search_path TO {quoted_schema}"))
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_schemas=True,
        version_table_schema=settings.db_schema,
    )

    # Desde aquí Alembic controla su propia transacción y la confirma al
    # terminar correctamente. Las migraciones quedan persistidas.
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"server_settings": {"search_path": settings.db_schema}},
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())
