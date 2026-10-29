"""Fixed-window rate limiting backed by Redis."""

import logging
from functools import lru_cache

import redis

from app.core.config import get_settings
from app.core.errors import AppError

log = logging.getLogger(__name__)


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


class RateLimiter:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    def hit(self, key: str, limit: int, window_s: int = 60) -> None:
        """Count one attempt; raise once `limit` is exceeded within the window.

        Fails open if Redis is unavailable: an outage must not lock every user out. The
        failure is logged, and readiness reports Redis as down.
        """
        full_key = f"rl:{key}"
        try:
            pipe = self.client.pipeline()
            pipe.incr(full_key)
            pipe.expire(full_key, window_s, nx=True)
            count = int(pipe.execute()[0])
        except redis.RedisError as exc:
            log.warning("rate_limit_unavailable", extra={"error_type": type(exc).__name__})
            return
        if count > limit:
            raise RateLimitedError("Too many attempts. Try again shortly.")


@lru_cache
def get_rate_limiter() -> RateLimiter:
    client = redis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
    )
    return RateLimiter(client)
