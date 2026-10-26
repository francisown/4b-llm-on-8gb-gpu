"""Ports used by the serving core.

Adapters such as vLLM-over-HTTP, a deterministic fake, or a future local
runtime implement these protocols.  The core never imports any of them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .models import ChatRequest, StreamEvent, TokenUsage


class RateLimiter(Protocol):
    async def check(self, identity: str) -> tuple[bool, int]:
        """Return whether the identity may proceed and a retry delay."""


class InferenceBackend(Protocol):
    async def start(self) -> None:
        """Initialize the backend and any owned transport resources."""

    async def close(self) -> None:
        """Release backend resources."""

    async def complete(
        self,
        request: ChatRequest,
        *,
        request_id: str,
    ) -> tuple[str, TokenUsage, str]:
        """Return answer text, usage and the backend model name."""

    def stream(self, request: ChatRequest, *, request_id: str) -> AsyncIterator[StreamEvent]:
        """Yield transport-neutral stream events."""

    async def open_stream(
        self,
        request: ChatRequest,
        *,
        request_id: str,
    ) -> AsyncIterator[StreamEvent]:
        """Open the upstream stream eagerly, before SSE headers are sent."""

    async def health(self) -> bool:
        """Return whether the backend is reachable."""

