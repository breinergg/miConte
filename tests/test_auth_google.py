"""Integration tests for the Google OpenID Connect authentication flow.

Uses the real PostgreSQL test database.  Google's token endpoint and ID-token
verification are mocked so no network calls reach Google.

Covered scenarios
-----------------
  LoginTransactionStore
    - register / consume (happy path, single-use, expiry)

  Callback endpoint
    - invalid / expired / already-consumed state → redirect with error
    - Google returns ``error`` query param → redirect with access_denied
    - exchange_code raises GoogleOIDCError → redirect with token_exchange_failed
    - id_token missing from exchange response → redirect with missing_id_token
    - id_token verification fails → redirect with invalid_token
    - new user is created by google_sub
    - existing user found by google_sub (returning login)
    - existing user found by email → google_sub is bound

  Logout
    - deletes session, clears cookie
    - safe when called with no active session

  Production session-cookie authentication
    - valid cookie → resolves user
    - expired session → HTTP 401
    - missing cookie → HTTP 401
    - X-User-Id in production → HTTP 403

  Config production validation
    - missing GOOGLE_LOGIN_CLIENT_ID → ValidationError
    - missing GOOGLE_LOGIN_CLIENT_SECRET → ValidationError
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.orm import Session

from miconte.core.config import Settings, get_settings
from miconte.main import app
from miconte.models.user import User
from miconte.persistence.repositories.session_repo import SessionRepository
from miconte.persistence.session import get_engine
from miconte.security.login import LoginTransactionStore

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session() -> Generator[Session]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def test_user(db_session: Session) -> User:
    user = User(
        email=f"oidc-test-{uuid.uuid4()}@example.com",
        hashed_password="!",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def client() -> Generator[TestClient]:
    yield TestClient(app, raise_server_exceptions=True)


# ─── LoginTransactionStore ────────────────────────────────────────────────────


class TestLoginTransactionStore:
    def test_register_and_consume_happy_path(self) -> None:
        store = LoginTransactionStore()
        verifier = "test_verifier_abc"
        nonce = "test_nonce_xyz"
        state = store.register(code_verifier=verifier, nonce=nonce, ttl_seconds=60)
        assert isinstance(state, str) and len(state) > 20
        recovered_verifier, recovered_nonce = store.consume(state)
        assert recovered_verifier == verifier
        assert recovered_nonce == nonce

    def test_consume_single_use(self) -> None:
        store = LoginTransactionStore()
        state = store.register(code_verifier="v", nonce="n", ttl_seconds=60)
        store.consume(state)
        with pytest.raises(ValueError, match="already been consumed"):
            store.consume(state)

    def test_consume_unknown_state(self) -> None:
        store = LoginTransactionStore()
        with pytest.raises(ValueError, match="not found"):
            store.consume("nonexistent_state")

    def test_expired_state_is_rejected(self) -> None:
        store = LoginTransactionStore()
        state = store.register(code_verifier="v", nonce="n", ttl_seconds=1)
        # Force expiry by backdating the transaction
        with store._lock:
            store._transactions[state].expires_at = time.time() - 1
        with pytest.raises(ValueError, match="expired"):
            store.consume(state)


# ─── Session repository ───────────────────────────────────────────────────────


class TestSessionRepository:
    def test_create_and_resolve_session(self, db_session: Session, test_user: User) -> None:
        db_session.commit()
        repo = SessionRepository(db_session)
        expires = datetime.now(UTC) + timedelta(hours=1)
        token = repo.create_session(user_id=test_user.id, expires_at=expires)
        assert len(token) > 30
        found = repo.get_user_by_token(token)
        assert found is not None
        assert found.id == test_user.id

    def test_expired_session_not_returned(self, db_session: Session, test_user: User) -> None:
        db_session.commit()
        repo = SessionRepository(db_session)
        past = datetime.now(UTC) - timedelta(seconds=1)
        token = repo.create_session(user_id=test_user.id, expires_at=past)
        found = repo.get_user_by_token(token)
        assert found is None

    def test_delete_by_token(self, db_session: Session, test_user: User) -> None:
        db_session.commit()
        repo = SessionRepository(db_session)
        expires = datetime.now(UTC) + timedelta(hours=1)
        token = repo.create_session(user_id=test_user.id, expires_at=expires)
        repo.delete_by_token(token)
        assert repo.get_user_by_token(token) is None

    def test_unknown_token_returns_none(self, db_session: Session) -> None:
        repo = SessionRepository(db_session)
        assert repo.get_user_by_token("totally_unknown_token") is None


# ─── /api/v1/auth/google/login ────────────────────────────────────────────────


class TestLoginEndpoint:
    def test_login_redirects_to_google(self, client: TestClient) -> None:
        with patch("miconte.api.auth.GoogleAuthService") as MockSvc:
            instance = MockSvc.return_value
            instance.build_login_url.return_value = (
                "https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
                "some_state",
            )
            response = client.get("/api/v1/auth/google/login", follow_redirects=False)

        assert response.status_code == 302
        assert "accounts.google.com" in response.headers["location"]

    def test_login_503_when_client_id_missing(self, client: TestClient) -> None:
        settings_no_id = Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="testing",
            google_login_client_id="",
        )
        get_settings.cache_clear()  # type: ignore[attr-defined]
        app.dependency_overrides[get_settings] = lambda: settings_no_id
        try:
            response = client.get("/api/v1/auth/google/login", follow_redirects=False)
            assert response.status_code == 503
        finally:
            app.dependency_overrides.pop(get_settings, None)
            get_settings.cache_clear()  # type: ignore[attr-defined]


# ─── /api/v1/auth/google/callback ─────────────────────────────────────────────


def _settings_with_google(env: str = "testing") -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment=env,
        google_login_client_id="test_client_id",
        google_login_client_secret=SecretStr("test_client_secret"),
        google_login_redirect_uri="http://127.0.0.1:8000/api/v1/auth/google/callback",
        frontend_url="http://127.0.0.1:4200",
    )


def _register_state_in_store() -> tuple[str, str]:
    """Register a fresh state in the default login store. Returns (state, verifier)."""
    import secrets as _secrets

    from miconte.security.login import default_login_store
    from miconte.security.oauth import generate_pkce_pair
    verifier, _ = generate_pkce_pair()
    nonce = _secrets.token_urlsafe(32)
    state = default_login_store.register(code_verifier=verifier, nonce=nonce, ttl_seconds=600)
    return state, verifier


class TestCallbackEndpoint:
    @pytest.fixture(autouse=True)
    def _setup_settings(self) -> Generator[None]:
        settings = _settings_with_google()
        get_settings.cache_clear()  # type: ignore[attr-defined]
        app.dependency_overrides[get_settings] = lambda: settings
        yield
        app.dependency_overrides.pop(get_settings, None)
        get_settings.cache_clear()  # type: ignore[attr-defined]

    def test_invalid_state_redirects_with_error(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "auth_code_xyz", "state": "bogus_state_token"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "invalid_state" in response.headers["location"]

    def test_google_error_param_redirects(self, client: TestClient) -> None:
        state, _ = _register_state_in_store()
        response = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "ignored", "state": state, "error": "access_denied"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "access_denied" in response.headers["location"]

    def test_exchange_failure_redirects(self, client: TestClient) -> None:
        state, _ = _register_state_in_store()
        with patch(
            "miconte.services.google_auth_service.GoogleAuthService.exchange_code",
            new_callable=AsyncMock,
            side_effect=__import__(
                "miconte.services.google_auth_service", fromlist=["GoogleOIDCError"]
            ).GoogleOIDCError("token exchange failed"),
        ):
            response = client.get(
                "/api/v1/auth/google/callback",
                params={"code": "bad_code", "state": state},
                follow_redirects=False,
            )
        assert response.status_code == 302
        assert "token_exchange_failed" in response.headers["location"]

    def test_missing_id_token_redirects(self, client: TestClient) -> None:
        state, _ = _register_state_in_store()
        with patch(
            "miconte.services.google_auth_service.GoogleAuthService.exchange_code",
            new_callable=AsyncMock,
            return_value={"access_token": "tok", "token_type": "Bearer"},  # no id_token
        ):
            response = client.get(
                "/api/v1/auth/google/callback",
                params={"code": "code_xyz", "state": state},
                follow_redirects=False,
            )
        assert response.status_code == 302
        assert "missing_id_token" in response.headers["location"]

    def test_invalid_id_token_redirects(self, client: TestClient) -> None:
        from miconte.services.google_auth_service import GoogleOIDCError

        state, _ = _register_state_in_store()
        with (
            patch(
                "miconte.services.google_auth_service.GoogleAuthService.exchange_code",
                new_callable=AsyncMock,
                return_value={"access_token": "tok", "id_token": "bad.jwt.token"},
            ),
            patch(
                "miconte.services.google_auth_service.GoogleAuthService.verify_id_token",
                new_callable=AsyncMock,
                side_effect=GoogleOIDCError("invalid signature"),
            ),
        ):
            response = client.get(
                "/api/v1/auth/google/callback",
                params={"code": "code_xyz", "state": state},
                follow_redirects=False,
            )
        assert response.status_code == 302
        assert "invalid_token" in response.headers["location"]

    async def test_nonce_mismatch_raises_oidc_error(self) -> None:
        """verify_id_token must raise GoogleOIDCError when nonce does not match."""
        from unittest.mock import MagicMock

        from miconte.services.google_auth_service import GoogleAuthService, GoogleOIDCError

        settings = _settings_with_google()
        svc = GoogleAuthService(session=MagicMock(), settings=settings)

        with (
            patch(
                "miconte.services.google_auth_service.google_requests.Request",
                return_value=MagicMock(),
            ),
            patch(
                "miconte.services.google_auth_service.google_id_token.verify_oauth2_token",
                return_value={"sub": "s", "email": "e@e.com", "nonce": "wrong_nonce"},
            ),
            pytest.raises(GoogleOIDCError, match="nonce mismatch"),
        ):
            await svc.verify_id_token("fake.id.token", expected_nonce="correct_nonce")

    def test_new_user_created_and_session_set(
        self, client: TestClient, db_session: Session
    ) -> None:
        state, _ = _register_state_in_store()
        google_sub = f"google_sub_{uuid.uuid4().hex}"
        email = f"newuser-{uuid.uuid4()}@example.com"

        with (
            patch(
                "miconte.services.google_auth_service.GoogleAuthService.exchange_code",
                new_callable=AsyncMock,
                return_value={"access_token": "at", "id_token": "raw_idt"},
            ),
            patch(
                "miconte.services.google_auth_service.GoogleAuthService.verify_id_token",
                new_callable=AsyncMock,
                return_value={"sub": google_sub, "email": email, "name": "New User"},
            ),
        ):
            response = client.get(
                "/api/v1/auth/google/callback",
                params={"code": "code_ok", "state": state},
                follow_redirects=False,
            )

        assert response.status_code == 302
        assert "auth_error" not in response.headers["location"]

        # Session cookie must be set
        cookie_name = "miconte_session"
        assert cookie_name in response.cookies

        # User must exist in DB
        from sqlalchemy import select

        found = db_session.execute(
            select(User).where(User.google_sub == google_sub)
        ).scalar_one_or_none()
        assert found is not None
        assert found.email == email

    def test_existing_user_by_google_sub_returns_session(
        self, client: TestClient, db_session: Session, test_user: User
    ) -> None:
        test_user.google_sub = f"sub_{uuid.uuid4().hex}"
        db_session.commit()

        state, _ = _register_state_in_store()
        with (
            patch(
                "miconte.services.google_auth_service.GoogleAuthService.exchange_code",
                new_callable=AsyncMock,
                return_value={"access_token": "at", "id_token": "raw"},
            ),
            patch(
                "miconte.services.google_auth_service.GoogleAuthService.verify_id_token",
                new_callable=AsyncMock,
                return_value={
                    "sub": test_user.google_sub,
                    "email": test_user.email,
                    "name": "Existing",
                },
            ),
        ):
            response = client.get(
                "/api/v1/auth/google/callback",
                params={"code": "code_ok", "state": state},
                follow_redirects=False,
            )

        assert response.status_code == 302
        assert "miconte_session" in response.cookies

    def test_existing_user_by_email_binds_google_sub(
        self, client: TestClient, db_session: Session, test_user: User
    ) -> None:
        # test_user has no google_sub yet
        assert test_user.google_sub is None
        db_session.commit()

        new_sub = f"new_sub_{uuid.uuid4().hex}"
        state, _ = _register_state_in_store()
        with (
            patch(
                "miconte.services.google_auth_service.GoogleAuthService.exchange_code",
                new_callable=AsyncMock,
                return_value={"access_token": "at", "id_token": "raw"},
            ),
            patch(
                "miconte.services.google_auth_service.GoogleAuthService.verify_id_token",
                new_callable=AsyncMock,
                return_value={"sub": new_sub, "email": test_user.email, "name": "Bind"},
            ),
        ):
            response = client.get(
                "/api/v1/auth/google/callback",
                params={"code": "code_ok", "state": state},
                follow_redirects=False,
            )

        assert response.status_code == 302
        db_session.expire_all()
        db_session.refresh(test_user)
        assert test_user.google_sub == new_sub


# ─── /api/v1/auth/logout ──────────────────────────────────────────────────────


class TestLogout:
    def test_logout_clears_session(
        self, client: TestClient, db_session: Session, test_user: User
    ) -> None:
        db_session.commit()
        repo = SessionRepository(db_session)
        token = repo.create_session(
            user_id=test_user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.commit()

        response = client.post(
            "/api/v1/auth/logout",
            cookies={"miconte_session": token},
        )
        assert response.status_code == 200
        assert response.json()["detail"] == "Logged out successfully"

        # Verify session is gone
        db_session.expire_all()
        assert repo.get_user_by_token(token) is None

    def test_logout_safe_without_session(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200


# ─── Production session-cookie authentication ─────────────────────────────────


class TestProductionSessionAuth:
    @pytest.fixture(autouse=True)
    def _prod_settings(self) -> Generator[None]:
        _valid_key = secrets.token_hex(32)
        _valid_secret = secrets.token_hex(32)
        prod = Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="production",
            token_encryption_key=_valid_key,
            oauth_state_secret=_valid_secret,
            google_login_client_id="gid",
            google_login_client_secret=SecretStr("gsecret"),
        )
        get_settings.cache_clear()  # type: ignore[attr-defined]
        app.dependency_overrides[get_settings] = lambda: prod
        yield
        app.dependency_overrides.pop(get_settings, None)
        get_settings.cache_clear()  # type: ignore[attr-defined]

    def test_x_user_id_forbidden_in_production(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/auth/me",
            headers={"X-User-Id": str(uuid.uuid4())},
        )
        assert response.status_code == 403

    def test_missing_cookie_returns_401(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_valid_cookie_resolves_user(
        self, client: TestClient, db_session: Session, test_user: User
    ) -> None:
        db_session.commit()
        repo = SessionRepository(db_session)
        token = repo.create_session(
            user_id=test_user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.commit()

        response = client.get(
            "/api/v1/auth/me",
            cookies={"miconte_session": token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_user.id)
        assert data["email"] == test_user.email

    def test_expired_cookie_returns_401(
        self, client: TestClient, db_session: Session, test_user: User
    ) -> None:
        db_session.commit()
        # Create session via repo so the hash is stored correctly
        repo = SessionRepository(db_session)
        past = datetime.now(UTC) - timedelta(seconds=1)
        token = repo.create_session(user_id=test_user.id, expires_at=past)
        db_session.commit()

        response = client.get(
            "/api/v1/auth/me",
            cookies={"miconte_session": token},
        )
        assert response.status_code == 401

    def test_unknown_token_returns_401(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/auth/me",
            cookies={"miconte_session": "completely_unknown_token"},
        )
        assert response.status_code == 401


# ─── Config production validation ─────────────────────────────────────────────


class TestConfigProductionGoogleValidation:
    def test_missing_google_client_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="MICONTE_GOOGLE_LOGIN_CLIENT_ID"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                environment="production",
                token_encryption_key=secrets.token_hex(32),
                oauth_state_secret=secrets.token_hex(32),
                google_login_client_id="",
                google_login_client_secret=SecretStr("some_secret"),
            )

    def test_missing_google_client_secret_rejected(self) -> None:
        with pytest.raises(ValidationError, match="MICONTE_GOOGLE_LOGIN_CLIENT_SECRET"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                environment="production",
                token_encryption_key=secrets.token_hex(32),
                oauth_state_secret=secrets.token_hex(32),
                google_login_client_id="some_id",
                google_login_client_secret=SecretStr(""),
            )

    def test_valid_production_config_accepted(self) -> None:
        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="production",
            token_encryption_key=secrets.token_hex(32),
            oauth_state_secret=secrets.token_hex(32),
            google_login_client_id="valid_id",
            google_login_client_secret=SecretStr("valid_secret"),
        )
        assert s.environment == "production"
