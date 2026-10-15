"""
Database engine and sessions (SQLAlchemy 2, sync; FastAPI runs sync routes in a thread pool).
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.api.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}  # sessions cross FastAPI's threads
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys, and so ON DELETE CASCADE / SET NULL, unless enabled per connection
        event.listen(engine, "connect", lambda dbapi_conn, _: dbapi_conn.execute("PRAGMA foreign_keys=ON"))
    return engine


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    with get_sessionmaker()() as session:
        yield session
