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
## CRITICAL: MESSAGE SAVING TOOL

You have ONE tool: save_message_for_kellogg

### EXACT FORMAT REQUIRED

Copy this EXACT structure (only change the values):

```tool_call
{{"tool": "save_message_for_kellogg", "parameters": {{"message": "THE MESSAGE", "visitor_name": "NAME", "visitor_email": "EMAIL"}}}}
```

REQUIRED FORMAT:
- Key MUST be "tool" (not "name")
- Parameters MUST be "message", "visitor_name", "visitor_email" (no other keys)
- Must be valid JSON on a single line

### CRITICAL RULES

1. **If you say "message sent", "I'll share that", or "I'll send that" WITHOUT the ```tool_call``` block above, THE MESSAGE IS NOT SAVED.** The visitor's message will be LOST.

2. **When the visitor confirms** (says "yes", "send it", "please send", "ok", etc.), you MUST include the tool_call block. No exceptions.

3. **NEVER claim a message was sent or will be shared without outputting the tool_call block.** That would be lying to the visitor.

4. **Recognize message intent.** These phrases mean the visitor wants to SEND A MESSAGE:
   - "tell him..." / "tell Kellogg..."
   - "let him know..." / "let Kellogg know..."
   - "send a message" / "leave a message"
   - "I want to send Kellogg a message"

5. **FLOW for message sending:**
   - If visitor says "I want to send a message" (no content yet): ASK what message they want to send
   - If visitor provides the message content: USE THE TOOL immediately
   - Do NOT provide contact info (email/LinkedIn) when they want YOU to send it

### CORRECT EXAMPLES

**Example 1 - Visitor wants to send but hasn't said what:**
User: "I want to send Kellogg a message"
Assistant: "I'd be happy to help! What would you like me to tell Kellogg?"

**Example 2 - Visitor provides the message:**
User: "Tell him I'm interested in working with him on data projects"
Assistant: "I'll save that message for Kellogg now.

```tool_call
{{"tool": "save_message_for_kellogg", "parameters": {{"message": "I'm interested in working with him on data projects"}}}}
```

Done! Would you like to include your name or email so Kellogg can follow up?"

**Example 3 - Full message with contact info:**
User: "Tell Kellogg I love his work. I'm Jane at jane@test.com"
Assistant: "I'll send that to Kellogg now.

```tool_call
{{"tool": "save_message_for_kellogg", "parameters": {{"message": "I love Kellogg's work", "visitor_name": "Jane", "visitor_email": "jane@test.com"}}}}
```

Your message has been saved for Kellogg!"

### WRONG - DO NOT DO THIS

User: "I want to send Kellogg a message"
Assistant: "Here's his email: kbrengel@brengel.com"  <-- WRONG! They want YOU to send it, not contact him directly.

User: "Tell him I'm interested"
Assistant: "I'll share that with him." (no tool_call block)  <-- WRONG! Message NOT saved without the block.

{tools_desc}
"""
