"""A small production-facing gateway in front of a local vLLM server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import sys
import time
import uuid
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field


VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen3.5-4B-INT4-AWQ-self")
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "60"))
MAX_CONCURRENT_REQUESTS = int(os.getenv("GATEWAY_MAX_CONCURRENT", "4"))
MAX_QUEUED_REQUESTS = int(os.getenv("GATEWAY_MAX_QUEUE", "4"))
QUEUE_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_QUEUE_TIMEOUT_SECONDS", "10"))
APP_DIR = Path(__file__).resolve().parent

LOG_FIELDS = (
    "request_id",
    "mode",
    "model",
    "status_code",
    "outcome",
    "reason",
    "queue_wait_ms",
    "ttft_ms",
    "latency_ms",
    "error_type",
)


class JsonLogFormatter(logging.Formatter):
    """Render application events as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }
        for field in LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logger() -> logging.Logger:
    application_logger = logging.getLogger("inference-gateway")
    application_logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    application_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    application_logger.addHandler(handler)
    application_logger.propagate = False
    return application_logger


logger = configure_logger()


def log_event(level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"event": event, **fields})

REQUESTS_TOTAL = Counter(
    "inference_gateway_requests_total",
    "Completed gateway requests by mode and outcome.",
    ("mode", "outcome"),
)
REJECTIONS_TOTAL = Counter(
    "inference_gateway_rejections_total",
    "Requests rejected before reaching vLLM.",
    ("reason",),
)
ACTIVE_REQUESTS = Gauge(
    "inference_gateway_active_requests",
    "Requests currently admitted to vLLM.",
)
WAITING_REQUESTS = Gauge(
    "inference_gateway_waiting_requests",
    "Requests waiting for an admission slot.",
)
QUEUE_WAIT_SECONDS = Histogram(
    "inference_gateway_queue_wait_seconds",
    "Time spent waiting for an admission slot.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
REQUEST_DURATION_SECONDS = Histogram(
    "inference_gateway_request_duration_seconds",
    "End-to-end gateway request duration.",
    ("mode",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
TTFT_SECONDS = Histogram(
    "inference_gateway_ttft_seconds",
    "Time to first streamed token.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
TOKENS_TOTAL = Counter(
    "inference_gateway_tokens_total",
    "Tokens processed by successful gateway requests.",
    ("direction",),
)
CLIENT_DISCONNECTS_TOTAL = Counter(
    "inference_gateway_client_disconnects_total",
    "Streaming clients that disconnected before completion.",
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    system_prompt: str | None = Field(default=None, max_length=10_000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
    max_tokens: int = Field(default=256, ge=1, le=2_048)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    enable_thinking: bool = False


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatResponse(BaseModel):
    request_id: str
    model: str
    answer: str
    usage: TokenUsage
    latency_ms: float


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
        self.controller.semaphore.release()
        async with self.controller.lock:
            self.controller.active -= 1
            self.controller.pending -= 1
            self.controller.update_gauges()


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

        try:
            await asyncio.wait_for(
                self.semaphore.acquire(),
                timeout=self.queue_timeout,
            )
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
            async with self.lock:
                self.pending -= 1
                self.update_gauges()
            raise

        async with self.lock:
            self.active += 1
            self.update_gauges()
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


def build_payload(body: ChatRequest, *, stream: bool) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if body.system_prompt:
        messages.append({"role": "system", "content": body.system_prompt})
    messages.extend(message.model_dump() for message in body.history)
    messages.append({"role": "user", "content": body.message})
    payload: dict[str, Any] = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": body.max_tokens,
        "temperature": body.temperature,
        "stream": stream,
        "chat_template_kwargs": {"enable_thinking": body.enable_thinking},
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def parse_usage(raw_usage: dict[str, Any] | None) -> TokenUsage:
    raw_usage = raw_usage or {}
    return TokenUsage(
        prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
        completion_tokens=int(raw_usage.get("completion_tokens") or 0),
        total_tokens=int(raw_usage.get("total_tokens") or 0),
    )


def normalize_unicode(text: str) -> str:
    """Replace isolated surrogates before encoding an SSE event as UTF-8."""
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def sse_event(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = httpx.Timeout(
        connect=2.0,
        read=UPSTREAM_TIMEOUT_SECONDS,
        write=10.0,
        pool=5.0,
    )
    app.state.http = httpx.AsyncClient(timeout=timeout)
    app.state.admission = AdmissionController(
        MAX_CONCURRENT_REQUESTS,
        MAX_QUEUED_REQUESTS,
        QUEUE_TIMEOUT_SECONDS,
    )
    yield
    await app.state.http.aclose()


app = FastAPI(
    title="AI Inference Gateway",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(APP_DIR / "index.html")


@app.get("/live")
async def live() -> dict[str, str]:
    """Liveness: this process is running, independent of the model server."""
    return {"status": "ok"}


@app.get("/health")
async def health() -> JSONResponse:
    """The gateway is healthy only when its vLLM upstream is reachable."""
    try:
        response = await app.state.http.get(f"{VLLM_BASE_URL}/health")
        response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        log_event(
            logging.WARNING,
            "health_check_failed",
            status_code=503,
            outcome="unhealthy",
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "vllm": "unreachable", "error": str(exc)},
        )
    return JSONResponse(content={"status": "ok", "vllm": "ok"})


@app.get("/gateway/status")
async def gateway_status() -> dict[str, int | float]:
    return await app.state.admission.snapshot()


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    x_request_id: str | None = Header(default=None),
) -> ChatResponse:
    request_id = x_request_id or str(uuid.uuid4())
    payload = build_payload(body, stream=False)
    started = time.perf_counter()
    try:
        lease = await app.state.admission.acquire(request_id)
    except HTTPException:
        REQUESTS_TOTAL.labels(mode="non_stream", outcome="rejected").inc()
        raise
    try:
        try:
            upstream = await app.state.http.post(
                f"{VLLM_BASE_URL}/v1/chat/completions",
                json=payload,
                headers={"X-Request-ID": request_id},
            )
        except httpx.TimeoutException as exc:
            REQUESTS_TOTAL.labels(mode="non_stream", outcome="timeout").inc()
            log_event(
                logging.WARNING,
                "request_failed",
                request_id=request_id,
                mode="non_stream",
                model=MODEL_NAME,
                status_code=504,
                outcome="timeout",
                queue_wait_ms=round(lease.queue_wait_ms, 1),
                latency_ms=round((time.perf_counter() - started) * 1_000, 1),
                error_type=type(exc).__name__,
            )
            raise HTTPException(status_code=504, detail="vLLM request timed out") from exc
        except httpx.ConnectError as exc:
            REQUESTS_TOTAL.labels(mode="non_stream", outcome="unavailable").inc()
            log_event(
                logging.WARNING,
                "request_failed",
                request_id=request_id,
                mode="non_stream",
                model=MODEL_NAME,
                status_code=503,
                outcome="unavailable",
                queue_wait_ms=round(lease.queue_wait_ms, 1),
                latency_ms=round((time.perf_counter() - started) * 1_000, 1),
                error_type=type(exc).__name__,
            )
            raise HTTPException(status_code=503, detail="vLLM is unavailable") from exc
    finally:
        await lease.release()

    if upstream.is_error:
        REQUESTS_TOTAL.labels(mode="non_stream", outcome="upstream_error").inc()
        detail = upstream.text[:1_000]
        log_event(
            logging.WARNING,
            "request_failed",
            request_id=request_id,
            mode="non_stream",
            model=MODEL_NAME,
            status_code=upstream.status_code,
            outcome="upstream_error",
            queue_wait_ms=round(lease.queue_wait_ms, 1),
            latency_ms=round((time.perf_counter() - started) * 1_000, 1),
            error_type="UpstreamHTTPError",
        )
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    data = upstream.json()
    usage = parse_usage(data.get("usage"))
    latency_ms = (time.perf_counter() - started) * 1_000
    REQUESTS_TOTAL.labels(mode="non_stream", outcome="success").inc()
    REQUEST_DURATION_SECONDS.labels(mode="non_stream").observe(latency_ms / 1_000)
    TOKENS_TOTAL.labels(direction="prompt").inc(usage.prompt_tokens)
    TOKENS_TOTAL.labels(direction="completion").inc(usage.completion_tokens)
    log_event(
        logging.INFO,
        "request_complete",
        request_id=request_id,
        mode="non_stream",
        model=MODEL_NAME,
        status_code=upstream.status_code,
        outcome="success",
        queue_wait_ms=round(lease.queue_wait_ms, 1),
        latency_ms=round(latency_ms, 1),
    )
    return ChatResponse(
        request_id=request_id,
        model=data.get("model", MODEL_NAME),
        answer=data["choices"][0]["message"]["content"],
        usage=usage,
        latency_ms=round(latency_ms, 1),
    )


@app.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    x_request_id: str | None = Header(default=None),
) -> StreamingResponse:
    request_id = x_request_id or str(uuid.uuid4())
    payload = build_payload(body, stream=True)
    started = time.perf_counter()
    try:
        lease = await app.state.admission.acquire(request_id)
    except HTTPException:
        REQUESTS_TOTAL.labels(mode="stream", outcome="rejected").inc()
        raise
    upstream_request = app.state.http.build_request(
        "POST",
        f"{VLLM_BASE_URL}/v1/chat/completions",
        json=payload,
        headers={"X-Request-ID": request_id},
    )
    try:
        upstream = await app.state.http.send(upstream_request, stream=True)
    except httpx.TimeoutException as exc:
        await lease.release()
        REQUESTS_TOTAL.labels(mode="stream", outcome="timeout").inc()
        log_event(
            logging.WARNING,
            "request_failed",
            request_id=request_id,
            mode="stream",
            model=MODEL_NAME,
            status_code=504,
            outcome="timeout",
            queue_wait_ms=round(lease.queue_wait_ms, 1),
            latency_ms=round((time.perf_counter() - started) * 1_000, 1),
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=504, detail="vLLM request timed out") from exc
    except httpx.ConnectError as exc:
        await lease.release()
        REQUESTS_TOTAL.labels(mode="stream", outcome="unavailable").inc()
        log_event(
            logging.WARNING,
            "request_failed",
            request_id=request_id,
            mode="stream",
            model=MODEL_NAME,
            status_code=503,
            outcome="unavailable",
            queue_wait_ms=round(lease.queue_wait_ms, 1),
            latency_ms=round((time.perf_counter() - started) * 1_000, 1),
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="vLLM is unavailable") from exc
    except BaseException:
        await lease.release()
        raise

    if upstream.is_error:
        detail = (await upstream.aread()).decode("utf-8", "replace")[:1_000]
        await upstream.aclose()
        await lease.release()
        REQUESTS_TOTAL.labels(mode="stream", outcome="upstream_error").inc()
        log_event(
            logging.WARNING,
            "request_failed",
            request_id=request_id,
            mode="stream",
            model=MODEL_NAME,
            status_code=upstream.status_code,
            outcome="upstream_error",
            queue_wait_ms=round(lease.queue_wait_ms, 1),
            latency_ms=round((time.perf_counter() - started) * 1_000, 1),
            error_type="UpstreamHTTPError",
        )
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    async def events() -> AsyncIterator[bytes]:
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        first_token_ms: float | None = None
        completed = False
        yield sse_event("meta", {"request_id": request_id, "model": MODEL_NAME})
        try:
            async for line in upstream.aiter_lines():
                if await request.is_disconnected():
                    CLIENT_DISCONNECTS_TOTAL.inc()
                    REQUESTS_TOTAL.labels(mode="stream", outcome="disconnected").inc()
                    log_event(
                        logging.INFO,
                        "client_disconnected",
                        request_id=request_id,
                        mode="stream",
                        model=MODEL_NAME,
                        outcome="disconnected",
                        queue_wait_ms=round(lease.queue_wait_ms, 1),
                        latency_ms=round(
                            (time.perf_counter() - started) * 1_000, 1
                        ),
                    )
                    return
                if not line.startswith("data:"):
                    continue
                raw_data = line[5:].strip()
                if raw_data == "[DONE]":
                    completed = True
                    break
                chunk = json.loads(raw_data)
                if chunk.get("usage"):
                    usage = parse_usage(chunk["usage"])
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                for field, channel in (
                    ("reasoning_content", "reasoning"),
                    ("content", "answer"),
                ):
                    text = delta.get(field)
                    if not text:
                        continue
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - started) * 1_000
                        TTFT_SECONDS.observe(first_token_ms / 1_000)
                    yield sse_event(
                        "token",
                        {"text": normalize_unicode(text), "channel": channel},
                    )
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            REQUESTS_TOTAL.labels(mode="stream", outcome="stream_error").inc()
            log_event(
                logging.WARNING,
                "stream_failed",
                request_id=request_id,
                mode="stream",
                model=MODEL_NAME,
                outcome="stream_error",
                queue_wait_ms=round(lease.queue_wait_ms, 1),
                ttft_ms=round(first_token_ms, 1) if first_token_ms else None,
                latency_ms=round((time.perf_counter() - started) * 1_000, 1),
                error_type=type(exc).__name__,
            )
            yield sse_event("error", {"message": str(exc)})
            return
        except asyncio.CancelledError:
            CLIENT_DISCONNECTS_TOTAL.inc()
            REQUESTS_TOTAL.labels(mode="stream", outcome="disconnected").inc()
            log_event(
                logging.INFO,
                "client_disconnected",
                request_id=request_id,
                mode="stream",
                model=MODEL_NAME,
                outcome="disconnected",
                queue_wait_ms=round(lease.queue_wait_ms, 1),
                ttft_ms=round(first_token_ms, 1) if first_token_ms else None,
                latency_ms=round((time.perf_counter() - started) * 1_000, 1),
            )
            raise
        finally:
            await upstream.aclose()
            await lease.release()

        if completed:
            latency_ms = (time.perf_counter() - started) * 1_000
            REQUESTS_TOTAL.labels(mode="stream", outcome="success").inc()
            REQUEST_DURATION_SECONDS.labels(mode="stream").observe(latency_ms / 1_000)
            TOKENS_TOTAL.labels(direction="prompt").inc(usage.prompt_tokens)
            TOKENS_TOTAL.labels(direction="completion").inc(usage.completion_tokens)
            log_event(
                logging.INFO,
                "stream_complete",
                request_id=request_id,
                mode="stream",
                model=MODEL_NAME,
                status_code=200,
                outcome="success",
                queue_wait_ms=round(lease.queue_wait_ms, 1),
                ttft_ms=round(first_token_ms or latency_ms, 1),
                latency_ms=round(latency_ms, 1),
            )
            yield sse_event(
                "done",
                {
                    "request_id": request_id,
                    "usage": usage.model_dump(),
                    "ttft_ms": round(first_token_ms or latency_ms, 1),
                    "latency_ms": round(latency_ms, 1),
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )
