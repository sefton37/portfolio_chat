"""
Layer 7: Response Revision

Self-critique and refinement pass for generated responses.
Skips revision for short responses (<200 chars) to reduce latency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from portfolio_chat.config import MODELS, PATHS
from portfolio_chat.models.ollama_client import (
    AsyncOllamaClient,
    OllamaError,
)

logger = logging.getLogger(__name__)


class Layer7Status:
    """Status codes for Layer 7 revision."""

    REVISED = "revised"
    SKIPPED = "skipped"  # Response too short
    PASSED = "passed"  # No changes needed
    ERROR = "error"


@dataclass
class Layer7Result:
    """Result of Layer 7 revision."""

    status: str
    passed: bool
    response: str
    was_revised: bool = False
    revision_notes: str | None = None


class Layer7Reviser:
    """
    Response reviser - self-critique pass.

    Checks for:
    - Accuracy to provided context
    - Tone consistency
    - Completeness
    - Markdown formatting

    Skips revision for responses <200 chars to reduce latency.
    """

    # Minimum length to trigger revision
    MIN_LENGTH_FOR_REVISION = 200

    DEFAULT_SYSTEM_PROMPT = """You are a quality checker for a portfolio chat representing Kellogg Brengel.

Review the response below and check for these issues:

1. ACCURACY: Does the response only contain information from the provided context? Flag any claims not supported by context.
2. TONE: Is the tone professional yet friendly? Should sound like a real person, not a corporate bot.
3. COMPLETENESS: Does the response address the user's question? Is anything important missing?
4. FORMATTING: Is markdown used appropriately? Are there formatting issues?
5. LENGTH: Is the response appropriately sized? Not too short (unhelpful) or too long (rambling)?

If the response is good, respond with just: {"needs_revision": false}

If the response needs improvement, respond with:
{
  "needs_revision": true,
  "issues": ["list of specific issues"],
  "revised_response": "the improved response"
}"""

    def __init__(
        self,
        client: AsyncOllamaClient | None = None,
        model: str | None = None,
        min_length: int | None = None,
    ) -> None:
        """
        Initialize reviser.

        Args:
            client: Ollama client instance.
            model: Model to use for revision (same as generator).
            min_length: Minimum response length to trigger revision.
        """
        self.client = client or AsyncOllamaClient()
        self.model = model or MODELS.GENERATOR_MODEL
        self.min_length = min_length or self.MIN_LENGTH_FOR_REVISION
        self._loaded_prompt: str | None = None

    def _get_system_prompt(self) -> str:
        """Get the system prompt for revision."""
        if self._loaded_prompt:
            return self._loaded_prompt

        # Try to load from prompts directory
        prompt_file = PATHS.PROMPTS_DIR / "revision_prompt.md"
        if prompt_file.exists():
            self._loaded_prompt = prompt_file.read_text().strip()
            return self._loaded_prompt

        return self.DEFAULT_SYSTEM_PROMPT

    def _format_revision_request(
        self,
        response: str,
        context: str,
        original_question: str,
    ) -> str:
        """Format the revision request."""
        return f"""ORIGINAL QUESTION:
{original_question}

CONTEXT PROVIDED:
```
{context[:2000]}
```

RESPONSE TO REVIEW:
```
{response}
```

Review the response and check for issues. Output JSON only."""

    async def revise(
        self,
        response: str,
        context: str,
        original_question: str,
    ) -> Layer7Result:
        """
        Review and potentially revise a response.

        Args:
            response: The generated response to review.
            context: The context that was provided.
            original_question: The original user question.

        Returns:
            Layer7Result with possibly revised response.
        """
        # Skip revision for short responses
        if len(response) < self.min_length:
            logger.debug(f"Skipping revision for short response ({len(response)} chars)")
            return Layer7Result(
                status=Layer7Status.SKIPPED,
                passed=True,
                response=response,
                was_revised=False,
                revision_notes="Response too short for revision",
            )

        try:
            revision_request = self._format_revision_request(
                response, context, original_question
            )

            result = await self.client.chat_json(
                system=self._get_system_prompt(),
                user=revision_request,
                model=self.model,
                timeout=MODELS.GENERATOR_TIMEOUT,
            )

            needs_revision = result.get("needs_revision", False)

            if not needs_revision:
                return Layer7Result(
                    status=Layer7Status.PASSED,
                    passed=True,
                    response=response,
                    was_revised=False,
                )

            # Get revised response
            revised = result.get("revised_response", "")
            issues = result.get("issues", [])

            if revised and len(revised) > 50:  # Sanity check
                logger.info(f"Response revised. Issues: {issues}")
                return Layer7Result(
                    status=Layer7Status.REVISED,
                    passed=True,
                    response=revised,
                    was_revised=True,
                    revision_notes=", ".join(issues) if issues else None,
                )

            # Revised response invalid, use original
            return Layer7Result(
                status=Layer7Status.PASSED,
                passed=True,
                response=response,
                was_revised=False,
                revision_notes="Revision produced invalid response",
            )

        except OllamaError as e:
            logger.warning(f"Error in revision, using original: {e}")
            # On error, pass through original response
            return Layer7Result(
                status=Layer7Status.ERROR,
                passed=True,  # Don't block on revision errors
                response=response,
                was_revised=False,
                revision_notes=str(e),
            )

        except Exception as e:
            logger.error(f"Unexpected error in revision: {e}")
            return Layer7Result(
                status=Layer7Status.ERROR,
                passed=True,
                response=response,
                was_revised=False,
                revision_notes=str(e),
            )
