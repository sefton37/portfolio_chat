"""Tests for configuration module."""

import os
from unittest import mock

import pytest

from portfolio_chat.config import (
    SecurityLimits,
    RateLimits,
    ModelConfig,
    ConversationLimits,
    SECURITY,
    RATE_LIMITS,
    MODELS,
    CONVERSATION,
)


class TestSecurityLimits:
    """Tests for SecurityLimits configuration."""

    def test_default_values(self):
        """Test default security limits."""
        assert SECURITY.MAX_INPUT_LENGTH >= 100
        assert SECURITY.MAX_REQUEST_SIZE >= 1024
        assert SECURITY.REQUEST_TIMEOUT >= 5

    def test_immutability(self):
        """Test that security limits are immutable."""
        with pytest.raises(AttributeError):
            SECURITY.MAX_INPUT_LENGTH = 100  # type: ignore


class TestRateLimits:
    """Tests for RateLimits configuration."""

    def test_default_values(self):
        """Test default rate limits."""
        assert RATE_LIMITS.PER_IP_PER_MINUTE >= 1
        assert RATE_LIMITS.PER_IP_PER_HOUR >= 10
        assert RATE_LIMITS.GLOBAL_PER_MINUTE >= 100

    def test_immutability(self):
        """Test that rate limits are immutable."""
        with pytest.raises(AttributeError):
            RATE_LIMITS.PER_IP_PER_MINUTE = 1000  # type: ignore


class TestModelConfig:
    """Tests for ModelConfig configuration."""

    def test_default_values(self):
        """Test default model configuration."""
        assert MODELS.CLASSIFIER_MODEL
        assert MODELS.ROUTER_MODEL
        assert MODELS.GENERATOR_MODEL
        assert MODELS.OLLAMA_URL.startswith("http")

    def test_timeout_minimums(self):
        """Test timeout minimum enforcement."""
        assert MODELS.CLASSIFIER_TIMEOUT >= 5.0
        assert MODELS.GENERATOR_TIMEOUT >= 10.0


class TestConversationLimits:
    """Tests for ConversationLimits configuration."""

    def test_default_values(self):
        """Test default conversation limits."""
        assert CONVERSATION.MAX_TURNS >= 2
        assert CONVERSATION.TTL_SECONDS >= 60
        assert CONVERSATION.MAX_HISTORY_TOKENS >= 500
