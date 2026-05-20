"""Centralized configuration via environment variables and .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Package root: quant_framework/ (parent of src/)
_PKG_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PKG_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cache_path: Path = Field(default=_PKG_ROOT / "data" / "cache.db", alias="CACHE_PATH")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_authorized_users: str = Field(default="", alias="TELEGRAM_AUTHORIZED_USERS")
    dashboard_port: int = Field(default=8501, alias="DASHBOARD_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    fundamentals_cache_days: int = Field(default=30, alias="FUNDAMENTALS_CACHE_DAYS")

    @field_validator("cache_path", mode="before")
    @classmethod
    def resolve_cache_path(cls, v: str | Path) -> Path:
        p = Path(v)
        if not p.is_absolute():
            p = _PKG_ROOT / p
        return p

    @property
    def authorized_user_ids(self) -> list[int]:
        if not self.telegram_authorized_users.strip():
            return []
        return [int(x.strip()) for x in self.telegram_authorized_users.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
