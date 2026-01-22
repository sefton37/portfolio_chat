"""Unit tests for Layer 0: Network Gateway."""

import pytest

from portfolio_chat.pipeline.layer0_network import (
    Layer0NetworkGateway,
    Layer0Result,
    Layer0Status,
)


class TestLayer0NetworkGateway:
    """Tests for Layer 0 Network Gateway."""

    @pytest.mark.asyncio
    async def test_passes_valid_request(self, network_gateway):
        """Test that valid requests pass through."""
        result = await network_gateway.validate_request(
            client_ip="127.0.0.1",
            request_id="test-123",
            content_type="application/json",
            content_length=100,
            has_message=True,
        )
        assert result.passed
        assert result.status == Layer0Status.PASSED
        assert result.ip_hash  # Should have hashed IP

    @pytest.mark.asyncio
    async def test_passes_with_charset_in_content_type(self, network_gateway):
        """Test that content-type with charset is accepted."""
        result = await network_gateway.validate_request(
            client_ip="127.0.0.1",
            request_id="test-123",
            content_type="application/json; charset=utf-8",
            content_length=100,
            has_message=True,
        )
        assert result.passed
        assert result.status == Layer0Status.PASSED

    @pytest.mark.asyncio
    async def test_rejects_invalid_content_type(self, network_gateway):
        """Test that invalid content type is rejected."""
        result = await network_gateway.validate_request(
            client_ip="127.0.0.1",
            request_id="test-123",
            content_type="text/plain",
            content_length=100,
            has_message=True,
        )
        assert result.blocked
        assert result.status == Layer0Status.INVALID_CONTENT_TYPE

    @pytest.mark.asyncio
    async def test_rejects_too_large_request(self, network_gateway):
        """Test that oversized requests are rejected."""
        result = await network_gateway.validate_request(
            client_ip="127.0.0.1",
            request_id="test-123",
            content_type="application/json",
            content_length=50000,  # Larger than 10000 limit
            has_message=True,
        )
        assert result.blocked
        assert result.status == Layer0Status.REQUEST_TOO_LARGE

    @pytest.mark.asyncio
    async def test_rejects_missing_message(self, network_gateway):
        """Test that requests without message are rejected."""
        result = await network_gateway.validate_request(
            client_ip="127.0.0.1",
            request_id="test-123",
            content_type="application/json",
            content_length=100,
            has_message=False,
        )
        assert result.blocked
        assert result.status == Layer0Status.MISSING_MESSAGE

    @pytest.mark.asyncio
    async def test_rate_limits_requests(self, network_gateway):
        """Test that rate limiting works."""
        client_ip = "192.168.1.100"

        # Make requests up to the limit (5 per minute)
        for i in range(5):
            result = await network_gateway.validate_request(
                client_ip=client_ip,
                request_id=f"test-{i}",
                content_type="application/json",
                content_length=100,
                has_message=True,
            )
            assert result.passed, f"Request {i} should pass"

        # 6th request should be rate limited
        result = await network_gateway.validate_request(
            client_ip=client_ip,
            request_id="test-6",
            content_type="application/json",
            content_length=100,
            has_message=True,
        )
        assert result.blocked
        assert result.status == Layer0Status.RATE_LIMITED
        assert result.retry_after is not None

    @pytest.mark.asyncio
    async def test_different_ips_independent(self, network_gateway):
        """Test that different IPs have independent rate limits."""
        # Exhaust rate limit for IP 1
        for i in range(6):
            await network_gateway.validate_request(
                client_ip="10.0.0.1",
                request_id=f"test-ip1-{i}",
                content_type="application/json",
                content_length=100,
                has_message=True,
            )

        # IP 2 should still be allowed
        result = await network_gateway.validate_request(
            client_ip="10.0.0.2",
            request_id="test-ip2-0",
            content_type="application/json",
            content_length=100,
            has_message=True,
        )
        assert result.passed

    @pytest.mark.asyncio
    async def test_accepts_none_content_type(self, network_gateway):
        """Test that None content-type is accepted (for flexibility)."""
        result = await network_gateway.validate_request(
            client_ip="127.0.0.1",
            request_id="test-123",
            content_type=None,
            content_length=100,
            has_message=True,
        )
        # Should pass since we only validate if content_type is provided
        assert result.passed

    @pytest.mark.asyncio
    async def test_accepts_none_content_length(self, network_gateway):
        """Test that None content-length is accepted."""
        result = await network_gateway.validate_request(
            client_ip="127.0.0.1",
            request_id="test-123",
            content_type="application/json",
            content_length=None,
            has_message=True,
        )
        assert result.passed

    def test_get_user_friendly_error_rate_limited(self, network_gateway):
        """Test user-friendly error for rate limiting."""
        result = Layer0Result(
            status=Layer0Status.RATE_LIMITED,
            passed=False,
            ip_hash="test",
            request_id="test",
        )
        error = network_gateway.get_user_friendly_error(result)
        assert "wait" in error.lower()

    def test_get_user_friendly_error_too_large(self, network_gateway):
        """Test user-friendly error for oversized request."""
        result = Layer0Result(
            status=Layer0Status.REQUEST_TOO_LARGE,
            passed=False,
            ip_hash="test",
            request_id="test",
        )
        error = network_gateway.get_user_friendly_error(result)
        assert "long" in error.lower() or "shorten" in error.lower()


class TestLayer0Result:
    """Tests for Layer0Result dataclass."""

    def test_blocked_property(self):
        """Test that blocked property is inverse of passed."""
        passed_result = Layer0Result(
            status=Layer0Status.PASSED,
            passed=True,
            ip_hash="test",
            request_id="test",
        )
        assert not passed_result.blocked

        blocked_result = Layer0Result(
            status=Layer0Status.RATE_LIMITED,
            passed=False,
            ip_hash="test",
            request_id="test",
        )
        assert blocked_result.blocked

    def test_error_message_optional(self):
        """Test that error_message is optional."""
        result = Layer0Result(
            status=Layer0Status.PASSED,
            passed=True,
            ip_hash="test",
            request_id="test",
        )
        assert result.error_message is None

        result_with_error = Layer0Result(
            status=Layer0Status.RATE_LIMITED,
            passed=False,
            ip_hash="test",
            request_id="test",
            error_message="Custom error",
        )
        assert result_with_error.error_message == "Custom error"
