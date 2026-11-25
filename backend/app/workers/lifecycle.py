"""Auction lifecycle worker (separate process).

Every tick (default 1 s) it persists auction transitions on time:
SCHEDULED → ACTIVE at bid start, ACTIVE → CLOSED / FORCE_CLOSED at the (possibly extended)
close, with activity-log entries and the winning bid. See app.services.lifecycle_service.

Safe to run several replicas (SELECT … FOR UPDATE SKIP LOCKED). Publishes a heartbeat to
Redis so /health/ready can report whether the worker is alive.

Run with:  python -m app.workers.lifecycle
"""

import asyncio
import contextlib
import json
import signal
import time
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.cache.redis import create_redis, ping_redis
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, create_sessionmaker, ping_db
from app.services.lifecycle_service import LifecycleService, TickStats

log = get_logger("app.worker.lifecycle")

HEARTBEAT_KEY = "worker:lifecycle:heartbeat"
HEARTBEAT_TTL_SECONDS = 30
SLOW_TICK_SECONDS = 2.0


async def publish_heartbeat(redis: Redis, stats: TickStats, tick_ms: float) -> None:
    """Best effort: a Redis outage must never stop auctions from closing."""
    try:
        await redis.set(
            HEARTBEAT_KEY,
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "tick_ms": round(tick_ms, 1),
                    "last_changes": stats.changed,
                }
            ),
            ex=HEARTBEAT_TTL_SECONDS,
        )
    except Exception as exc:
        log.warning("heartbeat_failed", error=type(exc).__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    engine = create_engine(settings)
    redis = create_redis(settings)
    service = LifecycleService(create_sessionmaker(engine))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await ping_db(engine)
    with contextlib.suppress(Exception):
        await ping_redis(redis)
    log.info("worker_started", tick_seconds=settings.worker_tick_seconds)

    try:
        while not stop.is_set():
            started = time.perf_counter()
            stats = TickStats()
            try:
                stats = await service.run_once()
            except Exception:
                # One bad tick must never kill the worker; the next tick retries.
                log.exception("worker_tick_failed")
            tick_ms = (time.perf_counter() - started) * 1000
            if tick_ms > SLOW_TICK_SECONDS * 1000:
                log.warning("worker_tick_slow", tick_ms=round(tick_ms))
            await publish_heartbeat(redis, stats, tick_ms)
            # Sleep until the next tick, waking immediately on shutdown.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_tick_seconds)
    finally:
        await redis.aclose()
        await engine.dispose()
        log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(run())
