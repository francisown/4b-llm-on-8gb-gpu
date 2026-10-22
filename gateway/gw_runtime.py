"""Runtime configuration, logging, metrics, and request/response models.

This module is imported by the gateway entrypoint and by the admission,
authentication, and upstream helper modules. Keeping it separate avoids the
circular imports that a single-file gateway would otherwise need.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Literal

from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, Field

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen3.5-4B-INT4-AWQ-self")
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "60"))
MAX_CONCURRENT_REQUESTS = int(os.getenv("GATEWAY_MAX_CONCURRENT", "4"))
MAX_QUEUED_REQUESTS = int(os.getenv("GATEWAY_MAX_QUEUE", "4"))
QUEUE_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_QUEUE_TIMEOUT_SECONDS", "10"))
HEALTH_TIMEOUT_SECONDS = float(os.getenv("HEALTH_TIMEOUT_SECONDS", "3"))
UPSTREAM_CONNECT_RETRIES = max(0, int(os.getenv("UPSTREAM_CONNECT_RETRIES", "1")))
RATE_LIMIT_PER_MINUTE = max(0, int(os.getenv("GATEWAY_RATE_LIMIT_PER_MINUTE", "0")))
RATE_LIMIT_MAX_IDENTITIES = max(
    1, int(os.getenv("GATEWAY_RATE_LIMIT_MAX_IDENTITIES", "10000"))
)
RATE_LIMIT_BACKEND = os.getenv("GATEWAY_RATE_LIMIT_BACKEND", "process").lower()
REDIS_URL = os.getenv("GATEWAY_REDIS_URL", "redis://127.0.0.1:6379/0")
AUTH_FAILURE_LIMIT_PER_MINUTE = max(
    0, int(os.getenv("GATEWAY_AUTH_FAILURE_LIMIT_PER_MINUTE", "20"))
)
# Keep this in sync with the vLLM --max-model-len for the served model.
MAX_CONTEXT_TOKENS = max(1, int(os.getenv("GATEWAY_MAX_CONTEXT_TOKENS", "2048")))
# Only trust X-Forwarded-For / X-Real-IP when the gateway is actually behind a
# proxy that overwrites them. Trusting them on a directly exposed pod lets any
# client spoof its rate-limit identity.
TRUST_PROXY_HEADERS = os.getenv("GATEWAY_TRUST_PROXY_HEADERS", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
POD_NAME = os.getenv("POD_NAME", "local")
GATEWAY_VERSION = os.getenv("GATEWAY_VERSION", "0.2.4")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")
GATEWAY_API_KEYS = tuple(
    key.strip() for key in os.getenv("GATEWAY_API_KEYS", "").split(",") if key.strip()
)

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
AUTH_FAILURES_TOTAL = Counter(
    "inference_gateway_auth_failures_total",
    "Requests rejected because the API key was missing or invalid.",
)
RATE_LIMITED_TOTAL = Counter(
    "inference_gateway_rate_limited_total",
    "Requests rejected by the per-identity rate limit.",
)
UPSTREAM_HEALTHY = Gauge(
    "inference_gateway_upstream_healthy",
    "Whether the last /health probe could reach the vLLM upstream.",
)
GATEWAY_INFO = Gauge(
    "inference_gateway_info",
    "Static gateway identity labels.",
    ("version", "pod"),
)
GATEWAY_INFO.labels(version=GATEWAY_VERSION, pod=POD_NAME).set(1)


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

