"""
Tool definitions for AI tool calling.

Defines the tools available to the AI during conversations.
Uses a simple schema similar to OpenAI/Anthropic function calling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ToolParameter:
    """Definition of a tool parameter."""

    name: str
    type: Literal["string", "integer", "boolean"]
    description: str
    required: bool = True


@dataclass(frozen=True)
class Tool:
    """Definition of a tool the AI can call."""

    name: str
    description: str
    parameters: tuple[ToolParameter, ...] = field(default_factory=tuple)

    def to_prompt_format(self) -> str:
        """Format tool for inclusion in system prompt."""
        params_desc = []
        for param in self.parameters:
            req = "required" if param.required else "optional"
            params_desc.append(f"    - {param.name} ({param.type}, {req}): {param.description}")

        params_str = "\n".join(params_desc) if params_desc else "    (no parameters)"

        return f"""- **{self.name}**: {self.description}
  Parameters:
{params_str}"""


# Define available tools
SAVE_MESSAGE_TOOL = Tool(
    name="save_message_for_kellogg",
    description="Save a message from the visitor for Kellogg Brengel to read later. Use this when a visitor explicitly wants to leave a message, send feedback, or contact Kellogg directly. Always confirm with the visitor what message they want to send before calling this tool.",
    parameters=(
        ToolParameter(
            name="message",
            type="string",
            description="The message content the visitor wants to send to Kellogg",
            required=True,
        ),
        ToolParameter(
            name="visitor_name",
            type="string",
            description="The visitor's name if they provided it",
            required=False,
        ),
        ToolParameter(
            name="visitor_email",
            type="string",
            description="The visitor's email if they provided it for follow-up",
            required=False,
        ),
    ),
)

# All available tools
AVAILABLE_TOOLS: tuple[Tool, ...] = (SAVE_MESSAGE_TOOL,)


def get_tools_prompt_section() -> str:
    """Generate the tools section for the system prompt."""
    if not AVAILABLE_TOOLS:
        return ""

    tools_desc = "\n\n".join(tool.to_prompt_format() for tool in AVAILABLE_TOOLS)

    return f"""
## AVAILABLE TOOLS

You have access to the following tools. To use a tool, output a JSON block in this exact format:

```tool_call
{{"tool": "tool_name", "parameters": {{"param1": "value1", "param2": "value2"}}}}
```

IMPORTANT RULES FOR TOOL USE:
1. Only use tools when the visitor explicitly requests the action (e.g., "I want to leave a message for Kellogg")
2. Before calling save_message_for_kellogg, confirm the exact message content with the visitor
3. After a tool call, wait for the result before responding to the visitor
4. Never fabricate tool results - only report what the tool actually returns

Available tools:

{tools_desc}
"""
