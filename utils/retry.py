"""Retry utilities for transient network failures."""

from functools import wraps
from typing import Callable, TypeVar

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from utils.logging import get_logger

logger = get_logger(__name__)

# Type variable for preserving function signatures
F = TypeVar("F", bound=Callable)


# Retry decorator for exchange API calls
# Handles transient network errors with exponential backoff
exchange_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
    )),
    before_sleep=before_sleep_log(logger, "WARNING"),
    reraise=True,
)


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 10.0,
) -> Callable[[F], F]:
    """
    Configurable retry decorator for exchange operations.

    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time between retries (seconds)
        max_wait: Maximum wait time between retries (seconds)

    Returns:
        Decorator that adds retry logic to the function
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type((
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
        )),
        before_sleep=before_sleep_log(logger, "WARNING"),
        reraise=True,
    )
