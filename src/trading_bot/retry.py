from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int
    retry_delay_seconds: float
    request_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least one")
        if self.retry_delay_seconds < 0 or self.request_delay_seconds < 0:
            raise ValueError("delays cannot be negative")


def call_with_retry(
    operation: Callable[[], T],
    policy: RetryPolicy,
    retryable: tuple[type[Exception], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    sleep(policy.request_delay_seconds)
    for attempt in range(1, policy.attempts + 1):
        try:
            return operation()
        except retryable:
            if attempt == policy.attempts:
                raise
            sleep(policy.retry_delay_seconds)
    raise RuntimeError("retry loop ended unexpectedly")


NETWORK_RETRY = RetryPolicy(attempts=5, retry_delay_seconds=3.0)
YAHOO_RETRY = RetryPolicy(
    attempts=3,
    retry_delay_seconds=3.0,
    request_delay_seconds=0.5,
)
