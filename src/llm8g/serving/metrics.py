"""Prometheus metrics for the HTTP serving adapter.

Each ``create_app`` call owns a ``ServingMetrics`` instance with its own
CollectorRegistry.  That keeps tests and embedded app instances isolated while
still exposing the historical metric names at ``/metrics``.
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

from .config import GatewaySettings


class ServingMetrics:
    def __init__(self, settings: GatewaySettings) -> None:
        self.registry = CollectorRegistry()
        self.requests_total = Counter(
            "inference_gateway_requests_total",
            "Completed gateway requests by mode and outcome.",
            ("mode", "outcome"),
            registry=self.registry,
        )
        self.rejections_total = Counter(
            "inference_gateway_rejections_total",
            "Requests rejected before reaching vLLM.",
            ("reason",),
            registry=self.registry,
        )
        self.active_requests = Gauge(
            "inference_gateway_active_requests",
            "Requests currently admitted to vLLM.",
            registry=self.registry,
        )
        self.waiting_requests = Gauge(
            "inference_gateway_waiting_requests",
            "Requests waiting for an admission slot.",
            registry=self.registry,
        )
        self.queue_wait_seconds = Histogram(
            "inference_gateway_queue_wait_seconds",
            "Time spent waiting for an admission slot.",
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
            registry=self.registry,
        )
        self.request_duration_seconds = Histogram(
            "inference_gateway_request_duration_seconds",
            "End-to-end gateway request duration.",
            ("mode",),
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
            registry=self.registry,
        )
        self.ttft_seconds = Histogram(
            "inference_gateway_ttft_seconds",
            "Time to first streamed token.",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
            registry=self.registry,
        )
        self.tokens_total = Counter(
            "inference_gateway_tokens_total",
            "Tokens processed by successful gateway requests.",
            ("direction",),
            registry=self.registry,
        )
        self.client_disconnects_total = Counter(
            "inference_gateway_client_disconnects_total",
            "Streaming clients that disconnected before completion.",
            registry=self.registry,
        )
        self.auth_failures_total = Counter(
            "inference_gateway_auth_failures_total",
            "Requests rejected because the API key was missing or invalid.",
            registry=self.registry,
        )
        self.rate_limited_total = Counter(
            "inference_gateway_rate_limited_total",
            "Requests rejected by the per-identity rate limit.",
            registry=self.registry,
        )
        self.upstream_healthy = Gauge(
            "inference_gateway_upstream_healthy",
            "Whether the last /health probe could reach the vLLM upstream.",
            registry=self.registry,
        )
        self.gateway_info = Gauge(
            "inference_gateway_info",
            "Static gateway identity labels.",
            ("version", "pod"),
            registry=self.registry,
        )
        self.gateway_info.labels(
            version=settings.version,
            pod=settings.pod_name,
        ).set(1)

    def observe_admission(self, active: int, waiting: int) -> None:
        self.active_requests.set(active)
        self.waiting_requests.set(waiting)
