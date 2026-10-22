"""FastAPI gateway entrypoint.

Implementation is split into four sibling modules:

* ``gw_runtime``   - configuration, logging, metrics, request/response models
* ``gw_admission`` - admission control and the in-process rate limiter
* ``gw_auth``      - API-key authentication and client identity
* ``gw_upstream``  - request building, context guard, SSE helpers, error translation

``gateway.py`` keeps the app wiring and routes so ``uvicorn gateway:app`` and the
existing offline test suite continue to work unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import time
import uuid

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.background import BackgroundTask

from gw_admission import AdmissionController, RateLimiter
from gw_auth import enforce_rate_limit, require_api_key
from gw_runtime import (
    AUTH_FAILURE_LIMIT_PER_MINUTE,
    CLIENT_DISCONNECTS_TOTAL,
    GATEWAY_VERSION,
    HEALTH_TIMEOUT_SECONDS,
    MAX_CONCURRENT_REQUESTS,
    MAX_QUEUED_REQUESTS,
    MODEL_NAME,
    POD_NAME,
    QUEUE_TIMEOUT_SECONDS,
    RATE_LIMIT_BACKEND,
    RATE_LIMIT_MAX_IDENTITIES,
    RATE_LIMIT_PER_MINUTE,
    REDIS_URL,
    REQUEST_DURATION_SECONDS,
    REQUESTS_TOTAL,
    TOKENS_TOTAL,
    TTFT_SECONDS,
    UPSTREAM_HEALTHY,
    UPSTREAM_TIMEOUT_SECONDS,
    VLLM_BASE_URL,
    ChatRequest,
    ChatResponse,
    TokenUsage,
    log_event,
)
from gw_upstream import (
    build_payload,
    enforce_context_window,
    normalize_unicode,
    parse_usage,
    post_with_connect_retry,
    send_stream_with_connect_retry,
    sse_event,
    translate_upstream_error,
)

APP_DIR = Path(__file__).resolve().parent


async def _close_upstream_on_disconnect(
    request: Request,
    upstream: httpx.Response,
) -> None:
    """Close a stalled upstream as soon as the client goes away.

    The SSE loop itself only notices a disconnect when the next upstream line
    arrives. A stalled vLLM stream would otherwise hold an admission slot until
    the read timeout. This watcher makes the disconnect independent of upstream
    progress.
    """
    try:
        while True:
            if await request.is_disconnected():
                await upstream.aclose()
                return
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        raise
    except Exception:
        return

@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = httpx.Timeout(
        connect=2.0,
        read=UPSTREAM_TIMEOUT_SECONDS,
        write=10.0,
        pool=5.0,
    )
    health_timeout = httpx.Timeout(
        connect=1.0,
        read=HEALTH_TIMEOUT_SECONDS,
        write=2.0,
        pool=2.0,
    )
    app.state.http = httpx.AsyncClient(timeout=timeout)
    app.state.health_http = httpx.AsyncClient(
        timeout=health_timeout,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=0),
    )
    app.state.admission = AdmissionController(
        MAX_CONCURRENT_REQUESTS,
        MAX_QUEUED_REQUESTS,
        QUEUE_TIMEOUT_SECONDS,
    )
    if RATE_LIMIT_BACKEND == "redis":
        import redis.asyncio as redis

        from gw_redis_limiter import RedisRateLimiter

        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        app.state.rate_limiter = RedisRateLimiter(
            RATE_LIMIT_PER_MINUTE, redis_client
        )
        app.state.auth_failures = RedisRateLimiter(
            AUTH_FAILURE_LIMIT_PER_MINUTE, redis_client
        )
    else:
        app.state.rate_limiter = RateLimiter(
            RATE_LIMIT_PER_MINUTE, RATE_LIMIT_MAX_IDENTITIES
        )
        app.state.auth_failures = RateLimiter(AUTH_FAILURE_LIMIT_PER_MINUTE)
    log_event(
        logging.INFO,
        "gateway_start",
        model=MODEL_NAME,
        outcome="started",
    )
    yield
    for limiter in (app.state.rate_limiter, app.state.auth_failures):
        close = getattr(limiter, "close", None)
        if close is not None:
            await close()
    await app.state.health_http.aclose()
    await app.state.http.aclose()


app = FastAPI(
    title="AI Inference Gateway",
    version=GATEWAY_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def gateway_identity_headers(request: Request, call_next):
    """Attach the serving pod and build version to every response."""
    response = await call_next(request)
    response.headers["X-Gateway-Pod"] = POD_NAME
    response.headers["X-Gateway-Version"] = GATEWAY_VERSION
    return response


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(APP_DIR / "index.html")


@app.get("/live")
async def live() -> dict[str, str]:
    """Liveness: this process is running, independent of the model server."""
    return {"status": "ok", "pod": POD_NAME, "version": GATEWAY_VERSION}


@app.get("/ready")
async def ready() -> dict[str, str]:
    """Readiness: the gateway process can accept traffic.

    Upstream dependency health is exposed separately at /health. Keeping
    readiness process-local prevents a vLLM outage from removing every gateway
    pod from the Service at once; /health still reports the dependency.
    """
    return {"status": "ready", "pod": POD_NAME, "version": GATEWAY_VERSION}


@app.get("/health")
async def health() -> JSONResponse:
    """The gateway is healthy only when its vLLM upstream is reachable."""
    try:
        response = await app.state.health_http.get(
            f"{VLLM_BASE_URL}/health",
            headers={"Connection": "close"},
        )
        response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        UPSTREAM_HEALTHY.set(0)
        log_event(
            logging.WARNING,
            "health_check_failed",
            status_code=503,
            outcome="unhealthy",
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "vllm": "unreachable",
                "error": str(exc)[:200],
                "pod": POD_NAME,
            },
        )
    UPSTREAM_HEALTHY.set(1)
    return JSONResponse(
        content={
            "status": "ok",
            "vllm": "ok",
            "pod": POD_NAME,
            "version": GATEWAY_VERSION,
        }
    )


@app.get("/gateway/status")
async def gateway_status() -> dict[str, int | float | str]:
    snapshot = await app.state.admission.snapshot()
    return {**snapshot, "pod": POD_NAME, "version": GATEWAY_VERSION}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)],
)
async def chat(
    body: ChatRequest,
    response: Response,
    x_request_id: str | None = Header(default=None),
) -> ChatResponse:
    request_id = x_request_id or str(uuid.uuid4())
    enforce_context_window(body)
    payload = build_payload(body, stream=False)
    started = time.perf_counter()
    try:
        lease = await app.state.admission.acquire(request_id)
    except HTTPException:
        REQUESTS_TOTAL.labels(mode="non_stream", outcome="rejected").inc()
        raise
    try:
        upstream = await post_with_connect_retry(
            app.state.http,
            f"{VLLM_BASE_URL}/v1/chat/completions",
            json=payload,
            headers={"X-Request-ID": request_id},
            request_id=request_id,
        )
    except httpx.HTTPError as exc:
        raise translate_upstream_error(
            exc,
            request_id=request_id,
            mode="non_stream",
            lease=lease,
            started=started,
        ) from exc
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

    try:
        data = upstream.json()
        answer = data["choices"][0]["message"]["content"]
        if not isinstance(answer, str):
            raise TypeError("upstream answer is not a string")
        usage = parse_usage(data.get("usage"))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        REQUESTS_TOTAL.labels(mode="non_stream", outcome="upstream_error").inc()
        log_event(
            logging.WARNING,
            "request_failed",
            request_id=request_id,
            mode="non_stream",
            model=MODEL_NAME,
            status_code=502,
            outcome="upstream_error",
            queue_wait_ms=round(lease.queue_wait_ms, 1),
            latency_ms=round((time.perf_counter() - started) * 1_000, 1),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="invalid response from vLLM",
        ) from exc

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
    response.headers["X-Request-ID"] = request_id
    return ChatResponse(
        request_id=request_id,
        model=data.get("model", MODEL_NAME),
        answer=answer,
        usage=usage,
        latency_ms=round(latency_ms, 1),
    )


@app.post("/chat/stream", dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)])
async def chat_stream(
    body: ChatRequest,
    request: Request,
    x_request_id: str | None = Header(default=None),
) -> StreamingResponse:
    request_id = x_request_id or str(uuid.uuid4())
    enforce_context_window(body)
    payload = build_payload(body, stream=True)
    started = time.perf_counter()
    try:
        lease = await app.state.admission.acquire(request_id)
    except HTTPException:
        REQUESTS_TOTAL.labels(mode="stream", outcome="rejected").inc()
        raise
    try:
        upstream = await send_stream_with_connect_retry(
            app.state.http,
            f"{VLLM_BASE_URL}/v1/chat/completions",
            json=payload,
            headers={"X-Request-ID": request_id},
            request_id=request_id,
        )
    except httpx.HTTPError as exc:
        await lease.release()
        raise translate_upstream_error(
            exc,
            request_id=request_id,
            mode="stream",
            lease=lease,
            started=started,
        ) from exc
    except BaseException:
        await lease.release()
        raise

    if upstream.is_error:
        try:
            detail = (await upstream.aread()).decode("utf-8", "replace")[:1_000]
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
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise translate_upstream_error(
                exc,
                request_id=request_id,
                mode="stream",
                lease=lease,
                started=started,
            ) from exc
        finally:
            try:
                await upstream.aclose()
            except Exception:
                pass
            await lease.release()

    async def events() -> AsyncIterator[bytes]:
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        first_token_ms: float | None = None
        completed = False
        disconnect_task = asyncio.create_task(
            _close_upstream_on_disconnect(request, upstream)
        )
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
                    latency_ms=round((time.perf_counter() - started) * 1_000, 1),
                    error_type=type(exc).__name__,
                )
                return
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
            disconnect_task.cancel()
            try:
                await disconnect_task
            except asyncio.CancelledError:
                pass
            try:
                await upstream.aclose()
            except Exception:
                pass
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
        else:
            # The upstream closed the stream without a [DONE] sentinel and
            # without raising. That is a real outcome (upstream crash, proxy
            # truncation) and must be counted, otherwise the request vanishes
            # from `requests_total` and the success ratio reads too high.
            latency_ms = (time.perf_counter() - started) * 1_000
            REQUESTS_TOTAL.labels(mode="stream", outcome="incomplete").inc()
            log_event(
                logging.WARNING,
                "stream_incomplete",
                request_id=request_id,
                mode="stream",
                model=MODEL_NAME,
                status_code=200,
                outcome="incomplete",
                queue_wait_ms=round(lease.queue_wait_ms, 1),
                ttft_ms=round(first_token_ms, 1) if first_token_ms else None,
                latency_ms=round(latency_ms, 1),
                error_type="MissingDoneSentinel",
            )

    # The lease must be released by the response, not only by the generator.
    # A client that disconnects before the first chunk never starts `events()`,
    # and an async generator that never ran does not execute its `finally`.
    # Without this the admission slot leaks and the gateway eventually rejects
    # everything. BackgroundTask runs on both completion and client disconnect.
    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        background=BackgroundTask(lease.release),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )
