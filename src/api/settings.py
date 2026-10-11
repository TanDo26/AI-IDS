"""
Web application settings, read from environment variables (prefix IDS_) and .env.

configs/config.yaml stays ML-only; everything about the running service lives here.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDS_", env_file=PROJECT_ROOT / ".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://ids:ids@localhost:5432/ids"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: SecretStr = SecretStr("dev-only-change-me")

    model_store: Path = PROJECT_ROOT / "model_store"
    data_dir: Path = PROJECT_ROOT / "data"           # uploads/ and results/ live here
    model_poll_seconds: float = 30.0

    max_upload_mb: int = 100                         # Cloudflare Free caps request bodies at 100 MB
    retention_days: int = 30
    enable_pcap: bool = False                        # until the flow extractor passes its parity test

    access_token_minutes: int = 15
    refresh_token_days: int = 7

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.env == "production" and settings.secret_key.get_secret_value() == "dev-only-change-me":
        raise RuntimeError("IDS_SECRET_KEY must be set in production")
    return settings
