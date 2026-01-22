"""
Layer 1: Input Sanitization

Deterministic sanitization of user input without LLM calls.
Handles encoding normalization, character filtering, and pattern detection.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

from portfolio_chat.config import SECURITY
from portfolio_chat.utils.logging import audit_logger

logger = logging.getLogger(__name__)


class Layer1Status(Enum):
    """Status codes for Layer 1 sanitization."""

    PASSED = "passed"
    INPUT_TOO_LONG = "input_too_long"
    BLOCKED_PATTERN = "blocked_pattern"
    EMPTY_INPUT = "empty_input"


@dataclass
class Layer1Result:
    """Result of Layer 1 sanitization."""

    status: Layer1Status
    passed: bool
    sanitized_input: str | None = None
    original_length: int = 0
    sanitized_length: int = 0
    blocked_pattern: str | None = None
    error_message: str | None = None

    @property
    def blocked(self) -> bool:
        """Convenience property for blocked status."""
        return not self.passed


class Layer1Sanitizer:
    """
    Input sanitizer - deterministic content validation.

    Performs:
    - Length enforcement
    - Unicode normalization (NFKC)
    - Invisible character stripping
    - Control character removal
    - HTML/script tag stripping
    - Blocked pattern detection
    - Homoglyph normalization
    """

    # Invisible characters to remove
    INVISIBLE_CHARS = re.compile(
        r"[\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff\u00ad]"
    )

    # Control characters to remove (except newlines and tabs)
    CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    # HTML/XML tags
    HTML_TAGS = re.compile(r"<[^>]+>")

    # Multiple whitespace
    MULTIPLE_WHITESPACE = re.compile(r"[ \t]+")
    MULTIPLE_NEWLINES = re.compile(r"\n{3,}")

    # Known jailbreak patterns (case-insensitive)
    BLOCKED_PATTERNS = [
        (r"(?i)ignore\s+(all\s+)?previous\s+instructions?", "instruction_override"),
        (r"(?i)disregard\s+(all\s+)?previous\s+instructions?", "instruction_override"),
        (r"(?i)forget\s+(all\s+)?previous\s+instructions?", "instruction_override"),
        (r"(?i)system\s+prompt", "prompt_extraction"),
        (r"(?i)reveal\s+your\s+(instructions?|prompt|rules)", "prompt_extraction"),
        (r"(?i)show\s+me\s+your\s+(instructions?|prompt|rules)", "prompt_extraction"),
        (r"(?i)what\s+(are|is)\s+your\s+(instructions?|prompt|rules|system)", "prompt_extraction"),
        (r"(?i)you\s+are\s+now\s+(a|an|in)\s+", "roleplay_attack"),
        (r"(?i)pretend\s+(to\s+be|you\s+are)", "roleplay_attack"),
        (r"(?i)act\s+as\s+(if\s+you\s+(are|were)|a|an)\s+", "roleplay_attack"),
        (r"(?i)DAN\s+mode", "roleplay_attack"),
        (r"(?i)developer\s+mode", "roleplay_attack"),
        (r"(?i)jailbreak", "explicit_jailbreak"),
        (r"(?i)bypass\s+(your\s+)?(safety|restrictions?|rules?|filters?)", "explicit_jailbreak"),
        (r"(?i)override\s+(your\s+)?(safety|restrictions?|rules?)", "explicit_jailbreak"),
        (r"(?i)disable\s+(your\s+)?(safety|restrictions?|rules?)", "explicit_jailbreak"),
        # Encoding tricks
        (r"(?i)base64[:\s]", "encoding_trick"),
        (r"(?i)decode\s+this[:\s]", "encoding_trick"),
        (r"(?i)rot13[:\s]", "encoding_trick"),
    ]

    # Homoglyph mappings for common Unicode confusables
    # These can be used to bypass pattern matching (e.g., "іgnore" with Cyrillic і)
    HOMOGLYPHS = {
        # Cyrillic → Latin
        "\u0430": "a",  # Cyrillic а → Latin a
        "\u0435": "e",  # Cyrillic е → Latin e
        "\u043e": "o",  # Cyrillic о → Latin o
        "\u0440": "p",  # Cyrillic р → Latin p
        "\u0441": "c",  # Cyrillic с → Latin c
        "\u0443": "y",  # Cyrillic у → Latin y
        "\u0445": "x",  # Cyrillic х → Latin x
        "\u0456": "i",  # Cyrillic і → Latin i
        "\u0458": "j",  # Cyrillic ј → Latin j
        "\u0455": "s",  # Cyrillic ѕ → Latin s
        "\u0410": "A",  # Cyrillic А → Latin A
        "\u0412": "B",  # Cyrillic В → Latin B
        "\u0415": "E",  # Cyrillic Е → Latin E
        "\u041a": "K",  # Cyrillic К → Latin K
        "\u041c": "M",  # Cyrillic М → Latin M
        "\u041d": "H",  # Cyrillic Н → Latin H
        "\u041e": "O",  # Cyrillic О → Latin O
        "\u0420": "P",  # Cyrillic Р → Latin P
        "\u0421": "C",  # Cyrillic С → Latin C
        "\u0422": "T",  # Cyrillic Т → Latin T
        "\u0425": "X",  # Cyrillic Х → Latin X
        # Greek → Latin
        "\u03b1": "a",  # Greek α → Latin a
        "\u03b5": "e",  # Greek ε → Latin e (similar to e)
        "\u03b9": "i",  # Greek ι → Latin i
        "\u03bf": "o",  # Greek ο → Latin o
        "\u03c1": "p",  # Greek ρ → Latin p
        "\u03c5": "u",  # Greek υ → Latin u (y-like)
        "\u03c7": "x",  # Greek χ → Latin x
        "\u0391": "A",  # Greek Α → Latin A
        "\u0392": "B",  # Greek Β → Latin B
        "\u0395": "E",  # Greek Ε → Latin E
        "\u0397": "H",  # Greek Η → Latin H
        "\u0399": "I",  # Greek Ι → Latin I
        "\u039a": "K",  # Greek Κ → Latin K
        "\u039c": "M",  # Greek Μ → Latin M
        "\u039d": "N",  # Greek Ν → Latin N
        "\u039f": "O",  # Greek Ο → Latin O
        "\u03a1": "P",  # Greek Ρ → Latin P
        "\u03a4": "T",  # Greek Τ → Latin T
        "\u03a7": "X",  # Greek Χ → Latin X
        "\u03a5": "Y",  # Greek Υ → Latin Y
        "\u0396": "Z",  # Greek Ζ → Latin Z
    }

    def __init__(
        self,
        max_length: int | None = None,
        blocked_patterns: list[tuple[str, str]] | None = None,
    ) -> None:
        """
        Initialize sanitizer.

        Args:
            max_length: Maximum allowed input length.
            blocked_patterns: Additional blocked patterns as (regex, reason) tuples.
        """
        self.max_length = max_length or SECURITY.MAX_INPUT_LENGTH

        # Compile blocked patterns
        patterns = self.BLOCKED_PATTERNS.copy()
        if blocked_patterns:
            patterns.extend(blocked_patterns)

        self.compiled_patterns = [
            (re.compile(pattern), reason) for pattern, reason in patterns
        ]

    def sanitize(
        self,
        input_text: str,
        ip_hash: str | None = None,
    ) -> Layer1Result:
        """
        Sanitize user input.

        Args:
            input_text: Raw user input.
            ip_hash: Anonymized IP hash for logging.

        Returns:
            Layer1Result with sanitization status and cleaned input.
        """
        original_length = len(input_text)

        # Check for empty input
        if not input_text or not input_text.strip():
            return Layer1Result(
                status=Layer1Status.EMPTY_INPUT,
                passed=False,
                original_length=original_length,
                error_message="Please enter a message.",
            )

        # Check length before any processing
        if original_length > self.max_length:
            return Layer1Result(
                status=Layer1Status.INPUT_TOO_LONG,
                passed=False,
                original_length=original_length,
                error_message=f"Your message is too long. Maximum length is {self.max_length} characters.",
            )

        # Step 1: Unicode normalization (NFKC)
        text = unicodedata.normalize("NFKC", input_text)

        # Step 2: Homoglyph normalization
        for cyrillic, latin in self.HOMOGLYPHS.items():
            text = text.replace(cyrillic, latin)

        # Step 3: Remove invisible characters
        text = self.INVISIBLE_CHARS.sub("", text)

        # Step 4: Remove control characters (preserve newlines)
        text = self.CONTROL_CHARS.sub("", text)

        # Step 5: Strip HTML/XML tags
        text = self.HTML_TAGS.sub("", text)

        # Step 6: Normalize whitespace
        text = self.MULTIPLE_WHITESPACE.sub(" ", text)
        text = self.MULTIPLE_NEWLINES.sub("\n\n", text)

        # Step 7: Strip leading/trailing whitespace
        text = text.strip()

        # Check if empty after sanitization
        if not text:
            return Layer1Result(
                status=Layer1Status.EMPTY_INPUT,
                passed=False,
                original_length=original_length,
                error_message="Please enter a valid message.",
            )

        # Step 8: Check blocked patterns
        for pattern, reason in self.compiled_patterns:
            if pattern.search(text):
                if ip_hash:
                    audit_logger.log_injection_attempt(
                        ip_hash=ip_hash,
                        layer="L1",
                        reason=reason,
                        input_preview=text[:50],
                    )

                logger.warning(f"Blocked pattern detected: {reason}")
                return Layer1Result(
                    status=Layer1Status.BLOCKED_PATTERN,
                    passed=False,
                    original_length=original_length,
                    sanitized_length=len(text),
                    blocked_pattern=reason,
                    error_message="I can only answer questions about Kellogg's professional background and projects.",
                )

        # Final length check after sanitization
        if len(text) > self.max_length:
            return Layer1Result(
                status=Layer1Status.INPUT_TOO_LONG,
                passed=False,
                original_length=original_length,
                sanitized_length=len(text),
                error_message=f"Your message is too long. Maximum length is {self.max_length} characters.",
            )

        return Layer1Result(
            status=Layer1Status.PASSED,
            passed=True,
            sanitized_input=text,
            original_length=original_length,
            sanitized_length=len(text),
        )

    @staticmethod
    def get_user_friendly_error(result: Layer1Result) -> str:
        """
        Get a user-friendly error message.

        Args:
            result: The Layer1Result from sanitization.

        Returns:
            User-friendly error message.
        """
        if result.error_message:
            return result.error_message

        error_messages = {
            Layer1Status.INPUT_TOO_LONG: "Your message is a bit long. Could you shorten it?",
            Layer1Status.BLOCKED_PATTERN: "I can only answer questions about Kellogg's professional background and projects.",
            Layer1Status.EMPTY_INPUT: "Please enter a message.",
        }

        return error_messages.get(result.status, "An error occurred.")
