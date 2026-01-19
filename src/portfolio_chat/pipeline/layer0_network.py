"""
Layer 0: Network Gateway

Handles request validation, rate limiting, and basic request constraints.
First line of defense before any content processing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from portfolio_chat.config import SECURITY
from portfolio_chat.utils.logging import audit_logger, hash_ip
from portfolio_chat.utils.rate_limit import InMemoryRateLimiter

logger = logging.getLogger(__name__)


class Layer0Status(Enum):
    """Status codes for Layer 0 validation."""

    PASSED = "passed"
    RATE_LIMITED = "rate_limited"
    REQUEST_TOO_LARGE = "request_too_large"
    INVALID_CONTENT_TYPE = "invalid_content_type"
    MISSING_MESSAGE = "missing_message"


@dataclass
class Layer0Result:
    """Result of Layer 0 validation."""

    status: Layer0Status
    passed: bool
    ip_hash: str
    request_id: str
    error_message: str | None = None
    retry_after: float | None = None

    @property
    def blocked(self) -> bool:
        """Convenience property for blocked status."""
        return not self.passed


class Layer0NetworkGateway:
    """
    Network Gateway - First line of defense.

    Validates:
    - Request size
    - Content-Type
    - Rate limits (per-IP and global)
    - Basic request structure
    """

    # Allowed content types
    ALLOWED_CONTENT_TYPES = frozenset(["application/json"])

    def __init__(
        self,
        rate_limiter: InMemoryRateLimiter | None = None,
        max_request_size: int | None = None,
    ) -> None:
        """
        Initialize network gateway.

        Args:
            rate_limiter: Rate limiter instance. Creates one if not provided.
            max_request_size: Maximum request size in bytes.
        """
        self.rate_limiter = rate_limiter or InMemoryRateLimiter()
        self.max_request_size = max_request_size or SECURITY.MAX_REQUEST_SIZE

    async def validate_request(
        self,
        client_ip: str,
        request_id: str,
        content_type: str | None,
        content_length: int | None,
        has_message: bool,
    ) -> Layer0Result:
        """
        Validate an incoming request.

        Args:
            client_ip: Client IP address (will be hashed).
            request_id: Unique request identifier.
            content_type: Request Content-Type header.
            content_length: Request Content-Length header.
            has_message: Whether request body contains a message.

        Returns:
            Layer0Result indicating validation status.
        """
        ip_hash = hash_ip(client_ip)

        # Check content type
        if content_type:
            # Handle content-type with charset (e.g., "application/json; charset=utf-8")
            base_content_type = content_type.split(";")[0].strip().lower()
            if base_content_type not in self.ALLOWED_CONTENT_TYPES:
                logger.warning(f"Invalid content type: {content_type}")
                return Layer0Result(
                    status=Layer0Status.INVALID_CONTENT_TYPE,
                    passed=False,
                    ip_hash=ip_hash,
                    request_id=request_id,
                    error_message="Invalid content type. Use application/json.",
                )

        # Check request size
        if content_length is not None and content_length > self.max_request_size:
            logger.warning(f"Request too large: {content_length} bytes")
            return Layer0Result(
                status=Layer0Status.REQUEST_TOO_LARGE,
                passed=False,
                ip_hash=ip_hash,
                request_id=request_id,
                error_message=f"Request too large. Maximum size is {self.max_request_size} bytes.",
            )

        # Check rate limits
        rate_result = await self.rate_limiter.check_rate_limit(ip_hash)
        if rate_result.blocked:
            audit_logger.log_rate_limit(
                ip_hash=ip_hash,
                limit_type=rate_result.status.value,
                current_count=rate_result.current_count,
            )
            return Layer0Result(
                status=Layer0Status.RATE_LIMITED,
                passed=False,
                ip_hash=ip_hash,
                request_id=request_id,
                error_message="Please wait a moment before sending another message.",
                retry_after=rate_result.retry_after,
            )

        # Check for message
        if not has_message:
            return Layer0Result(
                status=Layer0Status.MISSING_MESSAGE,
                passed=False,
                ip_hash=ip_hash,
                request_id=request_id,
                error_message="Message is required.",
            )

        # Record the request for rate limiting
        await self.rate_limiter.record_request(ip_hash)

        return Layer0Result(
            status=Layer0Status.PASSED,
            passed=True,
            ip_hash=ip_hash,
            request_id=request_id,
        )

    def get_user_friendly_error(self, result: Layer0Result) -> str:
        """
        Get a user-friendly error message.

        Args:
            result: The Layer0Result from validation.

        Returns:
            User-friendly error message.
        """
        error_messages = {
            Layer0Status.RATE_LIMITED: "Please wait a moment before sending another message.",
            Layer0Status.REQUEST_TOO_LARGE: "Your message is too long. Please shorten it.",
            Layer0Status.INVALID_CONTENT_TYPE: "Invalid request format.",
            Layer0Status.MISSING_MESSAGE: "Please enter a message.",
        }

        return error_messages.get(
            result.status,
            result.error_message or "An error occurred processing your request.",
        )
