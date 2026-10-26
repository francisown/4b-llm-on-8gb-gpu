from __future__ import annotations

from llm8g.serving.config import GatewaySettings
from llm8g.serving.errors import (
    AdmissionRejected,
    ContextLimitExceeded,
    UpstreamHTTPError,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from llm8g.serving.metrics import ServingMetrics
from llm8g.serving.transport import metric_outcome, request_id


def test_request_id_accepts_bounded_printable_values() -> None:
    assert request_id("req-123") == "req-123"
    assert request_id("").count("-") == 4
    assert request_id("x" * 129).count("-") == 4
    assert request_id("bad\r\nid").count("-") == 4


def test_metric_outcomes_match_dashboard_labels() -> None:
    assert metric_outcome(AdmissionRejected("capacity")) == "rejected"
    assert metric_outcome(ContextLimitExceeded("too long")) == "rejected"
    assert metric_outcome(UpstreamTimeout("timeout")) == "timeout"
    assert metric_outcome(UpstreamUnavailable("down")) == "unavailable"
    assert metric_outcome(UpstreamHTTPError(500, "boom")) == "upstream_error"


def test_serving_metrics_are_isolated_per_app() -> None:
    first = ServingMetrics(GatewaySettings(version="one", pod_name="pod-one"))
    second = ServingMetrics(GatewaySettings(version="two", pod_name="pod-two"))
    first.requests_total.labels(mode="non_stream", outcome="success").inc()

    first_names = {
        sample.name
        for metric in first.registry.collect()
        for sample in metric.samples
    }
    second_names = {
        sample.name
        for metric in second.registry.collect()
        for sample in metric.samples
    }
    assert "inference_gateway_requests_total" in first_names
    assert "inference_gateway_requests_total" not in second_names
    assert "inference_gateway_info" in first_names
    assert "inference_gateway_info" in second_names
