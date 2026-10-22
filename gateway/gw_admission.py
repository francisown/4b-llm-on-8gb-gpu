"""Admission control and in-process rate limiting."""

from __future__ import annotations

import asyncio
from collections import deque
import logging
import math
import time
from typing import Any

from fastapi import HTTPException

from gw_runtime import (
    ACTIVE_REQUESTS,
    QUEUE_WAIT_SECONDS,
    REJECTIONS_TOTAL,
    WAITING_REQUESTS,
    log_event,
)

class AdmissionLease:
    def __init__(
        self,
        controller: "AdmissionController",
        queue_wait_ms: float,
    ) -> None:
        self.controller = controller
        self.queue_wait_ms = queue_wait_ms
        self.released = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            async with self.controller.lock:
                self.controller.active -= 1
                self.controller.pending -= 1
                self.controller.update_gauges()
        finally:
            self.controller.semaphore.release()


class AdmissionController:
    """Bound active work and queued work before requests reach vLLM."""

    def __init__(self, max_concurrent: int, max_queue: int, queue_timeout: float):
        if max_concurrent < 1 or max_queue < 0 or queue_timeout <= 0:
            raise ValueError("invalid gateway admission settings")
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self.queue_timeout = queue_timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.lock = asyncio.Lock()
        self.pending = 0
        self.active = 0

    def update_gauges(self) -> None:
        ACTIVE_REQUESTS.set(self.active)
        WAITING_REQUESTS.set(self.pending - self.active)

    async def acquire(self, request_id: str) -> AdmissionLease:
        wait_started = time.perf_counter()
        async with self.lock:
            if self.pending >= self.max_concurrent + self.max_queue:
                REJECTIONS_TOTAL.labels(reason="capacity").inc()
                log_event(
                    logging.WARNING,
                    "request_rejected",
                    request_id=request_id,
                    status_code=429,
                    outcome="rejected",
                    reason="capacity",
                    queue_wait_ms=0.0,
                )
                raise HTTPException(
                    status_code=429,
                    detail="gateway is busy; retry later",
                    headers={"Retry-After": "2"},
                )
            self.pending += 1
            self.update_gauges()

        acquired = False
        try:
            await asyncio.wait_for(
                self.semaphore.acquire(),
                timeout=self.queue_timeout,
            )
            acquired = True
        except asyncio.TimeoutError as exc:
            async with self.lock:
                self.pending -= 1
                self.update_gauges()
            REJECTIONS_TOTAL.labels(reason="queue_timeout").inc()
            queue_wait_ms = (time.perf_counter() - wait_started) * 1_000
            log_event(
                logging.WARNING,
                "request_rejected",
                request_id=request_id,
                status_code=429,
                outcome="rejected",
                reason="queue_timeout",
                queue_wait_ms=round(queue_wait_ms, 1),
            )
            raise HTTPException(
                status_code=429,
                detail="gateway queue wait timed out",
                headers={"Retry-After": "2"},
            ) from exc
        except BaseException:
            if acquired:
                self.semaphore.release()
            async with self.lock:
                self.pending -= 1
                self.update_gauges()
            raise

        try:
            async with self.lock:
                self.active += 1
                self.update_gauges()
        except BaseException:
            self.semaphore.release()
            async with self.lock:
                self.pending -= 1
                self.update_gauges()
            raise
        queue_wait_seconds = time.perf_counter() - wait_started
        QUEUE_WAIT_SECONDS.observe(queue_wait_seconds)
        return AdmissionLease(self, queue_wait_ms=queue_wait_seconds * 1_000)

    async def snapshot(self) -> dict[str, int | float]:
        async with self.lock:
            return {
                "active": self.active,
                "waiting": self.pending - self.active,
                "max_concurrent": self.max_concurrent,
                "max_queue": self.max_queue,
                "queue_timeout_seconds": self.queue_timeout,
            }


class RateLimiter:
    """Per-identity sliding-window limit, kept in process memory.

    This is intentionally a single-process limiter. With N replicas the
    effective global limit is roughly N x the configured limit. The identity
    map is bounded; once it is full, new identities share one overflow bucket
    instead of growing memory without bound.
    """

    def __init__(
        self,
        limit_per_minute: int,
        max_identities: int = 10_000,
        clock: Any = time.monotonic,
    ):
        self.limit = max(0, limit_per_minute)
        self.window_seconds = 60.0
        self.max_identities = max(1, max_identities)
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for identity, events in list(self._events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                del self._events[identity]
        self._last_cleanup = now

    async def check(self, identity: str) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0
        now = self._clock()
        async with self._lock:
            if now - self._last_cleanup >= self.window_seconds:
                self._prune(now)
            events = self._events.get(identity)
            if events is None:
                if len(self._events) >= self.max_identities:
                    identity = "__overflow__"
                    events = self._events.get(identity)
                if events is None:
                    events = deque()
                    self._events[identity] = events
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, math.ceil(self.window_seconds - (now - events[0])))
                return False, retry_after
            events.append(now)
            return True, 0
