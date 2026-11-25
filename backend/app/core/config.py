from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEV_JWT_SECRET = "dev-insecure-jwt-secret-change-me"  # noqa: S105 - dev-only default


class Settings(BaseSettings):
    """Application settings, loaded from environment variables (and `.env` in dev)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "RFQ British Auction API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    api_v1_prefix: str = "/api/v1"
    expose_api_docs: bool = True  # Swagger UI + OpenAPI JSON; disable in production
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://rfq:rfq@localhost:5432/rfq_auction"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_echo: bool = False

    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")

    # Auth
    jwt_secret_key: SecretStr = SecretStr(INSECURE_DEV_JWT_SECRET)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "rfq-auction-api"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=30)
    refresh_cookie_name: str = "rfq_refresh"
    # Must be True whenever the app is served over HTTPS (staging/production).
    refresh_cookie_secure: bool = False

    # Supplier invitations
    supplier_invite_ttl_days: int = Field(default=7, ge=1, le=30)
    frontend_base_url: str = "http://localhost:5173"  # used to build links in emails

    # Email. "smtp" in deployed envs (and Mailpit locally); "memory" keeps messages
    # in-process for tests; "console" just logs them.
    email_backend: Literal["smtp", "console", "memory"] = "console"
    email_from: str = "RFQ Auctions <no-reply@rfq-auctions.local>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = False
    smtp_timeout_seconds: float = 10.0

    # Abuse protection
    rate_limit_enabled: bool = True

    # Real-time (WebSocket)
    ws_auth_timeout_seconds: float = 5.0
    ws_ping_seconds: float = 25.0  # keeps proxies from dropping idle sockets
    ws_max_subscriptions: int = 100

    # Lifecycle worker
    worker_tick_seconds: float = 1.0

    @property
    def is_deployed(self) -> bool:
        return self.environment in ("staging", "production")

    @property
    def refresh_cookie_path(self) -> str:
        # Cookie is only ever sent to the auth endpoints, never to the rest of the API.
        return f"{self.api_v1_prefix}/auth"

    @model_validator(mode="after")
    def _check_deployed_security(self) -> Self:
        if self.is_deployed:
            secret = self.jwt_secret_key.get_secret_value()
            if secret == INSECURE_DEV_JWT_SECRET or len(secret) < 32:
                raise ValueError("JWT_SECRET_KEY must be set to a random value of 32+ chars")
            if not self.refresh_cookie_secure:
                raise ValueError("REFRESH_COOKIE_SECURE must be true outside local/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
