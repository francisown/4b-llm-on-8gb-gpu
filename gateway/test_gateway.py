from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from starlette.requests import Request

import gateway


class FakeUpstream:
    def __init__(self) -> None:
        self.behavior = "success"
        self.connect_failures_remaining = 0
        self.post_calls: list[dict[str, Any]] = []
        self.health_calls: list[dict[str, str]] = []
        # Streaming path: build_request + send(stream=True) is what
        # send_stream_with_connect_retry calls, not post().
        self.stream_behavior = "success"
        self.stream_body = b""
        self.stream_calls: list[dict[str, Any]] = []

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
        if self.behavior == "malformed_json":
            return httpx.Response(200, text="not-json", request=request)
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

    def build_request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Request:
        return httpx.Request(method, url, json=json, headers=headers)

    async def send(
        self,
        request: httpx.Request,
        *,
        stream: bool = False,
    ) -> httpx.Response:
        self.stream_calls.append(
            {
                "url": str(request.url),
                "body": json.loads(request.content.decode("utf-8") or "{}"),
                "stream": stream,
            }
        )
        if self.connect_failures_remaining > 0:
            self.connect_failures_remaining -= 1
            raise httpx.ConnectError("connection refused", request=request)
        if self.stream_behavior == "timeout":
            raise httpx.ReadTimeout("upstream timed out", request=request)
        if self.stream_behavior == "connect_error":
            raise httpx.ConnectError("connection refused", request=request)
        if self.stream_behavior == "upstream_error":
            return httpx.Response(
                500,
                text="synthetic upstream failure",
                request=request,
            )
        return httpx.Response(200, content=self.stream_body, request=request)


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


def test_api_key_is_optional_and_enforced_when_configured(
    gateway_client: tuple[TestClient, FakeUpstream],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = gateway_client
    assert client.post("/chat", json=request_body()).status_code == 200

    monkeypatch.setattr(gateway, "GATEWAY_API_KEY", "secret-key")
    assert client.post("/chat", json=request_body()).status_code == 401
    assert client.post(
        "/chat",
        json=request_body(),
        headers={"X-API-Key": "wrong"},
    ).status_code == 401
    assert client.post(
        "/chat",
        json=request_body(),
        headers={"X-API-Key": "secret-key"},
    ).status_code == 200
    assert client.post(
        "/chat",
        json=request_body(),
        headers={"Authorization": "Bearer secret-key"},
    ).status_code == 200


def test_health_and_metrics_do_not_require_api_key(
    gateway_client: tuple[TestClient, FakeUpstream],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = gateway_client
    monkeypatch.setattr(gateway, "GATEWAY_API_KEY", "secret-key")
    assert client.get("/health").status_code == 200
    assert client.get("/live").status_code == 200
    assert client.get("/metrics").status_code == 200


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_rate_limiter_window_expires() -> None:
    clock = FakeClock()
    limiter = gateway.RateLimiter(2, clock=clock)
    assert asyncio.run(limiter.check("tenant")) == (True, 0)
    assert asyncio.run(limiter.check("tenant")) == (True, 0)
    allowed, retry_after = asyncio.run(limiter.check("tenant"))
    assert allowed is False
    assert retry_after == 60
    clock.advance(60.01)
    assert asyncio.run(limiter.check("tenant")) == (True, 0)


def test_rate_limiter_bounds_identity_map() -> None:
    clock = FakeClock()
    limiter = gateway.RateLimiter(5, max_identities=2, clock=clock)
    for identity in ("a", "b", "c", "d"):
        assert asyncio.run(limiter.check(identity)) == (True, 0)
    assert "__overflow__" in limiter._events
    assert len(limiter._events) <= 3


def test_rate_limit_ignores_untrusted_key_when_auth_disabled(
    gateway_client: tuple[TestClient, FakeUpstream],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = gateway_client
    monkeypatch.setattr(gateway, "GATEWAY_API_KEY", "")
    monkeypatch.setattr(gateway, "GATEWAY_API_KEYS", ())
    monkeypatch.setattr(gateway.app.state, "rate_limiter", gateway.RateLimiter(2))

    headers_a = {"X-API-Key": "tenant-a"}
    assert client.post("/chat", json=request_body(), headers=headers_a).status_code == 200
    assert client.post("/chat", json=request_body(), headers=headers_a).status_code == 200
    limited = client.post(
        "/chat",
        json=request_body(),
        headers={"X-API-Key": "tenant-b"},
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_rate_limit_is_per_authenticated_key(
    gateway_client: tuple[TestClient, FakeUpstream],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = gateway_client
    monkeypatch.setattr(gateway, "GATEWAY_API_KEY", "")
    monkeypatch.setattr(gateway, "GATEWAY_API_KEYS", ("tenant-a", "tenant-b"))
    monkeypatch.setattr(gateway.app.state, "rate_limiter", gateway.RateLimiter(2))

    headers_a = {"X-API-Key": "tenant-a"}
    assert client.post("/chat", json=request_body(), headers=headers_a).status_code == 200
    assert client.post("/chat", json=request_body(), headers=headers_a).status_code == 200
    limited = client.post("/chat", json=request_body(), headers=headers_a)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert client.post(
        "/chat",
        json=request_body(),
        headers={"X-API-Key": "tenant-b"},
    ).status_code == 200
    assert client.post(
        "/chat",
        json=request_body(),
        headers={"X-API-Key": "not-configured"},
    ).status_code == 401


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


def test_malformed_upstream_response_returns_502(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.behavior = "malformed_json"
    response = client.post("/chat", json=request_body())
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


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


# --- streaming path (/chat/stream) ------------------------------------------
# The stream branch consumes the upstream through build_request + send(stream=True),
# which is a different code path from post(). These tests exist because that
# branch had no coverage at all before 2026-10-22.


def upstream_sse(*chunks: dict[str, Any], done: bool = True) -> bytes:
    """Build an OpenAI-style SSE body, one data: line per chunk."""
    lines = [f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


def parse_sse(text: str) -> list[tuple[str | None, dict[str, Any]]]:
    events: list[tuple[str | None, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event_name: str | None = None
        data: dict[str, Any] | None = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if data is not None:
            events.append((event_name, data))
    return events


def test_stream_emits_meta_tokens_then_done(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = upstream_sse(
        {"choices": [{"delta": {"content": "你好"}}]},
        {"choices": [{"delta": {"content": "世界"}}]},
        {
            "choices": [],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        },
    )

    response = client.post("/chat/stream", json=request_body())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-Accel-Buffering"] == "no"
    assert response.headers["X-Request-ID"]

    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"

    tokens = [payload["text"] for name, payload in events if name == "token"]
    assert tokens == ["你好", "世界"]
    channels = [payload["channel"] for name, payload in events if name == "token"]
    assert channels == ["answer", "answer"]

    done = events[-1][1]
    assert done["usage"]["total_tokens"] == 7
    assert done["request_id"]
    assert done["ttft_ms"] >= 0


def test_stream_marks_upstream_payload_as_streaming(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = upstream_sse({"choices": [{"delta": {"content": "x"}}]})

    client.post("/chat/stream", json=request_body())

    assert len(fake.stream_calls) == 1
    assert fake.stream_calls[0]["stream"] is True
    assert fake.stream_calls[0]["body"]["stream"] is True
    assert fake.stream_calls[0]["url"].endswith("/v1/chat/completions")


def test_stream_timeout_returns_504(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_behavior = "timeout"

    response = client.post("/chat/stream", json=request_body())

    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]


def test_stream_upstream_error_status_is_passed_through(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_behavior = "upstream_error"

    response = client.post("/chat/stream", json=request_body())

    assert response.status_code == 500
    assert "synthetic upstream failure" in response.json()["detail"]


def test_stream_malformed_chunk_yields_error_event(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    # A data: line after the first frame that is not valid JSON.
    fake.stream_body = (
        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        b"data: not-json\n\n"
    )

    response = client.post("/chat/stream", json=request_body())

    assert response.status_code == 200
    names = [name for name, _ in parse_sse(response.text)]
    assert "error" in names
    # The generator returns after the error frame, so no done frame follows.
    assert "done" not in names


def test_stream_releases_admission_slot(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = upstream_sse({"choices": [{"delta": {"content": "x"}}]})

    client.post("/chat/stream", json=request_body())

    assert gateway.app.state.admission.active == 0
    assert gateway.app.state.admission.pending == 0


def test_stream_connect_failure_is_retried_before_failing(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = upstream_sse({"choices": [{"delta": {"content": "x"}}]})
    fake.connect_failures_remaining = 1

    response = client.post("/chat/stream", json=request_body())

    assert response.status_code == 200
    # One failed attempt, then a fresh request built for the retry.
    assert len(fake.stream_calls) == 2


def test_stream_without_done_sentinel_is_counted_as_incomplete(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    """A stream that ends without [DONE] and without an error must still count.

    Otherwise the request appears in neither `success` nor any failure outcome,
    and the observed success ratio is biased upward.
    """
    client, fake = gateway_client
    fake.stream_body = upstream_sse(
        {"choices": [{"delta": {"content": "x"}}]},
        done=False,
    )
    before = (
        REGISTRY.get_sample_value(
            "inference_gateway_requests_total",
            {"mode": "stream", "outcome": "incomplete"},
        )
        or 0.0
    )

    response = client.post("/chat/stream", json=request_body())

    assert response.status_code == 200
    names = [name for name, _ in parse_sse(response.text)]
    assert "done" not in names
    after = (
        REGISTRY.get_sample_value(
            "inference_gateway_requests_total",
            {"mode": "stream", "outcome": "incomplete"},
        )
        or 0.0
    )
    assert after == before + 1


def test_stream_lease_released_when_body_never_iterated(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    """A client can vanish before the first chunk is pulled.

    Starlette then closes the body iterator without ever starting it. An async
    generator that never ran does not execute its `finally`, so a lease released
    only inside `events()` would leak the admission slot permanently.
    """
    client, fake = gateway_client
    fake.stream_body = upstream_sse({"choices": [{"delta": {"content": "x"}}]})

    async def scenario() -> None:
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/chat/stream",
            "headers": [],
            "query_string": b"",
        }
        response = await gateway.chat_stream(
            gateway.ChatRequest(**request_body()),
            Request(scope),
            None,
        )
        assert gateway.app.state.admission.active == 1
        # Never pull a chunk: close the iterator the way Starlette does when the
        # client disconnects first. Starlette then runs the response background
        # task from its `finally`, which is what must release the lease.
        await response.body_iterator.aclose()
        assert gateway.app.state.admission.active == 1, "lease still held"
        assert response.background is not None
        await response.background()

    asyncio.run(scenario())

    assert gateway.app.state.admission.active == 0
    assert gateway.app.state.admission.pending == 0
