"""vLLM OpenAI-compatible adapter.

Only this module knows that the chosen runtime is vLLM over HTTP.  Replacing
vLLM therefore means implementing the small ``InferenceBackend`` port rather
than changing the gateway's policy or HTTP routes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any

import httpx

from .config import GatewaySettings
from .errors import (
    InvalidUpstreamResponse,
    UpstreamHTTPError,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from .models import ChatRequest, StreamEvent, TokenUsage


def _usage(raw: dict[str, Any] | None) -> TokenUsage:
    return TokenUsage.from_mapping(raw)


def normalize_unicode(text: str) -> str:
    """Replace isolated surrogates before encoding an SSE event as UTF-8."""
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


class VllmHttpBackend:
    """An ``InferenceBackend`` adapter for vLLM's chat-completions endpoint."""

    def __init__(self, settings: GatewaySettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=2.0,
                    read=self.settings.upstream_timeout_seconds,
                    write=10.0,
                    pool=5.0,
                )
            )

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("backend has not been started")
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def _payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": list(request.messages()),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": stream,
            "chat_template_kwargs": {"enable_thinking": request.enable_thinking},
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def _post(self, request: ChatRequest, *, request_id: str) -> httpx.Response:
        await self.start()
        last_error: httpx.ConnectError | None = None
        for attempt in range(self.settings.connect_retries + 1):
            try:
                return await self.client.post(
                    f"{self.settings.upstream_url}/v1/chat/completions",
                    json=self._payload(request, stream=False),
                    headers={"X-Request-ID": request_id},
                )
            except httpx.ConnectError as exc:
                last_error = exc
                if attempt < self.settings.connect_retries:
                    await asyncio.sleep(0.1 * (2**attempt))
        assert last_error is not None
        raise UpstreamUnavailable("vLLM is unavailable") from last_error

    async def complete(
        self,
        request: ChatRequest,
        *,
        request_id: str,
    ) -> tuple[str, TokenUsage, str]:
        try:
            response = await self._post(request, request_id=request_id)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout("vLLM request timed out") from exc
        if response.is_error:
            raise UpstreamHTTPError(response.status_code, response.text[:1_000])
        try:
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
            model = data.get("model", self.settings.model)
            if not isinstance(answer, str) or not isinstance(model, str):
                raise TypeError
            return answer, _usage(data.get("usage")), model
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise InvalidUpstreamResponse("invalid response from vLLM") from exc

    async def health(self) -> bool:
        await self.start()
        try:
            response = await self.client.get(
                f"{self.settings.upstream_url}/health",
                headers={"Connection": "close"},
                timeout=self.settings.health_timeout_seconds,
            )
            return response.is_success
        except httpx.HTTPError:
            return False

    async def open_stream(
        self,
        request: ChatRequest,
        *,
        request_id: str,
    ) -> AsyncIterator[StreamEvent]:
        """Open the upstream connection before returning an event iterator.

        The eager open lets the HTTP adapter preserve upstream HTTP status codes
        and connection errors instead of already having sent a 200 SSE header.
        """
        await self.start()
        last_error: httpx.ConnectError | None = None
        response: httpx.Response | None = None
        for attempt in range(self.settings.connect_retries + 1):
            prepared = self.client.build_request(
                "POST",
                f"{self.settings.upstream_url}/v1/chat/completions",
                json=self._payload(request, stream=True),
                headers={"X-Request-ID": request_id},
            )
            try:
                response = await self.client.send(prepared, stream=True)
                break
            except httpx.ConnectError as exc:
                last_error = exc
                if attempt < self.settings.connect_retries:
                    await asyncio.sleep(0.1 * (2**attempt))
            except httpx.TimeoutException as exc:
                raise UpstreamTimeout("vLLM request timed out") from exc
        if response is None:
            assert last_error is not None
            raise UpstreamUnavailable("vLLM is unavailable") from last_error
        if response.is_error:
            try:
                detail = (await response.aread()).decode("utf-8", "replace")[:1_000]
                raise UpstreamHTTPError(response.status_code, detail)
            finally:
                await response.aclose()
        return self._iter_response(response)

    async def _iter_response(
        self,
        response: httpx.Response,
    ) -> AsyncIterator[StreamEvent]:
        completed = False
        try:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    completed = True
                    break
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise InvalidUpstreamResponse("invalid streaming response from vLLM") from exc
                if chunk.get("usage"):
                    usage = _usage(chunk["usage"])
                    yield StreamEvent(
                        "usage",
                        {
                            "prompt_tokens": usage.prompt_tokens,
                            "completion_tokens": usage.completion_tokens,
                            "total_tokens": usage.total_tokens,
                        },
                    )
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                for field, channel in (("reasoning_content", "reasoning"), ("content", "answer")):
                    text = delta.get(field)
                    if text:
                        yield StreamEvent(
                            "token",
                            {"text": normalize_unicode(text), "channel": channel},
                        )
            if not completed:
                raise InvalidUpstreamResponse("vLLM stream ended before [DONE]")
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout("vLLM request timed out") from exc
        finally:
            await response.aclose()

    async def stream(self, request: ChatRequest, *, request_id: str) -> AsyncIterator[StreamEvent]:
        async for event in await self.open_stream(request, request_id=request_id):
            yield event

