"""Application settings loaded from MICONTE_ environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of application settings."""
    return Settings()
