"""Unit tests for Layer 7: Response Revision."""

import pytest
from unittest.mock import AsyncMock

from portfolio_chat.pipeline.layer7_revise import (
    Layer7Result,
    Layer7Reviser,
    Layer7Status,
)


class TestLayer7Reviser:
    """Tests for Layer 7 Response Reviser."""

    @pytest.mark.asyncio
    async def test_skips_short_responses(self, mock_ollama_client):
        """Test that short responses skip revision."""
        reviser = Layer7Reviser(client=mock_ollama_client)

        result = await reviser.revise(
            response="Short response.",  # Less than 200 chars
            context="Context here",
            original_question="What do you do?",
        )

        assert result.passed
        assert result.status == Layer7Status.SKIPPED
        assert not result.was_revised
        assert result.response == "Short response."
        # Client should not be called for short responses
        mock_ollama_client.chat_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_good_response(self, mock_ollama_client):
        """Test that good responses pass without revision."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={"needs_revision": False}
        )
        reviser = Layer7Reviser(client=mock_ollama_client, min_length=10)

        long_response = "A" * 250  # Exceeds minimum length
        result = await reviser.revise(
            response=long_response,
            context="Context here",
            original_question="Tell me about yourself",
        )

        assert result.passed
        assert result.status == Layer7Status.PASSED
        assert not result.was_revised
        assert result.response == long_response

    @pytest.mark.asyncio
    async def test_revises_problematic_response(self, mock_ollama_client):
        """Test that problematic responses get revised."""
        original = "A" * 250
        revised = "B" * 200  # Different revised response

        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "needs_revision": True,
                "issues": ["tone too casual", "missing information"],
                "revised_response": revised,
            }
        )
        reviser = Layer7Reviser(client=mock_ollama_client, min_length=10)

        result = await reviser.revise(
            response=original,
            context="Context here",
            original_question="Tell me about yourself",
        )

        assert result.passed
        assert result.status == Layer7Status.REVISED
        assert result.was_revised
        assert result.response == revised
        assert "tone too casual" in result.revision_notes

    @pytest.mark.asyncio
    async def test_ignores_invalid_revision(self, mock_ollama_client):
        """Test that invalid revisions are ignored."""
        original = "A" * 250

        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "needs_revision": True,
                "issues": ["some issue"],
                "revised_response": "Too short",  # Less than 50 chars
            }
        )
        reviser = Layer7Reviser(client=mock_ollama_client, min_length=10)

        result = await reviser.revise(
            response=original,
            context="Context here",
            original_question="Tell me about yourself",
        )

        assert result.passed
        assert result.status == Layer7Status.PASSED
        assert not result.was_revised
        assert result.response == original  # Original preserved

    @pytest.mark.asyncio
    async def test_handles_ollama_error(self, mock_ollama_client_error):
        """Test error handling - passes through original on error."""
        original = "A" * 250
        reviser = Layer7Reviser(client=mock_ollama_client_error, min_length=10)

        result = await reviser.revise(
            response=original,
            context="Context here",
            original_question="Tell me about yourself",
        )

        assert result.passed  # Don't block on revision errors
        assert result.status == Layer7Status.ERROR
        assert not result.was_revised
        assert result.response == original  # Original preserved
        assert result.revision_notes is not None

    @pytest.mark.asyncio
    async def test_custom_min_length(self, mock_ollama_client):
        """Test custom minimum length configuration."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={"needs_revision": False}
        )
        reviser = Layer7Reviser(client=mock_ollama_client, min_length=50)

        # 60 chars - above custom minimum
        result = await reviser.revise(
            response="A" * 60,
            context="Context",
            original_question="Question",
        )

        # Should have called LLM since above min_length
        mock_ollama_client.chat_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_truncation(self, mock_ollama_client):
        """Test that context is truncated for revision request."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={"needs_revision": False}
        )
        reviser = Layer7Reviser(client=mock_ollama_client, min_length=10)

        long_context = "X" * 5000  # 5000 chars
        await reviser.revise(
            response="A" * 250,
            context=long_context,
            original_question="Question",
        )

        call_args = mock_ollama_client.chat_json.call_args
        user_message = call_args.kwargs["user"]
        # Context should be truncated to 2000 chars in the request
        assert len(user_message) < len(long_context)

    @pytest.mark.asyncio
    async def test_custom_model(self, mock_ollama_client):
        """Test using custom model."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={"needs_revision": False}
        )
        reviser = Layer7Reviser(
            client=mock_ollama_client,
            model="custom-verifier",
            min_length=10,
        )

        await reviser.revise(
            response="A" * 250,
            context="Context",
            original_question="Question",
        )

        call_args = mock_ollama_client.chat_json.call_args
        assert call_args.kwargs["model"] == "custom-verifier"


class TestLayer7Result:
    """Tests for Layer7Result dataclass."""

    def test_default_values(self):
        """Test default values in result."""
        result = Layer7Result(
            status=Layer7Status.PASSED,
            passed=True,
            response="Test response",
        )

        assert not result.was_revised
        assert result.revision_notes is None

    def test_with_revision(self):
        """Test result with revision."""
        result = Layer7Result(
            status=Layer7Status.REVISED,
            passed=True,
            response="Revised response",
            was_revised=True,
            revision_notes="Fixed tone",
        )

        assert result.was_revised
        assert result.revision_notes == "Fixed tone"


class TestLayer7Status:
    """Tests for Layer7Status constants."""

    def test_all_status_values(self):
        """Test that all expected status values exist."""
        assert Layer7Status.REVISED == "revised"
        assert Layer7Status.SKIPPED == "skipped"
        assert Layer7Status.PASSED == "passed"
        assert Layer7Status.ERROR == "error"
