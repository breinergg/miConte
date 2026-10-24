"""Tests for application configuration with MICONTE_ prefix."""

import pytest

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

    get_settings.cache_clear()
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
    get_settings.cache_clear()
