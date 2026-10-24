"""Declarative base and naming conventions for SQLAlchemy 2.x models.

Domain tables (channels, videos, metrics, etc.) are intentionally deferred
until Phase 3 after empirical API validation in Phase 2.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

POSTGRES_INDEXES_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all future SQLAlchemy 2.x ORM models in miConte."""

    metadata = MetaData(naming_convention=POSTGRES_INDEXES_NAMING_CONVENTION)
