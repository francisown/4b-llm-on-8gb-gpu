"""Structured JSON logging shared by the serving adapters.

A request is one JSON object per line, which is what the soak scripts and the
Kubernetes log collection expect.  The core serving package only emits typed
exceptions; the HTTP adapter decides which events to log.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

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


def configure_logger(level: str | None = None) -> logging.Logger:
    application_logger = logging.getLogger("inference-gateway")
    application_logger.setLevel(str(level or os.getenv("LOG_LEVEL") or "INFO").upper())
    application_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    application_logger.addHandler(handler)
    application_logger.propagate = False
    return application_logger


logger = configure_logger()


def log_event(level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"event": event, **fields})
