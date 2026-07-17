"""Fixed-window rate limiting for sensitive endpoints (login, register).

Keyed by client IP + route, backed by Redis INCR/EXPIRE - cheap (one round
trip), and works correctly across multiple API replicas (unlike an in-memory
counter would). Fails open if Redis is briefly unavailable, so an auth
endpoint never goes down just because the rate limiter did.
"""
from fastapi import HTTPException, Request, status

from src.common.logging import get_logger
from src.common.redis_client import get_redis

logger = get_logger(__name__)


def rate_limiter(*, times: int, seconds: int, scope: str):
    """Returns a FastAPI dependency that allows `times` requests per
    `seconds` per client IP for the given `scope` (e.g. "login")."""

    async def _dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{scope}:{client_ip}"

        try:
            redis = await get_redis()
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, seconds)
        except Exception as exc:
            # Fail open: a Redis outage should not take down login/register.
            logger.warning("rate_limiter_unavailable", scope=scope, error=str(exc))
            return

        if current > times:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many {scope} attempts. Try again in a few minutes.",
            )

    return _dependency
