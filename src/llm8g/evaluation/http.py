"""Small HTTP helpers shared by the evaluation CLIs."""

from __future__ import annotations

import json
import time
from typing import Any
import urllib.error
import urllib.request


def post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers or {"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def chat_completion(
    *,
    base_url: str,
    model: str,
    prompt: str,
    timeout: float,
    max_tokens: int = 8,
    temperature: float = 0,
    seed: int = 42,
) -> tuple[str, dict[str, int], float]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "seed": seed,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    data = post_json(
        base_url.rstrip("/") + "/chat/completions",
        payload,
        timeout,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": "Bearer EMPTY",
        },
    )
    latency = time.perf_counter() - started
    usage = data.get("usage") or {}
    return (
        data["choices"][0]["message"]["content"],
        {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
        latency,
    )
