"""Test object factories for creating test data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time


class IntentFactory:
    """Factory for creating Intent objects for testing."""

    @staticmethod
    def create(
        topic: str = "skills",
        question_type: str = "factual",
        entities: list[str] | None = None,
        emotional_tone: str = "neutral",
        confidence: float = 0.85,
    ):
        """Create an Intent object for testing."""
        from portfolio_chat.pipeline.layer3_intent import (
            Intent,
            QuestionType,
            EmotionalTone,
        )

        return Intent(
            topic=topic,
            question_type=QuestionType(question_type),
            entities=entities or [],
            emotional_tone=EmotionalTone(emotional_tone),
            confidence=confidence,
        )

    @staticmethod
    def skills():
        """Create a skills-related intent."""
        return IntentFactory.create(
            topic="skills",
            question_type="factual",
            entities=["Python", "FastAPI"],
            confidence=0.9,
        )

    @staticmethod
    def experience():
        """Create an experience-related intent."""
        return IntentFactory.create(
            topic="work_experience",
            question_type="experience",
            entities=["Kohler"],
            emotional_tone="professional",
            confidence=0.88,
        )

    @staticmethod
    def greeting():
        """Create a greeting intent."""
        return IntentFactory.create(
            topic="general",
            question_type="greeting",
            entities=[],
            emotional_tone="casual",
            confidence=0.95,
        )

    @staticmethod
    def ambiguous():
        """Create an ambiguous intent."""
        return IntentFactory.create(
            topic="general",
            question_type="ambiguous",
            entities=[],
            confidence=0.3,
        )


class ChatResponseFactory:
    """Factory for creating ChatResponse objects for testing."""

    @staticmethod
    def success(
        response: str = "Test response content",
        domain: str = "professional",
        request_id: str = "test-request-123",
        conversation_id: str = "test-conv-456",
    ):
        """Create a successful ChatResponse."""
        from portfolio_chat.pipeline.layer9_deliver import (
            ChatResponse,
            ResponseMetadata,
        )

        return ChatResponse(
            success=True,
            response=response,
            domain=domain,
            metadata=ResponseMetadata(
                request_id=request_id,
                response_time_ms=100.0,
                domain=domain,
                conversation_id=conversation_id,
            ),
        )

    @staticmethod
    def error(
        error_code: str = "INTERNAL_ERROR",
        error_message: str = "An error occurred",
        request_id: str = "test-request-123",
        conversation_id: str = "test-conv-456",
    ):
        """Create an error ChatResponse."""
        from portfolio_chat.pipeline.layer9_deliver import (
            ChatResponse,
            ResponseMetadata,
        )

        return ChatResponse(
            success=False,
            error_code=error_code,
            error_message=error_message,
            metadata=ResponseMetadata(
                request_id=request_id,
                response_time_ms=50.0,
                domain=None,
                conversation_id=conversation_id,
            ),
        )

    @staticmethod
    def rate_limited():
        """Create a rate-limited error response."""
        return ChatResponseFactory.error(
            error_code="RATE_LIMITED",
            error_message="Please wait before sending another message",
        )

    @staticmethod
    def blocked():
        """Create a blocked input error response."""
        return ChatResponseFactory.error(
            error_code="BLOCKED_INPUT",
            error_message="I can only answer questions about Kellogg's professional background",
        )


class ConversationHistoryFactory:
    """Factory for creating conversation history for testing."""

    @staticmethod
    def create(
        exchanges: int = 2,
        user_messages: list[str] | None = None,
        assistant_messages: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """
        Create a conversation history.

        Args:
            exchanges: Number of user-assistant exchanges
            user_messages: Custom user messages
            assistant_messages: Custom assistant messages

        Returns:
            List of message dicts with role and content
        """
        history = []

        default_user = [
            "What programming languages do you know?",
            "Tell me more about Python",
            "What frameworks do you use?",
            "Can you give an example?",
            "Thanks, that's helpful!",
        ]

        default_assistant = [
            "I work primarily with Python, TypeScript, and SQL.",
            "I have extensive experience with Python, especially for backend development and data engineering.",
            "I frequently use FastAPI for APIs and Django for web applications.",
            "For example, this chat system is built with FastAPI and uses a 9-layer security pipeline.",
            "You're welcome! Let me know if you have any other questions.",
        ]

        user_msgs = user_messages or default_user
        assistant_msgs = assistant_messages or default_assistant

        for i in range(min(exchanges, len(user_msgs), len(assistant_msgs))):
            history.append({"role": "user", "content": user_msgs[i]})
            history.append({"role": "assistant", "content": assistant_msgs[i]})

        return history

    @staticmethod
    def empty() -> list[dict[str, str]]:
        """Create empty conversation history."""
        return []

    @staticmethod
    def single_exchange() -> list[dict[str, str]]:
        """Create a single exchange conversation."""
        return ConversationHistoryFactory.create(exchanges=1)

    @staticmethod
    def max_turns(max_turns: int = 5) -> list[dict[str, str]]:
        """Create conversation at max turns."""
        return ConversationHistoryFactory.create(exchanges=max_turns)


class Layer0ResultFactory:
    """Factory for creating Layer0Result objects."""

    @staticmethod
    def passed(ip_hash: str = "abc123", request_id: str = "req-123"):
        """Create a passed Layer0Result."""
        from portfolio_chat.pipeline.layer0_network import (
            Layer0Result,
            Layer0Status,
        )

        return Layer0Result(
            status=Layer0Status.PASSED,
            passed=True,
            ip_hash=ip_hash,
            request_id=request_id,
        )

    @staticmethod
    def rate_limited(ip_hash: str = "abc123", request_id: str = "req-123"):
        """Create a rate-limited Layer0Result."""
        from portfolio_chat.pipeline.layer0_network import (
            Layer0Result,
            Layer0Status,
        )

        return Layer0Result(
            status=Layer0Status.RATE_LIMITED,
            passed=False,
            ip_hash=ip_hash,
            request_id=request_id,
            error_message="Please wait before sending another message",
            retry_after=30.0,
        )


class Layer1ResultFactory:
    """Factory for creating Layer1 sanitization results."""

    @staticmethod
    def passed(sanitized_input: str = "Clean input text"):
        """Create a passed sanitization result."""
        from portfolio_chat.pipeline.layer1_sanitize import (
            Layer1Result,
            Layer1Status,
        )

        return Layer1Result(
            status=Layer1Status.PASSED,
            passed=True,
            sanitized_input=sanitized_input,
            original_length=len(sanitized_input),
            sanitized_length=len(sanitized_input),
        )

    @staticmethod
    def blocked(pattern: str = "instruction_override"):
        """Create a blocked sanitization result."""
        from portfolio_chat.pipeline.layer1_sanitize import (
            Layer1Result,
            Layer1Status,
        )

        return Layer1Result(
            status=Layer1Status.BLOCKED_PATTERN,
            passed=False,
            blocked_pattern=pattern,
            error_message="Input contains blocked pattern",
            original_length=50,
            sanitized_length=0,
        )


class Layer2ResultFactory:
    """Factory for creating Layer2 jailbreak detection results."""

    @staticmethod
    def safe(confidence: float = 0.95):
        """Create a safe detection result."""
        from portfolio_chat.pipeline.layer2_jailbreak import (
            Layer2Result,
            Layer2Status,
            JailbreakReason,
        )

        return Layer2Result(
            status=Layer2Status.SAFE,
            passed=True,
            reason=JailbreakReason.NONE,
            confidence=confidence,
        )

    @staticmethod
    def blocked(reason: str = "instruction_override", confidence: float = 0.92):
        """Create a blocked detection result."""
        from portfolio_chat.pipeline.layer2_jailbreak import (
            Layer2Result,
            Layer2Status,
            JailbreakReason,
        )

        return Layer2Result(
            status=Layer2Status.BLOCKED,
            passed=False,
            reason=JailbreakReason(reason),
            confidence=confidence,
            error_message="I can only answer questions about Kellogg's professional background",
        )
