"""Optional Redis-backed limiter for multi-replica deployments.

The default limiter is process-local and intentionally cheap. When the gateway
runs behind more than one replica, set ``GATEWAY_RATE_LIMIT_BACKEND=redis`` and
point ``GATEWAY_REDIS_URL`` at a shared Redis. This implementation uses a
fixed 60-second window (`INCR` + `EXPIRE`), which is easy to operate and is
accurate enough for admission/abuse protection. It is not a replacement for a
per-tenant quota system.
"""

from __future__ import annotations

import hashlib
from typing import Any


class RedisRateLimiter:
    def __init__(
        self,
        limit_per_minute: int,
        client: Any,
        *,
        window_seconds: int = 60,
    ) -> None:
        self.limit = max(0, limit_per_minute)
        self.client = client
        self.window_seconds = max(1, window_seconds)

    async def check(self, identity: str) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        key = f"gateway:rate:{digest}"
        count = int(await self.client.incr(key))
        if count == 1:
            await self.client.expire(key, self.window_seconds)
        if count > self.limit:
            ttl = int(await self.client.ttl(key) or 0)
            return False, max(1, ttl if ttl > 0 else self.window_seconds)
        return True, 0

    async def close(self) -> None:
        await self.client.aclose()
