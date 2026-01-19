"""Timing utilities for trading operations."""

import asyncio
import secrets
import time
from datetime import datetime, timezone
from typing import Tuple


def get_current_timestamp() -> int:
    """
    Get current Unix timestamp in milliseconds.
    
    Returns:
        Current time as Unix timestamp in milliseconds
    """
    return int(time.time() * 1000)


def get_current_datetime() -> datetime:
    """
    Get current UTC datetime.
    
    Returns:
        Current UTC datetime
    """
    return datetime.now(timezone.utc)


def timestamp_to_datetime(timestamp_ms: int) -> datetime:
    """
    Convert millisecond timestamp to datetime.
    
    Args:
        timestamp_ms: Unix timestamp in milliseconds
        
    Returns:
        UTC datetime
    """
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def datetime_to_timestamp(dt: datetime) -> int:
    """
    Convert datetime to millisecond timestamp.
    
    Args:
        dt: Datetime object
        
    Returns:
        Unix timestamp in milliseconds
    """
    return int(dt.timestamp() * 1000)


def get_expiration_timestamp(seconds_from_now: int) -> int:
    """
    Calculate expiration timestamp.
    
    Args:
        seconds_from_now: Seconds until expiration
        
    Returns:
        Expiration timestamp in milliseconds
    """
    return get_current_timestamp() + (seconds_from_now * 1000)


async def async_sleep_random(
    min_seconds: int,
    max_seconds: int,
) -> float:
    """
    Sleep for a cryptographically random duration.
    
    Uses secrets module for non-predictable timing.
    
    Args:
        min_seconds: Minimum sleep duration
        max_seconds: Maximum sleep duration
        
    Returns:
        Actual sleep duration in seconds
    """
    if min_seconds >= max_seconds:
        duration = min_seconds
    else:
        # Use secrets for cryptographic randomness
        range_size = max_seconds - min_seconds
        random_offset = secrets.randbelow(range_size * 1000) / 1000  # Sub-second precision
        duration = min_seconds + random_offset
    
    await asyncio.sleep(duration)
    return duration


async def async_sleep_with_jitter(
    base_seconds: float,
    jitter_percent: float = 0.1,
) -> float:
    """
    Sleep with random jitter.
    
    Adds randomness to prevent synchronized operations.
    
    Args:
        base_seconds: Base sleep duration
        jitter_percent: Maximum jitter as percentage of base
        
    Returns:
        Actual sleep duration
    """
    jitter_range = int(base_seconds * jitter_percent * 1000)
    if jitter_range > 0:
        jitter = secrets.randbelow(jitter_range * 2) - jitter_range
        duration = base_seconds + (jitter / 1000)
    else:
        duration = base_seconds
    
    duration = max(0.1, duration)  # Minimum 100ms
    await asyncio.sleep(duration)
    return duration


class CycleTimer:
    """
    Timer for tracking trading cycle durations.
    
    Provides precise timing with phase tracking.
    """
    
    def __init__(self):
        self._start_time: float | None = None
        self._phase_times: dict[str, Tuple[float, float]] = {}
        self._current_phase: str | None = None
        self._phase_start: float | None = None
    
    def start(self) -> None:
        """Start the cycle timer."""
        self._start_time = time.perf_counter()
        self._phase_times = {}
        self._current_phase = None
        self._phase_start = None
    
    def start_phase(self, phase: str) -> None:
        """
        Start timing a phase.
        
        Args:
            phase: Phase name (e.g., "opening", "holding", "closing")
        """
        if self._current_phase and self._phase_start:
            # End previous phase
            self._phase_times[self._current_phase] = (
                self._phase_start,
                time.perf_counter()
            )
        
        self._current_phase = phase
        self._phase_start = time.perf_counter()
    
    def end_phase(self) -> float | None:
        """
        End the current phase.
        
        Returns:
            Phase duration in seconds, or None if no phase active
        """
        if not self._current_phase or not self._phase_start:
            return None
        
        end_time = time.perf_counter()
        duration = end_time - self._phase_start
        self._phase_times[self._current_phase] = (self._phase_start, end_time)
        
        self._current_phase = None
        self._phase_start = None
        
        return duration
    
    def get_elapsed(self) -> float:
        """
        Get total elapsed time since start.
        
        Returns:
            Elapsed seconds
        """
        if not self._start_time:
            return 0.0
        return time.perf_counter() - self._start_time
    
    def get_phase_duration(self, phase: str) -> float | None:
        """
        Get duration of a completed phase.
        
        Args:
            phase: Phase name
            
        Returns:
            Duration in seconds, or None if phase not found
        """
        times = self._phase_times.get(phase)
        if not times:
            return None
        return times[1] - times[0]
    
    def get_summary(self) -> dict[str, float]:
        """
        Get timing summary for all phases.
        
        Returns:
            Dictionary of phase names to durations
        """
        summary = {}
        for phase, (start, end) in self._phase_times.items():
            summary[phase] = round(end - start, 3)
        summary["total"] = round(self.get_elapsed(), 3)
        return summary


class RateLimiter:
    """
    Async rate limiter for API calls.
    
    Uses token bucket algorithm with per-second refill.
    """
    
    def __init__(
        self,
        requests_per_minute: int = 1000,
        burst_size: int | None = None,
    ):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_minute: Maximum requests per minute
            burst_size: Maximum burst size (defaults to requests_per_minute / 60)
        """
        self._rate = requests_per_minute / 60.0  # Requests per second
        self._burst_size = burst_size or max(1, int(self._rate))
        self._tokens = float(self._burst_size)
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> float:
        """
        Acquire permission to make a request.
        
        Blocks if rate limit exceeded.
        
        Returns:
            Wait time in seconds (0 if immediate)
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            
            # Refill tokens
            self._tokens = min(
                self._burst_size,
                self._tokens + (elapsed * self._rate)
            )
            self._last_update = now
            
            if self._tokens >= 1:
                self._tokens -= 1
                return 0.0
            
            # Calculate wait time
            wait_time = (1 - self._tokens) / self._rate
            await asyncio.sleep(wait_time)
            
            self._tokens = 0
            self._last_update = time.monotonic()
            
            return wait_time
    
    @property
    def available_tokens(self) -> float:
        """Get current available tokens."""
        elapsed = time.monotonic() - self._last_update
        return min(
            self._burst_size,
            self._tokens + (elapsed * self._rate)
        )
