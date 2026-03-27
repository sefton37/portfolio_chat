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

    return """
## MESSAGE TOOL

To save a message for Kellogg, output a tool_call block:

```tool_call
{"action": "save_message_for_kellogg", "message": "The actual message text", "visitor_name": "Their Name", "visitor_email": "their@email.com"}
```

CRITICAL: You MUST output the ```tool_call``` code block exactly as shown above.
A text response like "I'll save that message" or "I've passed along your message" is NOT sufficient —
the tool_call block is what actually saves the message. Without it, the message is lost.

STRICT RULES for this tool:
- ONLY use when the visitor has EXPLICITLY asked to leave/send a message for Kellogg
- Do NOT use for greetings, questions about Kellogg, or casual conversation
- Do NOT use if the visitor just says "tell him" in the context of asking you a question
- NEVER use placeholder text — only save the visitor's actual words
- ALWAYS ask for the visitor's name and email BEFORE calling this tool
- If they decline to give contact info, save the message anyway but note that

When a visitor wants to send a message:
1. Ask what they'd like to say (if not already clear)
2. Ask for their name and email so Kellogg can reply
3. Only THEN use the tool_call block with their actual message
4. After the tool runs, confirm the message was saved
"""
