from fastapi import Request
from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        str(settings.redis_url),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


async def ping_redis(redis: Redis) -> None:
    await redis.ping()
