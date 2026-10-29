"""Application settings loaded from MICONTE_ environment variables."""

import base64
import binascii
import contextlib
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Known development defaults that must never be used in production.
# These values are published in .env.example / repository and are public knowledge.
# S105 is suppressed intentionally: the strings are comparison sentinels, not secrets.
_DEV_TOKEN_ENCRYPTION_KEY = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"  # noqa: S105
_DEV_OAUTH_STATE_SECRET = "dev_oauth_state_signing_secret_do_not_use_in_prod"  # noqa: S105


class Settings(BaseSettings):
    """Global application configuration for miConte."""

    model_config = SettingsConfigDict(
        env_prefix="MICONTE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="miConte", description="Visible product name")
    environment: Literal["development", "testing", "production"] = Field(
        default="development",
        description="Runtime environment name",
    )
    api_host: str = Field(default="127.0.0.1", description="Bind host for FastAPI server")
    api_port: int = Field(default=8000, ge=1, le=65535, description="Bind port for FastAPI server")

    postgres_user: str = Field(default="miconte_user", description="PostgreSQL user")
    postgres_password: SecretStr = Field(
        default=SecretStr("miconte_dev_password_change_me"),
        description="PostgreSQL password",
    )
    postgres_db: str = Field(default="miconte_db", description="PostgreSQL database name")
    postgres_host: str = Field(default="127.0.0.1", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, ge=1, le=65535, description="PostgreSQL port")

    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+psycopg://miconte_user:miconte_dev_password_change_me@127.0.0.1:5432/miconte_db"
        ),
        description="SQLAlchemy 2.x PostgreSQL connection URL using psycopg v3",
    )

    # Cryptography and Token Protection (Phase 4)
    # Default key is for local dev/testing only; prod MUST inject 256-bit key via env var.
    token_encryption_key: SecretStr = Field(
        default=SecretStr("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"),
        description="256-bit hex or base64 AES-GCM master key for sensitive token storage",
    )
    token_encryption_key_id: str = Field(
        default="k1",
        description="Key identifier used in ciphertext envelope for versioning and rotation",
    )
    oauth_state_secret: SecretStr = Field(
        default=SecretStr("dev_oauth_state_signing_secret_do_not_use_in_prod"),
        description="HMAC secret used to sign and verify OAuth CSRF state tokens",
    )

    # Google Cloud / YouTube API Integrations (Phase 4)
    youtube_client_id: str = Field(
        default="",
        description="Google Cloud OAuth 2.0 Web Client ID",
    )
    youtube_client_secret: SecretStr = Field(
        default=SecretStr(""),
        description="Google Cloud OAuth 2.0 Web Client Secret",
    )
    youtube_redirect_uri: str = Field(
        default="http://127.0.0.1:8000/api/v1/oauth/youtube/callback",
        description="Registered OAuth 2.0 redirect URI for YouTube authorization",
    )
    youtube_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Google Cloud YouTube Data API v3 public server key (optional for public mode)",
    )

    # Periodic Synchronization & Ingestion (Phase 5)
    sync_interval_hours: int = Field(
        default=24,
        ge=1,
        description="Interval in hours between automatic background sync cycles",
    )
    sync_enabled: bool = Field(
        default=True,
        description="Enable periodic background synchronization loop in server lifespan",
    )
    sync_max_videos_per_channel: int = Field(
        default=500,
        ge=1,
        description="Maximum videos to synchronize per channel in a single sync run",
    )
    sync_analytics_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Default window of days of analytics history to retrieve",
    )

    # ─── AI / LLM Layer (Phase 9) ──────────────────────────────────────────────
    # MICONTE_LLM_PROVIDER=none  → disabled (default, no network calls)
    # MICONTE_LLM_PROVIDER=ollama → local Ollama instance
    # MICONTE_LLM_PROVIDER=external → remote chat/completions-compatible API
    llm_provider: str = Field(
        default="none",
        description=(
            "LLM adapter to use for natural-language interpretation of analytics results. "
            "Values: none (default, disabled), ollama, external. "
            "Env var: MICONTE_LLM_PROVIDER"
        ),
    )
    llm_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        description="Request timeout in seconds for LLM adapter calls. "
        "Env var: MICONTE_LLM_TIMEOUT_SECONDS",
    )

    # Ollama (MICONTE_LLM_PROVIDER=ollama)
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL of the local Ollama instance. Env var: MICONTE_OLLAMA_BASE_URL",
    )
    ollama_model: str = Field(
        default="llama3.2",
        description="Ollama model name to use for interpretation. Env var: MICONTE_OLLAMA_MODEL",
    )

    # External API (MICONTE_LLM_PROVIDER=external)
    external_llm_base_url: str = Field(
        default="",
        description="Full chat/completions endpoint URL for the external LLM provider. "
        "Env var: MICONTE_EXTERNAL_LLM_BASE_URL",
    )
    external_llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Bearer token / API key for the external LLM provider. "
        "Never exposed to Angular. Env var: MICONTE_EXTERNAL_LLM_API_KEY",
    )
    external_llm_model: str = Field(
        default="",
        description="Model identifier for the external LLM provider. "
        "Env var: MICONTE_EXTERNAL_LLM_MODEL",
    )

    # Google OpenID Connect Login (Phase 10 — production authentication)
    # Uses the same Google Cloud project as YouTube OAuth but with a separate
    # redirect URI, separate scopes (openid email profile), and a separate
    # session transaction store — never mixed with YouTube channel authorization.
    google_login_client_id: str = Field(
        default="",
        description=(
            "Google OAuth 2.0 client_id for OpenID Connect login. "
            "May use the same value as MICONTE_YOUTUBE_CLIENT_ID. "
            "Required in production. Env var: MICONTE_GOOGLE_LOGIN_CLIENT_ID"
        ),
    )
    google_login_client_secret: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Google OAuth 2.0 client_secret for OpenID Connect login. "
            "Required in production. Env var: MICONTE_GOOGLE_LOGIN_CLIENT_SECRET"
        ),
    )
    google_login_redirect_uri: str = Field(
        default="http://127.0.0.1:8000/api/v1/auth/google/callback",
        description=(
            "Registered redirect URI for the Google OIDC login callback. "
            "Must match exactly what is registered in Google Cloud Console. "
            "Env var: MICONTE_GOOGLE_LOGIN_REDIRECT_URI"
        ),
    )
    session_cookie_name: str = Field(
        default="miconte_session",
        description="Name of the HttpOnly session cookie. Env var: MICONTE_SESSION_COOKIE_NAME",
    )
    session_max_age_seconds: int = Field(
        default=604800,
        ge=300,
        description=(
            "Session lifetime in seconds (default: 7 days = 604800). "
            "Env var: MICONTE_SESSION_MAX_AGE_SECONDS"
        ),
    )
    frontend_url: str = Field(
        default="http://127.0.0.1:4200",
        description=(
            "Frontend base URL used for post-login redirect. "
            "Env var: MICONTE_FRONTEND_URL"
        ),
    )

    # CORS (Phase 10)
    # Comma-separated list of allowed origins for the CORS middleware.
    # In production, set this to the exact frontend origin (e.g. https://app.example.com).
    # The empty default means no cross-origin requests are allowed, which is safe for
    # same-origin deployments (frontend served by the same host as the API).
    # DO NOT set to "*" in production — it would bypass browser CORS protections.
    cors_allow_origins: str = Field(
        default="",
        description=(
            "Comma-separated list of origins allowed to call the API via CORS. "
            "Empty string disables CORS middleware (same-origin deployments). "
            "Example: https://app.example.com,https://www.example.com. "
            "Env var: MICONTE_CORS_ALLOW_ORIGINS"
        ),
    )

    # YouTube API compliance gate (Phase 7)
    # Must remain False until BOTH of the following are formally approved:
    #   1. Google OAuth app verification (when required by scopes / publication status).
    #   2. YouTube Data API derived-metrics compliance: applicable permissions for the
    #      analytics use case must be requested and accepted by Google.
    # Neither approval has been obtained yet.
    # Set MICONTE_ANALYTICS_REAL_DATA_ENABLED=true ONLY after both are confirmed.
    analytics_real_data_enabled: bool = Field(
        default=False,
        description=(
            "Enable analytics and recommendations derived from real YouTube API data. "
            "Must remain False until (1) Google OAuth app verification is completed "
            "when required by the requested scopes and publication status, AND "
            "(2) YouTube Data API derived-metrics compliance requirements are met, "
            "including the request and acceptance of applicable permissions for the "
            "analytics use case. Neither approval has been obtained yet. "
            "Env var: MICONTE_ANALYTICS_REAL_DATA_ENABLED"
        ),
    )


    @model_validator(mode="after")
    def _reject_insecure_production_config(self) -> "Settings":
        """Reject startup in production if any secret retains its known development default
        or if the encryption key is not a valid 256-bit key.

        Rules apply only when environment == 'production'.
        The actual secret values are never included in error messages.
        """
        if self.environment != "production":
            return self

        key_val = self.token_encryption_key.get_secret_value()

        # Reject known development default key (publicly committed in .env.example)
        if key_val == _DEV_TOKEN_ENCRYPTION_KEY:
            raise ValueError(
                "MICONTE_TOKEN_ENCRYPTION_KEY retains the known development default. "
                "The application cannot start in production with a publicly known key. "
                "Generate a production key: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        # Verify the key resolves to exactly 32 bytes (hex or base64 formats)
        cleaned = key_val.strip()
        key_is_valid = False
        if len(cleaned) == 64:
            with contextlib.suppress(ValueError):
                key_is_valid = len(bytes.fromhex(cleaned)) == 32
        if not key_is_valid:
            with contextlib.suppress(ValueError, binascii.Error):
                raw = base64.urlsafe_b64decode(cleaned.encode("ascii"))
                key_is_valid = len(raw) == 32
        if not key_is_valid:
            with contextlib.suppress(ValueError, binascii.Error):
                raw = base64.b64decode(cleaned.encode("ascii"))
                key_is_valid = len(raw) == 32
        if not key_is_valid:
            raise ValueError(
                "MICONTE_TOKEN_ENCRYPTION_KEY is not a valid 256-bit key in production. "
                "Accepted formats: 64-char hex string or 44-char base64 string. "
                "Generate a valid key: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        # Reject known development default for OAuth CSRF state signing
        if self.oauth_state_secret.get_secret_value() == _DEV_OAUTH_STATE_SECRET:
            raise ValueError(
                "MICONTE_OAUTH_STATE_SECRET retains the known development default. "
                "The application cannot start in production with a publicly known CSRF secret. "
                "Generate a strong secret: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        # Require Google OIDC login credentials in production
        if not self.google_login_client_id.strip():
            raise ValueError(
                "MICONTE_GOOGLE_LOGIN_CLIENT_ID is required in production. "
                "Set it to the Google OAuth 2.0 client_id registered in Google Cloud Console."
            )
        if not self.google_login_client_secret.get_secret_value().strip():
            raise ValueError(
                "MICONTE_GOOGLE_LOGIN_CLIENT_SECRET is required in production. "
                "Set it to the Google OAuth 2.0 client_secret from Google Cloud Console."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of application settings."""
    return Settings()
