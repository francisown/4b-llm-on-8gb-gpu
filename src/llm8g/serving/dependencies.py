"""FastAPI dependencies for the serving adapter."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from .errors import AuthenticationFailed
from .transport import client_ip, log_rejection, provided_key


async def authorize(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    settings = request.app.state.settings
    try:
        await request.app.state.auth.identity(
            provided_key(authorization, x_api_key),
            client_ip(request, settings),
        )
    except AuthenticationFailed as exc:
        metrics = request.app.state.metrics
        if exc.kind == "rate_limit":
            metrics.rate_limited_total.inc()
            log_rejection(
                request_id=None,
                mode="http",
                status_code=429,
                reason="rate_limit",
                error_type="AuthenticationFailed",
            )
            raise HTTPException(
                status_code=429,
                detail=str(exc),
                headers={"Retry-After": str(exc.retry_after or 1)},
            ) from exc
        metrics.auth_failures_total.inc()
        log_rejection(
            request_id=None,
            mode="http",
            status_code=401,
            reason="auth",
            error_type="AuthenticationFailed",
        )
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
