"""
Alembic environment: the database URL comes from the app settings (IDS_DATABASE_URL),
the schema from src/api/db/models.py.

    alembic upgrade head                                # apply migrations
    alembic revision --autogenerate -m "add x"          # after changing the models
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from src.api.db.models import Base
from src.api.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
DATABASE_URL = get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (alembic upgrade head --sql)."""
    context.configure(url=DATABASE_URL, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite can't ALTER most things; batch mode rebuilds tables instead
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
