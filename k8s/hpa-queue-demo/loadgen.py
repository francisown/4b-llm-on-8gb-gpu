"""In-cluster load generator for the queue-depth HPA demo.

Deliberately small: it only needs to keep enough requests in flight to hold the
gateway admission queue non-empty, so the External metric and the HPA have
something to react to. It is not a benchmark harness.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx

URL = os.environ.get("LOADGEN_URL", "http://gateway:9000/chat")
WORKERS = int(os.environ.get("LOADGEN_WORKERS", "32"))
SECONDS = int(os.environ.get("LOADGEN_SECONDS", "240"))


async def worker(client: httpx.AsyncClient, deadline: float, counter: dict[str, int]) -> None:
    while time.time() < deadline:
        try:
            response = await client.post(
                URL,
                json={"message": "queue depth demo", "max_tokens": 16},
                timeout=60.0,
            )
            key = str(response.status_code)
        except Exception:
            key = "error"
        counter[key] = counter.get(key, 0) + 1


async def main() -> None:
    deadline = time.time() + SECONDS
    counter: dict[str, int] = {}
    started = time.time()
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *[worker(client, deadline, counter) for _ in range(WORKERS)]
        )
    elapsed = round(time.time() - started, 1)
    total = sum(counter.values())
    print(f"elapsed_s={elapsed} workers={WORKERS} total={total} outcomes={counter}")


if __name__ == "__main__":
    asyncio.run(main())
