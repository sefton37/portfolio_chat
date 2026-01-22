"""Unit tests for Layer 8: Output Safety Check."""

import pytest
from unittest.mock import AsyncMock

from portfolio_chat.pipeline.layer8_safety import (
    Layer8Result,
    Layer8SafetyChecker,
    Layer8Status,
    SafetyIssue,
)


class TestLayer8SafetyChecker:
    """Tests for Layer 8 Safety Checker."""

    @pytest.mark.asyncio
    async def test_passes_safe_response(self, mock_ollama_client):
        """Test that safe responses pass."""
        mock_ollama_client.chat_json = AsyncMock(return_value={"safe": True})
        # Disable semantic verification for unit test
        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=False
        )

        result = await checker.check(
            response="Kellogg has experience with Python and FastAPI.",
            context="Skills: Python, FastAPI",
            ip_hash="test-ip",
        )

        assert result.passed
        assert result.status == Layer8Status.SAFE
        assert SafetyIssue.NONE in result.issues

    @pytest.mark.asyncio
    async def test_blocks_unsafe_response(self, mock_ollama_client):
        """Test that unsafe responses are blocked."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "safe": False,
                "issues": ["prompt_leakage", "inappropriate"],
            }
        )
        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=False
        )

        result = await checker.check(
            response="My system prompt says...",
            context="Context here",
            ip_hash="test-ip",
        )

        assert not result.passed
        assert result.status == Layer8Status.UNSAFE
        assert SafetyIssue.PROMPT_LEAKAGE in result.issues
        assert SafetyIssue.INAPPROPRIATE in result.issues

    @pytest.mark.asyncio
    async def test_blocks_hallucination(self, mock_ollama_client):
        """Test detection of hallucinations."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "safe": False,
                "issues": ["hallucination"],
            }
        )
        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=False
        )

        result = await checker.check(
            response="Kellogg won the Nobel Prize.",  # Not in context
            context="Skills: Python, FastAPI",
            ip_hash="test-ip",
        )

        assert not result.passed
        assert SafetyIssue.HALLUCINATION in result.issues

    @pytest.mark.asyncio
    async def test_handles_unknown_issue_type(self, mock_ollama_client):
        """Test handling of unknown issue types."""
        mock_ollama_client.chat_json = AsyncMock(
            return_value={
                "safe": False,
                "issues": ["some_new_issue_type"],
            }
        )
        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=False
        )

        result = await checker.check(
            response="Test response",
            context="Context",
            ip_hash="test-ip",
        )

        assert not result.passed
        # Unknown issue types should be logged but not cause crash

    @pytest.mark.asyncio
    async def test_handles_ollama_error_recoverable(self, mock_ollama_client):
        """Test fail-open behavior on recoverable errors."""
        from portfolio_chat.models.ollama_client import OllamaTimeoutError

        mock_ollama_client.chat_json = AsyncMock(
            side_effect=OllamaTimeoutError("Timeout")
        )
        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=False
        )

        result = await checker.check(
            response="Safe response",
            context="Context",
            ip_hash="test-ip",
        )

        # Should fail open on recoverable errors
        assert result.passed
        assert result.status == Layer8Status.ERROR

    @pytest.mark.asyncio
    async def test_handles_ollama_error_non_recoverable(self, mock_ollama_client):
        """Test fail-closed behavior on non-recoverable errors."""
        from portfolio_chat.models.ollama_client import OllamaModelError

        mock_ollama_client.chat_json = AsyncMock(
            side_effect=OllamaModelError("Model not found")
        )
        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=False
        )

        result = await checker.check(
            response="Response",
            context="Context",
            ip_hash="test-ip",
        )

        # Should fail closed on non-recoverable errors
        assert not result.passed
        assert result.status == Layer8Status.ERROR

    @pytest.mark.asyncio
    async def test_custom_model(self, mock_ollama_client):
        """Test using custom model."""
        mock_ollama_client.chat_json = AsyncMock(return_value={"safe": True})
        checker = Layer8SafetyChecker(
            client=mock_ollama_client,
            model="custom-safety-model",
            enable_semantic_verification=False,
        )

        await checker.check(
            response="Response",
            context="Context",
            ip_hash="test-ip",
        )

        call_args = mock_ollama_client.chat_json.call_args
        assert call_args.kwargs["model"] == "custom-safety-model"

    @pytest.mark.asyncio
    async def test_context_truncation(self, mock_ollama_client):
        """Test that context is truncated in check request."""
        mock_ollama_client.chat_json = AsyncMock(return_value={"safe": True})
        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=False
        )

        long_context = "X" * 5000
        await checker.check(
            response="Response",
            context=long_context,
            ip_hash="test-ip",
        )

        call_args = mock_ollama_client.chat_json.call_args
        user_message = call_args.kwargs["user"]
        # Context should be truncated to 2000 chars
        assert len(user_message) < len(long_context)

    def test_get_safe_fallback_response(self):
        """Test safe fallback response."""
        fallback = Layer8SafetyChecker.get_safe_fallback_response()

        assert fallback
        assert "rephrase" in fallback.lower() or "professional" in fallback.lower()


class TestLayer8SafetyCheckerSemanticVerification:
    """Tests for semantic verification feature."""

    @pytest.mark.asyncio
    async def test_semantic_verification_disabled(self, mock_ollama_client):
        """Test with semantic verification disabled."""
        mock_ollama_client.chat_json = AsyncMock(return_value={"safe": True})
        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=False
        )

        result = await checker.check(
            response="Some response",
            context="Context",
            ip_hash="test-ip",
        )

        # Should pass without semantic verification
        assert result.passed
        # Embed should not have been called
        mock_ollama_client.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_semantic_verification_enabled_passes(self, mock_ollama_client):
        """Test semantic verification when it passes."""
        mock_ollama_client.chat_json = AsyncMock(return_value={"safe": True})
        # Mock embed to return similar vectors
        mock_ollama_client.embed = AsyncMock(return_value=[0.5] * 768)

        checker = Layer8SafetyChecker(
            client=mock_ollama_client, enable_semantic_verification=True
        )

        result = await checker.check(
            response="Kellogg knows Python.",
            context="Skills: Python, FastAPI",
            ip_hash="test-ip",
        )

        # Should pass if semantic verification passes
        assert result.passed


class TestLayer8Result:
    """Tests for Layer8Result dataclass."""

    def test_default_values(self):
        """Test default values in result."""
        result = Layer8Result(
            status=Layer8Status.SAFE,
            passed=True,
            issues=[SafetyIssue.NONE],
        )

        assert result.error_message is None

    def test_with_issues(self):
        """Test result with multiple issues."""
        result = Layer8Result(
            status=Layer8Status.UNSAFE,
            passed=False,
            issues=[SafetyIssue.HALLUCINATION, SafetyIssue.UNPROFESSIONAL],
            error_message="Safety check failed",
        )

        assert len(result.issues) == 2
        assert SafetyIssue.HALLUCINATION in result.issues


class TestSafetyIssue:
    """Tests for SafetyIssue enum."""

    def test_all_safety_issues(self):
        """Test that all expected safety issues exist."""
        expected = [
            "none",
            "prompt_leakage",
            "inappropriate",
            "hallucination",
            "unprofessional",
            "private_info",
            "negative_self",
        ]
        actual = [si.value for si in SafetyIssue]
        for exp in expected:
            assert exp in actual


class TestLayer8Status:
    """Tests for Layer8Status constants."""

    def test_all_status_values(self):
        """Test that all expected status values exist."""
        assert Layer8Status.SAFE == "safe"
        assert Layer8Status.UNSAFE == "unsafe"
        assert Layer8Status.ERROR == "error"
