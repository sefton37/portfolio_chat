"""Security tests for rate limiting."""

import pytest

from portfolio_chat.utils.rate_limit import (
    InMemoryRateLimiter,
    RateLimitStatus,
)


class TestRateLimitSecurity:
    """Security tests for rate limiting."""

    @pytest.mark.asyncio
    async def test_prevents_rapid_fire_requests(self):
        """Test that rapid requests are blocked."""
        limiter = InMemoryRateLimiter(
            per_ip_per_minute=5,
            per_ip_per_hour=100,
            global_per_minute=1000,
        )

        ip_hash = "attacker_ip"

        # Make 5 requests (the limit)
        for _ in range(5):
            result = await limiter.check_rate_limit(ip_hash)
            assert result.allowed
            await limiter.record_request(ip_hash)

        # 6th request should be blocked
        result = await limiter.check_rate_limit(ip_hash)
        assert result.blocked
        assert result.status == RateLimitStatus.BLOCKED_IP_MINUTE

    @pytest.mark.asyncio
    async def test_prevents_distributed_attack_global_limit(self):
        """Test that global limit prevents distributed attacks."""
        limiter = InMemoryRateLimiter(
            per_ip_per_minute=1000,  # High per-IP limit
            per_ip_per_hour=10000,
            global_per_minute=10,  # Low global limit
        )

        # Simulate many different IPs
        for i in range(10):
            ip_hash = f"attacker_{i}"
            result = await limiter.check_rate_limit(ip_hash)
            assert result.allowed
            await limiter.record_request(ip_hash)

        # 11th IP should hit global limit
        result = await limiter.check_rate_limit("attacker_10")
        assert result.blocked
        assert result.status == RateLimitStatus.BLOCKED_GLOBAL

    @pytest.mark.asyncio
    async def test_blocks_hourly_abuse(self):
        """Test that hourly limit catches sustained abuse."""
        limiter = InMemoryRateLimiter(
            per_ip_per_minute=100,  # High minute limit
            per_ip_per_hour=10,  # Low hour limit
            global_per_minute=1000,
        )

        ip_hash = "sustained_attacker"

        # Make 10 requests (hourly limit)
        for _ in range(10):
            result = await limiter.check_rate_limit(ip_hash)
            assert result.allowed
            await limiter.record_request(ip_hash)

        # 11th request should be blocked by hourly limit
        result = await limiter.check_rate_limit(ip_hash)
        assert result.blocked
        assert result.status == RateLimitStatus.BLOCKED_IP_HOUR

    @pytest.mark.asyncio
    async def test_provides_retry_after(self):
        """Test that retry-after is provided when blocked."""
        limiter = InMemoryRateLimiter(
            per_ip_per_minute=1,
            per_ip_per_hour=100,
            global_per_minute=1000,
        )

        ip_hash = "test_ip"

        # Make one request
        await limiter.check_rate_limit(ip_hash)
        await limiter.record_request(ip_hash)

        # Second should be blocked with retry_after
        result = await limiter.check_rate_limit(ip_hash)
        assert result.blocked
        assert result.retry_after > 0
        assert result.retry_after <= 60  # Within minute window

    @pytest.mark.asyncio
    async def test_different_ips_isolated(self):
        """Test that rate limits are isolated per IP."""
        limiter = InMemoryRateLimiter(
            per_ip_per_minute=2,
            per_ip_per_hour=100,
            global_per_minute=1000,
        )

        ip1 = "innocent_user"
        ip2 = "attacker"

        # Attacker exhausts their limit
        for _ in range(2):
            await limiter.check_rate_limit(ip2)
            await limiter.record_request(ip2)

        # Attacker is blocked
        result = await limiter.check_rate_limit(ip2)
        assert result.blocked

        # Innocent user is not affected
        result = await limiter.check_rate_limit(ip1)
        assert result.allowed

    @pytest.mark.asyncio
    async def test_cleanup_doesnt_reset_active_limits(self):
        """Test that cleanup doesn't reset active rate limits."""
        limiter = InMemoryRateLimiter(
            per_ip_per_minute=2,
            per_ip_per_hour=100,
            global_per_minute=1000,
        )

        ip_hash = "test_ip"

        # Exhaust the limit
        for _ in range(2):
            await limiter.check_rate_limit(ip_hash)
            await limiter.record_request(ip_hash)

        # Should be blocked
        result = await limiter.check_rate_limit(ip_hash)
        assert result.blocked

        # Cleanup
        await limiter.cleanup_expired()

        # Should still be blocked (entries are recent)
        result = await limiter.check_rate_limit(ip_hash)
        assert result.blocked
