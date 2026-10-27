"""
Web application settings, read from environment variables (prefix IDS_) and .env.

configs/config.yaml stays ML-only; everything about the running service lives here.
"""

import warnings
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEV_SECRET_KEY = "dev-only-insecure-secret-key-do-not-use-in-production"
MIN_SECRET_BYTES = 32  # HS256 key length recommended by RFC 7518 §3.2


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDS_", env_file=PROJECT_ROOT / ".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://ids:ids@localhost:5432/ids"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)

    model_store: Path = PROJECT_ROOT / "model_store"
    data_dir: Path = PROJECT_ROOT / "data"           # uploads/ and results/ live here
    model_poll_seconds: float = 30.0                 # fallback check of the active model version
    # Redis pub/sub for immediate model switches + per-process loaded-version reports (off in tests)
    model_events_enabled: bool = True

    disk_warning_percent: int = 85                   # /admin/server warns above this data-volume usage
    metrics_enabled: bool = True                     # GET /metrics for Prometheus (Caddy doesn't route it)

    max_upload_mb: int = 100                         # Cloudflare Free caps request bodies at 100 MB
    retention_days: int = 30
    enable_pcap: bool = True                         # pcap / pcapng uploads, turned into flows by src/flowmeter

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    # Browsers accept Secure cookies on http://localhost; set false only for plain-http access from elsewhere
    cookie_secure: bool = True
    rate_limits_enabled: bool = True

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    secret = settings.secret_key.get_secret_value()
    if secret == DEV_SECRET_KEY or len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        problem = (f"IDS_SECRET_KEY is the development default or shorter than {MIN_SECRET_BYTES} bytes; "
                   'generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"')
        if settings.env == "production":
            raise RuntimeError(problem)
        warnings.warn(problem, stacklevel=2)
    return settings
