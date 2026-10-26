"""Admission control for bounded model-server work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import time

from .errors import AdmissionRejected


@dataclass(slots=True)
class AdmissionLease:
    _controller: "AdmissionController"
    queue_wait_ms: float
    _released: bool = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        async with self._controller._lock:
            self._controller._active -= 1
            self._controller._pending -= 1
            self._controller._notify()
        self._controller._semaphore.release()


class AdmissionController:
    """Bound active and waiting requests before they reach the model server."""

    def __init__(
        self,
        max_concurrent: int,
        max_queue: int,
        queue_timeout_seconds: float,
        *,
        observer: Callable[[int, int], None] | None = None,
    ) -> None:
        if max_concurrent < 1 or max_queue < 0 or queue_timeout_seconds <= 0:
            raise ValueError("invalid admission settings")
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self.queue_timeout_seconds = queue_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._pending = 0
        self._active = 0
        self._observer = observer

    @property
    def active(self) -> int:
        return self._active

    @property
    def pending(self) -> int:
        return self._pending

    def _notify(self) -> None:
        if self._observer is not None:
            self._observer(self._active, self._pending - self._active)

    async def acquire(self, request_id: str | None = None) -> AdmissionLease:
        del request_id
        started = time.perf_counter()
        async with self._lock:
            if self._pending >= self.max_concurrent + self.max_queue:
                raise AdmissionRejected("capacity")
            self._pending += 1
            self._notify()
        acquired = False
        try:
            await asyncio.wait_for(self._semaphore.acquire(), self.queue_timeout_seconds)
            acquired = True
        except asyncio.TimeoutError as exc:
            async with self._lock:
                self._pending -= 1
                self._notify()
            raise AdmissionRejected("queue_timeout") from exc
        except BaseException:
            async with self._lock:
                self._pending -= 1
                self._notify()
            raise
        try:
            async with self._lock:
                self._active += 1
                self._notify()
        except BaseException:
            if acquired:
                self._semaphore.release()
            async with self._lock:
                self._pending -= 1
                self._notify()
            raise
        return AdmissionLease(self, (time.perf_counter() - started) * 1_000)

    async def snapshot(self) -> dict[str, int | float]:
        async with self._lock:
            return {
                "active": self._active,
                "waiting": self._pending - self._active,
                "max_concurrent": self.max_concurrent,
                "max_queue": self.max_queue,
                "queue_timeout_seconds": self.queue_timeout_seconds,
            }

