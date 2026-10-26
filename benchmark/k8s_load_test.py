"""Small, dependency-light load generator for the gateway contract.

It works against any OpenAI-compatible gateway exposing /chat or /chat/stream.
The summary is intentionally machine-readable so it can be checked into a
benchmark report without hand-copying numbers.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import statistics
import time
from typing import Any

import httpx


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))
    return round(ordered[index], 2)


def summarize(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "p99": None}
    return {
        "mean": round(statistics.mean(values), 2),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


async def one_request(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    *,
    stream: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    pod = None
    ttft_ms: float | None = None
    completion_tokens = 0
    error = None
    try:
        if stream:
            async with client.stream("POST", url, json=payload) as response:
                pod = response.headers.get("X-Gateway-Pod")
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    return {
                        "ok": False,
                        "status": response.status_code,
                        "error": body[:300],
                        "latency_ms": (time.perf_counter() - started) * 1_000,
                        "pod": pod,
                    }
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    data = json.loads(raw)
                    if "text" in data and ttft_ms is None:
                        ttft_ms = (time.perf_counter() - started) * 1_000
                    if "usage" in data:
                        completion_tokens = int(data["usage"].get("completion_tokens") or 0)
                    if "ttft_ms" in data:
                        ttft_ms = float(data["ttft_ms"])
        else:
            response = await client.post(url, json=payload)
            pod = response.headers.get("X-Gateway-Pod")
            if response.status_code != 200:
                return {
                    "ok": False,
                    "status": response.status_code,
                    "error": response.text[:300],
                    "latency_ms": (time.perf_counter() - started) * 1_000,
                    "pod": pod,
                }
            data = response.json()
            completion_tokens = int((data.get("usage") or {}).get("completion_tokens") or 0)
    except Exception as exc:  # noqa: BLE001 - recorded as a load-test failure
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - started) * 1_000
    return {
        "ok": error is None,
        "status": 200 if error is None else None,
        "error": error,
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "completion_tokens": completion_tokens,
        "pod": pod,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "message": args.prompt,
        "max_tokens": args.max_tokens,
        "temperature": 0,
        "enable_thinking": False,
    }
    limits = httpx.Limits(
        max_connections=max(args.concurrency * 2, 8),
        max_keepalive_connections=max(args.concurrency, 4),
    )
    timeout = httpx.Timeout(args.timeout, connect=5.0)
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        for _ in range(args.warmup):
            await one_request(client, args.url, payload, stream=args.stream)

        async def worker() -> dict[str, Any]:
            async with semaphore:
                return await one_request(client, args.url, payload, stream=args.stream)

        started = time.perf_counter()
        results = await asyncio.gather(*(worker() for _ in range(args.requests)))
        duration = time.perf_counter() - started

    latencies = [r["latency_ms"] for r in results if r["ok"]]
    ttfts = [r["ttft_ms"] for r in results if r["ok"] and r["ttft_ms"] is not None]
    completion_tokens = sum(r.get("completion_tokens") or 0 for r in results if r["ok"])
    pods = Counter(r["pod"] for r in results if r["ok"] and r["pod"])
    errors = [r for r in results if not r["ok"]]
    summary = {
        "url": args.url,
        "stream": args.stream,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "warmup": args.warmup,
        "duration_s": round(duration, 3),
        "success": len(latencies),
        "errors": len(errors),
        "error_rate": round(len(errors) / args.requests, 4),
        "throughput_rps": round(len(latencies) / duration, 3) if duration else None,
        "completion_tokens": completion_tokens,
        "tokens_per_second": round(completion_tokens / duration, 3) if duration else None,
        "latency_ms": summarize(latencies),
        "ttft_ms": summarize(ttfts) if args.stream else None,
        "pods": dict(pods),
        "error_samples": [e.get("error") for e in errors[:3]],
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9000/chat")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--prompt", default="Explain in one sentence why KV cache matters.")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run(args))
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
