"""Send a burst large enough to demonstrate gateway backpressure."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import statistics
import time

import httpx


async def main(users: int, base_url: str) -> None:
    start = asyncio.Event()
    stop_monitor = asyncio.Event()
    peak_active = 0
    peak_waiting = 0

    async with httpx.AsyncClient(timeout=30) as client:
        async def one(user_id: int) -> tuple[int, float]:
            await start.wait()
            began = time.perf_counter()
            response = await client.post(
                f"{base_url}/chat",
                headers={"X-Request-ID": f"load-{user_id:02d}"},
                json={
                    "message": "用编号列出十二条学习大模型推理工程的建议，每条一句话。",
                    "max_tokens": 128,
                    "temperature": 0,
                    "enable_thinking": False,
                },
            )
            return response.status_code, time.perf_counter() - began

        async def monitor() -> None:
            nonlocal peak_active, peak_waiting
            while not stop_monitor.is_set():
                response = await client.get(f"{base_url}/gateway/status")
                status = response.json()
                peak_active = max(peak_active, status["active"])
                peak_waiting = max(peak_waiting, status["waiting"])
                await asyncio.sleep(0.02)

        tasks = [asyncio.create_task(one(i)) for i in range(1, users + 1)]
        monitor_task = asyncio.create_task(monitor())
        wall_started = time.perf_counter()
        start.set()
        results = await asyncio.gather(*tasks)
        wall_time = time.perf_counter() - wall_started
        stop_monitor.set()
        await monitor_task

    counts = Counter(status for status, _ in results)
    successful_times = [elapsed for status, elapsed in results if status == 200]
    print("===== Gateway admission result =====")
    print(f"Burst requests: {users}")
    print(f"HTTP status counts: {dict(sorted(counts.items()))}")
    print(f"Peak active/waiting: {peak_active}/{peak_waiting}")
    print(f"Wall time: {wall_time:.2f} s")
    if successful_times:
        ordered = sorted(successful_times)
        p50 = statistics.median(ordered)
        p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
        print(f"Successful E2E P50/P95: {p50:.2f}/{p95:.2f} s")
    if counts[200] == 0 or counts[429] == 0:
        raise SystemExit("Expected both successful and rejected requests")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=16)
    parser.add_argument("--base-url", default="http://10.28.111.88:9000")
    args = parser.parse_args()
    asyncio.run(main(args.users, args.base_url.rstrip("/")))
