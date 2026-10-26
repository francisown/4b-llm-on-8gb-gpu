from __future__ import annotations

import asyncio
import pytest
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm8g.serving.admission import AdmissionController  # noqa: E402
from llm8g.serving.config import GatewaySettings  # noqa: E402
from llm8g.serving.errors import AdmissionRejected, ContextLimitExceeded  # noqa: E402
from llm8g.serving.limits import SlidingWindowLimiter  # noqa: E402
from llm8g.serving.models import ChatRequest, StreamEvent, TokenUsage  # noqa: E402
from llm8g.serving.service import GatewayService  # noqa: E402
from llm8g.serving.security import AuthPolicy, AuthenticationFailed  # noqa: E402


class FakeBackend:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def complete(self, request: ChatRequest, *, request_id: str):
        return "ok", TokenUsage(1, 2, 3), "fake"

    async def stream(self, request: ChatRequest, *, request_id: str):
        yield StreamEvent("token", {"text": "ok", "channel": "answer"})

    async def open_stream(self, request: ChatRequest, *, request_id: str):
        async def events():
            yield StreamEvent("token", {"text": "ok", "channel": "answer"})

        return events()

    async def health(self) -> bool:
        return True


class CoreTests(unittest.TestCase):
    def test_settings_are_explicit_and_validated(self) -> None:
        settings = GatewaySettings.from_env(
            {
                "VLLM_BASE_URL": "http://model/",
                "GATEWAY_MAX_QUEUE": "0",
                "GATEWAY_API_KEY": "one",
                "GATEWAY_API_KEYS": "two,one",
            }
        )
        self.assertEqual(settings.upstream_url, "http://model")
        self.assertEqual(settings.api_keys, ("one", "two"))
        with self.assertRaises(ValueError):
            GatewaySettings.from_env({"GATEWAY_MAX_CONCURRENT": "0"})

    def test_settings_can_load_a_profile_with_environment_overrides(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "profile.env"
            path.write_text(
                "MODEL_NAME=profile\nGATEWAY_MAX_QUEUE=1\n",
                encoding="utf-8",
            )
            settings = GatewaySettings.from_file(path, env={"GATEWAY_MAX_QUEUE": "2"})
            self.assertEqual(settings.model, "profile")
            self.assertEqual(settings.max_queue, 2)

    def test_request_mapping_and_context_guard(self) -> None:
        request = ChatRequest.from_mapping({"message": "hello", "max_tokens": 8})
        service = GatewayService(
            GatewaySettings(max_context_tokens=20),
            FakeBackend(),
            AdmissionController(1, 0, 0.1),
        )
        with self.assertRaises(ContextLimitExceeded):
            service.validate_context(ChatRequest(message="中" * 20, max_tokens=8))
        self.assertEqual(request.messages()[-1]["content"], "hello")

    def test_complete_releases_admission_lease(self) -> None:
        async def scenario() -> None:
            controller = AdmissionController(1, 0, 0.1)
            service = GatewayService(GatewaySettings(), FakeBackend(), controller)
            result = await service.complete(ChatRequest(message="hello"), request_id="r1")
            self.assertEqual(result.answer, "ok")
            self.assertEqual((await controller.snapshot())["active"], 0)

        asyncio.run(scenario())

    def test_open_stream_acquires_before_response_and_can_be_closed_unread(self) -> None:
        async def scenario() -> None:
            controller = AdmissionController(1, 0, 0.1)
            service = GatewayService(GatewaySettings(), FakeBackend(), controller)
            lease, stream = await service.open_stream(ChatRequest(message="hello"), request_id="r1")
            self.assertEqual((await controller.snapshot())["active"], 1)
            await lease.release()
            self.assertEqual((await controller.snapshot())["active"], 0)
            await stream.aclose()

        asyncio.run(scenario())

    def test_capacity_is_rejected_without_touching_backend(self) -> None:
        async def scenario() -> None:
            controller = AdmissionController(1, 0, 0.01)
            held = await controller.acquire()
            service = GatewayService(GatewaySettings(), FakeBackend(), controller)
            with self.assertRaises(AdmissionRejected):
                await service.complete(ChatRequest(message="hello"), request_id="r2")
            await held.release()

        asyncio.run(scenario())

    def test_limiter_window_and_overflow_bucket(self) -> None:
        now = [1000.0]
        limiter = SlidingWindowLimiter(2, max_identities=1, clock=lambda: now[0])

        async def scenario() -> None:
            self.assertEqual(await limiter.check("a"), (True, 0))
            self.assertEqual(await limiter.check("a"), (True, 0))
            self.assertFalse((await limiter.check("a"))[0])
            self.assertEqual(await limiter.check("b"), (True, 0))
            self.assertIn("__overflow__", limiter._events)
            now[0] += 60.1
            self.assertEqual(await limiter.check("a"), (True, 0))

        asyncio.run(scenario())

    def test_auth_policy_uses_ip_until_keys_are_configured(self) -> None:
        async def scenario() -> None:
            open_policy = AuthPolicy()
            identity = await open_policy.identity("rotating", "127.0.0.1")
            self.assertEqual(identity.value, "ip:127.0.0.1")
            protected = AuthPolicy(
                ("secret",),
                auth_failure_limiter=SlidingWindowLimiter(1),
            )
            with self.assertRaises(AuthenticationFailed):
                await protected.identity("wrong", "127.0.0.1")
            with self.assertRaises(AuthenticationFailed) as blocked:
                await protected.identity("wrong", "127.0.0.1")
            self.assertIsNotNone(blocked.exception.retry_after)
            identity = await protected.identity("secret", "127.0.0.1")
            self.assertTrue(identity.value.startswith("key:"))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()

def test_admission_capacity_and_queue_timeout_paths() -> None:
    async def scenario() -> None:
        saturated = AdmissionController(1, 0, 0.1)
        held = await saturated.acquire()
        try:
            with pytest.raises(AdmissionRejected):
                await saturated.acquire()
        finally:
            await held.release()

        queued = AdmissionController(1, 1, 0.01)
        held = await queued.acquire()
        try:
            with pytest.raises(AdmissionRejected) as exc:
                await queued.acquire()
            assert exc.value.reason == "queue_timeout"
        finally:
            await held.release()

    asyncio.run(scenario())
