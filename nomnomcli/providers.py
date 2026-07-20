from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from nomnomcli.errors import ProviderUnavailableError

RETRYABLE_STATUS_CODES = frozenset({429, *range(500, 600)})


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
