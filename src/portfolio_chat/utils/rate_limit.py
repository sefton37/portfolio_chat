"""
In-memory rate limiter with sliding window algorithm.

Thread-safe implementation using asyncio locks.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum

from portfolio_chat.config import RATE_LIMITS


class RateLimitStatus(Enum):
    """Rate limit check result status."""

    ALLOWED = "allowed"
    BLOCKED_IP_MINUTE = "blocked_ip_minute"
    BLOCKED_IP_HOUR = "blocked_ip_hour"
    BLOCKED_GLOBAL = "blocked_global"


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    status: RateLimitStatus
    allowed: bool
    retry_after: float = 0.0  # Seconds until rate limit resets
    current_count: int = 0
    limit: int = 0

    @property
    def blocked(self) -> bool:
        """Convenience property for blocked status."""
        return not self.allowed


@dataclass
class RequestWindow:
    """Sliding window for tracking requests."""

    timestamps: list[float] = field(default_factory=list)

    def add(self, timestamp: float) -> None:
        """Add a timestamp to the window."""
        self.timestamps.append(timestamp)

    def count_in_window(self, window_start: float) -> int:
        """Count timestamps within the window."""
        return sum(1 for ts in self.timestamps if ts >= window_start)

    def cleanup(self, cutoff: float) -> None:
        """Remove timestamps older than cutoff."""
        self.timestamps = [ts for ts in self.timestamps if ts >= cutoff]


class InMemoryRateLimiter:
    """
    In-memory rate limiter with sliding window algorithm.

    Supports per-IP and global rate limits with automatic cleanup.
    """

    def __init__(
        self,
        per_ip_per_minute: int | None = None,
        per_ip_per_hour: int | None = None,
        global_per_minute: int | None = None,
    ) -> None:
        """
        Initialize rate limiter.

        Args:
            per_ip_per_minute: Max requests per IP per minute.
            per_ip_per_hour: Max requests per IP per hour.
            global_per_minute: Max global requests per minute.
        """
        self.per_ip_per_minute = per_ip_per_minute or RATE_LIMITS.PER_IP_PER_MINUTE
        self.per_ip_per_hour = per_ip_per_hour or RATE_LIMITS.PER_IP_PER_HOUR
        self.global_per_minute = global_per_minute or RATE_LIMITS.GLOBAL_PER_MINUTE

        self._ip_windows: dict[str, RequestWindow] = {}
        self._global_window = RequestWindow()
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 60.0  # Cleanup every minute

    async def check_rate_limit(self, ip_hash: str) -> RateLimitResult:
        """
        Check if request is allowed under rate limits.

        Args:
            ip_hash: SHA256 hash of client IP address.

        Returns:
            RateLimitResult indicating if request is allowed.
        """
        async with self._lock:
            now = time.time()

            # Periodic cleanup
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired(now)
                self._last_cleanup = now

            # Get or create IP window
            if ip_hash not in self._ip_windows:
                self._ip_windows[ip_hash] = RequestWindow()

            ip_window = self._ip_windows[ip_hash]

            # Check per-IP per-minute limit
            minute_ago = now - 60
            ip_minute_count = ip_window.count_in_window(minute_ago)

            if ip_minute_count >= self.per_ip_per_minute:
                oldest_in_minute = min(
                    (ts for ts in ip_window.timestamps if ts >= minute_ago),
                    default=now,
                )
                retry_after = 60 - (now - oldest_in_minute)
                return RateLimitResult(
                    status=RateLimitStatus.BLOCKED_IP_MINUTE,
                    allowed=False,
                    retry_after=max(0, retry_after),
                    current_count=ip_minute_count,
                    limit=self.per_ip_per_minute,
                )

            # Check per-IP per-hour limit
            hour_ago = now - 3600
            ip_hour_count = ip_window.count_in_window(hour_ago)

            if ip_hour_count >= self.per_ip_per_hour:
                oldest_in_hour = min(
                    (ts for ts in ip_window.timestamps if ts >= hour_ago),
                    default=now,
                )
                retry_after = 3600 - (now - oldest_in_hour)
                return RateLimitResult(
                    status=RateLimitStatus.BLOCKED_IP_HOUR,
                    allowed=False,
                    retry_after=max(0, retry_after),
                    current_count=ip_hour_count,
                    limit=self.per_ip_per_hour,
                )

            # Check global per-minute limit
            global_count = self._global_window.count_in_window(minute_ago)

            if global_count >= self.global_per_minute:
                oldest_global = min(
                    (ts for ts in self._global_window.timestamps if ts >= minute_ago),
                    default=now,
                )
                retry_after = 60 - (now - oldest_global)
                return RateLimitResult(
                    status=RateLimitStatus.BLOCKED_GLOBAL,
                    allowed=False,
                    retry_after=max(0, retry_after),
                    current_count=global_count,
                    limit=self.global_per_minute,
                )

            return RateLimitResult(
                status=RateLimitStatus.ALLOWED,
                allowed=True,
                current_count=ip_minute_count,
                limit=self.per_ip_per_minute,
            )

    async def record_request(self, ip_hash: str) -> None:
        """
        Record a request for rate limiting.

        Args:
            ip_hash: SHA256 hash of client IP address.
        """
        async with self._lock:
            now = time.time()

            # Ensure IP window exists
            if ip_hash not in self._ip_windows:
                self._ip_windows[ip_hash] = RequestWindow()

            self._ip_windows[ip_hash].add(now)
            self._global_window.add(now)

    def _cleanup_expired(self, now: float) -> None:
        """
        Remove expired timestamps from all windows.

        Called periodically to prevent memory growth.
        """
        # Remove timestamps older than 1 hour
        hour_ago = now - 3600

        # Cleanup IP windows
        empty_ips = []
        for ip_hash, window in self._ip_windows.items():
            window.cleanup(hour_ago)
            if not window.timestamps:
                empty_ips.append(ip_hash)

        # Remove empty IP windows
        for ip_hash in empty_ips:
            del self._ip_windows[ip_hash]

        # Cleanup global window
        self._global_window.cleanup(hour_ago)

    async def cleanup_expired(self) -> None:
        """Public async method to trigger cleanup."""
        async with self._lock:
            self._cleanup_expired(time.time())

    def get_stats(self) -> dict[str, int]:
        """Get rate limiter statistics."""
        return {
            "tracked_ips": len(self._ip_windows),
            "global_requests_last_hour": len(self._global_window.timestamps),
        }
