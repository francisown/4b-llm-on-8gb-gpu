"""HTTP transport helpers shared by the serving adapter.

These functions deliberately know nothing about the app composition; they are
pure framing, validation, logging, and error-mapping helpers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import logging
from pathlib import Path
from typing import Any
import uuid

from fastapi import Request

from .config import GatewaySettings
from .errors import (
    AdmissionRejected,
    ContextLimitExceeded,
    InvalidUpstreamResponse,
    ServingError,
    UpstreamHTTPError,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from .logging import log_event
from .models import StreamEvent

STATIC_DIR = Path(__file__).with_name("static")


def event_bytes(kind: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {kind}\ndata: {data}\n\n".encode("utf-8")


def request_id(value: str | None) -> str:
    """Accept a bounded printable request ID; otherwise generate one.

    Client IDs are copied into response headers and JSON logs, so they must not
    contain control characters or grow without bound.
    """
    if (
        value
        and len(value) <= 128
        and all(0x20 <= ord(character) < 0x7F for character in value)
    ):
        return value
    return str(uuid.uuid4())


def client_ip(request: Request, settings: GatewaySettings) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def provided_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            return token.strip() or None
    return None


def status_for_error(exc: ServingError) -> tuple[int, str, str]:
    if isinstance(exc, ContextLimitExceeded):
        return 422, "context_length", str(exc)
    if isinstance(exc, AdmissionRejected):
        return 429, exc.reason, str(exc)
    if isinstance(exc, UpstreamTimeout):
        return 504, "timeout", str(exc)
    if isinstance(exc, UpstreamUnavailable):
        return 503, "unavailable", str(exc)
    if isinstance(exc, UpstreamHTTPError):
        status = exc.status_code if 400 <= exc.status_code < 600 else 502
        return status, "upstream_error", exc.detail
    if isinstance(exc, InvalidUpstreamResponse):
        return 502, "upstream_error", str(exc)
    return 502, "upstream_error", str(exc)


def metric_outcome(exc: ServingError) -> str:
    """Map a typed serving error to the historical dashboard outcome labels."""
    if isinstance(exc, (AdmissionRejected, ContextLimitExceeded)):
        return "rejected"
    if isinstance(exc, UpstreamTimeout):
        return "timeout"
    if isinstance(exc, UpstreamUnavailable):
        return "unavailable"
    return "upstream_error"


def error_headers(exc: ServingError) -> dict[str, str]:
    if isinstance(exc, AdmissionRejected):
        return {"Retry-After": str(exc.retry_after)}
    return {}


def log_rejection(
    *,
    request_id: str | None,
    mode: str,
    status_code: int,
    reason: str,
    error_type: str,
) -> None:
    log_event(
        logging.WARNING,
        "request_rejected",
        request_id=request_id,
        mode=mode,
        status_code=status_code,
        outcome="rejected",
        reason=reason,
        error_type=error_type,
    )


async def close_on_disconnect(
    request: Request,
    stream: AsyncIterator[StreamEvent],
) -> None:
    """Close a stalled upstream stream when the client goes away."""
    try:
        while True:
            if await request.is_disconnected():
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
                return
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        raise
    except Exception:
        return
