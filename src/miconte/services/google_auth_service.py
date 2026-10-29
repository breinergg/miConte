"""Google OpenID Connect authentication service.

Handles the OIDC login flow entirely separately from the YouTube channel
authorization flow. The two flows share the same Google Cloud project
credentials but use different redirect URIs, different scopes, and
completely separate state and session management.

Security contract:
- Users are identified by Google's stable `sub` claim, not by email.
- The ID token is verified with google-auth (signature + iss + aud + exp).
- No user-supplied claim is trusted before token verification.
- Session tokens are opaque random bytes; they convey no identity on their own.
"""

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from miconte.core.config import Settings
from miconte.models.user import User
from miconte.persistence.repositories.user_repo import UserRepository
from miconte.security.login import LoginTransactionStore, default_login_store
from miconte.security.oauth import generate_pkce_pair

logger = logging.getLogger(__name__)

_GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
_OIDC_SCOPES = "openid email profile"


class GoogleOIDCError(Exception):
    """Raised when the OIDC login flow fails."""


class GoogleAuthService:
    """Orchestrates Google OpenID Connect login, user provisioning, and session issuance."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        login_store: LoginTransactionStore | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.login_store = login_store or default_login_store
        self._http_client = http_client
        self._user_repo = UserRepository(session)

    def build_login_url(self, ttl_seconds: int = 600) -> tuple[str, str]:
        """Generate an authorization URL and register the login transaction.

        Returns (authorization_url, state_token).
        The state_token is stored in the login transaction store and must be
        validated in the callback to prevent CSRF.

        A nonce is included in the authorization request and stored alongside
        the PKCE verifier.  Google includes it in the signed ID token, and the
        callback verifies it to prevent token injection / replay attacks.
        """
        client_id = self.settings.google_login_client_id
        if not client_id:
            raise GoogleOIDCError("MICONTE_GOOGLE_LOGIN_CLIENT_ID is not configured")

        verifier, challenge = generate_pkce_pair()
        nonce = secrets.token_urlsafe(32)
        state = self.login_store.register(
            code_verifier=verifier,
            nonce=nonce,
            ttl_seconds=ttl_seconds,
        )

        import urllib.parse
        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": self.settings.google_login_redirect_uri,
            "response_type": "code",
            "scope": _OIDC_SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
        }
        url = f"{_GOOGLE_AUTH_BASE_URL}?{urllib.parse.urlencode(params)}"
        return url, state

    async def exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        """Exchange an authorization code for tokens. Returns the raw token response dict."""
        client_id = self.settings.google_login_client_id
        client_secret = self.settings.google_login_client_secret.get_secret_value()

        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": self.settings.google_login_redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }

        client = self._http_client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data=payload,
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError as exc:
            raise GoogleOIDCError(f"Network error reaching Google token endpoint: {exc}") from exc
        finally:
            if self._http_client is None:
                await client.aclose()

        if not resp.is_success:
            try:
                body = resp.json()
            except Exception:
                body = {}
            err = body.get("error", "unknown_error")
            raise GoogleOIDCError(f"Google token exchange failed ({resp.status_code}): {err}")

        return resp.json()  # type: ignore[no-any-return]

    async def verify_id_token(
        self,
        raw_id_token: str,
        expected_nonce: str | None = None,
    ) -> dict[str, Any]:
        """Validate the Google ID token and return verified claims.

        google-auth validates: signature, issuer, audience, expiry.
        After structural validation, this method additionally checks the nonce
        claim if expected_nonce is provided, protecting against token injection.

        Runs the synchronous google-auth verification in a thread pool to
        avoid blocking the event loop on the first public-key fetch.
        """
        client_id = self.settings.google_login_client_id

        def _verify() -> dict[str, Any]:
            request = google_requests.Request()
            return google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call, no-any-return]
                raw_id_token,
                request,
                client_id,
            )

        loop = asyncio.get_event_loop()
        try:
            claims: dict[str, Any] = await loop.run_in_executor(None, _verify)
        except ValueError as exc:
            raise GoogleOIDCError(f"ID token validation failed: {exc}") from exc

        if expected_nonce is not None:
            token_nonce = claims.get("nonce")
            if token_nonce != expected_nonce:
                raise GoogleOIDCError(
                    "ID token nonce mismatch — possible token injection or replay attack"
                )

        return claims

    def get_or_create_user(self, sub: str, email: str, full_name: str | None) -> User:
        """Find or create the local User record from verified Google identity claims.

        Resolution order:
        1. Find by google_sub (stable — survives email changes).
        2. Find by email and bind the google_sub (first Google login from existing account).
        3. Create a new User (first-time Google login, new account).

        The hashed_password is set to a disabled sentinel ('!') for Google-only accounts
        to prevent password-based login.
        """
        # 1. Find by stable Google sub
        existing = self._user_repo.get_by_google_sub(sub)
        if existing:
            if not existing.is_active:
                raise GoogleOIDCError("User account is deactivated")
            return existing

        # 2. Find by email and bind google_sub
        by_email = self._user_repo.get_by_email(email)
        if by_email:
            if not by_email.is_active:
                raise GoogleOIDCError("User account is deactivated")
            by_email.google_sub = sub
            self.session.flush()
            return by_email

        # 3. Create new user
        new_user = self._user_repo.create_user(
            email=email,
            hashed_password="!",  # noqa: S106 — disabled sentinel for Google-only accounts
            full_name=full_name,
            google_sub=sub,
        )
        return new_user

    def create_session(self, user_id: object) -> str:
        """Create a new server-side session for the given user. Returns the session token."""
        from miconte.persistence.repositories.session_repo import SessionRepository
        repo = SessionRepository(self.session)
        max_age = self.settings.session_max_age_seconds
        expires_at = datetime.now(UTC) + timedelta(seconds=max_age)
        token = repo.create_session(user_id=user_id, expires_at=expires_at)  # type: ignore[arg-type]
        return token
