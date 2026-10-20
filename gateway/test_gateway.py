from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import gateway


class FakeUpstream:
    def __init__(self) -> None:
        self.behavior = "success"
        self.connect_failures_remaining = 0
        self.post_calls: list[dict[str, Any]] = []
        self.health_calls: list[dict[str, str]] = []

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        request = httpx.Request("GET", url)
        self.health_calls.append(headers or {})
        if self.behavior == "connect_error":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, request=request)

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        request = httpx.Request("POST", url)
        self.post_calls.append({"url": url, "json": json, "headers": headers})
        if self.connect_failures_remaining > 0:
            self.connect_failures_remaining -= 1
            raise httpx.ConnectError("connection refused", request=request)
        if self.behavior == "timeout":
            raise httpx.ReadTimeout("upstream timed out", request=request)
        if self.behavior == "connect_error":
            raise httpx.ConnectError("connection refused", request=request)
        if self.behavior == "upstream_error":
            return httpx.Response(
                500,
                text="synthetic upstream failure",
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "model": gateway.MODEL_NAME,
                "choices": [{"message": {"content": "测试成功"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                },
            },
            request=request,
        )


@pytest.fixture
def gateway_client() -> tuple[TestClient, FakeUpstream]:
    client = TestClient(gateway.app)
    with client:
        original_http = gateway.app.state.http
        original_health_http = gateway.app.state.health_http
        fake = FakeUpstream()
        gateway.app.state.http = fake
        gateway.app.state.health_http = fake
        gateway.app.state.admission = gateway.AdmissionController(4, 4, 0.1)
        try:
            yield client, fake
        finally:
            gateway.app.state.http = original_http
            gateway.app.state.health_http = original_health_http


def request_body() -> dict[str, Any]:
    return {
        "message": "只回复测试成功",
        "max_tokens": 16,
        "temperature": 0,
        "enable_thinking": False,
    }


def test_live_and_healthy_upstream(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, _ = gateway_client
    assert client.get("/live").json()["status"] == "ok"
    assert client.get("/health").json()["status"] == "ok"


def test_response_carries_gateway_identity_headers(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, _ = gateway_client
    response = client.get("/live")
    assert response.headers["X-Gateway-Pod"] == gateway.POD_NAME
    assert response.headers["X-Gateway-Version"] == gateway.GATEWAY_VERSION


def test_connect_failure_is_retried_before_failing(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.connect_failures_remaining = 1
    response = client.post("/chat", json=request_body())
    assert response.status_code == 200
    assert response.json()["answer"] == "测试成功"
    assert len(fake.post_calls) == 2


def test_health_probe_disables_connection_reuse(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    assert client.get("/health").status_code == 200
    assert fake.health_calls[-1]["Connection"] == "close"


def test_chat_success_and_request_id_propagation(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    response = client.post(
        "/chat",
        headers={"X-Request-ID": "pytest-001"},
        json=request_body(),
    )
    assert response.status_code == 200
    assert response.json()["request_id"] == "pytest-001"
    assert response.json()["answer"] == "测试成功"
    assert response.json()["usage"]["total_tokens"] == 12
    assert fake.post_calls[0]["headers"]["X-Request-ID"] == "pytest-001"


def test_invalid_request_returns_422_without_calling_upstream(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    response = client.post("/chat", json={"message": "", "max_tokens": 0})
    assert response.status_code == 422
    assert fake.post_calls == []


@pytest.mark.parametrize(
    ("behavior", "expected_status", "expected_detail"),
    [
        ("timeout", 504, "vLLM request timed out"),
        ("connect_error", 503, "vLLM is unavailable"),
        ("upstream_error", 500, "synthetic upstream failure"),
    ],
)
def test_upstream_failures_are_translated(
    gateway_client: tuple[TestClient, FakeUpstream],
    behavior: str,
    expected_status: int,
    expected_detail: str,
) -> None:
    client, fake = gateway_client
    fake.behavior = behavior
    response = client.post("/chat", json=request_body())
    assert response.status_code == expected_status
    assert expected_detail in response.json()["detail"]


def test_capacity_limit_returns_429(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, _ = gateway_client
    controller = gateway.AdmissionController(1, 0, 0.1)
    controller.pending = 1
    controller.active = 1
    gateway.app.state.admission = controller

    response = client.post("/chat", json=request_body())
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert "busy" in response.json()["detail"]


def test_queue_timeout_returns_429(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, _ = gateway_client
    controller = gateway.AdmissionController(1, 1, 0.01)
    controller.pending = 1
    controller.active = 1
    controller.semaphore = asyncio.Semaphore(0)
    gateway.app.state.admission = controller

    response = client.post("/chat", json=request_body())
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert "queue wait timed out" in response.json()["detail"]


def test_json_formatter_emits_required_fields() -> None:
    record = logging.LogRecord(
        name="inference-gateway",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_complete",
        args=(),
        exc_info=None,
    )
    record.event = "request_complete"
    record.request_id = "pytest-log-001"
    record.status_code = 200
    record.queue_wait_ms = 1.25
    record.ttft_ms = 12.5
    record.latency_ms = 45.0

    payload = json.loads(gateway.JsonLogFormatter().format(record))
    assert payload["event"] == "request_complete"
    assert payload["request_id"] == "pytest-log-001"
    assert payload["status_code"] == 200
    assert payload["queue_wait_ms"] == 1.25
    assert payload["ttft_ms"] == 12.5
    assert payload["latency_ms"] == 45.0
