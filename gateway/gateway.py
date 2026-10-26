"""Compatibility entrypoint for ``uvicorn gateway:app``.

The implementation lives in :mod:`llm8g.serving.http`.  Keeping this module as
a thin adapter preserves the historical import path and the container command
while the capability package remains the single source of serving behavior.
"""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from llm8g.serving import (  # noqa: E402
    AdmissionController,
    AuthenticationFailed,
    ChatRequest as CoreChatRequest,
    ChatResult,
    GatewaySettings,
    SlidingWindowLimiter,
    TokenUsage as CoreTokenUsage,
)
from llm8g.serving.http import create_app  # noqa: E402
from llm8g.serving.schemas import (  # noqa: E402
    ChatRequestBody,
    ChatResponseBody,
    TokenUsageBody,
)

settings = GatewaySettings.from_env()
app = create_app(settings)

# Historical names used by smoke tests and external scripts.
MODEL_NAME = settings.model
POD_NAME = settings.pod_name
GATEWAY_VERSION = settings.version
GATEWAY_API_KEY = settings.api_keys[0] if settings.api_keys else ""
GATEWAY_API_KEYS = settings.api_keys
RateLimiter = SlidingWindowLimiter
ChatRequest = ChatRequestBody
ChatRequestModel = ChatRequestBody
ChatResponse = ChatResponseBody
TokenUsage = TokenUsageBody

__all__ = [
    "app",
    "create_app",
    "settings",
    "AdmissionController",
    "AuthenticationFailed",
    "ChatRequest",
    "ChatRequestModel",
    "CoreChatRequest",
    "CoreTokenUsage",
    "ChatResponse",
    "ChatResult",
    "GATEWAY_API_KEY",
    "GATEWAY_API_KEYS",
    "GATEWAY_VERSION",
    "GatewaySettings",
    "MODEL_NAME",
    "POD_NAME",
    "RateLimiter",
    "SlidingWindowLimiter",
    "TokenUsage",
]
