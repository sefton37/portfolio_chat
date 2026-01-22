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

    def log_user_message(
        self,
        request_id: str,
        conversation_id: str,
        turn: int,
        raw_message: str,
        sanitized_message: str,
        ip_hash: str,
    ) -> None:
        """
        Log the full user message for audit trail.

        Args:
            request_id: Unique request ID.
            conversation_id: Conversation ID.
            turn: Conversation turn number.
            raw_message: Original user input.
            sanitized_message: Message after sanitization.
            ip_hash: Anonymized IP hash.
        """
        self._logger.info(
            "User message received",
            extra={
                "extra_data": {
                    "event": "user_message",
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "turn": turn,
                    "ip_hash": ip_hash,
                    "raw_message": raw_message,
                    "sanitized_message": sanitized_message,
                    "raw_length": len(raw_message),
                    "sanitized_length": len(sanitized_message),
                }
            },
        )

    def log_bot_response(
        self,
        request_id: str,
        conversation_id: str,
        turn: int,
        response: str,
        domain: str,
        revised: bool,
    ) -> None:
        """
        Log the full bot response for audit trail.

        Args:
            request_id: Unique request ID.
            conversation_id: Conversation ID.
            turn: Conversation turn number.
            response: Final response content.
            domain: Matched domain.
            revised: Whether L7 revision was applied.
        """
        self._logger.info(
            "Bot response generated",
            extra={
                "extra_data": {
                    "event": "bot_response",
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "turn": turn,
                    "response": response,
                    "response_length": len(response),
                    "domain": domain,
                    "revised": revised,
                }
            },
        )

    def log_intent_parsed(
        self,
        request_id: str,
        topic: str,
        question_type: str,
        entities: list[str],
        emotional_tone: str,
        confidence: float,
    ) -> None:
        """
        Log intent parsing results (L3).

        Args:
            request_id: Unique request ID.
            topic: Parsed topic.
            question_type: Type of question.
            entities: Extracted entities.
            emotional_tone: Detected tone.
            confidence: Parser confidence score.
        """
        self._logger.info(
            "Intent parsed",
            extra={
                "extra_data": {
                    "event": "intent_parsed",
                    "request_id": request_id,
                    "topic": topic,
                    "question_type": question_type,
                    "entities": entities,
                    "emotional_tone": emotional_tone,
                    "confidence": confidence,
                }
            },
        )

    def log_domain_routed(
        self,
        request_id: str,
        domain: str,
        confidence: float,
        fallback_used: bool,
    ) -> None:
        """
        Log domain routing decision (L4).

        Args:
            request_id: Unique request ID.
            domain: Routed domain.
            confidence: Routing confidence.
            fallback_used: Whether fallback routing was used.
        """
        self._logger.info(
            "Domain routed",
            extra={
                "extra_data": {
                    "event": "domain_routed",
                    "request_id": request_id,
                    "domain": domain,
                    "confidence": confidence,
                    "fallback_used": fallback_used,
                }
            },
        )

    def log_context_retrieved(
        self,
        request_id: str,
        domain: str,
        sources_used: list[str],
        context_length: int,
    ) -> None:
        """
        Log context retrieval details (L5).

        Args:
            request_id: Unique request ID.
            domain: Domain used for retrieval.
            sources_used: List of context source names.
            context_length: Total context character count.
        """
        self._logger.info(
            "Context retrieved",
            extra={
                "extra_data": {
                    "event": "context_retrieved",
                    "request_id": request_id,
                    "domain": domain,
                    "sources_used": sources_used,
                    "context_length": context_length,
                }
            },
        )

    def log_llm_call(
        self,
        request_id: str,
        layer: str,
        model: str,
        purpose: str,
        prompt_tokens_approx: int,
        response_tokens_approx: int,
        duration_ms: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        """
        Log an LLM call with full details.

        Args:
            request_id: Unique request ID.
            layer: Which layer made the call (L2, L3, L6, etc).
            model: Model name used.
            purpose: Purpose of the call (classify, parse, generate, etc).
            prompt_tokens_approx: Approximate prompt token count.
            response_tokens_approx: Approximate response token count.
            duration_ms: Call duration in milliseconds.
            success: Whether call succeeded.
            error: Error message if failed.
        """
        self._logger.info(
            "LLM call completed",
            extra={
                "extra_data": {
                    "event": "llm_call",
                    "request_id": request_id,
                    "layer": layer,
                    "model": model,
                    "purpose": purpose,
                    "prompt_tokens_approx": prompt_tokens_approx,
                    "response_tokens_approx": response_tokens_approx,
                    "duration_ms": duration_ms,
                    "success": success,
                    "error": error,
                }
            },
        )

    def log_layer_timing(
        self,
        request_id: str,
        layer_timings: dict[str, float],
        total_time_ms: float,
    ) -> None:
        """
        Log all layer timings for a request.

        Args:
            request_id: Unique request ID.
            layer_timings: Dict of layer name to timing in seconds.
            total_time_ms: Total request time in milliseconds.
        """
        # Convert to ms for consistency
        timings_ms = {k: round(v * 1000, 2) for k, v in layer_timings.items()}
        self._logger.info(
            "Layer timings",
            extra={
                "extra_data": {
                    "event": "layer_timings",
                    "request_id": request_id,
                    "timings_ms": timings_ms,
                    "total_time_ms": round(total_time_ms, 2),
                }
            },
        )

    def log_safety_check(
        self,
        request_id: str,
        layer: str,
        passed: bool,
        classification: str,
        confidence: float,
        reason: str | None = None,
    ) -> None:
        """
        Log safety check results (L2 jailbreak, L8 output safety).

        Args:
            request_id: Unique request ID.
            layer: Which layer (L2 or L8).
            passed: Whether the check passed.
            classification: Classification result (SAFE/BLOCKED/UNSAFE).
            confidence: Classifier confidence.
            reason: Reason code if blocked.
        """
        self._logger.info(
            "Safety check completed",
            extra={
                "extra_data": {
                    "event": "safety_check",
                    "request_id": request_id,
                    "layer": layer,
                    "passed": passed,
                    "classification": classification,
                    "confidence": confidence,
                    "reason": reason,
                }
            },
        )

    def log_tool_execution(
        self,
        request_id: str,
        tool_name: str,
        success: bool,
        result_summary: str,
    ) -> None:
        """
        Log tool execution during conversation (L6).

        Args:
            request_id: Unique request ID.
            tool_name: Name of the tool executed.
            success: Whether the tool execution succeeded.
            result_summary: Brief summary of the result.
        """
        self._logger.info(
            "Tool executed",
            extra={
                "extra_data": {
                    "event": "tool_execution",
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "success": success,
                    "result_summary": result_summary,
                }
            },
        )


# Module-level audit logger instance
audit_logger = AuditLogger()
