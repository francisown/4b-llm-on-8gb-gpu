"""Model serving primitives and adapters."""

from .admission import AdmissionController, AdmissionLease
from .config import GatewaySettings
from .errors import (
    AdmissionRejected,
    AuthenticationFailed,
    ContextLimitExceeded,
    InvalidUpstreamResponse,
    ServingError,
    UpstreamHTTPError,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from .limits import SlidingWindowLimiter
from .models import ChatRequest, ChatResult, StreamEvent, TokenUsage
from .service import GatewayService
from .security import AuthPolicy, AuthIdentity
from .ports import InferenceBackend, RateLimiter

__all__ = [
    "AdmissionController",
    "AdmissionLease",
    "AdmissionRejected",
    "AuthenticationFailed",
    "AuthIdentity",
    "AuthPolicy",
    "ChatRequest",
    "ChatResult",
    "ContextLimitExceeded",
    "GatewayService",
    "GatewaySettings",
    "InferenceBackend",
    "InvalidUpstreamResponse",
    "RateLimiter",
    "ServingError",
    "SlidingWindowLimiter",
    "StreamEvent",
    "TokenUsage",
    "UpstreamHTTPError",
    "UpstreamTimeout",
    "UpstreamUnavailable",
]

