"""
Layer 9: Response Delivery

Final response formatting and metadata assembly.
Handles JSON response formatting and conversation history updates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from portfolio_chat.pipeline.layer4_route import Domain
from portfolio_chat.utils.logging import audit_logger


@dataclass
class ResponseMetadata:
    """Metadata included with responses."""

    request_id: str
    response_time_ms: float
    domain: str | None
    conversation_id: str
    layer_timings: dict[str, float] = field(default_factory=dict)


@dataclass
class ChatResponse:
    """Final chat response structure."""

    success: bool
    response: str | None = None
    domain: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: ResponseMetadata | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "success": self.success,
        }

        if self.success and self.response:
            result["response"] = {
                "content": self.response,
                "domain": self.domain,
            }
        elif not self.success:
            result["error"] = {
                "code": self.error_code or "INTERNAL_ERROR",
                "message": self.error_message or "An error occurred.",
            }

        if self.metadata:
            result["metadata"] = {
                "request_id": self.metadata.request_id,
                "response_time_ms": round(self.metadata.response_time_ms, 2),
                "conversation_id": self.metadata.conversation_id,
                "layer_timings_ms": {
                    layer: round(timing * 1000, 2)
                    for layer, timing in self.metadata.layer_timings.items()
                } if self.metadata.layer_timings else {},
            }

        return result


class Layer9Deliverer:
    """
    Response deliverer - final formatting and assembly.

    Handles:
    - JSON response formatting
    - Metadata inclusion
    - Anonymized logging
    - Conversation history updates
    """

    # Error code mappings
    ERROR_CODES = {
        "rate_limited": "RATE_LIMITED",
        "input_too_long": "INPUT_TOO_LONG",
        "blocked_input": "BLOCKED_INPUT",
        "out_of_scope": "OUT_OF_SCOPE",
        "safety_failed": "SAFETY_FAILED",
        "internal_error": "INTERNAL_ERROR",
    }

    # User-friendly error messages
    ERROR_MESSAGES = {
        "RATE_LIMITED": "Please wait a moment before sending another message.",
        "INPUT_TOO_LONG": "Your message is a bit long. Could you shorten it?",
        "BLOCKED_INPUT": "I can only answer questions about Kellogg's professional background and projects.",
        "OUT_OF_SCOPE": "I'm designed to answer questions about Kel's work and projects. For other topics, I'd recommend a general AI assistant.",
        "SAFETY_FAILED": "Let me rephrase that...",
        "INTERNAL_ERROR": "I'm having some technical difficulties. Please try again.",
    }

    def __init__(self) -> None:
        """Initialize deliverer."""
        pass

    def deliver_success(
        self,
        response: str,
        domain: Domain,
        request_id: str,
        conversation_id: str,
        start_time: float,
        ip_hash: str,
        layer_timings: dict[str, float] | None = None,
    ) -> ChatResponse:
        """
        Deliver a successful response.

        Args:
            response: The final response content.
            domain: The matched domain.
            request_id: Unique request ID.
            conversation_id: Conversation ID.
            start_time: Request start time (time.time()).
            ip_hash: Anonymized IP hash for logging.
            layer_timings: Optional timing data per layer.

        Returns:
            ChatResponse ready for serialization.
        """
        response_time_ms = (time.time() - start_time) * 1000

        metadata = ResponseMetadata(
            request_id=request_id,
            response_time_ms=response_time_ms,
            domain=domain.value,
            conversation_id=conversation_id,
            layer_timings=layer_timings or {},
        )

        # Log successful completion
        audit_logger.log_request_complete(
            ip_hash=ip_hash,
            domain=domain.value,
            response_time_ms=response_time_ms,
        )

        return ChatResponse(
            success=True,
            response=response,
            domain=domain.value,
            metadata=metadata,
        )

    def deliver_error(
        self,
        error_type: str,
        request_id: str,
        conversation_id: str,
        start_time: float,
        ip_hash: str,
        blocked_at_layer: str | None = None,
        custom_message: str | None = None,
    ) -> ChatResponse:
        """
        Deliver an error response.

        Args:
            error_type: Error type key (e.g., "rate_limited").
            request_id: Unique request ID.
            conversation_id: Conversation ID.
            start_time: Request start time.
            ip_hash: Anonymized IP hash for logging.
            blocked_at_layer: Which layer blocked the request.
            custom_message: Optional custom error message.

        Returns:
            ChatResponse with error details.
        """
        response_time_ms = (time.time() - start_time) * 1000

        error_code = self.ERROR_CODES.get(error_type, "INTERNAL_ERROR")
        error_message = custom_message or self.ERROR_MESSAGES.get(
            error_code, "An error occurred."
        )

        metadata = ResponseMetadata(
            request_id=request_id,
            response_time_ms=response_time_ms,
            domain=None,
            conversation_id=conversation_id,
        )

        # Log blocked/error completion
        audit_logger.log_request_complete(
            ip_hash=ip_hash,
            domain=None,
            response_time_ms=response_time_ms,
            blocked_at_layer=blocked_at_layer,
        )

        return ChatResponse(
            success=False,
            error_code=error_code,
            error_message=error_message,
            metadata=metadata,
        )

    def get_canned_response(self, error_code: str) -> str:
        """Get a canned response for an error type."""
        canned_responses = {
            "RATE_LIMITED": "Please wait a moment before sending another message.",
            "INPUT_TOO_LONG": "Your message is quite long. Could you try asking a shorter question?",
            "BLOCKED_INPUT": "I can only answer questions about Kellogg's professional background, projects, and related topics. Is there something in that area I can help with?",
            "OUT_OF_SCOPE": "I'm designed to discuss Kel's professional work and projects. For other topics, a general AI assistant might be more helpful. What would you like to know about Kel's experience?",
            "SAFETY_FAILED": "Let me try again. I'd be happy to discuss my professional background and projects. What would you like to know?",
            "INTERNAL_ERROR": "I'm experiencing some technical difficulties right now. Please try your question again in a moment.",
        }
        return canned_responses.get(error_code, "An error occurred. Please try again.")
