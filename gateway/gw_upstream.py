"""Upstream request building, context guard, SSE helpers, and error translation."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any

import httpx
from fastapi import HTTPException

from gw_admission import AdmissionLease
from gw_runtime import (
    ChatRequest,
    MAX_CONTEXT_TOKENS,
    MODEL_NAME,
    REJECTIONS_TOTAL,
    REQUESTS_TOTAL,
    TokenUsage,
    UPSTREAM_CONNECT_RETRIES,
    log_event,
)

def _is_cjk(code: int) -> bool:
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
    )


def estimate_tokens(text: str) -> int:
    """Conservative, tokenizer-free estimate for the context guard.

    CJK characters are counted as one token each; other text is counted as one
    token per four characters. This is intentionally approximate: the real
    tokenizer is model-specific, so the gateway only uses this to reject
    requests that are clearly far outside the configured context window.
    """
    cjk = sum(1 for character in text if _is_cjk(ord(character)))
    non_cjk = len(text) - cjk
    return cjk + math.ceil(non_cjk / 4)


def build_messages(body: ChatRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if body.system_prompt:
        messages.append({"role": "system", "content": body.system_prompt})
    messages.extend(message.model_dump() for message in body.history)
    messages.append({"role": "user", "content": body.message})
    return messages


def estimate_prompt_tokens(messages: list[dict[str, str]]) -> int:
    # The +16 covers role markers and chat-template overhead.
    return sum(estimate_tokens(message["content"]) for message in messages) + 16


def enforce_context_window(body: ChatRequest) -> None:
    estimated = estimate_prompt_tokens(build_messages(body))
    if estimated + body.max_tokens > MAX_CONTEXT_TOKENS:
        REJECTIONS_TOTAL.labels(reason="context_length").inc()
        raise HTTPException(
            status_code=422,
            detail=(
                "request exceeds the configured context window: "
                f"~{estimated} prompt tokens + {body.max_tokens} output tokens "
                f"> {MAX_CONTEXT_TOKENS}"
            ),
        )


def translate_upstream_error(
    exc: httpx.HTTPError,
    *,
    request_id: str,
    mode: str,
    lease: AdmissionLease,
    started: float,
) -> HTTPException:
    """Translate every httpx transport failure into a stable gateway response."""
    if isinstance(exc, httpx.TimeoutException):
        status, outcome, detail = 504, "timeout", "vLLM request timed out"
    elif isinstance(exc, httpx.ConnectError):
        status, outcome, detail = 503, "unavailable", "vLLM is unavailable"
    else:
        status, outcome, detail = 502, "upstream_error", "vLLM connection failed"
    REQUESTS_TOTAL.labels(mode=mode, outcome=outcome).inc()
    log_event(
        logging.WARNING,
        "request_failed",
        request_id=request_id,
        mode=mode,
        model=MODEL_NAME,
        status_code=status,
        outcome=outcome,
        queue_wait_ms=round(lease.queue_wait_ms, 1),
        latency_ms=round((time.perf_counter() - started) * 1_000, 1),
        error_type=type(exc).__name__,
    )
    return HTTPException(status_code=status, detail=detail)


def build_payload(body: ChatRequest, *, stream: bool) -> dict[str, Any]:
    messages = build_messages(body)
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


async def post_with_connect_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str],
    request_id: str,
) -> httpx.Response:
    """Retry only pre-send connection failures; never replay a read timeout."""
    for attempt in range(UPSTREAM_CONNECT_RETRIES + 1):
        try:
            return await client.post(url, json=json, headers=headers)
        except httpx.ConnectError:
            if attempt >= UPSTREAM_CONNECT_RETRIES:
                raise
            log_event(
                logging.WARNING,
                "upstream_connect_retry",
                request_id=request_id,
                outcome="retry",
                error_type="ConnectError",
            )
            await asyncio.sleep(0.1 * (2**attempt))
    raise RuntimeError("unreachable retry loop")


async def send_stream_with_connect_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str],
    request_id: str,
) -> httpx.Response:
    """Build a fresh streaming request for each pre-send connection attempt."""
    for attempt in range(UPSTREAM_CONNECT_RETRIES + 1):
        request = client.build_request("POST", url, json=json, headers=headers)
        try:
            return await client.send(request, stream=True)
        except httpx.ConnectError:
            if attempt >= UPSTREAM_CONNECT_RETRIES:
                raise
            log_event(
                logging.WARNING,
                "upstream_connect_retry",
                request_id=request_id,
                outcome="retry",
                error_type="ConnectError",
            )
            await asyncio.sleep(0.1 * (2**attempt))
    raise RuntimeError("unreachable retry loop")
