"""Redis rate limiting (fixed window, atomic via a Lua script).

Fails open: if Redis is unavailable, requests are allowed and a warning is logged.
Availability of bidding matters more than throttling during an outage.
"""

import math
from dataclasses import dataclass

from fastapi import Request
from redis.asyncio import Redis

from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger(__name__)

# INCR the window counter; start the window's expiry on the first hit.
_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return {current, redis.call('PTTL', KEYS[1])}
"""


@dataclass(frozen=True, slots=True)
class Limit:
    name: str
    max_requests: int
    window_seconds: int


# Tuned for humans and honest clients; each comfortably above normal use.
LOGIN_PER_IP = Limit("login-ip", 30, 60)
LOGIN_PER_ACCOUNT = Limit("login-account", 10, 300)  # slows password guessing on one email
REGISTER_PER_IP = Limit("register-ip", 10, 3600)
INVITE_TOKEN_PER_IP = Limit("invite-token-ip", 20, 60)  # inspect / accept sign-up links
REFRESH_PER_IP = Limit("refresh-ip", 60, 60)
BIDS_PER_SUPPLIER_RFQ = Limit("bid", 30, 60)  # one bid every 2 s on average, bursts allowed
INVITES_PER_BUYER = Limit("invite-send", 200, 3600)  # caps outbound email volume


class RateLimitedError(AppError):
    status_code = 429
    code = "RATE_LIMITED"

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "Too many requests. Please slow down and try again shortly.",
            extra={"retry_after": retry_after},
        )
        self.headers = {"Retry-After": str(retry_after)}


class RateLimiter:
    def __init__(self, redis: Redis | None, *, enabled: bool = True, prefix: str = "rl") -> None:
        self.enabled = enabled and redis is not None
        self.prefix = prefix
        self._script = redis.register_script(_LUA) if redis is not None else None

    async def check(self, limit: Limit, key: str) -> None:
        """Count one request against `limit` for `key`; raise 429 when over."""
        if not self.enabled or self._script is None:
            return
        redis_key = f"{self.prefix}:{limit.name}:{key}"
        try:
            count, ttl_ms = await self._script(keys=[redis_key], args=[limit.window_seconds * 1000])
        except Exception as exc:
            log.warning("rate_limit_unavailable", limit=limit.name, error=type(exc).__name__)
            return
        if int(count) > limit.max_requests:
            retry_after = max(1, math.ceil(int(ttl_ms) / 1000))
            log.info("rate_limited", limit=limit.name, retry_after=retry_after)
            raise RateLimitedError(retry_after)


def client_ip(request: Request) -> str:
    """Behind Nginx, uvicorn runs with --proxy-headers so this is the real client IP."""
    return request.client.host if request.client else "unknown"


async def enforce(request: Request, limit: Limit, key: str) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    await limiter.check(limit, key)
