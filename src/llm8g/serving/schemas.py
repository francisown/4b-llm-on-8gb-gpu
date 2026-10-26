"""HTTP request/response schemas for the optional FastAPI adapter.

Pydantic is deliberately confined to this module.  The serving core uses
plain dataclasses, so a CLI, a test, or another transport can reuse the same
policy without importing FastAPI.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import ChatMessage, ChatRequest, ChatResult, TokenUsage


class ChatMessageBody(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequestBody(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    system_prompt: str | None = Field(default=None, max_length=10_000)
    history: list[ChatMessageBody] = Field(default_factory=list, max_length=12)
    max_tokens: int = Field(default=256, ge=1, le=2_048)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    enable_thinking: bool = False

    def to_core(self) -> ChatRequest:
        return ChatRequest(
            message=self.message,
            system_prompt=self.system_prompt,
            history=tuple(
                ChatMessage(role=message.role, content=message.content)
                for message in self.history
            ),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            enable_thinking=self.enable_thinking,
        )


class TokenUsageBody(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    @classmethod
    def from_core(cls, usage: TokenUsage) -> "TokenUsageBody":
        return cls(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )


class ChatResponseBody(BaseModel):
    request_id: str
    model: str
    answer: str
    usage: TokenUsageBody
    latency_ms: float

    @classmethod
    def from_core(cls, result: ChatResult) -> "ChatResponseBody":
        return cls(
            request_id=result.request_id,
            model=result.model,
            answer=result.answer,
            usage=TokenUsageBody.from_core(result.usage),
            latency_ms=round(result.latency_ms, 1),
        )
