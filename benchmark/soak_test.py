"""Closed-loop soak test for the gateway.

This is a gateway-stability test, not a model benchmark. It can run against the
CPU-only mock stack or a real vLLM-backed gateway; the summary records which URL
was used so the result is not ambiguous.
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


async def get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    try:
        response = await client.get(url)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return None
    return None


async def run(args: argparse.Namespace) -> dict[str, Any]:
    base = args.url.rsplit("/chat", 1)[0]
    status_url = base + "/gateway/status"
    health_url = base + "/health"
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

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        for _ in range(args.warmup):
            await client.post(args.url, json=payload)

        health_before = await get_json(client, health_url)
        status_before = await get_json(client, status_url)

        deadline = time.perf_counter() + args.duration
        latencies: list[float] = []
        statuses: Counter[str] = Counter()
        rejections: list[str] = []
        errors: list[str] = []
        attempts = 0
        started = time.perf_counter()

        async def worker() -> None:
            nonlocal attempts
            while time.perf_counter() < deadline:
                attempts += 1
                request_started = time.perf_counter()
                try:
                    response = await client.post(args.url, json=payload)
                    statuses[str(response.status_code)] += 1
                    if response.status_code == 200:
                        latencies.append((time.perf_counter() - request_started) * 1_000)
                    elif response.status_code == 429:
                        if len(rejections) < 5:
                            rejections.append(response.text[:200])
                    else:
                        if len(errors) < 5:
                            errors.append(f"HTTP {response.status_code}: {response.text[:200]}")
                except Exception as exc:  # noqa: BLE001 - recorded as a soak failure
                    if len(errors) < 5:
                        errors.append(f"{type(exc).__name__}: {exc}")
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        duration = time.perf_counter() - started

        # Let queued work drain before checking gauges.
        await asyncio.sleep(args.drain_seconds)
        health_after = await get_json(client, health_url)
        status_after = await get_json(client, status_url)

    rejected_count = statuses.get("429", 0)
    other_error_count = max(0, attempts - len(latencies) - rejected_count)
    summary = {
        "url": args.url,
        "duration_s": round(duration, 3),
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "requests": attempts,
        "success": len(latencies),
        "rejected_429": rejected_count,
        "errors": other_error_count,
        "error_rate": round(other_error_count / attempts, 6) if attempts else None,
        "rejection_rate": round(rejected_count / attempts, 6) if attempts else None,
        "throughput_rps": round(attempts / duration, 3) if duration else None,
        "success_rps": round(len(latencies) / duration, 3) if duration else None,
        "latency_ms": summarize(latencies),
        "status_counts": dict(statuses),
        "health_before": health_before,
        "health_after": health_after,
        "status_before": status_before,
        "status_after": status_after,
        "rejection_samples": rejections,
        "error_samples": errors[:5],
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9000/chat")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--drain-seconds", type=float, default=1.0)
    parser.add_argument("--prompt", default="Soak test request.")
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
