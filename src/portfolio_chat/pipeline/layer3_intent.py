"""
Layer 3: Intent Parsing

LLM-based intent extraction using a small router model.
Extracts structured intent information for downstream routing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from portfolio_chat.config import MODELS, PATHS
from portfolio_chat.models.ollama_client import (
    AsyncOllamaClient,
    OllamaError,
)

logger = logging.getLogger(__name__)


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


class Layer3IntentParser:
    """
    Intent parser using LLM.

    Extracts structured intent information:
    - Topic
    - Question type
    - Named entities
    - Emotional tone
    """

    DEFAULT_SYSTEM_PROMPT = """You are an intent parser for a portfolio chat system about Kellogg Brengel, a software engineer.

Parse the user's message and extract structured intent information.

VALID TOPICS (choose the most specific that applies):
- work_experience: Questions about jobs, roles, responsibilities
- skills: Technical skills, programming languages, tools
- projects: Specific projects, portfolio items, GitHub work
- education: Degrees, certifications, learning
- achievements: Awards, accomplishments, successes
- hobbies: Personal interests, volunteering, FIRST robotics
- philosophy: Problem-solving approach, values, working style
- contact: How to reach Kellogg, LinkedIn, networking
- chat_system: Questions about this chat interface itself
- general: General or unclear topics

QUESTION TYPES:
- factual: Asking for specific facts ("What languages do you know?")
- experience: Asking about experience ("Tell me about your work at...")
- opinion: Asking for opinions ("What do you think about...")
- comparison: Comparing things ("How does X compare to Y?")
- procedural: Asking about processes ("How do you approach...")
- clarification: Follow-up questions ("Can you explain more about...")
- greeting: Greetings ("Hello", "Hi")
- ambiguous: Can't determine intent

EMOTIONAL TONES:
- neutral, curious, professional, casual, skeptical, enthusiastic

OUTPUT FORMAT (JSON only):
{
  "topic": "one of the valid topics",
  "question_type": "one of the question types",
  "entities": ["list", "of", "mentioned", "entities"],
  "emotional_tone": "one of the tones",
  "confidence": 0.0 to 1.0
}"""

    def __init__(
        self,
        client: AsyncOllamaClient | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """
        Initialize intent parser.

        Args:
            client: Ollama client instance.
            model: Model to use for parsing.
            system_prompt: Custom system prompt.
        """
        self.client = client or AsyncOllamaClient()
        self.model = model or MODELS.ROUTER_MODEL
        self._system_prompt = system_prompt
        self._loaded_prompt: str | None = None

    def _get_system_prompt(self) -> str:
        """Get the system prompt, loading from file if available."""
        if self._system_prompt:
            return self._system_prompt

        if self._loaded_prompt:
            return self._loaded_prompt

        # Try to load from prompts directory
        prompt_file = PATHS.PROMPTS_DIR / "intent_parser.md"
        if prompt_file.exists():
            self._loaded_prompt = prompt_file.read_text().strip()
            return self._loaded_prompt

        return self.DEFAULT_SYSTEM_PROMPT

    async def parse(self, message: str) -> Layer3Result:
        """
        Parse intent from a message.

        Args:
            message: The sanitized user message.

        Returns:
            Layer3Result with extracted intent.
        """
        try:
            response = await self.client.chat_json(
                system=self._get_system_prompt(),
                user=f"Parse the intent of this message:\n\n{message}",
                model=self.model,
                timeout=MODELS.CLASSIFIER_TIMEOUT,
                layer="L3",
                purpose="intent_parsing",
            )

            # Parse response
            topic = response.get("topic", "general")
            question_type_str = response.get("question_type", "ambiguous")
            entities = response.get("entities", [])
            tone_str = response.get("emotional_tone", "neutral")
            confidence = float(response.get("confidence", 0.5))

            # Map to enums
            try:
                question_type = QuestionType(question_type_str)
            except ValueError:
                question_type = QuestionType.AMBIGUOUS

            try:
                emotional_tone = EmotionalTone(tone_str)
            except ValueError:
                emotional_tone = EmotionalTone.NEUTRAL

            # Ensure entities is a list of strings
            if not isinstance(entities, list):
                entities = []
            entities = [str(e) for e in entities]

            intent = Intent(
                topic=topic,
                question_type=question_type,
                entities=entities,
                emotional_tone=emotional_tone,
                confidence=confidence,
                raw_response=response,
            )

            # Check if ambiguous
            if question_type == QuestionType.AMBIGUOUS or confidence < 0.3:
                return Layer3Result(
                    status=Layer3Status.AMBIGUOUS,
                    passed=True,  # Still pass, routing will handle
                    intent=intent,
                )

            return Layer3Result(
                status=Layer3Status.PARSED,
                passed=True,
                intent=intent,
            )

        except OllamaError as e:
            logger.error(f"Ollama error in intent parsing: {e}")
            # Return a default intent on error
            default_intent = Intent(
                topic="general",
                question_type=QuestionType.AMBIGUOUS,
                confidence=0.0,
            )
            return Layer3Result(
                status=Layer3Status.ERROR,
                passed=True,  # Still pass, let routing try to handle
                intent=default_intent,
                error_message="Unable to parse intent",
            )

        except Exception as e:
            logger.error(f"Unexpected error in intent parsing: {e}")
            default_intent = Intent(
                topic="general",
                question_type=QuestionType.AMBIGUOUS,
                confidence=0.0,
            )
            return Layer3Result(
                status=Layer3Status.ERROR,
                passed=True,
                intent=default_intent,
                error_message=str(e),
            )
