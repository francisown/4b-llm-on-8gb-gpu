#!/usr/bin/env python3
"""Run a small, realistic multi-user chat load test against vLLM."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import aiohttp


TOPICS = [
    "KV Cache",
    "连续批处理",
    "Transformer 自回归推理",
    "首 token 延迟",
    "吞吐量与并发的关系",
    "模型量化",
    "FP8 与 BF16 的区别",
    "显存带宽瓶颈",
]


@dataclass
class RequestResult:
    user_id: int
    turn: int
    ok: bool
    ttft_ms: float | None
    latency_ms: float
    output_chars: int
    error: str | None = None


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


async def stream_reply(
    client: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    user_id: int,
    turn: int,
) -> tuple[RequestResult, str]:
    start = time.perf_counter()
    first_token_at: float | None = None
    pieces: list[str] = []

    try:
        async with semaphore:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": True,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            async with client.post(endpoint, json=payload) as response:
                if response.status != 200:
                    detail = await response.text()
                    raise RuntimeError(f"HTTP {response.status}: {detail[:500]}")

                async for raw_line in response.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    content = choices[0].get("delta", {}).get("content")
                    if content:
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                        pieces.append(content)
    except Exception as exc:  # Keep the other virtual users running.
        end = time.perf_counter()
        return (
            RequestResult(
                user_id=user_id,
                turn=turn,
                ok=False,
                ttft_ms=None,
                latency_ms=(end - start) * 1000,
                output_chars=0,
                error=f"{type(exc).__name__}: {exc}",
            ),
            "",
        )

    end = time.perf_counter()
    answer = "".join(pieces)
    ttft_ms = ((first_token_at or end) - start) * 1000
    return (
        RequestResult(
            user_id=user_id,
            turn=turn,
            ok=True,
            ttft_ms=ttft_ms,
            latency_ms=(end - start) * 1000,
            output_chars=len(answer),
        ),
        answer,
    )


async def run_user(
    user_id: int,
    turns: int,
    client: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    endpoint: str,
    model: str,
    max_tokens: int,
) -> tuple[list[RequestResult], str]:
    topic = TOPICS[(user_id - 1) % len(TOPICS)]
    prompts = [
        f"请用不超过三句话解释{topic}。",
        f"请继续针对{topic}举一个简单例子。",
        f"请把刚才关于{topic}的内容压缩成一句话。",
    ]
    messages: list[dict[str, str]] = []
    results: list[RequestResult] = []
    latest_answer = ""

    for turn in range(1, turns + 1):
        prompt = prompts[(turn - 1) % len(prompts)] + " /no_think"
        messages.append({"role": "user", "content": prompt})
        result, answer = await stream_reply(
            client,
            semaphore,
            endpoint,
            model,
            messages,
            max_tokens,
            user_id,
            turn,
        )
        results.append(result)
        if not result.ok:
            break
        messages.append({"role": "assistant", "content": answer})
        latest_answer = answer

    return results, latest_answer


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=64)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="Qwen/Qwen3-0.6B")
    parser.add_argument(
        "--output",
        default="benchmark/results/real-chat-u64-t3.json",
    )
    args = parser.parse_args()

    if args.users < 1 or args.turns < 1 or args.concurrency < 1:
        parser.error("users, turns and concurrency must all be positive")

    semaphore = asyncio.Semaphore(args.concurrency)
    endpoint = args.base_url.rstrip("/") + "/chat/completions"
    timeout = aiohttp.ClientTimeout(total=180.0)
    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0, enable_cleanup_closed=True)

    started = time.perf_counter()
    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={"Authorization": "Bearer EMPTY"},
    ) as client:
        sessions = await asyncio.gather(
            *(
                run_user(
                    user_id,
                    args.turns,
                    client,
                    semaphore,
                    endpoint,
                    args.model,
                    args.max_tokens,
                )
                for user_id in range(1, args.users + 1)
            )
        )
    wall_seconds = time.perf_counter() - started

    results = [result for session, _ in sessions for result in session]
    successful = [result for result in results if result.ok]
    failed = [result for result in results if not result.ok]
    ttfts = [result.ttft_ms for result in successful if result.ttft_ms is not None]
    latencies = [result.latency_ms for result in successful]

    summary = {
        "users": args.users,
        "turns_per_user": args.turns,
        "concurrency_limit": args.concurrency,
        "attempted_requests": len(results),
        "successful_requests": len(successful),
        "failed_requests": len(failed),
        "wall_seconds": wall_seconds,
        "request_throughput": len(successful) / wall_seconds if wall_seconds else 0,
        "ttft_p50_ms": percentile(ttfts, 50),
        "ttft_p95_ms": percentile(ttfts, 95),
        "ttft_p99_ms": percentile(ttfts, 99),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "latency_p99_ms": percentile(latencies, 99),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "requests": [asdict(result) for result in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== Real multi-user chat result =====")
    print(f"Virtual users:       {args.users}")
    print(f"Turns per user:      {args.turns}")
    print(f"Concurrency limit:   {args.concurrency}")
    print(f"Successful requests: {len(successful)}/{len(results)}")
    print(f"Wall time:           {wall_seconds:.2f} s")
    print(f"Request throughput:  {summary['request_throughput']:.2f} req/s")
    print(f"TTFT P50/P95/P99:    {summary['ttft_p50_ms']:.1f} / {summary['ttft_p95_ms']:.1f} / {summary['ttft_p99_ms']:.1f} ms")
    print(f"E2E  P50/P95/P99:    {summary['latency_p50_ms']:.1f} / {summary['latency_p95_ms']:.1f} / {summary['latency_p99_ms']:.1f} ms")
    print(f"Saved result:        {output_path}")

    if failed:
        print("\nFirst errors:")
        for result in failed[:5]:
            print(f"  user={result.user_id} turn={result.turn}: {result.error}")

    print("\nSample final answers:")
    for user_id, (_, answer) in enumerate(sessions[:3], start=1):
        print(f"  user {user_id}: {answer[:160].replace(chr(10), ' ')}")


if __name__ == "__main__":
    asyncio.run(main())
