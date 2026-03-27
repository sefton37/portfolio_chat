"""
Intent data types.

Shared dataclasses used by layer2_combined (classifier) and layer4_route (router).
The standalone Layer3IntentParser class was removed — intent extraction is now
handled by the combined L2+L3 classifier in layer2_combined.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QuestionType(Enum):
    """Types of questions that can be asked."""

    FACTUAL = "factual"  # "What is X?"
    EXPERIENCE = "experience"  # "Tell me about your experience with X"
    OPINION = "opinion"  # "What do you think about X?"
    COMPARISON = "comparison"  # "How does X compare to Y?"
    PROCEDURAL = "procedural"  # "How do you approach X?"
    CLARIFICATION = "clarification"  # Follow-up questions
    GREETING = "greeting"  # "Hello", "Hi there"
    AMBIGUOUS = "ambiguous"  # Unclear intent


class EmotionalTone(Enum):
    """Emotional tone of the message."""

    NEUTRAL = "neutral"
    CURIOUS = "curious"
    PROFESSIONAL = "professional"
    CASUAL = "casual"
    SKEPTICAL = "skeptical"
    ENTHUSIASTIC = "enthusiastic"


@dataclass
class Intent:
    """Structured intent extracted from user message."""

    topic: str  # Main topic of the question
    question_type: QuestionType
    entities: list[str] = field(default_factory=list)  # Named entities mentioned
    emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
    confidence: float = 0.0
    raw_response: dict | None = None  # For debugging


class Layer3Status(Enum):
    """Status codes for Layer 3 intent parsing."""

    PARSED = "parsed"
    AMBIGUOUS = "ambiguous"
    ERROR = "error"


@dataclass
class Layer3Result:
    """Result of Layer 3 intent parsing."""

    status: Layer3Status
    passed: bool
    intent: Intent | None = None
    error_message: str | None = None


