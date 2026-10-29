"""Tests for application configuration with MICONTE_ prefix."""

import secrets

import pytest
from pydantic import ValidationError

from miconte.core.config import Settings, get_settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify default configuration values when no environment variables are set."""
    monkeypatch.delenv("MICONTE_ENVIRONMENT", raising=False)
    monkeypatch.delenv("MICONTE_DATABASE_URL", raising=False)
    monkeypatch.delenv("MICONTE_POSTGRES_DB", raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_name == "miConte"
    assert settings.environment == "development"
    assert settings.postgres_db == "miconte_db"
    assert "miconte_db" in settings.database_url.get_secret_value()
    assert "postgresql+psycopg://" in settings.database_url.get_secret_value()


def test_settings_loads_miconte_prefix_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify MICONTE_ prefixed environment variables override defaults."""
    monkeypatch.setenv("MICONTE_ENVIRONMENT", "testing")
    monkeypatch.setenv("MICONTE_API_PORT", "9001")
    monkeypatch.setenv(
        "MICONTE_DATABASE_URL",
        "postgresql+psycopg://custom_user:custom_pass@127.0.0.1:5433/miconte_db",
    )

    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()

    assert settings.environment == "testing"
    assert settings.api_port == 9001
    assert (
        settings.database_url.get_secret_value()
        == "postgresql+psycopg://custom_user:custom_pass@127.0.0.1:5433/miconte_db"
    )
    # SecretStr must not expose credentials in string representation
    assert "custom_pass" not in str(settings.database_url)
    assert "custom_pass" not in repr(settings.database_url)
    get_settings.cache_clear()  # type: ignore[attr-defined]


# ─── Production startup security validation ──────────────────────────────────

_VALID_PROD_KEY = secrets.token_hex(32)  # fresh 64-char hex key, not the known dev default
_VALID_PROD_SECRET = secrets.token_hex(32)


def _prod_settings(**overrides: str) -> Settings:
    """Build Settings with environment=production and safe defaults, allowing field overrides."""
    base: dict[str, str] = {
        "environment": "production",
        "token_encryption_key": _VALID_PROD_KEY,
        "oauth_state_secret": _VALID_PROD_SECRET,
        "google_login_client_id": "test_google_client_id",
        "google_login_client_secret": "test_google_client_secret",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_production_rejects_dev_encryption_key() -> None:
    """Backend must not start in production with the known development encryption key."""
    with pytest.raises(ValidationError, match="MICONTE_TOKEN_ENCRYPTION_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            token_encryption_key="000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
            oauth_state_secret=_VALID_PROD_SECRET,
            google_login_client_id="gid",
            google_login_client_secret="gsecret",
        )  # type: ignore[call-arg]


def test_production_rejects_dev_oauth_state_secret() -> None:
    """Backend must not start in production with the known development CSRF state secret."""
    with pytest.raises(ValidationError, match="MICONTE_OAUTH_STATE_SECRET"):
        Settings(
            _env_file=None,
            environment="production",
            token_encryption_key=_VALID_PROD_KEY,
            oauth_state_secret="dev_oauth_state_signing_secret_do_not_use_in_prod",
            google_login_client_id="gid",
            google_login_client_secret="gsecret",
        )  # type: ignore[call-arg]


def test_production_rejects_short_encryption_key() -> None:
    """A key that does not decode to 32 bytes must be rejected in production."""
    with pytest.raises(ValidationError, match="MICONTE_TOKEN_ENCRYPTION_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            token_encryption_key="tooshort",
            oauth_state_secret=_VALID_PROD_SECRET,
            google_login_client_id="gid",
            google_login_client_secret="gsecret",
        )  # type: ignore[call-arg]


def test_production_accepts_valid_hex_key() -> None:
    """A fresh 64-char hex key with a custom CSRF secret is accepted in production."""
    settings = _prod_settings()
    assert settings.environment == "production"
    assert settings.token_encryption_key.get_secret_value() == _VALID_PROD_KEY


def test_production_accepts_valid_base64_key() -> None:
    """A valid 44-char urlsafe-base64 key is accepted in production."""
    import base64
    raw = secrets.token_bytes(32)
    b64_key = base64.urlsafe_b64encode(raw).decode("ascii")
    settings = _prod_settings(token_encryption_key=b64_key)
    assert settings.environment == "production"


def test_development_accepts_dev_defaults() -> None:
    """Development and testing environments must keep working with default dev values."""
    for env in ("development", "testing"):
        settings = Settings(_env_file=None, environment=env)  # type: ignore[call-arg]
        assert settings.environment == env
