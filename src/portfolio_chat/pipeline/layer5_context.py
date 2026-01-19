"""
Layer 5: Context Retrieval

Retrieves relevant context based on domain routing.
Uses registry pattern with static file lookup (no RAG).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from portfolio_chat.config import PATHS, SECURITY
from portfolio_chat.pipeline.layer3_intent import Intent
from portfolio_chat.pipeline.layer4_route import Domain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextSource:
    """Definition of a context source."""

    name: str  # Internal identifier
    display_name: str  # UI label
    file_pattern: str  # Relative path or glob pattern
    domain: Domain  # Which domain this belongs to
    required: bool = False  # Always include for this domain?
    priority: int = 0  # Higher priority loaded first


# Registry of all context sources
CONTEXT_SOURCES: tuple[ContextSource, ...] = (
    # Professional domain
    ContextSource(
        name="resume",
        display_name="Resume",
        file_pattern="professional/resume.md",
        domain=Domain.PROFESSIONAL,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="skills",
        display_name="Skills",
        file_pattern="professional/skills.md",
        domain=Domain.PROFESSIONAL,
        required=False,
        priority=5,
    ),
    ContextSource(
        name="achievements",
        display_name="Achievements",
        file_pattern="professional/achievements.md",
        domain=Domain.PROFESSIONAL,
        required=False,
        priority=3,
    ),
    # Projects domain
    ContextSource(
        name="projects_overview",
        display_name="Projects Overview",
        file_pattern="projects/overview.md",
        domain=Domain.PROJECTS,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="portfolio_site",
        display_name="Portfolio Site",
        file_pattern="projects/portfolio_site.md",
        domain=Domain.PROJECTS,
        required=False,
        priority=5,
    ),
    ContextSource(
        name="talking_rock",
        display_name="Talking Rock",
        file_pattern="projects/talking_rock.md",
        domain=Domain.PROJECTS,
        required=False,
        priority=5,
    ),
    # Hobbies domain
    ContextSource(
        name="first_robotics",
        display_name="FIRST Robotics",
        file_pattern="hobbies/first_robotics.md",
        domain=Domain.HOBBIES,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="volunteering",
        display_name="Volunteering",
        file_pattern="hobbies/volunteering.md",
        domain=Domain.HOBBIES,
        required=False,
        priority=5,
    ),
    # Philosophy domain
    ContextSource(
        name="problem_solving",
        display_name="Problem Solving",
        file_pattern="philosophy/problem_solving.md",
        domain=Domain.PHILOSOPHY,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="values",
        display_name="Values",
        file_pattern="philosophy/values.md",
        domain=Domain.PHILOSOPHY,
        required=False,
        priority=5,
    ),
    # LinkedIn domain
    ContextSource(
        name="contact",
        display_name="Contact Info",
        file_pattern="meta/contact.md",
        domain=Domain.LINKEDIN,
        required=True,
        priority=10,
    ),
    # Meta domain
    ContextSource(
        name="about_chat",
        display_name="About Chat",
        file_pattern="meta/about_chat.md",
        domain=Domain.META,
        required=True,
        priority=10,
    ),
)

# Set of valid source names for validation
VALID_SOURCE_NAMES = frozenset(s.name for s in CONTEXT_SOURCES)


class Layer5Status:
    """Status codes for Layer 5 context retrieval."""

    SUCCESS = "success"
    PARTIAL = "partial"  # Some files missing
    NO_CONTEXT = "no_context"
    ERROR = "error"


@dataclass
class Layer5Result:
    """Result of Layer 5 context retrieval."""

    status: str
    passed: bool
    context: str
    sources_loaded: list[str]
    sources_missing: list[str]
    total_length: int


class Layer5ContextRetriever:
    """
    Context retriever using registry pattern.

    Loads relevant context files based on domain routing.
    No RAG - uses static, pre-curated content only.
    """

    def __init__(
        self,
        context_dir: Path | None = None,
        max_context_length: int | None = None,
    ) -> None:
        """
        Initialize context retriever.

        Args:
            context_dir: Directory containing context files.
            max_context_length: Maximum total context length.
        """
        self.context_dir = context_dir or PATHS.CONTEXT_DIR
        self.max_context_length = max_context_length or SECURITY.MAX_CONTEXT_LENGTH

        # Build domain to sources mapping
        self._domain_sources: dict[Domain, list[ContextSource]] = {}
        for source in CONTEXT_SOURCES:
            if source.domain not in self._domain_sources:
                self._domain_sources[source.domain] = []
            self._domain_sources[source.domain].append(source)

        # Sort by priority (higher first)
        for domain in self._domain_sources:
            self._domain_sources[domain].sort(key=lambda s: -s.priority)

    def _get_sources_for_domain(self, domain: Domain) -> Iterator[ContextSource]:
        """Get context sources for a domain, required first."""
        sources = self._domain_sources.get(domain, [])

        # Yield required sources first
        for source in sources:
            if source.required:
                yield source

        # Then optional sources
        for source in sources:
            if not source.required:
                yield source

    def _load_file(self, source: ContextSource) -> str | None:
        """Load a single context file."""
        file_path = self.context_dir / source.file_pattern

        if not file_path.exists():
            logger.debug(f"Context file not found: {file_path}")
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
            return content.strip()
        except Exception as e:
            logger.error(f"Error reading context file {file_path}: {e}")
            return None

    def retrieve(
        self,
        domain: Domain,
        _intent: Intent | None = None,
    ) -> Layer5Result:
        """
        Retrieve context for a domain.

        Args:
            domain: The target domain.
            intent: Optional intent for more specific retrieval.

        Returns:
            Layer5Result with concatenated context.
        """
        # Handle out of scope
        if domain == Domain.OUT_OF_SCOPE:
            return Layer5Result(
                status=Layer5Status.NO_CONTEXT,
                passed=True,
                context="",
                sources_loaded=[],
                sources_missing=[],
                total_length=0,
            )

        # Collect context from sources
        context_parts: list[str] = []
        sources_loaded: list[str] = []
        sources_missing: list[str] = []
        total_length = 0

        for source in self._get_sources_for_domain(domain):
            # Check if we have room for more context
            if total_length >= self.max_context_length:
                break

            content = self._load_file(source)

            if content is None:
                sources_missing.append(source.name)
                continue

            # Check if adding this would exceed limit
            remaining = self.max_context_length - total_length
            if len(content) > remaining:
                # Truncate if necessary
                content = content[:remaining] + "\n[Content truncated]"

            # Add section header for clarity
            context_parts.append(f"## {source.display_name}\n\n{content}")
            sources_loaded.append(source.name)
            total_length += len(content)

        # Build final context
        context = "\n\n---\n\n".join(context_parts)

        # Determine status
        if not sources_loaded:
            status = Layer5Status.NO_CONTEXT
        elif sources_missing:
            status = Layer5Status.PARTIAL
        else:
            status = Layer5Status.SUCCESS

        return Layer5Result(
            status=status,
            passed=True,  # Always passes - empty context is handled by generator
            context=context,
            sources_loaded=sources_loaded,
            sources_missing=sources_missing,
            total_length=len(context),
        )

    def get_available_sources(self) -> dict[str, list[str]]:
        """Get available sources grouped by domain."""
        result: dict[str, list[str]] = {}
        for domain, sources in self._domain_sources.items():
            result[domain.value] = [s.name for s in sources]
        return result


# Module-level retriever instance
context_retriever = Layer5ContextRetriever()
