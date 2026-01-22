"""Unit tests for Layer 6: Response Generation."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from portfolio_chat.pipeline.layer4_route import Domain
from portfolio_chat.pipeline.layer6_generate import (
    Layer6Generator,
    Layer6Result,
    Layer6Status,
)
from portfolio_chat.tools.executor import ToolCall, ToolResult


class TestLayer6Generator:
    """Tests for Layer 6 Response Generator."""

    @pytest.mark.asyncio
    async def test_generates_response(self, mock_ollama_client):
        """Test basic response generation."""
        mock_ollama_client.chat_text = AsyncMock(
            return_value="Kellogg has extensive experience with Python and FastAPI."
        )
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=False)

        result = await generator.generate(
            message="What programming languages do you know?",
            domain=Domain.PROFESSIONAL,
            context="Skills: Python, FastAPI, TypeScript",
        )

        assert result.passed
        assert result.status == Layer6Status.SUCCESS
        assert "Python" in result.response
        assert result.model_used is not None

    @pytest.mark.asyncio
    async def test_handles_out_of_scope(self, mock_ollama_client):
        """Test handling of out-of-scope domain."""
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=False)

        result = await generator.generate(
            message="What's the weather today?",
            domain=Domain.OUT_OF_SCOPE,
            context="",
        )

        assert result.passed
        assert result.status == Layer6Status.SUCCESS
        assert "designed to answer questions" in result.response.lower()

    @pytest.mark.asyncio
    async def test_handles_empty_response(self, mock_ollama_client):
        """Test handling of empty response from Ollama."""
        mock_ollama_client.chat_text = AsyncMock(return_value="")
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=False)

        result = await generator.generate(
            message="Test question",
            domain=Domain.PROFESSIONAL,
            context="Some context",
        )

        assert not result.passed
        assert result.status == Layer6Status.EMPTY

    @pytest.mark.asyncio
    async def test_handles_ollama_error(self, mock_ollama_client_error):
        """Test error handling on Ollama failure."""
        generator = Layer6Generator(client=mock_ollama_client_error, enable_tools=False)

        result = await generator.generate(
            message="Test question",
            domain=Domain.PROFESSIONAL,
            context="Some context",
        )

        assert not result.passed
        assert result.status == Layer6Status.ERROR
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_includes_conversation_history(self, mock_ollama_client):
        """Test that conversation history is included."""
        mock_ollama_client.chat_text = AsyncMock(return_value="Follow-up response.")
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=False)
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        await generator.generate(
            message="Tell me more",
            domain=Domain.PROFESSIONAL,
            context="Context here",
            conversation_history=history,
        )

        call_args = mock_ollama_client.chat_text.call_args
        user_message = call_args.kwargs["user"]
        assert "RECENT CONVERSATION" in user_message

    @pytest.mark.asyncio
    async def test_includes_sources(self, mock_ollama_client):
        """Test that sources are included in prompt."""
        mock_ollama_client.chat_text = AsyncMock(return_value="Response with sources.")
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=False)

        await generator.generate(
            message="Test question",
            domain=Domain.PROFESSIONAL,
            context="Context here",
            sources=["resume.md", "skills.md"],
        )

        call_args = mock_ollama_client.chat_text.call_args
        user_message = call_args.kwargs["user"]
        assert "resume.md" in user_message

    @pytest.mark.asyncio
    async def test_spotlighting_markers(self, mock_ollama_client):
        """Test that user message is wrapped in spotlighting markers."""
        mock_ollama_client.chat_text = AsyncMock(return_value="Response")
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=False)

        await generator.generate(
            message="User question here",
            domain=Domain.PROFESSIONAL,
            context="Context",
        )

        call_args = mock_ollama_client.chat_text.call_args
        user_message = call_args.kwargs["user"]
        assert "<<<USER_MESSAGE>>>" in user_message
        assert "<<<END_USER_MESSAGE>>>" in user_message

    @pytest.mark.asyncio
    async def test_generates_fallback_response(self, mock_ollama_client):
        """Test fallback response generation."""
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=False)

        fallback = await generator.generate_fallback_response(Domain.PROFESSIONAL)
        assert "experience" in fallback.lower() or "help" in fallback.lower()

        fallback = await generator.generate_fallback_response(Domain.PROJECTS)
        assert "projects" in fallback.lower()

        fallback = await generator.generate_fallback_response(Domain.META)
        assert "talking rock" in fallback.lower()


class TestLayer6GeneratorToolCalling:
    """Tests for Layer 6 tool calling functionality."""

    @pytest.mark.asyncio
    async def test_detects_tool_call_in_response(self, mock_ollama_client, contact_storage):
        """Test detection of tool calls in response."""
        response_with_tool = """I'll save that message for Kellogg.

```tool_call
{"tool": "save_message_for_kellogg", "parameters": {"message": "Hello from visitor"}}
```

The message has been saved."""

        mock_ollama_client.chat_text = AsyncMock(return_value=response_with_tool)

        from portfolio_chat.tools.executor import ToolExecutor

        generator = Layer6Generator(client=mock_ollama_client, enable_tools=True)
        executor = ToolExecutor(contact_storage=contact_storage)
        generator.set_tool_executor(executor)

        result = await generator.generate(
            message="Please save a message for Kellogg",
            domain=Domain.META,
            context="Contact information available",
        )

        assert result.status == Layer6Status.TOOL_CALL
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool == "save_message_for_kellogg"

    @pytest.mark.asyncio
    async def test_removes_tool_blocks_from_response(self, mock_ollama_client, contact_storage):
        """Test that tool call blocks are removed from visible response."""
        response_with_tool = """I'll save that message.

```tool_call
{"tool": "save_message_for_kellogg", "parameters": {"message": "Test"}}
```

Done!"""

        mock_ollama_client.chat_text = AsyncMock(return_value=response_with_tool)

        from portfolio_chat.tools.executor import ToolExecutor

        generator = Layer6Generator(client=mock_ollama_client, enable_tools=True)
        executor = ToolExecutor(contact_storage=contact_storage)
        generator.set_tool_executor(executor)

        result = await generator.generate(
            message="Save message",
            domain=Domain.META,
            context="Context",
        )

        assert "tool_call" not in result.response
        assert "I'll save that message" in result.response

    @pytest.mark.asyncio
    async def test_handles_tool_results(self, mock_ollama_client):
        """Test generation with tool results."""
        mock_ollama_client.chat_text = AsyncMock(
            return_value="Your message has been saved successfully!"
        )
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=True)

        tool_results = [
            ToolResult(
                tool_name="save_message_for_kellogg",
                success=True,
                result="Message saved with ID abc123",
            )
        ]

        await generator.generate(
            message="Save this message",
            domain=Domain.META,
            context="Context",
            tool_results=tool_results,
        )

        call_args = mock_ollama_client.chat_text.call_args
        user_message = call_args.kwargs["user"]
        assert "TOOL EXECUTION RESULTS" in user_message
        assert "save_message_for_kellogg" in user_message
        assert "SUCCESS" in user_message

    @pytest.mark.asyncio
    async def test_no_tools_without_executor(self, mock_ollama_client):
        """Test that tools are not processed without executor."""
        response_with_tool = """```tool_call
{"tool": "save_message_for_kellogg", "parameters": {"message": "Test"}}
```"""

        mock_ollama_client.chat_text = AsyncMock(return_value=response_with_tool)
        generator = Layer6Generator(client=mock_ollama_client, enable_tools=True)
        # No executor set

        result = await generator.generate(
            message="Save message",
            domain=Domain.META,
            context="Context",
        )

        # Without executor, should not detect tool calls
        assert result.status == Layer6Status.SUCCESS


class TestLayer6Result:
    """Tests for Layer6Result dataclass."""

    def test_default_values(self):
        """Test default values in result."""
        result = Layer6Result(
            status=Layer6Status.SUCCESS,
            passed=True,
            response="Test response",
            model_used="test-model",
        )

        assert result.error_message is None
        assert result.tool_calls == []
        assert result.tool_results == []

    def test_with_tool_calls(self):
        """Test result with tool calls."""
        tool_call = ToolCall(
            tool="test_tool",
            parameters={"key": "value"},
            raw_match="",
        )
        result = Layer6Result(
            status=Layer6Status.TOOL_CALL,
            passed=True,
            response="Response",
            model_used="test-model",
            tool_calls=[tool_call],
        )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool == "test_tool"
