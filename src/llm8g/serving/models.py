"""Transport-neutral request and response models.

These dataclasses are the interface between the gateway and every transport
adapter.  FastAPI/Pydantic models belong in the HTTP adapter and should not
leak into the serving implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("message content must not be empty")
        if len(self.content) > 20_000:
            raise ValueError("message content is too long")


@dataclass(frozen=True, slots=True)
class ChatRequest:
    message: str
    system_prompt: str | None = None
    history: tuple[ChatMessage, ...] = field(default_factory=tuple)
    max_tokens: int = 256
    temperature: float = 0.7
    enable_thinking: bool = False

    def __post_init__(self) -> None:
        if not self.message or len(self.message) > 20_000:
            raise ValueError("message must contain 1 to 20,000 characters")
        if self.system_prompt is not None and len(self.system_prompt) > 10_000:
            raise ValueError("system_prompt is too long")
        if len(self.history) > 12:
            raise ValueError("history cannot contain more than 12 messages")
        if not 1 <= self.max_tokens <= 2_048:
            raise ValueError("max_tokens must be between 1 and 2048")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ChatRequest":
        raw_history = payload.get("history") or []
        history = tuple(
            ChatMessage(role=item["role"], content=item["content"])
            for item in raw_history
        )
        return cls(
            message=payload["message"],
            system_prompt=payload.get("system_prompt"),
            history=history,
            max_tokens=payload.get("max_tokens", 256),
            temperature=payload.get("temperature", 0.7),
            enable_thinking=payload.get("enable_thinking", False),
        )

    def messages(self) -> tuple[dict[str, str], ...]:
        items: list[dict[str, str]] = []
        if self.system_prompt:
            items.append({"role": "system", "content": self.system_prompt})
        items.extend({"role": item.role, "content": item.content} for item in self.history)
        items.append({"role": "user", "content": self.message})
        return tuple(items)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "TokenUsage":
        raw = raw or {}
        return cls(
            prompt_tokens=int(raw.get("prompt_tokens") or 0),
            completion_tokens=int(raw.get("completion_tokens") or 0),
            total_tokens=int(raw.get("total_tokens") or 0),
        )


@dataclass(frozen=True, slots=True)
class ChatResult:
    request_id: str
    model: str
    answer: str
    usage: TokenUsage
    latency_ms: float
    queue_wait_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """An event emitted by the serving core, before transport encoding."""

    kind: Literal["meta", "token", "usage", "done", "error"]
    payload: dict[str, Any]

