"""Unit tests for Layer 3: Intent Parsing."""

import pytest
from unittest.mock import AsyncMock

from portfolio_chat.pipeline.layer3_intent import (
    EmotionalTone,
    Intent,
    Layer3IntentParser,
    Layer3Result,
    Layer3Status,
    QuestionType,
)


class TestLayer3IntentParser:
    """Tests for Layer 3 Intent Parser."""

    @pytest.mark.asyncio
    async def test_parses_factual_question(self, mock_ollama_client):
        """Test parsing a factual question."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "topic": "skills",
                "question_type": "factual",
                "entities": ["Python", "JavaScript"],
                "emotional_tone": "curious",
                "confidence": 0.92,
            }
        )
        parser = Layer3IntentParser(client=mock_ollama_client)

        result = await parser.parse("What programming languages do you know?")

        assert result.passed
        assert result.status == Layer3Status.PARSED
        assert result.intent is not None
        assert result.intent.topic == "skills"
        assert result.intent.question_type == QuestionType.FACTUAL
        assert "Python" in result.intent.entities
        assert result.intent.emotional_tone == EmotionalTone.CURIOUS
        assert result.intent.confidence == 0.92

    @pytest.mark.asyncio
    async def test_parses_experience_question(self, mock_ollama_client):
        """Test parsing an experience question."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "topic": "work_experience",
                "question_type": "experience",
                "entities": ["Kohler"],
                "emotional_tone": "professional",
                "confidence": 0.88,
            }
        )
        parser = Layer3IntentParser(client=mock_ollama_client)

        result = await parser.parse("Tell me about your experience at Kohler")

        assert result.passed
        assert result.intent.question_type == QuestionType.EXPERIENCE
        assert "Kohler" in result.intent.entities

    @pytest.mark.asyncio
    async def test_parses_greeting(self, mock_ollama_client):
        """Test parsing a greeting."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "topic": "general",
                "question_type": "greeting",
                "entities": [],
                "emotional_tone": "casual",
                "confidence": 0.95,
            }
        )
        parser = Layer3IntentParser(client=mock_ollama_client)

        result = await parser.parse("Hello!")

        assert result.passed
        assert result.intent.question_type == QuestionType.GREETING

    @pytest.mark.asyncio
    async def test_handles_ambiguous_intent(self, mock_ollama_client):
        """Test handling of ambiguous intent."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "topic": "general",
                "question_type": "ambiguous",
                "entities": [],
                "emotional_tone": "neutral",
                "confidence": 0.25,
            }
        )
        parser = Layer3IntentParser(client=mock_ollama_client)

        result = await parser.parse("hmm")

        assert result.passed  # Still passes, routing handles ambiguity
        assert result.status == Layer3Status.AMBIGUOUS
        assert result.intent.question_type == QuestionType.AMBIGUOUS

    @pytest.mark.asyncio
    async def test_handles_low_confidence(self, mock_ollama_client):
        """Test that low confidence triggers ambiguous status."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "topic": "skills",
                "question_type": "factual",
                "entities": [],
                "emotional_tone": "neutral",
                "confidence": 0.15,  # Below 0.3 threshold
            }
        )
        parser = Layer3IntentParser(client=mock_ollama_client)

        result = await parser.parse("xyz abc")

        assert result.status == Layer3Status.AMBIGUOUS

    @pytest.mark.asyncio
    async def test_handles_ollama_error(self, mock_ollama_client_error):
        """Test error handling on Ollama failure."""
        parser = Layer3IntentParser(client=mock_ollama_client_error)

        result = await parser.parse("What skills do you have?")

        assert result.passed  # Still passes with default intent
        assert result.status == Layer3Status.ERROR
        assert result.intent is not None
        assert result.intent.question_type == QuestionType.AMBIGUOUS
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_handles_invalid_question_type(self, mock_ollama_client):
        """Test handling of unknown question type."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "topic": "skills",
                "question_type": "unknown_type",
                "entities": [],
                "emotional_tone": "neutral",
                "confidence": 0.8,
            }
        )
        parser = Layer3IntentParser(client=mock_ollama_client)

        result = await parser.parse("Test question")

        assert result.passed
        assert result.intent.question_type == QuestionType.AMBIGUOUS

    @pytest.mark.asyncio
    async def test_handles_invalid_emotional_tone(self, mock_ollama_client):
        """Test handling of unknown emotional tone."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "topic": "skills",
                "question_type": "factual",
                "entities": [],
                "emotional_tone": "angry",  # Not in enum
                "confidence": 0.8,
            }
        )
        parser = Layer3IntentParser(client=mock_ollama_client)

        result = await parser.parse("Test question")

        assert result.intent.emotional_tone == EmotionalTone.NEUTRAL

    @pytest.mark.asyncio
    async def test_handles_non_list_entities(self, mock_ollama_client):
        """Test handling when entities is not a list."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "topic": "skills",
                "question_type": "factual",
                "entities": "Python",  # String instead of list
                "emotional_tone": "neutral",
                "confidence": 0.8,
            }
        )
        parser = Layer3IntentParser(client=mock_ollama_client)

        result = await parser.parse("Test question")

        assert result.intent.entities == []

    @pytest.mark.asyncio
    async def test_custom_system_prompt(self, mock_ollama_client):
        """Test using custom system prompt."""
        custom_prompt = "Custom intent parser prompt"
        parser = Layer3IntentParser(
            client=mock_ollama_client,
            system_prompt=custom_prompt,
        )

        await parser.parse("Test")

        call_args = mock_ollama_client.chat_json.call_args
        assert call_args.kwargs["system"] == custom_prompt

    @pytest.mark.asyncio
    async def test_custom_model(self, mock_ollama_client):
        """Test using custom model."""
        parser = Layer3IntentParser(
            client=mock_ollama_client,
            model="custom-model",
        )

        await parser.parse("Test")

        call_args = mock_ollama_client.chat_json.call_args
        assert call_args.kwargs["model"] == "custom-model"


class TestIntent:
    """Tests for Intent dataclass."""

    def test_default_values(self):
        """Test Intent default values."""
        intent = Intent(topic="general", question_type=QuestionType.AMBIGUOUS)

        assert intent.entities == []
        assert intent.emotional_tone == EmotionalTone.NEUTRAL
        assert intent.confidence == 0.0
        assert intent.raw_response is None

    def test_full_initialization(self):
        """Test Intent with all values."""
        intent = Intent(
            topic="skills",
            question_type=QuestionType.FACTUAL,
            entities=["Python", "FastAPI"],
            emotional_tone=EmotionalTone.ENTHUSIASTIC,
            confidence=0.95,
            raw_response={"key": "value"},
        )

        assert intent.topic == "skills"
        assert intent.question_type == QuestionType.FACTUAL
        assert intent.entities == ["Python", "FastAPI"]
        assert intent.emotional_tone == EmotionalTone.ENTHUSIASTIC
        assert intent.confidence == 0.95
        assert intent.raw_response == {"key": "value"}


class TestQuestionType:
    """Tests for QuestionType enum."""

    def test_all_question_types(self):
        """Test that all expected question types exist."""
        expected = [
            "factual",
            "experience",
            "opinion",
            "comparison",
            "procedural",
            "clarification",
            "greeting",
            "ambiguous",
        ]
        actual = [qt.value for qt in QuestionType]
        for exp in expected:
            assert exp in actual


class TestEmotionalTone:
    """Tests for EmotionalTone enum."""

    def test_all_emotional_tones(self):
        """Test that all expected emotional tones exist."""
        expected = [
            "neutral",
            "curious",
            "professional",
            "casual",
            "skeptical",
            "enthusiastic",
        ]
        actual = [et.value for et in EmotionalTone]
        for exp in expected:
            assert exp in actual
