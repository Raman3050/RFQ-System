from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1.router import api_router
from app.cache.redis import create_redis
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.rate_limit import RateLimiter
from app.db.session import create_engine, create_sessionmaker
from app.email.sender import create_email_sender
from app.realtime import ws
from app.realtime.manager import ConnectionManager
from app.realtime.publisher import NullPublisher, RedisPublisher

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.redis = create_redis(settings)
        app.state.publisher = RedisPublisher(app.state.redis)
        app.state.rate_limiter = RateLimiter(app.state.redis, enabled=settings.rate_limit_enabled)
        await app.state.ws_manager.start()
        log.info("startup", environment=settings.environment)
        try:
            yield
        finally:
            await app.state.ws_manager.stop()
            await app.state.redis.aclose()
            await engine.dispose()
            log.info("shutdown")

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json" if settings.expose_api_docs else None,
        docs_url=f"{settings.api_v1_prefix}/docs" if settings.expose_api_docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.email_sender = create_email_sender(settings)
    # Replaced with the Redis-backed publisher at startup; tests may swap in doubles.
    app.state.publisher = NullPublisher()
    app.state.rate_limiter = RateLimiter(None, enabled=False)
    app.state.ws_manager = ConnectionManager(str(settings.redis_url))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_deployed)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(ws.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
