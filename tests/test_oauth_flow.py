"""Unit and integration tests for OAuth 2.0 Web Server flow and OAuthService."""

import asyncio
import base64
import hashlib
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

from miconte.core.config import Settings, get_settings
from miconte.integrations.youtube.exceptions import (
    InsufficientPermissionsError,
    OAuthError,
)
from miconte.main import app
from miconte.persistence.repositories.user_repo import UserRepository
from miconte.persistence.session import get_engine
from miconte.security.crypto import TokenEncryptionService, build_token_aad
from miconte.security.exceptions import SecurityAuthorizationError
from miconte.security.oauth import (
    REQUIRED_SCOPES,
    OAuthTransactionStore,
    check_scopes_sufficient,
    create_state_token,
    generate_authorization_url,
    generate_pkce_pair,
    verify_state_token,
)
from miconte.services.oauth_service import OAuthService


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        youtube_client_id="test_client_id_123.apps.googleusercontent.com",
        youtube_client_secret=SecretStr("test_client_secret_xyz"),
        youtube_redirect_uri="http://127.0.0.1:8000/api/v1/oauth/youtube/callback",
    )


@pytest.fixture
def crypto_svc(test_settings: Settings) -> TokenEncryptionService:
    return TokenEncryptionService(
        primary_key=test_settings.token_encryption_key.get_secret_value(),
        primary_key_id=test_settings.token_encryption_key_id,
    )


@pytest.fixture
def db_session() -> Generator[Session]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
        session.rollback()


def test_state_token_roundtrip_and_tamper_detection(test_settings: Settings) -> None:
    secret = test_settings.oauth_state_secret.get_secret_value()
    user_id = uuid.uuid4()

    state, nonce = create_state_token(user_id=user_id, secret=secret, ttl_seconds=300)
    assert "." in state
    assert len(nonce) == 32

    # Valid token extracts matching user_id and nonce
    extracted_id, extracted_nonce, sid = verify_state_token(state=state, secret=secret)
    assert extracted_id == user_id
    assert extracted_nonce == nonce
    assert sid is None

    # Tampered signature fails
    payload_part, sig_part = state.split(".", 1)
    tampered_sig = ("a" if sig_part[0] != "a" else "b") + sig_part[1:]
    with pytest.raises(OAuthError, match="signature verification failed"):
        verify_state_token(state=f"{payload_part}.{tampered_sig}", secret=secret)

    # Expired token fails
    expired_state, _ = create_state_token(user_id=user_id, secret=secret, ttl_seconds=-10)
    with pytest.raises(OAuthError, match="expired"):
        verify_state_token(state=expired_state, secret=secret)

    # Malformed state
    with pytest.raises(OAuthError, match="Malformed"):
        verify_state_token(state="invalid_state_without_dot", secret=secret)


def test_pkce_generation_and_challenge_derivation() -> None:
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    # Check challenge matches base64url(sha256(verifier))
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert challenge == expected


def test_oauth_transaction_store_single_use_and_replay_protection() -> None:
    store = OAuthTransactionStore()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    state_nonce = uuid.uuid4().hex
    verifier = "mock_verifier_123"

    store.register(state_nonce=state_nonce, user_id=user_a, code_verifier=verifier, ttl_seconds=300)

    # First consumption succeeds
    consumed_verifier = store.consume(state_nonce=state_nonce, expected_user_id=user_a)
    assert consumed_verifier == verifier

    # Second consumption with same state nonce fails (Replay Attack Rejection)
    with pytest.raises(OAuthError, match="already been consumed"):
        store.consume(state_nonce=state_nonce, expected_user_id=user_a)

    # Different user fails
    nonce_2 = uuid.uuid4().hex
    store.register(state_nonce=nonce_2, user_id=user_a, code_verifier="ver_2", ttl_seconds=300)
    with pytest.raises(OAuthError, match="does not match"):
        store.consume(state_nonce=nonce_2, expected_user_id=user_b)

    # Expired transaction fails
    nonce_exp = uuid.uuid4().hex
    store.register(state_nonce=nonce_exp, user_id=user_a, code_verifier="ver_exp", ttl_seconds=-5)
    with pytest.raises(OAuthError, match="expired|purged"):
        store.consume(state_nonce=nonce_exp, expected_user_id=user_a)


def test_oauth_transaction_store_concurrent_consumption_thread_safety() -> None:
    """Verify that under concurrent requests, exactly one consumer succeeds and all others fail."""
    import concurrent.futures

    store = OAuthTransactionStore()
    user_id = uuid.uuid4()
    state_nonce = uuid.uuid4().hex
    verifier = "secret_verifier_pkce_999"

    store.register(
        state_nonce=state_nonce,
        user_id=user_id,
        code_verifier=verifier,
        ttl_seconds=300,
    )

    successes: list[str] = []
    failures: list[Exception] = []

    def _attempt_consume() -> None:
        try:
            v = store.consume(state_nonce=state_nonce, expected_user_id=user_id)
            successes.append(v)
        except Exception as exc:
            failures.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_attempt_consume) for _ in range(20)]
        concurrent.futures.wait(futures)

    # Exactly 1 thread must succeed; all other 19 threads must be rejected
    assert len(successes) == 1
    assert successes[0] == verifier
    assert len(failures) == 19
    for f in failures:
        assert isinstance(f, OAuthError)
        assert "already been consumed" in str(f)


def test_authorization_url_generation(test_settings: Settings) -> None:
    state = "dummy_state_token"
    verifier, challenge = generate_pkce_pair()
    url = generate_authorization_url(
        client_id=test_settings.youtube_client_id,
        redirect_uri=test_settings.youtube_redirect_uri,
        state=state,
        code_challenge=challenge,
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test_client_id_123" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=dummy_state_token" in url
    assert f"code_challenge={challenge}" in url
    assert "code_challenge_method=S256" in url
    assert "youtube.readonly" in url
    assert "yt-analytics.readonly" in url


def test_check_scopes_sufficient() -> None:
    full_scopes = (
        "https://www.googleapis.com/auth/youtube.readonly "
        "https://www.googleapis.com/auth/yt-analytics.readonly"
    )
    assert check_scopes_sufficient(full_scopes) is True

    # Missing yt-analytics.readonly
    only_yt = "https://www.googleapis.com/auth/youtube.readonly"
    assert check_scopes_sufficient(only_yt) is False

    # Extra scopes also valid if required are present
    extra = f"{full_scopes} https://www.googleapis.com/auth/userinfo.profile"
    assert check_scopes_sufficient(extra) is True


@pytest.mark.integration
def test_oauth_service_initiate_authorization(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=f"oauth_init_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw_xyz",
    )
    db_session.commit()

    service = OAuthService(session=db_session, settings=test_settings, crypto_service=crypto_svc)
    auth_url, state = service.initiate_authorization(user_id=user.id)

    assert "https://accounts.google.com" in auth_url
    assert "code_challenge=" in auth_url
    assert state is not None

    # Verify state extracts this user
    verified_user_id, state_nonce, _ = verify_state_token(
        state=state, secret=test_settings.oauth_state_secret.get_secret_value()
    )
    assert verified_user_id == user.id
    assert state_nonce is not None

    # Nonexistent user raises SecurityAuthorizationError
    with pytest.raises(SecurityAuthorizationError, match="not found"):
        service.initiate_authorization(user_id=uuid.uuid4())


@pytest.mark.integration
def test_oauth_service_callback_single_use_replay_prevention(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    async def _run() -> None:
        user_repo = UserRepository(db_session)
        user = user_repo.create_user(
            email=f"replay_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pw",
        )
        db_session.commit()

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "oauth2.googleapis.com/token" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "ya29.access_1",
                        "expires_in": 3600,
                        "refresh_token": "1//refresh_1",
                        "scope": " ".join(REQUIRED_SCOPES),
                    },
                )
            if "youtube/v3/channels" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": "UC_REPLAY_TEST",
                                "snippet": {"title": "Replay Channel"},
                                "contentDetails": {"relatedPlaylists": {"uploads": "UU_REPLAY"}},
                                "statistics": {"viewCount": "100"},
                            }
                        ]
                    },
                )
            return httpx.Response(404)

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        local_store = OAuthTransactionStore()
        service = OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_http,
            transaction_store=local_store,
        )

        _, state = service.initiate_authorization(user_id=user.id)

        # 1. First callback invocation succeeds
        channel_dto = await service.handle_callback(
            code="code_once", state=state, current_user_id=user.id
        )
        assert channel_dto.youtube_channel_id == "UC_REPLAY_TEST"

        # 2. Second callback with identical state fails BEFORE code exchange
        with pytest.raises(OAuthError, match="already been consumed"):
            await service.handle_callback(code="code_once", state=state, current_user_id=user.id)

    asyncio.run(_run())


@pytest.mark.integration
def test_oauth_service_callback_persistence_and_refresh_token_preservation(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    async def _run() -> None:
        user_repo = UserRepository(db_session)
        user = user_repo.create_user(
            email=f"oauth_flow_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="hashed_pw_abc",
        )
        db_session.commit()

        revocation_requests: list[str] = []

        # Mock Google Token endpoint, YouTube Data API & Revocation
        def mock_google_transport(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            # Token exchange
            if "oauth2.googleapis.com/token" in url_str:
                token_payload = {
                    "access_token": "ya29.initial_mock_access_token_123",
                    "expires_in": 3600,
                    "refresh_token": "1//initial_mock_refresh_token_xyz",
                    "scope": " ".join(REQUIRED_SCOPES),
                    "token_type": "Bearer",
                }
                return httpx.Response(200, json=token_payload)

            # Data API channels.list(mine=true)
            if "youtube/v3/channels" in url_str:
                channel_payload = {
                    "items": [
                        {
                            "id": "UC_MOCK_PROD_001",
                            "snippet": {
                                "title": "Production Test Channel",
                                "description": "Verified channel description",
                                "customUrl": "@prodtest",
                                "publishedAt": "2021-06-01T10:00:00Z",
                            },
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "UU_MOCK_PROD_001"}
                            },
                            "statistics": {
                                "viewCount": "89000",
                                "subscriberCount": "1200",
                                "hiddenSubscriberCount": False,
                                "videoCount": "15",
                            },
                        }
                    ]
                }
                return httpx.Response(200, json=channel_payload)

            # Revocation endpoint: must be POST with body
            if "oauth2.googleapis.com/revoke" in url_str:
                body = request.read().decode("utf-8")
                revocation_requests.append(body)
                return httpx.Response(200)

            return httpx.Response(404)

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_google_transport))
        local_store = OAuthTransactionStore()
        service = OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_http,
            transaction_store=local_store,
        )

        _, state = service.initiate_authorization(user_id=user.id)

        # 1. Execute initial callback
        channel_dto = await service.handle_callback(
            code="auth_code_001", state=state, current_user_id=user.id
        )
        assert channel_dto.youtube_channel_id == "UC_MOCK_PROD_001"
        assert channel_dto.title == "Production Test Channel"

        # Check persistence in DB: Tokens must be stored encrypted (never plain)
        conn = user_repo.get_oauth_connection(
            user_id=user.id, external_channel_id="UC_MOCK_PROD_001"
        )
        assert conn is not None
        assert conn.is_active is True
        assert conn.encrypted_access_token is not None
        assert conn.encrypted_refresh_token is not None
        assert conn.encrypted_access_token.startswith("v1:k1:")
        assert conn.encrypted_refresh_token.startswith("v1:k1:")
        assert "ya29.initial" not in conn.encrypted_access_token
        assert "initial_mock" not in conn.encrypted_refresh_token

        initial_encrypted_refresh = conn.encrypted_refresh_token

        # 2. Test get_valid_access_token when token is still fresh
        access_tok = await service.get_valid_access_token(
            user_id=user.id, external_channel_id="UC_MOCK_PROD_001"
        )
        assert access_tok == "ya29.initial_mock_access_token_123"

        # 3. Simulate re-authorization where Google DOES NOT return a refresh_token
        def mock_reauth_transport(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "oauth2.googleapis.com/token" in url_str:
                token_payload = {
                    "access_token": "ya29.second_mock_access_token_456",
                    "expires_in": 3600,
                    "scope": " ".join(REQUIRED_SCOPES),
                    "token_type": "Bearer",
                }
                return httpx.Response(200, json=token_payload)

            if "youtube/v3/channels" in url_str:
                return mock_google_transport(request)

            return httpx.Response(404)

        mock_http_reauth = httpx.AsyncClient(
            transport=httpx.MockTransport(mock_reauth_transport)
        )
        service_reauth = OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_http_reauth,
            transaction_store=local_store,
        )

        _, state2 = service_reauth.initiate_authorization(user_id=user.id)
        await service_reauth.handle_callback(
            code="auth_code_002", state=state2, current_user_id=user.id
        )

        # Refresh token must be preserved, NOT overwritten with None!
        db_session.expire_all()
        conn_after = user_repo.get_oauth_connection(
            user_id=user.id, external_channel_id="UC_MOCK_PROD_001"
        )
        assert conn_after is not None
        assert conn_after.encrypted_refresh_token == initial_encrypted_refresh

        # Access token was updated
        valid_tok2 = await service_reauth.get_valid_access_token(
            user_id=user.id, external_channel_id="UC_MOCK_PROD_001"
        )
        assert valid_tok2 == "ya29.second_mock_access_token_456"

        # 4. Test Token Refresh when token is expired
        conn_after.token_expires_at = datetime.now(UTC) - timedelta(minutes=10)
        db_session.commit()

        def mock_refresh_transport(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "oauth2.googleapis.com/token" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "ya29.refreshed_access_token_789",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                )
            return httpx.Response(404)

        mock_http_refresh = httpx.AsyncClient(
            transport=httpx.MockTransport(mock_refresh_transport)
        )
        service_refresh = OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_http_refresh,
            transaction_store=local_store,
        )

        refreshed_tok = await service_refresh.get_valid_access_token(
            user_id=user.id, external_channel_id="UC_MOCK_PROD_001"
        )
        assert refreshed_tok == "ya29.refreshed_access_token_789"

        # 5. Test Disconnect and Remote Revocation
        res = await service.disconnect(
            user_id=user.id, external_channel_id="UC_MOCK_PROD_001"
        )
        assert res.local_disconnected is True
        assert res.remote_revoked is True
        assert "successfully revoked" in res.details

        # Verify Google received revocation request for the refresh token
        assert len(revocation_requests) == 1
        assert (
            "token=1%2F%2Finitial_mock_refresh_token_xyz" in revocation_requests[0]
            or "initial_mock_refresh" in revocation_requests[0]
        )

        # Verify complete local purge of ciphertexts
        db_session.expire_all()
        conn_disc = user_repo.get_oauth_connection(
            user_id=user.id, external_channel_id="UC_MOCK_PROD_001"
        )
        assert conn_disc is not None
        assert conn_disc.is_active is False
        assert conn_disc.encrypted_access_token is None
        assert conn_disc.encrypted_refresh_token is None
        assert conn_disc.token_expires_at is None

    asyncio.run(_run())


@pytest.mark.integration
def test_oauth_service_insufficient_scopes_rejection(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    async def _run() -> None:
        user_repo = UserRepository(db_session)
        user = user_repo.create_user(
            email=f"insuf_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pw",
        )
        db_session.commit()

        def mock_insufficient(request: httpx.Request) -> httpx.Response:
            if "oauth2.googleapis.com/token" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "access_token": "ya29.insufficient",
                        "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/youtube.readonly",
                    },
                )
            return httpx.Response(404)

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_insufficient))
        service = OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_http,
        )

        _, state = service.initiate_authorization(user_id=user.id)

        with pytest.raises(InsufficientPermissionsError, match="are insufficient"):
            await service.handle_callback(
                code="code_bad_scope", state=state, current_user_id=user.id
            )

    asyncio.run(_run())


@pytest.mark.integration
def test_oauth_api_endpoints_multitenancy_isolation_idor(
    db_session: Session, test_settings: Settings
) -> None:
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        user_repo = UserRepository(db_session)
        user_a = user_repo.create_user(
            email=f"user_a_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pw_a",
        )
        user_b = user_repo.create_user(
            email=f"user_b_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pw_b",
        )
        db_session.commit()

        client = TestClient(app)

        # 1. GET /api/v1/oauth/youtube/authorize bound to User A via X-User-Id header
        resp_a = client.get(
            "/api/v1/oauth/youtube/authorize",
            headers={"X-User-Id": str(user_a.id)},
        )
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert "authorization_url" in data_a
        assert "code_challenge=" in data_a["authorization_url"]

        # 2. Simulate User A having an active connection in DB
        user_repo.upsert_oauth_connection(
            user_id=user_a.id,
            external_channel_id="UC_PRIVATE_CHANNEL_A",
            granted_scopes=" ".join(REQUIRED_SCOPES),
            is_active=True,
        )
        db_session.commit()

        # 3. IDOR Check: User B queries /status for User A's channel
        # Must return is_connected=False because User B does NOT own that connection!
        resp_b_stat = client.get(
            "/api/v1/oauth/youtube/status?channel_id=UC_PRIVATE_CHANNEL_A",
            headers={"X-User-Id": str(user_b.id)},
        )
        assert resp_b_stat.status_code == 200
        assert resp_b_stat.json()["is_connected"] is False

        # User A queries their own channel -> is_connected=True
        resp_a_stat = client.get(
            "/api/v1/oauth/youtube/status?channel_id=UC_PRIVATE_CHANNEL_A",
            headers={"X-User-Id": str(user_a.id)},
        )
        assert resp_a_stat.status_code == 200
        assert resp_a_stat.json()["is_connected"] is True
        assert "access_token" not in resp_a_stat.json()

        # 4. IDOR Check: User B attempts to disconnect User A's channel
        disc_b = client.post(
            "/api/v1/oauth/youtube/disconnect",
            json={"channel_id": "UC_PRIVATE_CHANNEL_A"},
            headers={"X-User-Id": str(user_b.id)},
        )
        assert disc_b.status_code == 200
        # For User B, no connection existed -> remote_revoked is False
        assert disc_b.json()["local_disconnected"] is True
        assert disc_b.json()["remote_revoked"] is False

        # User A's connection must remain active and unaffected!
        conn_a = user_repo.get_oauth_connection(
            user_id=user_a.id, external_channel_id="UC_PRIVATE_CHANNEL_A"
        )
        assert conn_a is not None
        assert conn_a.is_active is True

        # 5. Invalid / Nonexistent user in header returns 401
        fake_uid = uuid.uuid4()
        bad_auth = client.get(
            "/api/v1/oauth/youtube/authorize",
            headers={"X-User-Id": str(fake_uid)},
        )
        assert bad_auth.status_code == 401

    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.integration
def test_oauth_disconnect_when_google_revocation_fails(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify that when Google revocation fails or errors, local tokens are still purged safely."""
    async def _run() -> None:
        user_repo = UserRepository(db_session)
        user = user_repo.create_user(
            email=f"fail_rev_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pw",
        )
        # Store an active connection with encrypted tokens bound to AAD context
        aad_rf = build_token_aad(
            user_id=str(user.id),
            platform="youtube",
            external_channel_id="UC_FAIL_REV_001",
            credential_kind="refresh",
        )
        user_repo.upsert_oauth_connection(
            user_id=user.id,
            external_channel_id="UC_FAIL_REV_001",
            granted_scopes=" ".join(REQUIRED_SCOPES),
            encrypted_refresh_token=crypto_svc.encrypt("1//mock_refresh_token", aad=aad_rf),
            is_active=True,
        )
        db_session.commit()

        # Mock Google revocation returning 500 error
        def mock_error_revocation(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error at Google")

        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_error_revocation))
        service = OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_http,
        )

        res = await service.disconnect(
            user_id=user.id, external_channel_id="UC_FAIL_REV_001"
        )
        # Must report remote_revoked=False while local_disconnected=True
        assert res.local_disconnected is True
        assert res.remote_revoked is False
        assert "rejected by Google" in res.details

        # Ensure tokens were NOT retained locally
        db_session.expire_all()
        conn = user_repo.get_oauth_connection(
            user_id=user.id, external_channel_id="UC_FAIL_REV_001"
        )
        assert conn is not None
        assert conn.is_active is False
        assert conn.encrypted_access_token is None
        assert conn.encrypted_refresh_token is None

        # Test case: Network timeout communicating with Google
        conn.is_active = True
        conn.encrypted_refresh_token = crypto_svc.encrypt("1//timeout_token", aad=aad_rf)
        db_session.commit()

        def mock_timeout_revocation(_req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("Connection timed out to oauth2.googleapis.com")

        mock_timeout_http = httpx.AsyncClient(
            transport=httpx.MockTransport(mock_timeout_revocation)
        )
        service_timeout = OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_timeout_http,
        )

        res_timeout = await service_timeout.disconnect(
            user_id=user.id, external_channel_id="UC_FAIL_REV_001"
        )
        assert res_timeout.local_disconnected is True
        assert res_timeout.remote_revoked is False
        assert "local credentials purged safely" in res_timeout.details

        db_session.expire_all()
        conn_after_timeout = user_repo.get_oauth_connection(
            user_id=user.id, external_channel_id="UC_FAIL_REV_001"
        )
        assert conn_after_timeout is not None
        assert conn_after_timeout.is_active is False
        assert conn_after_timeout.encrypted_refresh_token is None

    asyncio.run(_run())


def test_production_environment_rejects_client_supplied_x_user_id(db_session: Session) -> None:
    """Verify that in production environments, X-User-Id is strictly prohibited."""
    import secrets as _secrets
    _prod_key = _secrets.token_hex(32)
    _prod_state_secret = _secrets.token_hex(32)
    prod_settings = Settings(
        environment="production",
        token_encryption_key=_prod_key,
        oauth_state_secret=_prod_state_secret,
        youtube_client_id="prod_id",
        youtube_client_secret=SecretStr("prod_secret"),
        google_login_client_id="prod_google_id",
        google_login_client_secret=SecretStr("prod_google_secret"),
    )
    app.dependency_overrides[get_settings] = lambda: prod_settings
    try:
        client = TestClient(app)

        # 1. Supplying X-User-Id in production must be rejected with 403 Forbidden
        arbitrary_uid = uuid.uuid4()
        for endpoint, method in [
            ("/api/v1/oauth/youtube/authorize", "GET"),
            ("/api/v1/oauth/youtube/status?channel_id=UC123", "GET"),
            ("/api/v1/oauth/youtube/disconnect", "POST"),
        ]:
            if method == "GET":
                resp_spoof = client.get(endpoint, headers={"X-User-Id": str(arbitrary_uid)})
            else:
                resp_spoof = client.post(
                    endpoint,
                    json={"channel_id": "UC123"},
                    headers={"X-User-Id": str(arbitrary_uid)},
                )
            assert resp_spoof.status_code == 403
            assert "strictly prohibited in production" in resp_spoof.json()["detail"]

        # 2. Supplying no credentials in production returns 401
        for endpoint, method in [
            ("/api/v1/oauth/youtube/authorize", "GET"),
            ("/api/v1/oauth/youtube/status?channel_id=UC123", "GET"),
            ("/api/v1/oauth/youtube/disconnect", "POST"),
        ]:
            if method == "GET":
                resp_no_auth = client.get(endpoint)
            else:
                resp_no_auth = client.post(endpoint, json={"channel_id": "UC123"})
            assert resp_no_auth.status_code == 401
            detail = resp_no_auth.json()["detail"]
            assert "session cookie" in detail or "Authentication required" in detail

    finally:
        app.dependency_overrides.pop(get_settings, None)


# ---------------------------------------------------------------------------
# Phase 5 — OAuth data-deletion integration tests (real PostgreSQL)
# ---------------------------------------------------------------------------

def _build_channel(
    session: Session,
    user_id: uuid.UUID,
    youtube_channel_id: str,
) -> object:
    """Helper: persist a minimal Channel row and return it."""
    from miconte.models.channel import Channel  # noqa: PLC0415

    ch = Channel(
        user_id=user_id,
        youtube_channel_id=youtube_channel_id,
        title=f"Test Channel {youtube_channel_id}",
        uploads_playlist_id=f"UU_{youtube_channel_id}",
    )
    session.add(ch)
    session.flush()
    return ch


@pytest.mark.integration
def test_disconnect_deletes_channel_videos_snapshots_and_metrics(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """disconnect() deletes Channel and all cascading API data (videos, snapshots, sync_runs)."""
    import asyncio  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from miconte.models.analysis import AnalysisRun, SyncRun  # noqa: PLC0415
    from miconte.models.channel import Channel  # noqa: PLC0415
    from miconte.models.video import Video, VideoPublicSnapshot  # noqa: PLC0415

    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=f"del_full_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="pw",
    )
    db_session.commit()

    yt_id = f"UC_DEL_{uuid.uuid4().hex[:8]}"
    ch = _build_channel(db_session, user.id, yt_id)

    vid = Video(
        channel_id=ch.id,
        youtube_video_id=f"vid_{uuid.uuid4().hex[:8]}",
        title="Test Video",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
        duration_iso="PT5M",
        duration_seconds=300,
    )
    db_session.add(vid)
    db_session.flush()

    snap = VideoPublicSnapshot(
        video_id=vid.id,
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
        view_count=100,
    )
    sync_run = SyncRun(channel_id=ch.id, sync_type="metadata", status="completed")
    analysis_run = AnalysisRun(
        channel_id=ch.id,
        analysis_type="cohort_baseline",
        status="completed",
        parameters={},
    )
    db_session.add_all([snap, sync_run, analysis_run])

    aad_rf = build_token_aad(
        user_id=str(user.id), platform="youtube",
        external_channel_id=yt_id, credential_kind="refresh",
    )
    user_repo.upsert_oauth_connection(
        user_id=user.id, external_channel_id=yt_id, granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//tok", aad=aad_rf), is_active=True,
    )
    db_session.commit()

    channel_pk = ch.id
    video_pk = vid.id
    snap_pk = snap.id

    async def _run() -> None:
        mock_http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200))
        )
        service = OAuthService(
            session=db_session, settings=test_settings,
            crypto_service=crypto_svc, http_client=mock_http,
        )
        res = await service.disconnect(user_id=user.id, external_channel_id=yt_id)
        assert res.local_disconnected is True

    asyncio.run(_run())

    db_session.expire_all()
    assert db_session.get(Channel, channel_pk) is None
    assert db_session.get(Video, video_pk) is None
    assert db_session.get(VideoPublicSnapshot, snap_pk) is None
    assert db_session.execute(
        select(SyncRun).where(SyncRun.channel_id == channel_pk)
    ).scalar_one_or_none() is None
    assert db_session.execute(
        select(AnalysisRun).where(AnalysisRun.channel_id == channel_pk)
    ).scalar_one_or_none() is None


@pytest.mark.integration
def test_disconnect_deletes_reporting_ingestions(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """disconnect() deletes reporting_report_ingestions via DB-level FK cascade."""
    import asyncio  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from miconte.models.reporting import ReportingReportIngestion  # noqa: PLC0415

    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=f"del_rep_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw",
    )
    db_session.commit()

    yt_id = f"UC_REP_{uuid.uuid4().hex[:8]}"
    ch = _build_channel(db_session, user.id, yt_id)

    ingestion = ReportingReportIngestion(
        channel_id=ch.id,
        report_id=f"rpt_{uuid.uuid4().hex}",
        job_id="job_001",
        rows_ingested=10,
    )
    db_session.add(ingestion)
    aad_rf = build_token_aad(
        user_id=str(user.id), platform="youtube",
        external_channel_id=yt_id, credential_kind="refresh",
    )
    user_repo.upsert_oauth_connection(
        user_id=user.id, external_channel_id=yt_id, granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//tok", aad=aad_rf), is_active=True,
    )
    db_session.commit()

    channel_pk = ch.id

    async def _run() -> None:
        mock_http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200))
        )
        service = OAuthService(
            session=db_session, settings=test_settings,
            crypto_service=crypto_svc, http_client=mock_http,
        )
        await service.disconnect(user_id=user.id, external_channel_id=yt_id)

    asyncio.run(_run())

    db_session.expire_all()
    remaining = db_session.execute(
        select(ReportingReportIngestion).where(
            ReportingReportIngestion.channel_id == channel_pk
        )
    ).scalars().all()
    assert remaining == []


@pytest.mark.integration
def test_disconnect_preserves_other_channel_of_same_user(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """disconnect() on channel A must not affect channel B owned by the same user."""
    import asyncio  # noqa: PLC0415

    from miconte.models.channel import Channel  # noqa: PLC0415

    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=f"del_iso_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw",
    )
    db_session.commit()

    yt_a = f"UC_A_{uuid.uuid4().hex[:8]}"
    yt_b = f"UC_B_{uuid.uuid4().hex[:8]}"
    ch_a = _build_channel(db_session, user.id, yt_a)
    ch_b = _build_channel(db_session, user.id, yt_b)

    aad_a = build_token_aad(
        user_id=str(user.id), platform="youtube",
        external_channel_id=yt_a, credential_kind="refresh",
    )
    aad_b = build_token_aad(
        user_id=str(user.id), platform="youtube",
        external_channel_id=yt_b, credential_kind="refresh",
    )
    user_repo.upsert_oauth_connection(
        user_id=user.id, external_channel_id=yt_a, granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//tok_a", aad=aad_a), is_active=True,
    )
    user_repo.upsert_oauth_connection(
        user_id=user.id, external_channel_id=yt_b, granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//tok_b", aad=aad_b), is_active=True,
    )
    db_session.commit()

    pk_a = ch_a.id
    pk_b = ch_b.id

    async def _run() -> None:
        mock_http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200))
        )
        service = OAuthService(
            session=db_session, settings=test_settings,
            crypto_service=crypto_svc, http_client=mock_http,
        )
        await service.disconnect(user_id=user.id, external_channel_id=yt_a)

    asyncio.run(_run())

    db_session.expire_all()
    assert db_session.get(Channel, pk_a) is None, "channel A must be deleted"
    assert db_session.get(Channel, pk_b) is not None, "channel B must survive"
    conn_b = user_repo.get_oauth_connection(user_id=user.id, external_channel_id=yt_b)
    assert conn_b is not None and conn_b.is_active is True


@pytest.mark.integration
def test_disconnect_preserves_other_users_channel(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """disconnect() must not delete data belonging to a different user's channel."""
    import asyncio  # noqa: PLC0415

    from miconte.models.channel import Channel  # noqa: PLC0415

    user_repo = UserRepository(db_session)
    user_a = user_repo.create_user(
        email=f"del_ua_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw",
    )
    user_b = user_repo.create_user(
        email=f"del_ub_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw",
    )
    db_session.commit()

    yt_a = f"UC_UA_{uuid.uuid4().hex[:8]}"
    yt_b = f"UC_UB_{uuid.uuid4().hex[:8]}"
    _build_channel(db_session, user_a.id, yt_a)
    ch_b = _build_channel(db_session, user_b.id, yt_b)

    aad_a = build_token_aad(
        user_id=str(user_a.id), platform="youtube",
        external_channel_id=yt_a, credential_kind="refresh",
    )
    user_repo.upsert_oauth_connection(
        user_id=user_a.id, external_channel_id=yt_a, granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//tok_a", aad=aad_a), is_active=True,
    )
    user_repo.upsert_oauth_connection(
        user_id=user_b.id, external_channel_id=yt_b, granted_scopes=" ".join(REQUIRED_SCOPES),
        is_active=True,
    )
    db_session.commit()

    pk_b = ch_b.id

    async def _run() -> None:
        mock_http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200))
        )
        service = OAuthService(
            session=db_session, settings=test_settings,
            crypto_service=crypto_svc, http_client=mock_http,
        )
        await service.disconnect(user_id=user_a.id, external_channel_id=yt_a)

    asyncio.run(_run())

    db_session.expire_all()
    assert db_session.get(Channel, pk_b) is not None, "user B's channel must be unaffected"
    conn_b = user_repo.get_oauth_connection(user_id=user_b.id, external_channel_id=yt_b)
    assert conn_b is not None and conn_b.is_active is True


@pytest.mark.integration
def test_disconnect_deactivates_oauth_connection(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """disconnect() deactivates OAuthConnection and nulls stored tokens; row is not deleted."""
    import asyncio  # noqa: PLC0415

    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=f"del_conn_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw",
    )
    db_session.commit()

    yt_id = f"UC_CONN_{uuid.uuid4().hex[:8]}"
    _build_channel(db_session, user.id, yt_id)

    aad_rf = build_token_aad(
        user_id=str(user.id), platform="youtube",
        external_channel_id=yt_id, credential_kind="refresh",
    )
    user_repo.upsert_oauth_connection(
        user_id=user.id, external_channel_id=yt_id, granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//tok", aad=aad_rf), is_active=True,
    )
    db_session.commit()

    async def _run() -> None:
        mock_http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200))
        )
        service = OAuthService(
            session=db_session, settings=test_settings,
            crypto_service=crypto_svc, http_client=mock_http,
        )
        await service.disconnect(user_id=user.id, external_channel_id=yt_id)

    asyncio.run(_run())

    db_session.expire_all()
    conn = user_repo.get_oauth_connection(user_id=user.id, external_channel_id=yt_id)
    assert conn is not None, "OAuthConnection row must still exist"
    assert conn.is_active is False
    assert conn.encrypted_access_token is None
    assert conn.encrypted_refresh_token is None
    assert conn.token_expires_at is None


@pytest.mark.integration
def test_disconnect_no_channel_created_yet_succeeds(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """disconnect() completes gracefully when no Channel row exists for the connection."""
    import asyncio  # noqa: PLC0415

    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=f"del_noc_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw",
    )
    yt_id = f"UC_NOC_{uuid.uuid4().hex[:8]}"
    aad_rf = build_token_aad(
        user_id=str(user.id), platform="youtube",
        external_channel_id=yt_id, credential_kind="refresh",
    )
    user_repo.upsert_oauth_connection(
        user_id=user.id, external_channel_id=yt_id, granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//tok", aad=aad_rf), is_active=True,
    )
    db_session.commit()

    async def _run() -> None:
        mock_http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200))
        )
        service = OAuthService(
            session=db_session, settings=test_settings,
            crypto_service=crypto_svc, http_client=mock_http,
        )
        res = await service.disconnect(user_id=user.id, external_channel_id=yt_id)
        assert res.local_disconnected is True

    asyncio.run(_run())

    db_session.expire_all()
    conn = user_repo.get_oauth_connection(user_id=user.id, external_channel_id=yt_id)
    assert conn is not None and conn.is_active is False


@pytest.mark.integration
def test_invalid_grant_during_refresh_deletes_channel_data(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """get_valid_access_token() detects invalid_grant and deletes all channel API data."""
    import asyncio  # noqa: PLC0415
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from miconte.integrations.youtube.exceptions import InvalidGrantError  # noqa: PLC0415
    from miconte.models.channel import Channel  # noqa: PLC0415

    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=f"del_igr_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw",
    )
    db_session.commit()

    yt_id = f"UC_IGR_{uuid.uuid4().hex[:8]}"
    ch = _build_channel(db_session, user.id, yt_id)
    channel_pk = ch.id

    aad_rf = build_token_aad(
        user_id=str(user.id), platform="youtube",
        external_channel_id=yt_id, credential_kind="refresh",
    )
    user_repo.upsert_oauth_connection(
        user_id=user.id,
        external_channel_id=yt_id,
        granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//expired_refresh", aad=aad_rf),
        token_expires_at=datetime.now(UTC) - timedelta(hours=2),
        is_active=True,
    )
    db_session.commit()

    def mock_invalid_grant(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Token has been revoked."}
        )

    async def _run() -> None:
        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_invalid_grant))
        service = OAuthService(
            session=db_session, settings=test_settings,
            crypto_service=crypto_svc, http_client=mock_http,
        )
        with pytest.raises(InvalidGrantError):
            await service.get_valid_access_token(
                user_id=user.id, external_channel_id=yt_id
            )

    asyncio.run(_run())

    db_session.expire_all()
    assert db_session.get(Channel, channel_pk) is None, "channel must be deleted on invalid_grant"
    conn = user_repo.get_oauth_connection(user_id=user.id, external_channel_id=yt_id)
    assert conn is not None
    assert conn.is_active is False
    assert conn.encrypted_refresh_token is None


@pytest.mark.integration
def test_disconnect_analysis_runs_and_recommendations_deleted(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """disconnect() cascades through analysis_runs to recommendations."""
    import asyncio  # noqa: PLC0415

    from miconte.models.analysis import AnalysisRun, Recommendation  # noqa: PLC0415

    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=f"del_anr_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw",
    )
    db_session.commit()

    yt_id = f"UC_ANR_{uuid.uuid4().hex[:8]}"
    ch = _build_channel(db_session, user.id, yt_id)

    analysis_run = AnalysisRun(
        channel_id=ch.id,
        analysis_type="cohort_baseline",
        status="completed",
        parameters={},
    )
    db_session.add(analysis_run)
    db_session.flush()

    rec = Recommendation(
        analysis_run_id=analysis_run.id,
        channel_id=ch.id,
        rule_code="R001",
        title="Test Recommendation",
        description="Test description without causal claims",
        priority="medium",
        metrics_evidence={},
    )
    db_session.add(rec)

    aad_rf = build_token_aad(
        user_id=str(user.id), platform="youtube",
        external_channel_id=yt_id, credential_kind="refresh",
    )
    user_repo.upsert_oauth_connection(
        user_id=user.id, external_channel_id=yt_id, granted_scopes=" ".join(REQUIRED_SCOPES),
        encrypted_refresh_token=crypto_svc.encrypt("1//tok", aad=aad_rf), is_active=True,
    )
    db_session.commit()

    ar_pk = analysis_run.id
    rec_pk = rec.id

    async def _run() -> None:
        mock_http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200))
        )
        service = OAuthService(
            session=db_session, settings=test_settings,
            crypto_service=crypto_svc, http_client=mock_http,
        )
        await service.disconnect(user_id=user.id, external_channel_id=yt_id)

    asyncio.run(_run())

    db_session.expire_all()
    assert db_session.get(AnalysisRun, ar_pk) is None
    assert db_session.get(Recommendation, rec_pk) is None
