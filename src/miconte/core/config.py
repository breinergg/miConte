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


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of application settings."""
    return Settings()
