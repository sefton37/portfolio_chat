"""
Structured logging utilities.

Provides JSON logging with request ID propagation and anonymized IP logging.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from portfolio_chat.config import SERVER

# Context variable for request ID propagation
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


def hash_ip(ip: str) -> str:
    """
    Hash an IP address for anonymized logging.

    Args:
        ip: Raw IP address.

    Returns:
        SHA256 hash of the IP address (first 16 chars).
    """
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request ID if available
        request_id = request_id_var.get()
        if request_id:
            log_data["request_id"] = request_id

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class RequestContextAdapter(logging.LoggerAdapter):
    """Logger adapter that automatically includes request context."""

    def process(
        self, msg: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Add request context to log record."""
        extra = kwargs.get("extra", {})

        # Add request ID
        request_id = request_id_var.get()
        if request_id:
            extra["request_id"] = request_id

        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging(
    level: str | None = None,
    json_format: bool = True,
) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        json_format: Whether to use JSON formatting.
    """
    log_level = getattr(logging, (level or SERVER.LOG_LEVEL).upper(), logging.INFO)

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if json_format:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )

    root_logger.addHandler(console_handler)

    # Set third-party loggers to WARNING
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Configured logger instance.
    """
    return logging.getLogger(name)


class AuditLogger:
    """
    Specialized logger for security audit events.

    Logs injection attempts and other security-relevant events
    with appropriate detail for analysis.
    """

    def __init__(self) -> None:
        """Initialize audit logger."""
        self._logger = logging.getLogger("portfolio_chat.audit")

    def log_injection_attempt(
        self,
        ip_hash: str,
        layer: str,
        reason: str,
        input_preview: str | None = None,
    ) -> None:
        """
        Log a detected injection attempt.

        Args:
            ip_hash: Anonymized IP hash.
            layer: Layer that detected the attempt (e.g., "L1", "L2").
            reason: Reason code for the block.
            input_preview: First N chars of input (for analysis).
        """
        self._logger.warning(
            "Injection attempt detected",
            extra={
                "extra_data": {
                    "event": "injection_attempt",
                    "ip_hash": ip_hash,
                    "layer": layer,
                    "reason": reason,
                    "input_preview": input_preview[:50] if input_preview else None,
                }
            },
        )

    def log_rate_limit(
        self,
        ip_hash: str,
        limit_type: str,
        current_count: int,
    ) -> None:
        """
        Log a rate limit event.

        Args:
            ip_hash: Anonymized IP hash.
            limit_type: Type of limit hit (minute, hour, global).
            current_count: Current request count.
        """
        self._logger.info(
            "Rate limit triggered",
            extra={
                "extra_data": {
                    "event": "rate_limit",
                    "ip_hash": ip_hash,
                    "limit_type": limit_type,
                    "current_count": current_count,
                }
            },
        )

    def log_request_complete(
        self,
        ip_hash: str,
        domain: str | None,
        response_time_ms: float,
        blocked_at_layer: str | None = None,
    ) -> None:
        """
        Log completion of a request.

        Args:
            ip_hash: Anonymized IP hash.
            domain: Matched domain or None.
            response_time_ms: Total response time.
            blocked_at_layer: Layer that blocked (if any).
        """
        self._logger.info(
            "Request completed",
            extra={
                "extra_data": {
                    "event": "request_complete",
                    "ip_hash": ip_hash,
                    "domain": domain,
                    "response_time_ms": response_time_ms,
                    "blocked_at_layer": blocked_at_layer,
                }
            },
        )


# Module-level audit logger instance
audit_logger = AuditLogger()
