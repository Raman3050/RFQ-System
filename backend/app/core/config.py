from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables (and `.env` in dev)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "RFQ British Auction API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://rfq:rfq@localhost:5432/rfq_auction"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_echo: bool = False

    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")

    # Lifecycle worker
    worker_tick_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
