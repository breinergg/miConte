"""FastAPI dependency injection declarations using Annotated."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from miconte.core.config import Settings, get_settings
from miconte.persistence.session import create_db_session


def get_db_session() -> Generator[Session]:
    """Provide a database session for request scope."""
    yield from create_db_session()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]
