"""Unit tests for the tool calling functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from portfolio_chat.tools.definitions import (
    AVAILABLE_TOOLS,
    Tool,
    ToolParameter,
    get_tools_prompt_section,
)
from portfolio_chat.tools.executor import (
    ToolCall,
    ToolExecutor,
    ToolResult,
    TOOL_CALL_PATTERN,
)


class TestToolDefinitions:
    """Tests for tool definitions."""

    def test_available_tools_not_empty(self):
        """Test that we have at least one tool defined."""
        assert len(AVAILABLE_TOOLS) > 0

    def test_save_message_tool_exists(self):
        """Test that the save_message_for_kellogg tool exists."""
        tool_names = [t.name for t in AVAILABLE_TOOLS]
        assert "save_message_for_kellogg" in tool_names

    def test_save_message_tool_has_required_params(self):
        """Test that save_message tool has message as required param."""
        save_tool = next(t for t in AVAILABLE_TOOLS if t.name == "save_message_for_kellogg")

        param_names = [p.name for p in save_tool.parameters]
        assert "message" in param_names

        message_param = next(p for p in save_tool.parameters if p.name == "message")
        assert message_param.required is True

    def test_tool_to_prompt_format(self):
        """Test tool formatting for system prompt."""
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters=(
                ToolParameter(name="param1", type="string", description="A param", required=True),
            ),
        )

        formatted = tool.to_prompt_format()
        assert "test_tool" in formatted
        assert "A test tool" in formatted
        assert "param1" in formatted

    def test_get_tools_prompt_section(self):
        """Test that tools prompt section includes instructions."""
        section = get_tools_prompt_section()

        assert "AVAILABLE TOOLS" in section
        assert "tool_call" in section
        assert "save_message_for_kellogg" in section


class TestToolCallParsing:
    """Tests for parsing tool calls from AI responses."""

    def test_parse_valid_tool_call(self):
        """Test parsing a valid tool call from response."""
        executor = ToolExecutor()

        response = '''I'll save that message for Kellogg.

```tool_call
{"tool": "save_message_for_kellogg", "parameters": {"message": "Hello, this is a test"}}
```

The message has been saved.'''

        tool_calls = executor.parse_tool_calls(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].tool == "save_message_for_kellogg"
        assert tool_calls[0].parameters["message"] == "Hello, this is a test"

    def test_parse_tool_call_with_all_params(self):
        """Test parsing tool call with all parameters."""
        executor = ToolExecutor()

        response = '''```tool_call
{"tool": "save_message_for_kellogg", "parameters": {"message": "Test message", "visitor_name": "John", "visitor_email": "john@example.com"}}
```'''

        tool_calls = executor.parse_tool_calls(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].parameters["message"] == "Test message"
        assert tool_calls[0].parameters["visitor_name"] == "John"
        assert tool_calls[0].parameters["visitor_email"] == "john@example.com"

    def test_parse_no_tool_calls(self):
        """Test that normal response returns no tool calls."""
        executor = ToolExecutor()

        response = "Kellogg is a software engineer with experience in Python."

        tool_calls = executor.parse_tool_calls(response)

        assert len(tool_calls) == 0

    def test_parse_invalid_json_ignored(self):
        """Test that invalid JSON in tool call block is ignored."""
        executor = ToolExecutor()

        response = '''```tool_call
{invalid json here}
```'''

        tool_calls = executor.parse_tool_calls(response)

        assert len(tool_calls) == 0

    def test_parse_unknown_tool_ignored(self):
        """Test that unknown tools are ignored."""
        executor = ToolExecutor()

        response = '''```tool_call
{"tool": "unknown_tool", "parameters": {}}
```'''

        tool_calls = executor.parse_tool_calls(response)

        assert len(tool_calls) == 0

    def test_has_tool_calls(self):
        """Test has_tool_calls detection."""
        executor = ToolExecutor()

        with_tools = '''```tool_call
{"tool": "save_message_for_kellogg", "parameters": {"message": "test"}}
```'''
        without_tools = "Just a normal response."

        assert executor.has_tool_calls(with_tools) is True
        assert executor.has_tool_calls(without_tools) is False

    def test_remove_tool_calls(self):
        """Test removing tool call blocks from response."""
        executor = ToolExecutor()

        response = '''I'll save that for you.

```tool_call
{"tool": "save_message_for_kellogg", "parameters": {"message": "test"}}
```

Done!'''

        cleaned = executor.remove_tool_calls(response)

        assert "tool_call" not in cleaned
        assert "I'll save that for you." in cleaned
        assert "Done!" in cleaned


class TestToolExecution:
    """Tests for tool execution."""

    @pytest.mark.asyncio
    async def test_execute_save_message_success(self):
        """Test successful message saving."""
        # Mock contact storage
        mock_storage = MagicMock()
        mock_storage.store = AsyncMock(return_value=MagicMock(id="test123"))

        executor = ToolExecutor(
            contact_storage=mock_storage,
            conversation_id="conv-123",
            client_ip_hash="abc123",
        )

        tool_call = ToolCall(
            tool="save_message_for_kellogg",
            parameters={"message": "Test message for Kellogg"},
            raw_match="",
        )

        result = await executor.execute(tool_call)

        assert result.success is True
        assert "saved" in result.result.lower()
        mock_storage.store.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_save_message_missing_message(self):
        """Test save message fails without message param."""
        executor = ToolExecutor()

        tool_call = ToolCall(
            tool="save_message_for_kellogg",
            parameters={},  # No message
            raw_match="",
        )

        result = await executor.execute(tool_call)

        assert result.success is False
        assert "no message" in result.result.lower()

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        """Test executing unknown tool returns error."""
        executor = ToolExecutor()

        tool_call = ToolCall(
            tool="nonexistent_tool",
            parameters={},
            raw_match="",
        )

        result = await executor.execute(tool_call)

        assert result.success is False
        assert "unknown" in result.result.lower()

    @pytest.mark.asyncio
    async def test_execute_all(self):
        """Test executing multiple tool calls."""
        mock_storage = MagicMock()
        mock_storage.store = AsyncMock(return_value=MagicMock(id="test123"))

        executor = ToolExecutor(contact_storage=mock_storage)

        tool_calls = [
            ToolCall(
                tool="save_message_for_kellogg",
                parameters={"message": "First message"},
                raw_match="",
            ),
            ToolCall(
                tool="save_message_for_kellogg",
                parameters={"message": "Second message"},
                raw_match="",
            ),
        ]

        results = await executor.execute_all(tool_calls)

        assert len(results) == 2
        assert all(r.success for r in results)


class TestToolCallPattern:
    """Tests for the tool call regex pattern."""

    def test_pattern_matches_basic(self):
        """Test pattern matches basic tool call."""
        text = '```tool_call\n{"tool": "test"}\n```'
        match = TOOL_CALL_PATTERN.search(text)
        assert match is not None

    def test_pattern_matches_with_whitespace(self):
        """Test pattern handles various whitespace."""
        text = '```tool_call\n  {"tool": "test"}  \n```'
        match = TOOL_CALL_PATTERN.search(text)
        assert match is not None

    def test_pattern_captures_json(self):
        """Test pattern captures the JSON content."""
        text = '```tool_call\n{"tool": "test", "params": {}}\n```'
        match = TOOL_CALL_PATTERN.search(text)
        assert match is not None
        assert '"tool": "test"' in match.group(1)
