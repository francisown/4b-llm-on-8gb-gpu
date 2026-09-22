"""Reproduce the best-case N-gram speculative-decoding throughput."""

from __future__ import annotations

import os
import statistics
import subprocess
import time

from openai import OpenAI


def default_base_url() -> str:
    ip = subprocess.check_output(["hostname", "-I"], text=True).split()[0]
    return f"http://{ip}:8000/v1"


base_url = os.getenv("VLLM_BASE_URL", default_base_url())
client = OpenAI(base_url=base_url, api_key="x")
prompt = "Continue the exact pattern, one line at a time:\n" + (
    "alpha beta gamma delta epsilon\n" * 20
)


def run() -> float:
    started = time.perf_counter()
    response = client.completions.create(
        model="Qwen3.5-4B-INT4-AWQ-self",
        prompt=prompt,
        max_tokens=256,
        temperature=0,
        extra_body={"ignore_eos": True},
    )
    elapsed = time.perf_counter() - started
    tokens = response.usage.completion_tokens
    print(f"{tokens} tokens | {elapsed:.3f} s | {tokens / elapsed:.2f} tok/s")
    return elapsed


print(f"Server: {base_url}")
print("Warmup (not counted):")
run()

print("Measured runs:")
times = [run() for _ in range(3)]
print(f"Mean: {256 / statistics.mean(times):.2f} tok/s")
