"""OAuth 2.0 Web Server authorization flow handler for YouTube APIs."""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from miconte.integrations.youtube.dto import OAuthTokenResponseDTO
from miconte.integrations.youtube.exceptions import (
    InsufficientPermissionsError,
    OAuthError,
    parse_google_api_error,
)

_GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


@dataclass
class OAuthTransaction:
    """State record for an active OAuth authorization transaction."""

    user_id: uuid.UUID
    code_verifier: str
    expires_at: float
    session_id: str | None = None
    consumed: bool = False


class OAuthTransactionStore:
    """Thread-safe in-memory store for OAuth transactions enforcing single-use and PKCE.

    Single-process limitation
    -------------------------
    This store uses an in-memory dict and is not replicated across workers.
    A YouTube authorization flow that initiates on worker A will fail if the
    callback arrives on worker B. See also LoginTransactionStore in
    security/login.py for the same constraint. Multi-worker deployments require
    sticky-session routing or an external shared store (e.g. Redis).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._transactions: dict[str, OAuthTransaction] = {}

    def register(
        self,
        state_nonce: str,
        user_id: uuid.UUID,
        code_verifier: str,
        ttl_seconds: int = 600,
        session_id: str | None = None,
    ) -> None:
        """Register a new authorization transaction with TTL and PKCE verifier."""
        with self._lock:
            self._cleanup_expired()
            self._transactions[state_nonce] = OAuthTransaction(
                user_id=user_id,
                code_verifier=code_verifier,
                expires_at=time.time() + ttl_seconds,
                session_id=session_id,
                consumed=False,
            )

    def consume(
        self,
        state_nonce: str,
        expected_user_id: uuid.UUID,
        expected_session_id: str | None = None,
    ) -> str:
        """Atomically validate and consume a transaction. Returns code_verifier.

        Raises OAuthError if not found, expired, already consumed, or user mismatch.
        """
        with self._lock:
            self._cleanup_expired()
            txn = self._transactions.get(state_nonce)
            if txn is None:
                raise OAuthError("OAuth state transaction not found or already purged")
            if txn.consumed:
                raise OAuthError(
                    "OAuth state token has already been consumed (replay attack detected)"
                )
            if time.time() > txn.expires_at:
                raise OAuthError("OAuth state transaction has expired")
            if txn.user_id != expected_user_id:
                raise OAuthError("OAuth state user does not match the authorized user")
            if (
                expected_session_id is not None
                and txn.session_id is not None
                and txn.session_id != expected_session_id
            ):
                raise OAuthError("OAuth state session mismatch")

            # Single-use consumption
            txn.consumed = True
            return txn.code_verifier

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._transactions.items() if now > v.expires_at]
        for k in expired:
            del self._transactions[k]


# Global thread-safe transaction store singleton
default_transaction_store = OAuthTransactionStore()


def generate_pkce_pair() -> tuple[str, str]:
    """Generate RFC 7636 PKCE (code_verifier, code_challenge) with SHA-256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def create_state_token(
    user_id: uuid.UUID,
    secret: str,
    ttl_seconds: int = 600,
    session_id: str | None = None,
) -> tuple[str, str]:
    """Generate a tamper-proof, timestamped CSRF state token bound to user and session.

    Returns (state_token, state_nonce).
    """
    state_nonce = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "u": str(user_id),
        "exp": int(time.time()) + ttl_seconds,
        "rnd": state_nonce,
    }
    if session_id:
        payload["sid"] = session_id

    raw_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw_payload).decode("ascii")

    sig = hmac.new(
        secret.encode("utf-8"), b64_payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{b64_payload}.{sig}", state_nonce


def verify_state_token(
    state: str,
    secret: str,
) -> tuple[uuid.UUID, str, str | None]:
    """Validate CSRF state token signature and expiry.

    Returns (user_id, state_nonce, session_id).
    """
    if not state or "." not in state:
        raise OAuthError("Malformed or empty OAuth state token")

    b64_payload, signature = state.split(".", 1)
    expected_sig = hmac.new(
        secret.encode("utf-8"), b64_payload.encode("ascii"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        raise OAuthError("OAuth state signature verification failed: state has been tampered with")

    try:
        raw_payload = base64.urlsafe_b64decode(b64_payload.encode("ascii"))
        payload = json.loads(raw_payload.decode("utf-8"))
    except Exception as exc:
        raise OAuthError("Failed to decode OAuth state payload") from exc

    exp = payload.get("exp", 0)
    if time.time() > exp:
        raise OAuthError("OAuth state token has expired")

    user_str = payload.get("u")
    state_nonce = payload.get("rnd")
    session_id = payload.get("sid")

    if not user_str or not state_nonce:
        raise OAuthError("OAuth state token missing required identity fields")

    try:
        return uuid.UUID(user_str), str(state_nonce), session_id
    except ValueError as exc:
        raise OAuthError("Invalid user UUID inside OAuth state token") from exc


def generate_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str | None = None,
) -> str:
    """Construct Google OAuth 2.0 Web Server authorization URL with PKCE support."""
    if not client_id:
        raise OAuthError("Google client_id is not configured")

    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(REQUIRED_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"

    return f"{_GOOGLE_AUTH_BASE_URL}?{urllib.parse.urlencode(params)}"


def check_scopes_sufficient(granted_scopes: str) -> bool:
    """Verify that all required read-only scopes were granted by the user."""
    granted_set = set(granted_scopes.split())
    return all(req in granted_set for req in REQUIRED_SCOPES)


async def exchange_code_for_tokens(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    token_url: str = _GOOGLE_TOKEN_URL,
) -> OAuthTokenResponseDTO:
    """Exchange authorization code for access and refresh tokens using PKCE verifier."""
    if not client_id or not client_secret:
        raise OAuthError("Google OAuth client_id or client_secret is missing")

    payload: dict[str, str] = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    headers = {"Accept": "application/json"}

    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(token_url, data=payload, headers=headers)
    except httpx.RequestError as exc:
        raise OAuthError(f"HTTP error communicating with Google token endpoint: {exc}") from exc
    finally:
        if http_client is None:
            await client.aclose()

    if not resp.is_success:
        try:
            err_data: dict[str, Any] = resp.json()
        except Exception:
            err_data = {}
        raise parse_google_api_error(resp.status_code, err_data, resp.text)

    data = resp.json()
    granted_scope = data.get("scope", "")

    if not check_scopes_sufficient(granted_scope):
        raise InsufficientPermissionsError(
            f"Granted scopes '{granted_scope}' are insufficient. Required: {REQUIRED_SCOPES}"
        )

    return OAuthTokenResponseDTO(
        access_token=data["access_token"],
        token_type=data.get("token_type", "Bearer"),
        expires_in=int(data.get("expires_in", 3600)),
        refresh_token=data.get("refresh_token"),
        scope=granted_scope,
    )


async def refresh_oauth_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    http_client: httpx.AsyncClient | None = None,
    token_url: str = _GOOGLE_TOKEN_URL,
) -> OAuthTokenResponseDTO:
    """Refresh an expired access token using the stored refresh token."""
    if not refresh_token:
        raise OAuthError("Cannot refresh access token without a refresh_token")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    headers = {"Accept": "application/json"}

    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(token_url, data=payload, headers=headers)
    except httpx.RequestError as exc:
        raise OAuthError(f"HTTP error refreshing Google OAuth token: {exc}") from exc
    finally:
        if http_client is None:
            await client.aclose()

    if not resp.is_success:
        try:
            err_data: dict[str, Any] = resp.json()
        except Exception:
            err_data = {}
        raise parse_google_api_error(resp.status_code, err_data, resp.text)

    data = resp.json()
    return OAuthTokenResponseDTO(
        access_token=data["access_token"],
        token_type=data.get("token_type", "Bearer"),
        expires_in=int(data.get("expires_in", 3600)),
        refresh_token=data.get("refresh_token", refresh_token),
        scope=data.get("scope", " ".join(REQUIRED_SCOPES)),
    )


async def revoke_oauth_token(
    token: str,
    http_client: httpx.AsyncClient | None = None,
    revoke_url: str = _GOOGLE_REVOKE_URL,
) -> bool:
    """Revoke an OAuth token with Google servers via POST body."""
    if not token:
        return True

    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        # Send token in request body to avoid logging in query string
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = await client.post(revoke_url, data={"token": token}, headers=headers)
        return resp.status_code in (200, 204)
    except httpx.RequestError:
        return False
    finally:
        if http_client is None:
            await client.aclose()
