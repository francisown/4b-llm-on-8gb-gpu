"""Small, replaceable rate-limit adapters."""

from __future__ import annotations

import asyncio
from collections import deque
import math
import time
from typing import Callable


class SlidingWindowLimiter:
    """A bounded process-local sliding-window limiter.

    The interface is intentionally the same shape a Redis adapter can satisfy:
    callers only need ``check(identity)`` and do not know where state lives.
    """

    def __init__(
        self,
        limit_per_minute: int,
        *,
        max_identities: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit_per_minute < 0 or max_identities < 1:
            raise ValueError("invalid limiter settings")
        self.limit = limit_per_minute
        self.max_identities = max_identities
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - 60.0
        for identity, events in list(self._events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                del self._events[identity]

    async def check(self, identity: str) -> tuple[bool, int]:
        if self.limit == 0:
            return True, 0
        now = self._clock()
        async with self._lock:
            # Full-map cleanup is O(number of identities). Running it on every
            # request turns a cheap limiter into a scaling bottleneck, so keep
            # the same periodic cleanup strategy as the historical gateway.
            if now - self._last_cleanup >= 60.0:
                self._prune(now)
            events = self._events.get(identity)
            if events is None:
                if len(self._events) >= self.max_identities:
                    identity = "__overflow__"
                    events = self._events.get(identity)
                if events is None:
                    events = deque()
                    self._events[identity] = events
            while events and events[0] <= now - 60.0:
                events.popleft()
            if len(events) >= self.limit:
                return False, max(1, math.ceil(60.0 - (now - events[0])))
            events.append(now)
            return True, 0

