"""
Tool executor for handling AI tool calls.

Parses tool calls from AI responses and executes them.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from portfolio_chat.contact.storage import ContactStorage
from portfolio_chat.tools.definitions import AVAILABLE_TOOLS

logger = logging.getLogger(__name__)

# Pattern to match tool calls in AI responses
# Matches ```tool_call\n{...}\n``` blocks
TOOL_CALL_PATTERN = re.compile(
    r"```tool_call\s*\n?\s*(\{[^`]+\})\s*\n?```",
    re.MULTILINE | re.DOTALL,
)


@dataclass
class ToolCall:
    """A parsed tool call from AI response."""

    tool: str
    parameters: dict[str, Any]
    raw_match: str  # The full matched string for replacement


@dataclass
class ToolResult:
    """Result of executing a tool."""

    success: bool
    tool_name: str
    result: str  # Human-readable result message
    data: dict[str, Any] | None = None  # Structured data if applicable


class ToolExecutor:
    """
    Executes tools called by the AI.

    Handles parsing tool calls from responses and executing them.
    """

    def __init__(
        self,
        contact_storage: ContactStorage | None = None,
        conversation_id: str | None = None,
        client_ip_hash: str | None = None,
    ) -> None:
        """
        Initialize tool executor.

        Args:
            contact_storage: Storage for contact messages.
            conversation_id: Current conversation ID for context.
            client_ip_hash: Hashed client IP for spam detection.
        """
        self._contact_storage = contact_storage
        self._conversation_id = conversation_id
        self._client_ip_hash = client_ip_hash

        # Map tool names to handlers
        self._handlers = {
            "save_message_for_kellogg": self._handle_save_message,
        }

    def parse_tool_calls(self, response: str) -> list[ToolCall]:
        """
        Parse tool calls from an AI response.

        Args:
            response: The AI's response text.

        Returns:
            List of parsed ToolCall objects.
        """
        tool_calls = []

        for match in TOOL_CALL_PATTERN.finditer(response):
            json_str = match.group(1)
            raw_match = match.group(0)

            try:
                data = json.loads(json_str)

                # Accept multiple key formats - LLMs have different conventions
                # Priority: "tool" > "name" > "action"
                tool_name = data.get("tool") or data.get("name") or data.get("action")
                if not tool_name:
                    logger.warning(f"Tool call missing tool name field: {json_str}")
                    continue

                # Accept multiple parameter formats:
                # 1. {"tool": "x", "parameters": {"message": "..."}} - standard
                # 2. {"action": "x", "message": "..."} - mistral style (flat)
                parameters = data.get("parameters") or {}

                # If parameters empty, extract flat keys that look like params
                if not parameters:
                    param_keys = {"message", "visitor_name", "visitor_email"}
                    for key in param_keys:
                        if key in data:
                            parameters[key] = data[key]

                # Validate tool exists
                valid_tools = {t.name for t in AVAILABLE_TOOLS}
                if tool_name not in valid_tools:
                    logger.warning(f"Unknown tool called: {tool_name}")
                    continue

                tool_calls.append(
                    ToolCall(
                        tool=tool_name,
                        parameters=parameters,
                        raw_match=raw_match,
                    )
                )

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse tool call JSON: {e}")
                continue

        return tool_calls

    def has_tool_calls(self, response: str) -> bool:
        """Check if response contains any tool calls."""
        return bool(TOOL_CALL_PATTERN.search(response))

    def remove_tool_calls(self, response: str) -> str:
        """Remove tool call blocks from response, leaving surrounding text."""
        return TOOL_CALL_PATTERN.sub("", response).strip()

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute a single tool call.

        Args:
            tool_call: The parsed tool call to execute.

        Returns:
            ToolResult with success/failure and result message.
        """
        handler = self._handlers.get(tool_call.tool)

        if handler is None:
            return ToolResult(
                success=False,
                tool_name=tool_call.tool,
                result=f"Unknown tool: {tool_call.tool}",
            )

        try:
            return await handler(tool_call.parameters)
        except Exception as e:
            logger.error(f"Error executing tool {tool_call.tool}: {e}")
            return ToolResult(
                success=False,
                tool_name=tool_call.tool,
                result=f"Error executing tool: {str(e)}",
            )

    async def execute_all(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute all tool calls and return results."""
        results = []
        for tool_call in tool_calls:
            result = await self.execute(tool_call)
            results.append(result)
        return results

    # Placeholder/template patterns that indicate the LLM hallucinated a tool call
    # rather than using the visitor's actual words
    _PLACEHOLDER_PATTERNS = {
        "visitor's message here",
        "your message here",
        "visitor_message",
        "user_message",
        "message here",
        "message text",
        "question here",
        "question about",
        "[your message",
        "[your question",
        "[your email",
        "[visitor",
        "[your name",
        "[insert",
        "<<<user",
        "<<<visitor",
        "{message}",
        "your visitor",
        "your name",
        "your email",
    }

    # Patterns indicating the LLM fabricated a message rather than using visitor words
    _FABRICATION_PATTERNS = re.compile(
        r"(?i)"
        r"(?:^I have a question about Kellogg)"
        r"|(?:^I(?:'m| am) interested in (?:learning|discussing|knowing) more about)"
        r"|(?:^(?:The )?visitor (?:would like|wants|is asking|asked))"
        r"|(?:^(?:Hi|Hello|Hey) Kellogg,? I(?:'m| am) \w+ (?:from|at|and))"  # LLM roleplaying as visitor
        r"|(?:@example\.com)"
        r"|(?:your@email)"
        r"|(?:^What (?:does|is|are|did|can|programming|technologies).*(?:Kellogg|he)\b)"  # rephrased questions about Kellogg
    )

    # Placeholder email patterns
    _PLACEHOLDER_EMAIL_PATTERNS = re.compile(
        r"(?i)"
        r"(?:@example\.com)"
        r"|(?:^your@)"
        r"|(?:^your\.email@)"
        r"|(?:^visitor@)"
        r"|(?:^\[.*(?:email|your).*\]$)"
        r"|(?:^your email$)"
    )

    # Placeholder name patterns
    _PLACEHOLDER_NAME_PATTERNS = re.compile(
        r"(?i)"
        r"(?:^Your Name$)"
        r"|(?:^\[.*name.*\]$)"
        r"|(?:^Visitor$)"
        r"|(?:^User$)"
        r"|(?:^Name$)"
    )

    async def _handle_save_message(self, params: dict[str, Any]) -> ToolResult:
        """Handle the save_message_for_kellogg tool."""
        message = params.get("message")

        if not message:
            return ToolResult(
                success=False,
                tool_name="save_message_for_kellogg",
                result="No message provided to save.",
            )

        # Reject placeholder/template text that the LLM copied from its prompt
        message_lower = message.strip().lower()
        for placeholder in self._PLACEHOLDER_PATTERNS:
            if placeholder in message_lower:
                logger.warning(f"Rejected placeholder message: {message[:80]}")
                return ToolResult(
                    success=False,
                    tool_name="save_message_for_kellogg",
                    result="Please ask the visitor what specific message they'd like to send to Kellogg.",
                )

        # Reject LLM-fabricated messages (not visitor's actual words)
        if self._FABRICATION_PATTERNS.search(message.strip()):
            logger.warning(f"Rejected fabricated message: {message[:80]}")
            return ToolResult(
                success=False,
                tool_name="save_message_for_kellogg",
                result="Please ask the visitor what specific message they'd like to send to Kellogg.",
            )

        if not self._contact_storage:
            # Create storage if not provided
            self._contact_storage = ContactStorage()

        visitor_name = params.get("visitor_name")
        visitor_email = params.get("visitor_email")

        # Strip placeholder names and emails the LLM fabricated
        if visitor_email and self._PLACEHOLDER_EMAIL_PATTERNS.search(visitor_email.strip()):
            logger.info(f"Stripped placeholder email: {visitor_email}")
            visitor_email = None
        if visitor_name and self._PLACEHOLDER_NAME_PATTERNS.search(visitor_name.strip()):
            logger.info(f"Stripped placeholder name: {visitor_name}")
            visitor_name = None

        try:
            stored = await self._contact_storage.store(
                message=message,
                sender_name=visitor_name,
                sender_email=visitor_email,
                context=f"Message submitted via Talking Rock chat",
                ip_hash=self._client_ip_hash,
                conversation_id=self._conversation_id,
            )

            logger.info(f"Tool saved message {stored.id} for Kellogg")

            return ToolResult(
                success=True,
                tool_name="save_message_for_kellogg",
                result=f"Message saved successfully. Kellogg will be able to read it.",
                data={"message_id": stored.id},
            )

        except Exception as e:
            logger.error(f"Failed to save message: {e}")
            return ToolResult(
                success=False,
                tool_name="save_message_for_kellogg",
                result="Sorry, there was an error saving the message. Please try again.",
            )


def format_tool_results_for_ai(results: list[ToolResult]) -> str:
    """Format tool results for inclusion in follow-up AI prompt."""
    if not results:
        return ""

    parts = ["TOOL RESULTS:"]
    for result in results:
        status = "SUCCESS" if result.success else "FAILED"
        parts.append(f"- {result.tool_name} [{status}]: {result.result}")

    parts.append("")
    parts.append("Now respond to the visitor based on these tool results. Be natural and conversational.")

    return "\n".join(parts)
