"""API-key authentication and per-identity rate limiting dependencies."""

from __future__ import annotations

import hashlib
import logging
import secrets

from fastapi import Header, HTTPException, Request

import gw_runtime as runtime
from gw_runtime import AUTH_FAILURES_TOTAL, RATE_LIMITED_TOTAL, log_event


def client_host(request: Request) -> str:
    """Return the best-effort client IP, honouring proxy headers only when asked."""
    if runtime.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def configured_api_keys() -> tuple[str, ...]:
    """Return the accepted API keys without exposing them in logs or metrics."""
    keys: list[str] = []
    if runtime.GATEWAY_API_KEY:
        keys.append(runtime.GATEWAY_API_KEY)
    for key in runtime.GATEWAY_API_KEYS:
        if key not in keys:
            keys.append(key)
    return tuple(keys)


async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Optional bearer/X-API-Key authentication.

    Authentication is disabled when neither GATEWAY_API_KEY nor
    GATEWAY_API_KEYS is set, preserving the local/GPU demo path. Health,
    liveness, and metrics stay unauthenticated so Kubernetes probes and
    Prometheus can reach them.
    """
    keys = configured_api_keys()
    if not keys:
        return
    provided = x_api_key or ""
    if not provided and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            provided = token.strip()
    valid = False
    if provided:
        for key in keys:
            if secrets.compare_digest(provided, key):
                valid = True
    if not valid:
        allowed, retry_after = await request.app.state.auth_failures.check(
            "auth:" + client_host(request)
        )
        AUTH_FAILURES_TOTAL.inc()
        if not allowed:
            log_event(
                logging.WARNING,
                "request_rejected",
                status_code=429,
                outcome="rate_limited",
                reason="auth",
            )
            raise HTTPException(
                status_code=429,
                detail="too many authentication failures",
                headers={"Retry-After": str(retry_after)},
            )
        log_event(
            logging.WARNING,
            "request_rejected",
            status_code=401,
            outcome="unauthorized",
            reason="auth",
        )
        raise HTTPException(
            status_code=401,
            detail="invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def request_identity(
    request: Request,
    authorization: str | None,
    x_api_key: str | None,
) -> str:
    key = x_api_key or ""
    if not key and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            key = token.strip()
    # Only treat a key as an identity after authentication is configured.
    # Otherwise clients could rotate arbitrary X-API-Key headers to bypass
    # the per-IP limit.
    if key and configured_api_keys():
        # Do not keep raw tokens in the in-memory limiter.
        return "key:" + hashlib.sha256(key.encode("utf-8")).hexdigest()
    return "ip:" + client_host(request)


async def enforce_rate_limit(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Optional per-identity rate limit; disabled when the limit is 0."""
    limiter = request.app.state.rate_limiter
    if limiter.limit <= 0:
        return
    identity = request_identity(request, authorization, x_api_key)
    allowed, retry_after = await limiter.check(identity)
    if not allowed:
        RATE_LIMITED_TOTAL.inc()
        log_event(
            logging.WARNING,
            "request_rejected",
            status_code=429,
            outcome="rate_limited",
            reason="rate_limit",
        )
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
