from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from nomnomcli.errors import ProviderUnavailableError

RETRYABLE_STATUS_CODES = frozenset({429, *range(500, 600)})


def provider_url(default: str, replay_path: str) -> str:
    """Use loopback-only frozen provider replay when eval mode is explicitly enabled."""
    if os.getenv("NOMNOM_EVAL_MODE", "").strip() != "1":
        return default
    base = os.getenv("NOMNOM_EVAL_PROVIDER_URL", "").strip()
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ProviderUnavailableError(
            "eval_replay",
            "eval_provider_url_invalid",
            "Eval provider replay URL must be an explicit loopback HTTP(S) URL",
            retryable=False,
            details={"host": parsed.hostname, "eval_mode": True},
        )
    return f"{base.rstrip('/')}/{replay_path.lstrip('/')}"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_base: float = 0.25
    max_delay: float = 2.0
    max_retry_after: float = 5.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if min(self.backoff_base, self.max_delay, self.max_retry_after) < 0:
            raise ValueError("retry delays must be non-negative")

    def delay(self, failed_attempt: int, response) -> float:
        retry_after = str(getattr(response, "headers", {}).get("Retry-After", "")).strip()
        try:
            numeric_retry_after = float(retry_after)
        except ValueError:
            numeric_retry_after = math.nan
        if (
            math.isfinite(numeric_retry_after)
            and 0 <= numeric_retry_after <= self.max_retry_after
        ):
            return numeric_retry_after
        return min(self.backoff_base * (2 ** (failed_attempt - 1)), self.max_delay)


def request_with_retry(
    *,
    provider: str,
    code: str,
    message: str,
    request_get: Callable,
    url: str,
    request_kwargs: dict,
    details: dict,
    retry_policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
):
    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            response = request_get(url, **request_kwargs)
        except requests.RequestException as exc:
            raise ProviderUnavailableError(
                provider,
                code,
                message,
                retryable=True,
                details={**details, "reason": "network_error", "attempts": attempt},
            ) from exc

        status = int(getattr(response, "status_code", 200))
        if status not in RETRYABLE_STATUS_CODES:
            return response
        if attempt == retry_policy.max_attempts:
            raise ProviderUnavailableError(
                provider,
                code,
                message,
                retryable=True,
                details={
                    **details,
                    "reason": "http_error",
                    "status": status,
                    "attempts": attempt,
                },
            )
        sleep(retry_policy.delay(attempt, response))
    raise AssertionError("retry loop exhausted unexpectedly")
