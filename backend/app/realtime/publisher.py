"""Fan-out of auction updates to every API process via Redis pub/sub.

Publishing happens *after* the database commit and is best-effort: if Redis is down the
bid still succeeds, and clients recover through their periodic/reconnect refetch.
(A transactional outbox would make delivery guaranteed — listed as a known limitation.)
"""

import json
from typing import Any, Protocol

from redis.asyncio import Redis

from app.core.logging import get_logger

log = get_logger(__name__)

CHANNEL_PREFIX = "auction:"
CHANNEL_PATTERN = f"{CHANNEL_PREFIX}*"


def channel_for(rfq_id: str) -> str:
    return f"{CHANNEL_PREFIX}{rfq_id}"


class EventPublisher(Protocol):
    async def publish(self, message: dict[str, Any]) -> None: ...


class RedisPublisher:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(self, message: dict[str, Any]) -> None:
        try:
            await self.redis.publish(channel_for(message["rfq_id"]), json.dumps(message))
        except Exception as exc:  # never fail the caller's (already committed) work
            log.warning(
                "realtime_publish_failed", rfq_id=message.get("rfq_id"), error=type(exc).__name__
            )


class MemoryPublisher:
    """Test double: records every published message."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def publish(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


class NullPublisher:
    async def publish(self, message: dict[str, Any]) -> None:
        return None
