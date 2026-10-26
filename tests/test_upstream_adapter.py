from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover - optional serving extra
    httpx = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm8g.serving.config import GatewaySettings  # noqa: E402
from llm8g.serving.models import ChatRequest  # noqa: E402
from llm8g.serving.upstream import VllmHttpBackend  # noqa: E402


@unittest.skipIf(httpx is None, "httpx is required for the vLLM adapter test")
class VllmAdapterTests(unittest.TestCase):
    def test_complete_and_stream_use_the_openai_contract(self) -> None:
        assert httpx is not None
        stream_body = (
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1,'
            b'"total_tokens":2}}\n\n'
            b"data: [DONE]\n\n"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, request=request)
            if json.loads(request.content.decode())["stream"]:
                return httpx.Response(200, content=stream_body, request=request)
            return httpx.Response(
                200,
                json={
                    "model": "fake",
                    "choices": [{"message": {"content": "hello"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
                request=request,
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend = VllmHttpBackend(GatewaySettings(), client)

        async def scenario() -> None:
            answer, usage, model = await backend.complete(
                ChatRequest(message="hello"),
                request_id="r1",
            )
            self.assertEqual((answer, usage.total_tokens, model), ("hello", 2, "fake"))
            events = [
                event
                async for event in backend.stream(
                    ChatRequest(message="hello"),
                    request_id="r1",
                )
            ]
            self.assertEqual(events[0].payload["text"], "hi")
            self.assertEqual(events[1].kind, "usage")
            self.assertTrue(await backend.health())
            await backend.close()
            await client.aclose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()

