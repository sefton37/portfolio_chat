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
## TOOLS - READ CAREFULLY

When a visitor wants to contact Kellogg or leave a message, you MUST output this exact block:

```tool_call
{{"tool": "save_message_for_kellogg", "parameters": {{"message": "MESSAGE_HERE", "visitor_name": "NAME_HERE", "visitor_email": "EMAIL_HERE"}}}}
```

This is the ONLY way to actually save messages. If you don't output this block, the message is NOT saved.

WHEN TO USE IT:
- Visitor says "send", "yes", "please send", "send it", "submit", "forward", or similar confirmation
- Visitor asks to leave a message, contact Kellogg, or provide feedback
- DO NOT keep asking for confirmation - if they said yes, USE THE TOOL

EXAMPLE:
User: "Tell Kellogg I want to hire him. I'm John at john@test.com. Send it."
You respond with:
I'll save that message for Kellogg now.

```tool_call
{{"tool": "save_message_for_kellogg", "parameters": {{"message": "I want to hire Kellogg", "visitor_name": "John", "visitor_email": "john@test.com"}}}}
```

{tools_desc}
"""
