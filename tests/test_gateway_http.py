from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from llm8g.serving.config import GatewaySettings
from llm8g.serving.errors import AdmissionRejected
from llm8g.serving.http import create_app
from llm8g.serving.transport import close_on_disconnect
from llm8g.serving.limits import SlidingWindowLimiter
from llm8g.serving.logging import JsonLogFormatter
from llm8g.serving.redis_limits import RedisRateLimiter
from llm8g.serving.upstream import VllmHttpBackend


class BrokenErrorResponse:
    is_error = True
    status_code = 500

    async def aread(self) -> bytes:
        request = httpx.Request("POST", "http://upstream.invalid/v1/chat/completions")
        raise httpx.ReadError("error body read failed", request=request)

    async def aclose(self) -> None:
        return None


class FakeUpstream:
    def __init__(self) -> None:
        self.behavior = "success"
        self.connect_failures_remaining = 0
        self.post_calls: list[dict[str, Any]] = []
        self.health_calls: list[dict[str, str]] = []
        self.stream_behavior = "success"
        self.stream_body = b""
        self.stream_calls: list[dict[str, Any]] = []

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        del timeout
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
        if self.behavior == "read_error":
            raise httpx.ReadError("upstream read failed", request=request)
        if self.behavior == "connect_error":
            raise httpx.ConnectError("connection refused", request=request)
        if self.behavior == "upstream_error":
            return httpx.Response(500, text="synthetic upstream failure", request=request)
        if self.behavior == "malformed_json":
            return httpx.Response(200, text="not-json", request=request)
        return httpx.Response(
            200,
            json={
                "model": "fake-model",
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
        if self.stream_behavior == "read_error":
            raise httpx.ReadError("upstream read failed", request=request)
        if self.stream_behavior == "connect_error":
            raise httpx.ConnectError("connection refused", request=request)
        if self.stream_behavior == "broken_error":
            return BrokenErrorResponse()  # type: ignore[return-value]
        if self.stream_behavior == "upstream_error":
            return httpx.Response(
                500,
                text="synthetic upstream failure",
                request=request,
            )
        return httpx.Response(200, content=self.stream_body, request=request)


def request_body() -> dict[str, Any]:
    return {
        "message": "只回复测试成功",
        "max_tokens": 16,
        "temperature": 0,
        "enable_thinking": False,
    }


def stream_body(*, usage: bool = True, done: bool = True) -> bytes:
    lines = [
        'data: {"choices":[{"delta":{"content":"你"}}]}',
        'data: {"choices":[{"delta":{"content":"好"}}]}',
    ]
    if usage:
        lines.append(
            'data: {"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}'
        )
    if done:
        lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode("utf-8")


def make_client(
    settings: GatewaySettings | None = None,
    fake: FakeUpstream | None = None,
) -> tuple[TestClient, FakeUpstream]:
    resolved = settings or GatewaySettings(
        upstream_timeout_seconds=1,
        health_timeout_seconds=1,
        connect_retries=1,
    )
    upstream = fake or FakeUpstream()
    backend = VllmHttpBackend(resolved, client=upstream)  # type: ignore[arg-type]
    app = create_app(resolved, backend=backend)
    return TestClient(app), upstream


@pytest.fixture
def gateway_client() -> tuple[TestClient, FakeUpstream]:
    client, fake = make_client()
    with client:
        yield client, fake


def test_live_ready_health_and_identity_headers(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, _ = gateway_client
    assert client.get("/live").json()["status"] == "ok"
    assert client.get("/ready").json()["status"] == "ready"
    assert client.get("/health").json()["status"] == "ok"
    response = client.get("/live")
    assert response.headers["X-Gateway-Pod"] == "local"
    assert response.headers["X-Gateway-Version"] == "stable"


def test_ready_is_process_local_when_upstream_is_down(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.behavior = "connect_error"
    assert client.get("/ready").status_code == 200
    assert client.get("/health").status_code == 503


def test_health_probe_disables_connection_reuse(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    assert client.get("/health").status_code == 200
    assert fake.health_calls[-1]["Connection"] == "close"


def test_index_and_metrics_are_served(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, _ = gateway_client
    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "inference_gateway_requests_total" in metrics.text


def test_api_key_is_optional_and_enforced_when_configured() -> None:
    client, _ = make_client()
    with client:
        assert client.post("/chat", json=request_body()).status_code == 200

    protected, _ = make_client(GatewaySettings(api_keys=("secret-key",)))
    with protected:
        assert protected.post("/chat", json=request_body()).status_code == 401
        assert (
            protected.post(
                "/chat", json=request_body(), headers={"X-API-Key": "secret-key"}
            ).status_code
            == 200
        )
        assert protected.get("/health").status_code == 200
        assert protected.get("/metrics").status_code == 200


def test_bearer_token_is_accepted() -> None:
    client, _ = make_client(GatewaySettings(api_keys=("secret-key",)))
    with client:
        response = client.post(
            "/chat",
            json=request_body(),
            headers={"Authorization": "Bearer secret-key"},
        )
        assert response.status_code == 200


def test_repeated_bad_api_keys_are_rate_limited() -> None:
    client, _ = make_client(
        GatewaySettings(
            api_keys=("secret-key",),
            auth_failure_limit_per_minute=1,
        )
    )
    with client:
        assert client.post("/chat", json=request_body()).status_code == 401
        blocked = client.post("/chat", json=request_body())
        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"]


def test_chat_success_and_request_id_propagation(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    response = client.post(
        "/chat",
        json=request_body(),
        headers={"X-Request-ID": "req-123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "测试成功"
    assert body["request_id"] == "req-123"
    assert response.headers["X-Request-ID"] == "req-123"
    assert fake.post_calls[0]["json"]["stream"] is False
    assert fake.post_calls[0]["json"]["messages"][-1]["content"] == "只回复测试成功"


def test_invalid_request_returns_422_without_calling_upstream(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    response = client.post("/chat", json={"message": "", "max_tokens": 0})
    assert response.status_code == 422
    assert fake.post_calls == []


def test_context_window_guard_rejects_before_upstream() -> None:
    client, fake = make_client(GatewaySettings(max_context_tokens=20))
    with client:
        response = client.post(
            "/chat",
            json={"message": "中" * 20, "max_tokens": 8},
        )
        assert response.status_code == 422
        assert fake.post_calls == []


def test_connect_failure_is_retried_before_failing(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.connect_failures_remaining = 1
    response = client.post("/chat", json=request_body())
    assert response.status_code == 200
    assert len(fake.post_calls) == 2


@pytest.mark.parametrize(
    ("behavior", "status_code"),
    [
        ("timeout", 504),
        ("connect_error", 503),
        ("read_error", 502),
        ("malformed_json", 502),
        ("upstream_error", 500),
    ],
)
def test_upstream_failures_are_translated(
    gateway_client: tuple[TestClient, FakeUpstream],
    behavior: str,
    status_code: int,
) -> None:
    client, fake = gateway_client
    fake.behavior = behavior
    response = client.post("/chat", json=request_body())
    assert response.status_code == status_code


def test_capacity_and_queue_timeout_map_to_429(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, _ = gateway_client

    class RejectingService:
        async def complete(self, request, *, request_id):
            raise AdmissionRejected("capacity")

        async def open_stream(self, request, *, request_id):
            raise AdmissionRejected("queue_timeout")

    client.app.state.service = RejectingService()  # type: ignore[attr-defined]
    response = client.post("/chat", json=request_body())
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    stream = client.post("/chat/stream", json=request_body())
    assert stream.status_code == 429


def test_stream_emits_meta_tokens_then_done(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = stream_body()
    response = client.post("/chat/stream", json=request_body())
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert "event: meta" in response.text
    assert response.text.count("event: token") == 2
    assert "event: done" in response.text
    done = [
        json.loads(line[5:].strip())
        for line in response.text.splitlines()
        if line.startswith("data:") and '"ttft_ms"' in line
    ][0]
    assert done["usage"]["completion_tokens"] == 2
    assert done["ttft_ms"] >= 0
    assert done["latency_ms"] >= 0
    assert fake.stream_calls[0]["stream"] is True


def test_stream_marks_upstream_payload_as_streaming(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = stream_body()
    client.post("/chat/stream", json=request_body())
    assert fake.stream_calls[0]["body"]["stream"] is True
    assert fake.stream_calls[0]["body"]["stream_options"] == {"include_usage": True}


@pytest.mark.parametrize(
    ("behavior", "status_code"),
    [
        ("timeout", 504),
        ("connect_error", 503),
        ("read_error", 502),
        ("upstream_error", 500),
    ],
)
def test_stream_open_failures_are_translated(
    gateway_client: tuple[TestClient, FakeUpstream],
    behavior: str,
    status_code: int,
) -> None:
    client, fake = gateway_client
    fake.stream_behavior = behavior
    response = client.post("/chat/stream", json=request_body())
    assert response.status_code == status_code


def test_stream_without_done_sentinel_is_an_error_event(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = stream_body(done=False)
    response = client.post("/chat/stream", json=request_body())
    assert "event: error" in response.text


def test_stream_malformed_chunk_becomes_an_error_event(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = b"data: not-json\n\n"
    response = client.post("/chat/stream", json=request_body())
    assert response.status_code == 200
    assert "event: error" in response.text


def test_stream_connect_failure_is_retried(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.connect_failures_remaining = 1
    fake.stream_body = stream_body()
    response = client.post("/chat/stream", json=request_body())
    assert response.status_code == 200
    assert "event: done" in response.text
    assert len(fake.stream_calls) == 2


def test_stream_error_body_read_failure_releases_admission_slot(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_behavior = "broken_error"
    response = client.post("/chat/stream", json=request_body())
    assert response.status_code == 502
    status = client.get("/gateway/status").json()
    assert status["active"] == 0


def test_stream_releases_admission_slot(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, fake = gateway_client
    fake.stream_body = stream_body()
    client.post("/chat/stream", json=request_body())
    status = client.get("/gateway/status").json()
    assert status["active"] == 0
    assert status["waiting"] == 0


def test_rate_limiter_window_and_overflow_bucket() -> None:
    now = [1000.0]
    limiter = SlidingWindowLimiter(2, max_identities=1, clock=lambda: now[0])

    async def scenario() -> None:
        assert await limiter.check("a") == (True, 0)
        assert await limiter.check("a") == (True, 0)
        assert (await limiter.check("a"))[0] is False
        assert await limiter.check("b") == (True, 0)
        assert "__overflow__" in limiter._events
        now[0] += 60.1
        assert await limiter.check("a") == (True, 0)

    asyncio.run(scenario())


def test_rate_limit_is_per_identity() -> None:
    client, _ = make_client(GatewaySettings(rate_limit_per_minute=2))
    with client:
        assert client.post("/chat", json=request_body()).status_code == 200
        assert client.post("/chat", json=request_body()).status_code == 200
        assert client.post("/chat", json=request_body()).status_code == 429


def test_trusted_proxy_headers_change_rate_limit_identity() -> None:
    client, _ = make_client(
        GatewaySettings(
            rate_limit_per_minute=1,
            trust_proxy_headers=True,
        )
    )
    with client:
        headers_a = {"X-Forwarded-For": "203.0.113.10"}
        headers_b = {"X-Forwarded-For": "203.0.113.11"}
        assert client.post("/chat", json=request_body(), headers=headers_a).status_code == 200
        assert client.post("/chat", json=request_body(), headers=headers_a).status_code == 429
        assert client.post("/chat", json=request_body(), headers=headers_b).status_code == 200


def test_untrusted_api_key_does_not_bypass_ip_limit() -> None:
    client, _ = make_client(GatewaySettings(rate_limit_per_minute=1))
    with client:
        first = client.post(
            "/chat", json=request_body(), headers={"X-API-Key": "rotating-a"}
        )
        second = client.post(
            "/chat", json=request_body(), headers={"X-API-Key": "rotating-b"}
        )
        assert first.status_code == 200
        assert second.status_code == 429


def test_rate_limit_is_per_authenticated_key() -> None:
    client, _ = make_client(
        GatewaySettings(
            api_keys=("tenant-a", "tenant-b"),
            rate_limit_per_minute=1,
        )
    )
    with client:
        first = client.post(
            "/chat", json=request_body(), headers={"X-API-Key": "tenant-a"}
        )
        second = client.post(
            "/chat", json=request_body(), headers={"X-API-Key": "tenant-a"}
        )
        third = client.post(
            "/chat", json=request_body(), headers={"X-API-Key": "tenant-b"}
        )
        assert first.status_code == 200
        assert second.status_code == 429
        assert third.status_code == 200


def test_json_formatter_emits_required_fields() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        "inference-gateway",
        logging.INFO,
        __file__,
        1,
        "request_complete",
        (),
        None,
    )
    record.event = "request_complete"
    record.request_id = "req-1"
    record.outcome = "success"
    payload = json.loads(formatter.format(record))
    assert payload["event"] == "request_complete"
    assert payload["request_id"] == "req-1"
    assert payload["outcome"] == "success"


def test_disconnect_watcher_closes_the_upstream_stream() -> None:
    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    class ClosableStream:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    stream = ClosableStream()
    asyncio.run(close_on_disconnect(DisconnectedRequest(), stream))  # type: ignore[arg-type]
    assert stream.closed is True


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, 60)

    async def aclose(self) -> None:
        return None


def test_redis_limiter_is_shared_state_compatible() -> None:
    async def scenario() -> None:
        redis = FakeRedis()
        first = RedisRateLimiter(2, redis)
        second = RedisRateLimiter(2, redis)
        assert await first.check("tenant") == (True, 0)
        assert await second.check("tenant") == (True, 0)
        allowed, retry_after = await first.check("tenant")
        assert allowed is False
        assert retry_after >= 1

    asyncio.run(scenario())


def test_metrics_registry_contains_gateway_metrics(
    gateway_client: tuple[TestClient, FakeUpstream],
) -> None:
    client, _ = gateway_client
    assert client.post("/chat", json=request_body()).status_code == 200
    names = {
        sample.name
        for metric in client.app.state.metrics.registry.collect()
        for sample in metric.samples
    }
    assert "inference_gateway_requests_total" in names
    assert "inference_gateway_ttft_seconds_count" in names
    assert "inference_gateway_upstream_healthy" in names
