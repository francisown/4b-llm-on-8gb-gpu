"""Errors that cross the serving core interface."""

from __future__ import annotations


class ServingError(Exception):
    """Base class for errors that can be translated by an adapter."""


class AdmissionRejected(ServingError):
    """The gateway cannot accept the request right now."""

    def __init__(self, reason: str, *, retry_after: int = 2) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = max(1, retry_after)


class UpstreamUnavailable(ServingError):
    """The model server could not be reached."""


class UpstreamTimeout(ServingError):
    """The model server did not answer within the configured timeout."""


class InvalidUpstreamResponse(ServingError):
    """The model server returned a response outside the supported contract."""


class UpstreamHTTPError(ServingError):
    """The model server returned a non-success HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AuthenticationFailed(ServingError):
    """Authentication or rate-limit rejection that an adapter maps to HTTP."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: int | None = None,
        kind: str = "auth",
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.kind = kind


class ContextLimitExceeded(ServingError):
    """The request is larger than the configured model context window."""

