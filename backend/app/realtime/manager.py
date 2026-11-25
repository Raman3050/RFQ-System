"""In-process registry of WebSocket connections + the Redis pub/sub listener.

Each API process subscribes once to `auction:*` and fans messages out to the local
sockets subscribed to that RFQ. Any number of API replicas can run: every one of them
receives every message from Redis.
"""

import asyncio
import contextlib
import uuid
from collections import defaultdict

from redis.asyncio import Redis

from app.core.logging import get_logger
from app.realtime.publisher import CHANNEL_PATTERN, CHANNEL_PREFIX

log = get_logger(__name__)

QUEUE_SIZE = 256


class Connection:
    """One browser socket. Outgoing messages go through a queue drained by a single
    writer task, so sends never interleave."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.rfq_ids: set[str] = set()
        self.overflowed = False  # a client too slow to keep up gets disconnected

    def offer(self, raw: str) -> None:
        try:
            self.queue.put_nowait(raw)
        except asyncio.QueueFull:
            self.overflowed = True


class ConnectionManager:
    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._subs: dict[str, set[Connection]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None

    # ---------------------------------------------------------------- registry

    def subscribe(self, conn: Connection, rfq_id: str) -> None:
        self._subs[rfq_id].add(conn)
        conn.rfq_ids.add(rfq_id)

    def unsubscribe(self, conn: Connection, rfq_id: str) -> None:
        self._subs.get(rfq_id, set()).discard(conn)
        if not self._subs.get(rfq_id):
            self._subs.pop(rfq_id, None)
        conn.rfq_ids.discard(rfq_id)

    def remove(self, conn: Connection) -> None:
        for rfq_id in list(conn.rfq_ids):
            self.unsubscribe(conn, rfq_id)

    def dispatch(self, rfq_id: str, raw: str) -> int:
        targets = list(self._subs.get(rfq_id, ()))
        for conn in targets:
            conn.offer(raw)
        return len(targets)

    # ---------------------------------------------------------------- redis listener

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen(), name="realtime-listener")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _listen(self) -> None:
        backoff = 1.0
        while True:
            # Dedicated connection without a read timeout: pub/sub sits idle legitimately.
            redis = Redis.from_url(self.redis_url, decode_responses=True, health_check_interval=30)
            try:
                async with redis.pubsub() as pubsub:
                    await pubsub.psubscribe(CHANNEL_PATTERN)
                    log.info("realtime_listener_subscribed", pattern=CHANNEL_PATTERN)
                    backoff = 1.0
                    async for message in pubsub.listen():
                        if message.get("type") != "pmessage":
                            continue
                        rfq_id = str(message["channel"]).removeprefix(CHANNEL_PREFIX)
                        self.dispatch(rfq_id, str(message["data"]))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("realtime_listener_error", error=type(exc).__name__, retry_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                await redis.aclose()
