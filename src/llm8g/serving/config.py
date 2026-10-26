"""Validated serving configuration.

Environment variables are read once, at the composition root.  Core modules
receive this value explicitly, which makes tests deterministic and makes it
possible to run two gateway instances with different settings in one process.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _int(env: dict[str, str], name: str, default: int, *, minimum: int = 0) -> int:
    value = int(env.get(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float(env: dict[str, str], name: str, default: float, *, minimum: float = 0.0) -> float:
    value = float(env.get(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    upstream_url: str = "http://127.0.0.1:8000"
    model: str = "Qwen3.5-4B-INT4-AWQ-self"
    max_context_tokens: int = 2_048
    upstream_timeout_seconds: float = 60.0
    health_timeout_seconds: float = 3.0
    connect_retries: int = 1
    max_concurrent: int = 4
    max_queue: int = 4
    queue_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 0
    rate_limit_max_identities: int = 10_000
    auth_failure_limit_per_minute: int = 20
    api_keys: tuple[str, ...] = ()
    trust_proxy_headers: bool = False
    version: str = "stable"
    pod_name: str = "local"
    rate_limit_backend: str = "process"
    redis_url: str = "redis://127.0.0.1:6379/0"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "GatewaySettings":
        source = dict(os.environ if env is None else env)
        defaults = cls()
        return cls(
            upstream_url=source.get("VLLM_BASE_URL", defaults.upstream_url).rstrip("/"),
            model=source.get("MODEL_NAME", defaults.model),
            max_context_tokens=_int(source, "GATEWAY_MAX_CONTEXT_TOKENS", 2_048, minimum=1),
            upstream_timeout_seconds=_float(source, "UPSTREAM_TIMEOUT_SECONDS", 60.0, minimum=0.1),
            health_timeout_seconds=_float(source, "HEALTH_TIMEOUT_SECONDS", 3.0, minimum=0.1),
            connect_retries=_int(source, "UPSTREAM_CONNECT_RETRIES", 1),
            max_concurrent=_int(source, "GATEWAY_MAX_CONCURRENT", 4, minimum=1),
            max_queue=_int(source, "GATEWAY_MAX_QUEUE", 4),
            queue_timeout_seconds=_float(
                source,
                "GATEWAY_QUEUE_TIMEOUT_SECONDS",
                10.0,
                minimum=0.001,
            ),
            rate_limit_per_minute=_int(source, "GATEWAY_RATE_LIMIT_PER_MINUTE", 0),
            rate_limit_max_identities=_int(
                source,
                "GATEWAY_RATE_LIMIT_MAX_IDENTITIES",
                10_000,
                minimum=1,
            ),
            auth_failure_limit_per_minute=_int(source, "GATEWAY_AUTH_FAILURE_LIMIT_PER_MINUTE", 20),
            api_keys=tuple(
                dict.fromkeys(
                    key.strip()
                    for key in (
                        [source.get("GATEWAY_API_KEY", "")]
                        + source.get("GATEWAY_API_KEYS", "").split(",")
                    )
                    if key.strip()
                )
            ),
            trust_proxy_headers=source.get("GATEWAY_TRUST_PROXY_HEADERS", "0").lower()
            in {"1", "true", "yes", "on"},
            version=source.get("GATEWAY_VERSION", defaults.version),
            pod_name=source.get("POD_NAME", defaults.pod_name),
            rate_limit_backend=source.get(
                "GATEWAY_RATE_LIMIT_BACKEND", defaults.rate_limit_backend
            ).lower(),
            redis_url=source.get("GATEWAY_REDIS_URL", defaults.redis_url),
            log_level=source.get("LOG_LEVEL", defaults.log_level).upper(),
        )

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        env: dict[str, str] | None = None,
    ) -> "GatewaySettings":
        """Load a small dotenv-style profile, with explicit env overrides."""
        values: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            if not separator or not name.strip():
                raise ValueError(f"invalid configuration line in {path}: {raw_line}")
            values[name.strip()] = value.strip().strip('"').strip("'")
        values.update(env or {})
        return cls.from_env(values)

