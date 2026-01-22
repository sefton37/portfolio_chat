"""
Layer 8 Fast: Pattern-based Safety Check

Fast output validation using regex patterns instead of LLM calls.
Checks for prompt leakage, inappropriate content, and obvious issues.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SafetyIssue(Enum):
    """Types of safety issues that can be detected."""

    NONE = "none"
    PROMPT_LEAKAGE = "prompt_leakage"
    INAPPROPRIATE = "inappropriate"
    PRIVATE_INFO = "private_info"
    NEGATIVE_SELF = "negative_self"


@dataclass
class FastSafetyResult:
    """Result of fast safety check."""

    passed: bool
    issues: list[SafetyIssue]
    issue_details: str | None = None


# Patterns that indicate prompt leakage
PROMPT_LEAKAGE_PATTERNS = [
    r"system prompt",
    r"my instructions are",
    r"i was told to",
    r"i am programmed to",
    r"my programming says",
    r"my rules are",
    r"<<<.*>>>",  # Spotlighting markers
    r"CONTEXT ABOUT KEL",
    r"CURRENT QUESTION:",
    r"Layer \d+ ",  # Space after to avoid matching "Layer 1" in other contexts
    r"inference pipeline",  # More specific - not "data pipeline"
    r"jailbreak attempt",
    r"injection attempt",
]

# Patterns that indicate inappropriate content
INAPPROPRIATE_PATTERNS = [
    r"\b(fuck|shit|damn|ass|bitch)\b",
    r"(kill|murder|attack|harm)\s+(yourself|himself|people)",
    r"(illegal|criminal)\s+activit",
]

# Patterns that leak private info
PRIVATE_INFO_PATTERNS = [
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # Phone numbers
    r"(?<!\w)(?:\d{1,3}\.){3}\d{1,3}(?!\w)",  # IP addresses (but not versions)
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Emails (except known public ones)
]

# Known safe emails (public contact info)
SAFE_EMAILS = ["kbrengel@brengel.com"]

# Patterns indicating negative self-talk about Kellogg
NEGATIVE_SELF_PATTERNS = [
    r"kellogg (is|was) (bad|terrible|awful|incompetent)",
    r"kellogg (doesn't|does not) know",
    r"kellogg (can't|cannot) (do|handle)",
    r"kellogg (failed|sucks)",
    r"wouldn't recommend.*kellogg",
    r"don't hire.*kellogg",
]


class Layer8FastChecker:
    """
    Fast pattern-based safety checker.

    Uses regex instead of LLM for ~100x speedup.
    """

    def __init__(self) -> None:
        # Compile patterns for efficiency
        self._leakage_re = [re.compile(p, re.IGNORECASE) for p in PROMPT_LEAKAGE_PATTERNS]
        self._inappropriate_re = [re.compile(p, re.IGNORECASE) for p in INAPPROPRIATE_PATTERNS]
        self._private_re = [re.compile(p) for p in PRIVATE_INFO_PATTERNS]
        self._negative_re = [re.compile(p, re.IGNORECASE) for p in NEGATIVE_SELF_PATTERNS]

    def check(self, response: str, context: str | None = None) -> FastSafetyResult:
        """
        Check response for safety issues using pattern matching.

        Args:
            response: The generated response to check.
            context: Optional context (unused in fast check).

        Returns:
            FastSafetyResult with pass/fail and any issues found.
        """
        issues: list[SafetyIssue] = []
        details: list[str] = []

        # Check for prompt leakage
        for pattern in self._leakage_re:
            if pattern.search(response):
                issues.append(SafetyIssue.PROMPT_LEAKAGE)
                details.append(f"Prompt leakage pattern: {pattern.pattern}")
                break

        # Check for inappropriate content
        for pattern in self._inappropriate_re:
            if pattern.search(response):
                issues.append(SafetyIssue.INAPPROPRIATE)
                details.append(f"Inappropriate pattern: {pattern.pattern}")
                break

        # Check for private info (excluding known safe emails)
        for pattern in self._private_re:
            matches = pattern.findall(response)
            for match in matches:
                if match not in SAFE_EMAILS:
                    issues.append(SafetyIssue.PRIVATE_INFO)
                    details.append(f"Private info pattern: {pattern.pattern}")
                    break

        # Check for negative self-talk
        for pattern in self._negative_re:
            if pattern.search(response):
                issues.append(SafetyIssue.NEGATIVE_SELF)
                details.append(f"Negative pattern: {pattern.pattern}")
                break

        passed = len(issues) == 0
        issue_details = "; ".join(details) if details else None

        if not passed:
            logger.warning(f"Fast safety check failed: {issue_details}")

        return FastSafetyResult(
            passed=passed,
            issues=issues,
            issue_details=issue_details,
        )

    @staticmethod
    def get_safe_fallback_response() -> str:
        """Get a safe fallback response when check fails."""
        return (
            "I'd be happy to help you learn about Kellogg's professional background. "
            "What would you like to know about his work, projects, or experience?"
        )
