"""Repository for server-side user sessions.

Token-storage security model
-----------------------------
PostgreSQL stores a SHA-256 hex digest of the session token, not the raw token.
The raw token (returned to the caller and placed in the cookie) never touches the
database. If the database is compromised, an attacker cannot derive the original
token from its hash because the token has 384 bits of entropy — brute-force is
computationally infeasible.

Lookup and deletion always hash the incoming value before querying.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from miconte.models.session import UserSession
from miconte.models.user import User


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest used as the database key for a session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionRepository:
    """Manages creation, lookup, and deletion of HttpOnly session tokens."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(self, *, user_id: uuid.UUID, expires_at: datetime) -> str:
        """Create a new server-side session.

        Generates a cryptographically random token (384 bits of entropy),
        stores its SHA-256 hash in PostgreSQL, and returns the raw token
        for placement in the HttpOnly cookie.
        """
        token = secrets.token_urlsafe(48)
        record = UserSession(
            user_id=user_id,
            session_token=_hash_token(token),
            expires_at=expires_at,
        )
        self.session.add(record)
        self.session.flush()
        return token

    def get_user_by_token(self, token: str) -> User | None:
        """Resolve a session token to an active, unexpired User or return None."""
        now = datetime.now(UTC)
        stmt = (
            select(UserSession)
            .where(UserSession.session_token == _hash_token(token))
            .where(UserSession.expires_at > now)
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            return None
        user: User = record.user
        if not user or not user.is_active:
            return None
        return user

    def delete_by_token(self, token: str) -> None:
        """Delete a session by token (logout)."""
        stmt = delete(UserSession).where(UserSession.session_token == _hash_token(token))
        self.session.execute(stmt)
        self.session.flush()

    def delete_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke all active sessions for a user (e.g., account security action)."""
        stmt = delete(UserSession).where(UserSession.user_id == user_id)
        self.session.execute(stmt)
        self.session.flush()
