"""Login transaction store for Google OpenID Connect flow.

Separate from the YouTube OAuth transaction store (security/oauth.py) to
prevent cross-contamination between the YouTube channel authorization flow
and user login sessions.
"""

import secrets
import threading
import time
from dataclasses import dataclass


@dataclass
class LoginTransaction:
    """State record for an active OpenID Connect login transaction."""

    code_verifier: str
    nonce: str
    expires_at: float
    consumed: bool = False


class LoginTransactionStore:
    """Thread-safe in-memory store for OIDC login state tokens.

    Each state token is single-use and expires after TTL.
    No user_id is bound at registration time — the user identity
    is established only after the Google callback is processed.

    Single-process limitation
    -------------------------
    This store uses an in-memory dict and is not replicated across workers.
    A login flow that initiates on worker A will fail if the callback arrives
    on worker B. This is the same limitation as OAuthTransactionStore in
    security/oauth.py. Both stores require a sticky-session load balancer
    or an external shared store (e.g. Redis) before scaling to multiple
    Uvicorn workers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._transactions: dict[str, LoginTransaction] = {}

    def register(
        self,
        code_verifier: str,
        nonce: str,
        ttl_seconds: int = 600,
    ) -> str:
        """Register a new login transaction. Returns the opaque state token."""
        state = secrets.token_urlsafe(32)
        with self._lock:
            self._cleanup_expired()
            self._transactions[state] = LoginTransaction(
                code_verifier=code_verifier,
                nonce=nonce,
                expires_at=time.time() + ttl_seconds,
            )
        return state

    def consume(self, state: str) -> tuple[str, str]:
        """Atomically validate and consume a login transaction.

        Returns (code_verifier, nonce) on success.
        Raises ValueError if not found, expired, or already consumed.
        """
        with self._lock:
            txn = self._transactions.get(state)
            if txn is None:
                raise ValueError("Login state token not found or already purged")
            if txn.consumed:
                raise ValueError("Login state token has already been consumed (replay detected)")
            if time.time() > txn.expires_at:
                del self._transactions[state]
                raise ValueError("Login state token has expired")
            txn.consumed = True
            self._cleanup_expired()
            return txn.code_verifier, txn.nonce

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._transactions.items() if now > v.expires_at]
        for k in expired:
            del self._transactions[k]


default_login_store = LoginTransactionStore()
