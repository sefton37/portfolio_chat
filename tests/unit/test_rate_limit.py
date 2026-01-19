"""Tests for rate limiter."""

import pytest
import time

from portfolio_chat.utils.rate_limit import (
    InMemoryRateLimiter,
    RateLimitStatus,
    RateLimitResult,
)


@pytest.fixture
def rate_limiter():
    """Create a rate limiter with low limits for testing."""
    return InMemoryRateLimiter(
        per_ip_per_minute=3,
        per_ip_per_hour=10,
        global_per_minute=100,
    )


class TestInMemoryRateLimiter:
    """Tests for InMemoryRateLimiter."""

    @pytest.mark.asyncio
    async def test_allows_first_request(self, rate_limiter):
        """Test that first request is allowed."""
        result = await rate_limiter.check_rate_limit("test_ip_hash")
        assert result.allowed
        assert result.status == RateLimitStatus.ALLOWED

    @pytest.mark.asyncio
    async def test_blocks_after_per_minute_limit(self, rate_limiter):
        """Test that requests are blocked after per-minute limit."""
        ip_hash = "test_ip_1"

        # Make requests up to the limit
        for _ in range(3):
            result = await rate_limiter.check_rate_limit(ip_hash)
            assert result.allowed
            await rate_limiter.record_request(ip_hash)

        # Next request should be blocked
        result = await rate_limiter.check_rate_limit(ip_hash)
        assert result.blocked
        assert result.status == RateLimitStatus.BLOCKED_IP_MINUTE

    @pytest.mark.asyncio
    async def test_different_ips_independent(self, rate_limiter):
        """Test that different IPs have independent limits."""
        ip1 = "ip_hash_1"
        ip2 = "ip_hash_2"

        # Exhaust ip1's limit
        for _ in range(3):
            await rate_limiter.check_rate_limit(ip1)
            await rate_limiter.record_request(ip1)

        # ip1 should be blocked
        result1 = await rate_limiter.check_rate_limit(ip1)
        assert result1.blocked

        # ip2 should still be allowed
        result2 = await rate_limiter.check_rate_limit(ip2)
        assert result2.allowed

    @pytest.mark.asyncio
    async def test_retry_after_provided(self, rate_limiter):
        """Test that retry_after is provided when blocked."""
        ip_hash = "test_ip_retry"

        for _ in range(3):
            await rate_limiter.check_rate_limit(ip_hash)
            await rate_limiter.record_request(ip_hash)

        result = await rate_limiter.check_rate_limit(ip_hash)
        assert result.blocked
        assert result.retry_after > 0
        assert result.retry_after <= 60  # Should be within the minute window

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_entries(self, rate_limiter):
        """Test that cleanup removes old entries."""
        ip_hash = "test_ip_cleanup"

        await rate_limiter.record_request(ip_hash)

        # Get stats before cleanup
        stats_before = rate_limiter.get_stats()
        assert stats_before["tracked_ips"] == 1

        # Cleanup shouldn't remove recent entries
        await rate_limiter.cleanup_expired()
        stats_after = rate_limiter.get_stats()
        assert stats_after["tracked_ips"] == 1

    @pytest.mark.asyncio
    async def test_stats_tracking(self, rate_limiter):
        """Test that stats are tracked correctly."""
        await rate_limiter.record_request("ip1")
        await rate_limiter.record_request("ip2")
        await rate_limiter.record_request("ip1")

        stats = rate_limiter.get_stats()
        assert stats["tracked_ips"] == 2
        assert stats["global_requests_last_hour"] == 3
