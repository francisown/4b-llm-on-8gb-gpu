"""The deep serving module.

``GatewayService`` is the seam between HTTP and inference.  It owns request
validation, context admission, and lifecycle cleanup; HTTP adapters only need
to translate their input/output format and map typed errors to status codes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import math
import time

from .admission import AdmissionController, AdmissionLease
from .config import GatewaySettings
from .errors import ContextLimitExceeded
from .models import ChatRequest, ChatResult, StreamEvent, TokenUsage
from .ports import InferenceBackend


def _is_cjk(code: int) -> bool:
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
    )


def estimate_tokens(text: str) -> int:
    cjk = sum(1 for character in text if _is_cjk(ord(character)))
    return cjk + math.ceil((len(text) - cjk) / 4)


class GatewayService:
    """Serve chat requests through one injected inference backend."""

    def __init__(
        self,
        settings: GatewaySettings,
        backend: InferenceBackend,
        admission: AdmissionController,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.admission = admission

    def validate_context(self, request: ChatRequest) -> None:
        prompt_tokens = sum(estimate_tokens(item["content"]) for item in request.messages()) + 16
        if prompt_tokens + request.max_tokens > self.settings.max_context_tokens:
            raise ContextLimitExceeded(
                f"request exceeds the configured context window: ~{prompt_tokens} prompt tokens "
                f"+ {request.max_tokens} output tokens > {self.settings.max_context_tokens}"
            )

    async def complete(self, request: ChatRequest, *, request_id: str) -> ChatResult:
        self.validate_context(request)
        lease = await self.admission.acquire()
        started = time.perf_counter()
        try:
            answer, usage, model = await self.backend.complete(request, request_id=request_id)
            return ChatResult(
                request_id=request_id,
                model=model,
                answer=answer,
                usage=usage,
                latency_ms=(time.perf_counter() - started) * 1_000,
                queue_wait_ms=lease.queue_wait_ms,
            )
        finally:
            await lease.release()

    async def stream(self, request: ChatRequest, *, request_id: str) -> AsyncIterator[StreamEvent]:
        self.validate_context(request)
        lease = await self.admission.acquire()
        async for event in self._stream_with_lease(request, request_id, lease):
            yield event

    async def open_stream(
        self,
        request: ChatRequest,
        *,
        request_id: str,
    ) -> tuple[AdmissionLease, AsyncIterator[StreamEvent]]:
        """Acquire before creating a response, so capacity failures stay HTTP 429."""
        self.validate_context(request)
        lease = await self.admission.acquire()
        try:
            backend_stream = await self.backend.open_stream(
                request,
                request_id=request_id,
            )
        except BaseException:
            await lease.release()
            raise
        return lease, self._stream_with_lease(
            request,
            request_id,
            lease,
            backend_stream,
        )

    async def _stream_with_lease(
        self,
        request: ChatRequest,
        request_id: str,
        lease: AdmissionLease,
        backend_stream: AsyncIterator[StreamEvent] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        usage = TokenUsage()
        try:
            yield StreamEvent("meta", {"request_id": request_id, "model": self.settings.model})
            source = (
                backend_stream
                if backend_stream is not None
                else self.backend.stream(request, request_id=request_id)
            )
            async for event in source:
                if event.kind == "usage":
                    usage = TokenUsage.from_mapping(event.payload)
                yield event
            yield StreamEvent(
                "done",
                {
                    "request_id": request_id,
                    "usage": {
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                    },
                },
            )
        finally:
            await lease.release()

