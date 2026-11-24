"""Auction lifecycle worker (separate process).

Phase 0: runs the loop skeleton with graceful shutdown and a DB/Redis heartbeat.
Phase 4: each tick activates SCHEDULED auctions and closes / force-closes ACTIVE ones
using `SELECT ... FOR UPDATE SKIP LOCKED` (see docs/HLD.md §4.4).

Run with:  python -m app.workers.lifecycle
"""

import asyncio
import contextlib
import signal

from app.cache.redis import create_redis, ping_redis
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, ping_db

log = get_logger("app.worker.lifecycle")


async def tick() -> None:
    """One pass of lifecycle work. Filled in Phase 4."""


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    engine = create_engine(settings)
    redis = create_redis(settings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await ping_db(engine)
    await ping_redis(redis)
    log.info("worker_started", tick_seconds=settings.worker_tick_seconds)

    try:
        while not stop.is_set():
            try:
                await tick()
            except Exception:
                # One bad tick must never kill the worker.
                log.exception("worker_tick_failed")
            # Sleep until the next tick, waking immediately on shutdown.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_tick_seconds)
    finally:
        await redis.aclose()
        await engine.dispose()
        log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(run())
