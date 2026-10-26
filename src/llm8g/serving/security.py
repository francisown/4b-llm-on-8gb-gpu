"""Authentication and identity policy, independent of HTTP framework details."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac

from .errors import AuthenticationFailed
from .ports import RateLimiter


@dataclass(frozen=True, slots=True)
class AuthIdentity:
    value: str


class AuthPolicy:
    """Optional API-key authentication plus per-identity rate limiting."""

    def __init__(
        self,
        keys: tuple[str, ...] = (),
        *,
        rate_limiter: RateLimiter | None = None,
        auth_failure_limiter: RateLimiter | None = None,
    ) -> None:
        self.keys = tuple(dict.fromkeys(key for key in keys if key))
        self.rate_limiter = rate_limiter
        self.auth_failure_limiter = auth_failure_limiter

    async def identity(self, provided_key: str | None, client_ip: str) -> AuthIdentity:
        if self.keys:
            if not provided_key or not any(
                hmac.compare_digest(provided_key, key) for key in self.keys
            ):
                if self.auth_failure_limiter is not None:
                    allowed, retry_after = await self.auth_failure_limiter.check(
                        f"auth:{client_ip}"
                    )
                    if not allowed:
                        raise AuthenticationFailed(
                            "too many authentication failures",
                            retry_after=retry_after,
                            kind="rate_limit",
                        )
                raise AuthenticationFailed("invalid or missing API key")
            raw = hashlib.sha256(provided_key.encode("utf-8")).hexdigest()
            identity = AuthIdentity(f"key:{raw}")
        else:
            identity = AuthIdentity(f"ip:{client_ip}")
        if self.rate_limiter is not None:
            allowed, retry_after = await self.rate_limiter.check(identity.value)
            if not allowed:
                raise AuthenticationFailed(
                    "rate limit exceeded",
                    retry_after=retry_after,
                    kind="rate_limit",
                )
        return identity

