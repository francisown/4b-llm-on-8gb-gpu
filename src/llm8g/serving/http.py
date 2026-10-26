"""FastAPI adapter for :mod:`llm8g.serving`.

The import is intentionally lazy at the package level: installing ``llm8g``
without the web extra still gives a usable core for evaluation and offline
tests.  This module is the only place that knows about FastAPI, SSE framing,
Prometheus exposition, and HTTP status codes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request

from .admission import AdmissionController
from .config import GatewaySettings
from .limits import SlidingWindowLimiter
from .logging import configure_logger, log_event
from .metrics import ServingMetrics
from .ports import InferenceBackend
from .security import AuthPolicy
from .routes import router
from .service import GatewayService
from .upstream import VllmHttpBackend

def create_app(
    settings: GatewaySettings | None = None,
    *,
    backend: InferenceBackend | None = None,
) -> FastAPI:
    """Build the HTTP adapter around an explicitly configured serving core."""

    resolved = settings or GatewaySettings.from_env()
    configure_logger(resolved.log_level)
    resolved_backend: InferenceBackend = (
        backend if backend is not None else VllmHttpBackend(resolved)
    )
    metrics = ServingMetrics(resolved)

    rate_limiter = SlidingWindowLimiter(
        resolved.rate_limit_per_minute,
        max_identities=resolved.rate_limit_max_identities,
    )
    auth_failure_limiter = SlidingWindowLimiter(
        resolved.auth_failure_limit_per_minute,
        max_identities=resolved.rate_limit_max_identities,
    )
    auth = AuthPolicy(
        resolved.api_keys,
        rate_limiter=rate_limiter,
        auth_failure_limiter=auth_failure_limiter,
    )
    admission = AdmissionController(
        resolved.max_concurrent,
        resolved.max_queue,
        resolved.queue_timeout_seconds,
        observer=metrics.observe_admission,
    )
    metrics.observe_admission(0, 0)
    service = GatewayService(resolved, resolved_backend, admission)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await resolved_backend.start()
        redis_client = None
        if resolved.rate_limit_backend == "redis":
            import redis.asyncio as redis

            from .redis_limits import RedisRateLimiter

            redis_client = redis.from_url(resolved.redis_url, decode_responses=True)
            app.state.auth = AuthPolicy(
                resolved.api_keys,
                rate_limiter=RedisRateLimiter(
                    resolved.rate_limit_per_minute, redis_client
                ),
                auth_failure_limiter=RedisRateLimiter(
                    resolved.auth_failure_limit_per_minute, redis_client
                ),
            )
        log_event(
            logging.INFO,
            "gateway_start",
            model=resolved.model,
            outcome="started",
        )
        try:
            yield
        finally:
            if redis_client is not None:
                await redis_client.aclose()
            await resolved_backend.close()

    app = FastAPI(
        title="LLM8G inference gateway",
        version=resolved.version,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.metrics = metrics
    app.state.backend = resolved_backend
    app.state.service = service
    app.state.admission = admission
    app.state.auth = auth
    app.state.rate_limiter = rate_limiter
    app.state.auth_failures = auth_failure_limiter

    @app.middleware("http")
    async def gateway_identity_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Gateway-Pod"] = resolved.pod_name
        response.headers["X-Gateway-Version"] = resolved.version
        return response

    app.include_router(router)
    return app
