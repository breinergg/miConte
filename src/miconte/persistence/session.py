"""SQLAlchemy 2.x engine and session factory for PostgreSQL (miconte_db)."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from miconte.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create and cache the SQLAlchemy 2.x Engine for PostgreSQL."""
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return a cached SQLAlchemy sessionmaker bound to the PostgreSQL engine."""
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


def create_db_session() -> Generator[Session]:
    """Yield a managed SQLAlchemy Session and close it after request completion."""
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session


def check_database_connection(session: Session) -> bool:
    """Execute a lightweight query to verify real PostgreSQL connectivity.

    Never exposes connection strings, credentials, or internal driver errors.
    """
    try:
        result: object = session.execute(text("SELECT 1")).scalar_one()
        return bool(result == 1)
    except SQLAlchemyError:
        return False
