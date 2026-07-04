import os
from pathlib import Path

from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_sqlite_url() -> str:
    base = Path(__file__).resolve().parent.parent
    (base / "data").mkdir(parents=True, exist_ok=True)
    db_path = (base / "data" / "trippack_v1.db").resolve()
    return f"sqlite:///{db_path.as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str = Field(default_factory=_default_sqlite_url)
    backend_mode: str = Field(
        default="RELEASE",
        validation_alias=AliasChoices("TRIPPACK_BACKEND_MODE", "backend_mode"),
    )
    api_host: str = "127.0.0.1"
    api_port: int = 8810
    provider_connected: int = Field(
        default=0,
        validation_alias=AliasChoices("TRIPPACK_PROVIDER_CONNECTED", "provider_connected"),
    )

    def resolved_backend_mode(self) -> str:
        m = (self.backend_mode or "RELEASE").strip().upper()
        return "DEBUG_DEMO" if m == "DEBUG_DEMO" else "RELEASE"

    def provider_mode_public(self) -> str:
        """DEBUG_DEMO | NOT_CONNECTED | CONNECTED"""
        if self.resolved_backend_mode() == "DEBUG_DEMO":
            return "DEBUG_DEMO"
        if int(self.provider_connected or 0) == 1:
            return "CONNECTED"
        return "NOT_CONNECTED"


settings = Settings()
