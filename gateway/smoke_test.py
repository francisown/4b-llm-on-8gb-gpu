"""End-to-end smoke test for the running inference gateway."""

from __future__ import annotations

import os

import httpx


BASE_URL = os.getenv("GATEWAY_BASE_URL", "http://10.28.111.88:9000")

live = httpx.get(f"{BASE_URL}/live")
assert live.status_code == 200, live.text

health = httpx.get(f"{BASE_URL}/health")
assert health.status_code == 200, health.text

gateway_status = httpx.get(f"{BASE_URL}/gateway/status")
assert gateway_status.status_code == 200, gateway_status.text
assert gateway_status.json()["max_concurrent"] >= 1

index = httpx.get(BASE_URL)
assert index.status_code == 200, index.text
assert "本地 AI 推理实验室" in index.text

response = httpx.post(
    f"{BASE_URL}/chat",
    headers={"X-Request-ID": "smoke-001"},
    json={
        "message": "只用一句话说明什么是推理网关。",
        "max_tokens": 64,
        "temperature": 0,
        "enable_thinking": False,
        "history": [
            {"role": "user", "content": "请记住代号是蓝鲸。"},
            {"role": "assistant", "content": "好的，我记住了。"},
        ],
    },
    timeout=30,
)
assert response.status_code == 200, response.text
body = response.json()
assert body["request_id"] == "smoke-001"
assert isinstance(body["answer"], str) and body["answer"]
assert set(body["usage"]) == {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
}

invalid = httpx.post(
    f"{BASE_URL}/chat",
    json={"message": "test", "max_tokens": 0},
)
assert invalid.status_code == 422, invalid.text

with httpx.stream(
    "POST",
    f"{BASE_URL}/chat/stream",
    headers={"X-Request-ID": "smoke-stream-001"},
    json={
        "message": "只回答：流式测试成功",
        "max_tokens": 32,
        "temperature": 0,
        "enable_thinking": False,
    },
    timeout=30,
) as stream:
    assert stream.status_code == 200, stream.read().decode("utf-8", "replace")
    event_stream = "".join(stream.iter_text())
assert "event: token" in event_stream, event_stream
assert "event: done" in event_stream, event_stream
assert "smoke-stream-001" in event_stream, event_stream

metrics = httpx.get(f"{BASE_URL}/metrics")
assert metrics.status_code == 200, metrics.text
assert "inference_gateway_requests_total" in metrics.text
assert "inference_gateway_ttft_seconds" in metrics.text
print("PASS: page, live/readiness, chat, SSE, admission, metrics, and validation")
