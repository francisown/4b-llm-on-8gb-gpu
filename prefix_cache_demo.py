#!/usr/bin/env python3
"""Demonstrate vLLM automatic prefix caching with measurable cache hits."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass

import httpx


BASE_URL = os.environ.get("VLLM_BASE_URL", "http://127.0.1.1:8000/v1")
MODEL = os.environ.get("VLLM_MODEL", "Qwen3.5-4B-FP8")
METRICS_URL = BASE_URL.removesuffix("/v1") + "/metrics"


@dataclass
class CacheCounters:
    queries: float
    hits: float


def read_cache_counters(client: httpx.Client) -> CacheCounters:
    metrics = client.get(METRICS_URL).text

    def value(metric: str) -> float:
        pattern = rf"^{re.escape(metric)}\{{[^}}]*\}}\s+([0-9.eE+-]+)$"
        match = re.search(pattern, metrics, flags=re.MULTILINE)
        if match is None:
            raise RuntimeError(f"找不到指标：{metric}")
        return float(match.group(1))

    return CacheCounters(
        queries=value("vllm:prefix_cache_queries_total"),
        hits=value("vllm:prefix_cache_hits_total"),
    )


def run_request(client: httpx.Client, name: str, prompt: str) -> None:
    before = read_cache_counters(client)
    started = time.perf_counter()
    first_token_at: float | None = None
    generated = ""

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "max_tokens": 16,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    with client.stream("POST", f"{BASE_URL}/completions", json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[6:])
            choices = event.get("choices", [])
            if choices:
                text = choices[0].get("text", "")
                if text and first_token_at is None:
                    first_token_at = time.perf_counter()
                generated += text

    finished = time.perf_counter()
    after = read_cache_counters(client)
    queried = int(after.queries - before.queries)
    hits = int(after.hits - before.hits)
    hit_rate = hits / queried * 100 if queried else 0.0
    ttft_ms = (first_token_at - started) * 1000 if first_token_at else float("nan")
    e2e_ms = (finished - started) * 1000

    print(
        f"{name:<16} 查询 {queried:>4} tokens | "
        f"命中 {hits:>4} tokens ({hit_rate:>5.1f}%) | "
        f"TTFT {ttft_ms:>7.1f} ms | E2E {e2e_ms:>7.1f} ms"
    )


def main() -> None:
    # The first character deliberately differs between A and B. Prefix-cache
    # blocks form a chain, so changing the beginning prevents a false hit even
    # though the following document text has the same length.
    body = (
        "连续批处理把多个请求组织到同一次GPU计算中，提高计算单元利用率；"
        "KV Cache保存已处理token的注意力状态，避免自回归生成时重复计算。\n"
    ) * 24
    run_id = uuid.uuid4().hex
    prefix_a = f"实验批次{run_id}，A类共享文档。\n" + body + "文档结束。\n问题："
    prefix_b = f"实验批次{run_id}，B类独立文档。\n" + body + "文档结束。\n问题："

    with httpx.Client(timeout=60.0) as client:
        health = client.get(BASE_URL.removesuffix("/v1") + "/health")
        health.raise_for_status()

        print("\n===== Prefix Cache 对照实验 =====")
        print("冷请求：此前没见过该前缀；热请求：复用刚才的长前缀。\n")
        run_request(client, "A 冷请求", prefix_a + "什么是连续批处理？")
        run_request(client, "A 热请求", prefix_a + "KV Cache解决什么问题？")
        run_request(client, "B 冷对照", prefix_b + "什么是连续批处理？")
        run_request(client, "B 热请求", prefix_b + "KV Cache解决什么问题？")


if __name__ == "__main__":
    main()
