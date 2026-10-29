"""FastAPI dependency injection declarations using Annotated."""

import uuid
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from miconte.core.config import Settings, get_settings
from miconte.models.user import User
from miconte.persistence.repositories.session_repo import SessionRepository
from miconte.persistence.repositories.user_repo import UserRepository
from miconte.persistence.session import create_db_session
from miconte.security.crypto import TokenEncryptionService
from miconte.services.oauth_service import OAuthService
from miconte.services.scheduler import SyncScheduler, default_scheduler
from miconte.services.sync_service import SyncService


def get_db_session() -> Generator[Session]:
    """Provide a database session for request scope."""
    yield from create_db_session()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]


def get_crypto_service(settings: SettingsDep) -> TokenEncryptionService:
    """Provide token encryption service using configured master key."""
    return TokenEncryptionService(
        primary_key=settings.token_encryption_key.get_secret_value(),
        primary_key_id=settings.token_encryption_key_id,
    )


CryptoServiceDep = Annotated[TokenEncryptionService, Depends(get_crypto_service)]


def get_oauth_service(
    session: DbSessionDep,
    settings: SettingsDep,
    crypto: CryptoServiceDep,
) -> OAuthService:
    """Provide OAuth coordination service."""
    return OAuthService(
        session=session,
        settings=settings,
        crypto_service=crypto,
    )


OAuthServiceDep = Annotated[OAuthService, Depends(get_oauth_service)]


def get_sync_service(
    session: DbSessionDep,
    settings: SettingsDep,
    oauth_service: OAuthServiceDep,
) -> SyncService:
    """Provide domain data synchronization service."""
    return SyncService(
        session=session,
        settings=settings,
        oauth_service=oauth_service,
    )


SyncServiceDep = Annotated[SyncService, Depends(get_sync_service)]


def get_scheduler(settings: SettingsDep) -> SyncScheduler:
    """Provide synchronization scheduler instance."""
    return default_scheduler


SchedulerDep = Annotated[SyncScheduler, Depends(get_scheduler)]


def get_current_authenticated_user(
    request: Request,
    session: DbSessionDep,
    settings: SettingsDep,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> User:
    """Resolve authenticated user identity from request context.

    Security rules:
    - In production: X-User-Id header is strictly prohibited (HTTP 403).
      Authentication is via HttpOnly session cookie set by the Google OIDC flow.
    - In development/testing: X-User-Id header is permitted for local testing,
      validated against active User records in PostgreSQL. Falls back to the
      first active user when no header is provided.
    """
    if settings.environment not in ("development", "testing"):
        if x_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="X-User-Id header is strictly prohibited in production environments",
            )
        # Production: authenticate via session cookie
        token = request.cookies.get(settings.session_cookie_name)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required: valid session cookie missing",
                headers={"WWW-Authenticate": "Cookie"},
            )
        repo = SessionRepository(session)
        user = repo.get_user_by_token(token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired or invalid — please log in again",
                headers={"WWW-Authenticate": "Cookie"},
            )
        return user

    user_repo = UserRepository(session)
    if x_user_id:
        try:
            uid = uuid.UUID(x_user_id.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed X-User-Id header (valid UUID required)",
            ) from exc

        user = user_repo.get_by_id(uid)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated user identity not found or account is deactivated",
            )
        return user

    stmt = select(User).where(User.is_active.is_(True))
    dev_user = session.execute(stmt).scalars().first()
    if dev_user:
        return dev_user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required: X-User-Id header or active session required",
    )


CurrentUserDep = Annotated[User, Depends(get_current_authenticated_user)]


def get_optional_authenticated_user(
    session: DbSessionDep,
    settings: SettingsDep,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> User | None:
    """Optionally resolve user if header is present in dev/test for callbacks."""
    if settings.environment not in ("development", "testing") or not x_user_id:
        return None
    try:
        uid = uuid.UUID(x_user_id.strip())
        user_repo = UserRepository(session)
        user = user_repo.get_by_id(uid)
        return user if (user and user.is_active) else None
    except ValueError:
        return None


OptionalUserDep = Annotated[User | None, Depends(get_optional_authenticated_user)]
