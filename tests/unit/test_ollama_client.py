"""Unit tests for the Ollama client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from portfolio_chat.models.ollama_client import (
    AsyncOllamaClient,
    OllamaConnectionError,
    OllamaError,
    OllamaModelError,
    OllamaResponseError,
    OllamaTimeoutError,
)


class TestAsyncOllamaClient:
    """Tests for AsyncOllamaClient."""

    def test_init_default_values(self):
        """Test client initialization with defaults."""
        client = AsyncOllamaClient()
        assert client.url  # Should have default URL
        assert client._client is None

    def test_init_custom_values(self):
        """Test client initialization with custom values."""
        client = AsyncOllamaClient(
            url="http://custom:11434",
            default_model="custom-model",
        )
        assert client.url == "http://custom:11434"
        assert client.default_model == "custom-model"

    def test_url_trailing_slash_stripped(self):
        """Test that trailing slash is stripped from URL."""
        client = AsyncOllamaClient(url="http://localhost:11434/")
        assert client.url == "http://localhost:11434"

    @pytest.mark.asyncio
    async def test_get_client_creates_client(self):
        """Test that _get_client creates httpx client."""
        client = AsyncOllamaClient()
        http_client = await client._get_client()

        assert http_client is not None
        assert isinstance(http_client, httpx.AsyncClient)
        await client.close()

    @pytest.mark.asyncio
    async def test_close_closes_client(self):
        """Test that close properly closes the client."""
        client = AsyncOllamaClient()
        await client._get_client()  # Create client
        await client.close()

        assert client._client is None or client._client.is_closed

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with AsyncOllamaClient() as client:
            assert client is not None

    def test_resolve_model_explicit(self):
        """Test model resolution with explicit model."""
        client = AsyncOllamaClient(default_model="default-model")
        resolved = client._resolve_model("explicit-model")
        assert resolved == "explicit-model"

    def test_resolve_model_default(self):
        """Test model resolution with default model."""
        client = AsyncOllamaClient(default_model="default-model")
        resolved = client._resolve_model(None)
        assert resolved == "default-model"

    def test_strip_markdown_json_plain(self):
        """Test stripping markdown from plain JSON."""
        content = '{"key": "value"}'
        result = AsyncOllamaClient._strip_markdown_json(content)
        assert result == '{"key": "value"}'

    def test_strip_markdown_json_with_code_block(self):
        """Test stripping markdown from code block."""
        content = '```json\n{"key": "value"}\n```'
        result = AsyncOllamaClient._strip_markdown_json(content)
        assert result == '{"key": "value"}'

    def test_strip_markdown_json_with_plain_block(self):
        """Test stripping markdown from plain code block."""
        content = '```\n{"key": "value"}\n```'
        result = AsyncOllamaClient._strip_markdown_json(content)
        assert result == '{"key": "value"}'


class TestAsyncOllamaClientChatText:
    """Tests for chat_text method."""

    @pytest.mark.asyncio
    async def test_chat_text_success(self):
        """Test successful text chat."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": {"content": "Hello! How can I help?"}
            }

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()
            result = await client.chat_text(
                system="You are helpful.",
                user="Hello",
                model="test-model",
            )

            assert result == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_chat_text_model_not_found(self):
        """Test handling of model not found error."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()

            with pytest.raises(OllamaModelError) as exc_info:
                await client.chat_text(
                    system="System",
                    user="User",
                    model="nonexistent-model",
                )

            assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_chat_text_empty_response(self):
        """Test handling of empty response."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"message": {"content": ""}}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()

            with pytest.raises(OllamaResponseError) as exc_info:
                await client.chat_text(system="System", user="User")

            assert "empty" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_chat_text_connection_error(self):
        """Test handling of connection errors."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()

            with pytest.raises(OllamaConnectionError):
                await client.chat_text(system="System", user="User")

    @pytest.mark.asyncio
    async def test_chat_text_timeout_error(self):
        """Test handling of timeout errors."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()

            with pytest.raises(OllamaTimeoutError):
                await client.chat_text(system="System", user="User")


class TestAsyncOllamaClientChatJson:
    """Tests for chat_json method."""

    @pytest.mark.asyncio
    async def test_chat_json_success(self):
        """Test successful JSON chat."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": {"content": '{"classification": "SAFE"}'}
            }

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()
            result = await client.chat_json(
                system="Classify",
                user="Test",
                model="classifier",
            )

            assert result == {"classification": "SAFE"}

    @pytest.mark.asyncio
    async def test_chat_json_strips_markdown(self):
        """Test that markdown is stripped from JSON response."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": {"content": '```json\n{"key": "value"}\n```'}
            }

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()
            result = await client.chat_json(system="System", user="User")

            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_chat_json_invalid_json(self):
        """Test handling of invalid JSON in response."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "message": {"content": "not valid json"}
            }

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()

            with pytest.raises(OllamaResponseError) as exc_info:
                await client.chat_json(system="System", user="User")

            assert "not valid json" in str(exc_info.value).lower()


class TestAsyncOllamaClientHealthCheck:
    """Tests for health_check method."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test successful health check."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()
            result = await client.health_check()

            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check failure."""
        with patch.object(AsyncOllamaClient, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_get_client.return_value = mock_client

            client = AsyncOllamaClient()
            result = await client.health_check()

            assert result is False


class TestOllamaExceptions:
    """Tests for Ollama exception hierarchy."""

    def test_ollama_error_base(self):
        """Test base OllamaError."""
        error = OllamaError("Test error")
        assert str(error) == "Test error"
        assert error.recoverable is False

    def test_ollama_connection_error_recoverable(self):
        """Test OllamaConnectionError is recoverable."""
        error = OllamaConnectionError("Connection failed")
        assert error.recoverable is True

    def test_ollama_timeout_error_recoverable(self):
        """Test OllamaTimeoutError is recoverable."""
        error = OllamaTimeoutError("Timeout")
        assert error.recoverable is True

    def test_ollama_model_error_not_recoverable(self):
        """Test OllamaModelError is not recoverable."""
        error = OllamaModelError("Model not found")
        assert error.recoverable is False

    def test_ollama_response_error_not_recoverable(self):
        """Test OllamaResponseError is not recoverable."""
        error = OllamaResponseError("Invalid response")
        assert error.recoverable is False
