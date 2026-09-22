#!/usr/bin/env python3
"""Measure how a long prefill interferes with an active streaming request."""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
import uuid

import httpx
from transformers import AutoTokenizer


BASE_URL = os.environ.get("VLLM_BASE_URL", "http://127.0.1.1:8000/v1")
MODEL = os.environ.get("VLLM_MODEL", "Qwen3.5-4B-FP8")
MODEL_DIR = os.environ.get(
    "VLLM_MODEL_DIR", "/mnt/e/Desktop/qwen3.5/model/qwen3.5-4b-fp8"
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return ordered[index]


def stream_completion(prompt: str, max_tokens: int, timestamps: list[float]) -> None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0,
        "ignore_eos": True,
        "stream": True,
    }
    with httpx.Client(timeout=90.0) as client:
        with client.stream("POST", f"{BASE_URL}/completions", json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                event = json.loads(line[6:])
                choices = event.get("choices", [])
                if choices and choices[0].get("text", ""):
                    timestamps.append(time.perf_counter())


def make_long_prompt(target_tokens: int) -> tuple[str, int]:
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_DIR, local_files_only=True, trust_remote_code=True
    )
    marker = f"实验批次{uuid.uuid4().hex}。以下是一份从未缓存过的技术文档：\n"
    body = (
        "推理服务器通过调度请求、管理KV缓存和组织GPU批次来平衡吞吐与延迟。"
        "长提示词需要先进行预填充计算，之后才能进入逐token生成阶段。\n"
    ) * 120
    token_ids = tokenizer.encode(marker + body, add_special_tokens=False)[:target_tokens]
    prompt = tokenizer.decode(token_ids, skip_special_tokens=True)
    actual_tokens = len(tokenizer.encode(prompt, add_special_tokens=False))
    return prompt, actual_tokens


def main() -> None:
    long_prompt, long_tokens = make_long_prompt(1800)
    decoder_prompt = (
        f"实验批次{uuid.uuid4().hex}。请不断输出自然数，每个数字用逗号分隔："
    )

    decoder_times: list[float] = []
    long_times: list[float] = []
    decoder_started = time.perf_counter()
    decoder = threading.Thread(
        target=stream_completion,
        args=(decoder_prompt, 384, decoder_times),
        daemon=True,
    )
    decoder.start()

    deadline = time.perf_counter() + 15
    while not decoder_times and time.perf_counter() < deadline:
        time.sleep(0.005)
    if not decoder_times:
        raise RuntimeError("持续生成请求未收到第一个token")

    # Let the decoder reach steady state before injecting the long prompt.
    time.sleep(0.20)
    long_started = time.perf_counter()
    long_request = threading.Thread(
        target=stream_completion,
        args=(long_prompt, 8, long_times),
        daemon=True,
    )
    long_request.start()
    long_request.join()
    long_finished = time.perf_counter()
    decoder.join()

    intervals = [
        (right - left) * 1000
        for left, right in zip(decoder_times, decoder_times[1:])
    ]
    overlapping = [
        (right - left) * 1000
        for left, right in zip(decoder_times, decoder_times[1:])
        if left <= long_finished and right >= long_started
    ]

    decoder_ttft = (decoder_times[0] - decoder_started) * 1000
    long_ttft = (
        (long_times[0] - long_started) * 1000 if long_times else float("nan")
    )
    print("\n===== Chunked Prefill 混合负载 =====")
    print(f"长请求输入：              {long_tokens} tokens")
    print(f"持续生成请求收到：        {len(decoder_times)} 个流式片段")
    print(f"持续生成请求 TTFT：       {decoder_ttft:.1f} ms")
    print(f"正常生成 ITL 中位数：     {statistics.median(intervals):.1f} ms")
    print(f"正常生成 ITL P99：        {percentile(intervals, 0.99):.1f} ms")
    print(f"长Prefill期间最大停顿：   {max(overlapping):.1f} ms")
    print(f"长请求 TTFT：             {long_ttft:.1f} ms")
    print(f"长请求 E2E：              {(long_finished - long_started) * 1000:.1f} ms")


if __name__ == "__main__":
    main()
