"""User and OAuth credentials repository."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from miconte.models.user import OAuthConnection, User


class UserRepository:
    """Repository handling User and OAuthConnection persistence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_user(
        self,
        *,
        email: str,
        hashed_password: str,
        full_name: str | None = None,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email.strip().lower(),
            hashed_password=hashed_password,
            full_name=full_name,
            is_active=is_active,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_oauth_connection(
        self,
        *,
        user_id: uuid.UUID,
        external_channel_id: str,
        granted_scopes: str,
        platform: str = "youtube",
        encrypted_access_token: str | None = None,
        encrypted_refresh_token: str | None = None,
        token_expires_at: datetime | None = None,
        is_active: bool = True,
    ) -> OAuthConnection:
        stmt = select(OAuthConnection).where(
            OAuthConnection.user_id == user_id,
            OAuthConnection.platform == platform,
            OAuthConnection.external_channel_id == external_channel_id,
        )
        conn = self.session.execute(stmt).scalar_one_or_none()
        if conn is None:
            conn = OAuthConnection(
                user_id=user_id,
                platform=platform,
                external_channel_id=external_channel_id,
                granted_scopes=granted_scopes,
                encrypted_access_token=encrypted_access_token,
                encrypted_refresh_token=encrypted_refresh_token,
                token_expires_at=token_expires_at,
                is_active=is_active,
            )
            self.session.add(conn)
        else:
            conn.granted_scopes = granted_scopes
            conn.encrypted_access_token = encrypted_access_token
            conn.encrypted_refresh_token = encrypted_refresh_token
            conn.token_expires_at = token_expires_at
            conn.is_active = is_active

        self.session.flush()
        return conn

    def get_oauth_connection(
        self,
        *,
        user_id: uuid.UUID,
        external_channel_id: str,
        platform: str = "youtube",
    ) -> OAuthConnection | None:
        stmt = select(OAuthConnection).where(
            OAuthConnection.user_id == user_id,
            OAuthConnection.platform == platform,
            OAuthConnection.external_channel_id == external_channel_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

