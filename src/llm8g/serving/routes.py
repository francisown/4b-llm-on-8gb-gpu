"""HTTP routes for the serving adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import logging
import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.background import BackgroundTask

from .dependencies import authorize
from .errors import ServingError
from .logging import log_event
from .models import TokenUsage
from .schemas import ChatRequestBody, ChatResponseBody
from .transport import (
    STATIC_DIR,
    close_on_disconnect,
    error_headers,
    event_bytes,
    log_rejection,
    metric_outcome,
    request_id as make_request_id,
    status_for_error,
)

router = APIRouter()


@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/live")
async def live(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {"status": "ok", "pod": settings.pod_name, "version": settings.version}


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {"status": "ready", "pod": settings.pod_name, "version": settings.version}


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    metrics = request.app.state.metrics
    failure: str | None = None
    try:
        healthy = await request.app.state.backend.health()
    except Exception as exc:
        healthy = False
        failure = type(exc).__name__
    metrics.upstream_healthy.set(1 if healthy else 0)
    if not healthy:
        log_event(
            logging.WARNING,
            "health_check_failed",
            status_code=503,
            outcome="unhealthy",
            error_type=failure or "UpstreamUnhealthy",
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "vllm": "unreachable",
                "pod": settings.pod_name,
            },
        )
    return JSONResponse(
        content={
            "status": "ok",
            "vllm": "ok",
            "pod": settings.pod_name,
            "version": settings.version,
        }
    )


@router.get("/gateway/status")
async def status(request: Request) -> dict[str, int | float | str]:
    settings = request.app.state.settings
    snapshot = await request.app.state.admission.snapshot()
    return {**snapshot, "pod": settings.pod_name, "version": settings.version}


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    return Response(
        generate_latest(request.app.state.metrics.registry),
        media_type=CONTENT_TYPE_LATEST,
    )


@router.post("/chat", response_model=ChatResponseBody, dependencies=[Depends(authorize)])
async def chat(
    body: ChatRequestBody,
    request: Request,
    response: Response,
    x_request_id: str | None = Header(default=None),
) -> ChatResponseBody:
    metrics = request.app.state.metrics
    request_id = make_request_id(x_request_id)
    started = time.perf_counter()
    try:
        result = await request.app.state.service.complete(
            body.to_core(),
            request_id=request_id,
        )
    except ServingError as exc:
        status_code, reason, detail = status_for_error(exc)
        metrics.rejections_total.labels(reason=reason).inc()
        log_rejection(
            request_id=request_id,
            mode="non_stream",
            status_code=status_code,
            reason=reason,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status_code,
            detail=detail,
            headers=error_headers(exc),
        ) from exc
    except httpx.HTTPError as exc:
        metrics.rejections_total.labels(reason="upstream_error").inc()
        log_rejection(
            request_id=request_id,
            mode="non_stream",
            status_code=502,
            reason="upstream_error",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="vLLM connection failed") from exc

    latency_ms = (time.perf_counter() - started) * 1_000
    metrics.requests_total.labels(mode="non_stream", outcome="success").inc()
    metrics.request_duration_seconds.labels(mode="non_stream").observe(latency_ms / 1_000)
    metrics.queue_wait_seconds.observe(result.queue_wait_ms / 1_000)
    metrics.tokens_total.labels(direction="prompt").inc(result.usage.prompt_tokens)
    metrics.tokens_total.labels(direction="completion").inc(result.usage.completion_tokens)
    log_event(
        logging.INFO,
        "request_complete",
        request_id=request_id,
        mode="non_stream",
        model=result.model,
        status_code=200,
        outcome="success",
        queue_wait_ms=round(result.queue_wait_ms, 1),
        latency_ms=round(latency_ms, 1),
    )
    response.headers["X-Request-ID"] = request_id
    return ChatResponseBody.from_core(result)


@router.post("/chat/stream", dependencies=[Depends(authorize)])
async def chat_stream(
    body: ChatRequestBody,
    request: Request,
    x_request_id: str | None = Header(default=None),
) -> StreamingResponse:
    settings = request.app.state.settings
    metrics = request.app.state.metrics
    request_id = make_request_id(x_request_id)
    try:
        lease, stream = await request.app.state.service.open_stream(
            body.to_core(),
            request_id=request_id,
        )
    except ServingError as exc:
        status_code, reason, detail = status_for_error(exc)
        metrics.rejections_total.labels(reason=reason).inc()
        metrics.requests_total.labels(
            mode="stream",
            outcome=metric_outcome(exc),
        ).inc()
        log_rejection(
            request_id=request_id,
            mode="stream",
            status_code=status_code,
            reason=reason,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status_code,
            detail=detail,
            headers=error_headers(exc),
        ) from exc
    except httpx.HTTPError as exc:
        metrics.rejections_total.labels(reason="upstream_error").inc()
        raise HTTPException(status_code=502, detail="vLLM connection failed") from exc

    async def events() -> AsyncIterator[bytes]:
        started = time.perf_counter()
        first_token_ms: float | None = None
        usage = TokenUsage()
        completed = False
        disconnect_task = asyncio.create_task(close_on_disconnect(request, stream))
        try:
            async for event in stream:
                if await request.is_disconnected():
                    metrics.client_disconnects_total.inc()
                    metrics.requests_total.labels(mode="stream", outcome="disconnected").inc()
                    log_event(
                        logging.INFO,
                        "client_disconnected",
                        request_id=request_id,
                        mode="stream",
                        model=settings.model,
                        outcome="disconnected",
                        queue_wait_ms=round(lease.queue_wait_ms, 1),
                        latency_ms=round(
                            (time.perf_counter() - started) * 1_000, 1
                        ),
                    )
                    return
                if event.kind == "usage":
                    usage = TokenUsage.from_mapping(event.payload)
                    continue
                if event.kind == "token":
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - started) * 1_000
                        metrics.ttft_seconds.observe(first_token_ms / 1_000)
                    yield event_bytes("token", event.payload)
                    continue
                if event.kind == "done":
                    completed = True
                    latency_ms = (time.perf_counter() - started) * 1_000
                    payload = dict(event.payload)
                    payload["ttft_ms"] = round(first_token_ms or latency_ms, 1)
                    payload["latency_ms"] = round(latency_ms, 1)
                    metrics.requests_total.labels(mode="stream", outcome="success").inc()
                    metrics.request_duration_seconds.labels(mode="stream").observe(
                        latency_ms / 1_000
                    )
                    metrics.queue_wait_seconds.observe(lease.queue_wait_ms / 1_000)
                    metrics.tokens_total.labels(direction="prompt").inc(
                        usage.prompt_tokens
                    )
                    metrics.tokens_total.labels(direction="completion").inc(
                        usage.completion_tokens
                    )
                    log_event(
                        logging.INFO,
                        "stream_complete",
                        request_id=request_id,
                        mode="stream",
                        model=settings.model,
                        status_code=200,
                        outcome="success",
                        queue_wait_ms=round(lease.queue_wait_ms, 1),
                        ttft_ms=round(first_token_ms or latency_ms, 1),
                        latency_ms=round(latency_ms, 1),
                    )
                    yield event_bytes("done", payload)
                    continue
                yield event_bytes(event.kind, event.payload)
            if not completed:
                latency_ms = (time.perf_counter() - started) * 1_000
                metrics.requests_total.labels(mode="stream", outcome="incomplete").inc()
                log_event(
                    logging.WARNING,
                    "stream_incomplete",
                    request_id=request_id,
                    mode="stream",
                    model=settings.model,
                    status_code=200,
                    outcome="incomplete",
                    queue_wait_ms=round(lease.queue_wait_ms, 1),
                    latency_ms=round(latency_ms, 1),
                    error_type="MissingDoneSentinel",
                )
        except asyncio.CancelledError:
            metrics.client_disconnects_total.inc()
            metrics.requests_total.labels(mode="stream", outcome="disconnected").inc()
            raise
        except (ServingError, httpx.HTTPError) as exc:
            status_code, reason, detail = (
                status_for_error(exc)
                if isinstance(exc, ServingError)
                else (502, "upstream_error", "vLLM connection failed")
            )
            outcome = (
                metric_outcome(exc)
                if isinstance(exc, ServingError)
                else "upstream_error"
            )
            metrics.requests_total.labels(mode="stream", outcome=outcome).inc()
            log_event(
                logging.WARNING,
                "stream_failed",
                request_id=request_id,
                mode="stream",
                model=settings.model,
                status_code=status_code,
                outcome=outcome,
                queue_wait_ms=round(lease.queue_wait_ms, 1),
                ttft_ms=round(first_token_ms, 1) if first_token_ms else None,
                latency_ms=round((time.perf_counter() - started) * 1_000, 1),
                error_type=type(exc).__name__,
            )
            yield event_bytes("error", {"message": detail})
        finally:
            disconnect_task.cancel()
            try:
                await disconnect_task
            except asyncio.CancelledError:
                pass
            close = getattr(stream, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

    async def cleanup() -> None:
        close = getattr(stream, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass
        await lease.release()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        background=BackgroundTask(cleanup),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )
