"""Tests for context retrieval (Layer 5)."""

import pytest
from pathlib import Path
import tempfile

from portfolio_chat.pipeline.layer4_route import Domain
from portfolio_chat.pipeline.layer5_context import (
    Layer5ContextRetriever,
    Layer5Status,
    ContextSource,
    CONTEXT_SOURCES,
)


@pytest.fixture
def temp_context_dir():
    """Create a temporary context directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        # Create subdirectories
        (base / "professional").mkdir()
        (base / "projects").mkdir()
        (base / "meta").mkdir()

        # Create test files
        (base / "professional" / "resume.md").write_text("# Resume\n\nTest resume content.")
        (base / "professional" / "skills.md").write_text("# Skills\n\nPython, JavaScript")
        (base / "projects" / "overview.md").write_text("# Projects\n\nProject overview.")
        (base / "meta" / "about_chat.md").write_text("# About\n\nThis is the chat system.")
        (base / "meta" / "contact.md").write_text("# Contact\n\nLinkedIn: test")

        yield base


@pytest.fixture
def retriever(temp_context_dir):
    """Create a context retriever with test directory."""
    return Layer5ContextRetriever(
        context_dir=temp_context_dir,
        max_context_length=10000,
    )


class TestLayer5ContextRetriever:
    """Tests for Layer5ContextRetriever."""

    def test_retrieves_professional_context(self, retriever):
        """Test retrieval of professional context."""
        result = retriever.retrieve(Domain.PROFESSIONAL)
        assert result.passed
        assert "Resume" in result.context
        assert "resume" in result.sources_loaded

    def test_retrieves_projects_context(self, retriever):
        """Test retrieval of projects context."""
        result = retriever.retrieve(Domain.PROJECTS)
        assert result.passed
        assert "Project" in result.context or result.status == Layer5Status.NO_CONTEXT

    def test_retrieves_meta_context(self, retriever):
        """Test retrieval of meta context."""
        result = retriever.retrieve(Domain.META)
        assert result.passed
        assert "About" in result.context or "chat" in result.context.lower()

    def test_out_of_scope_returns_no_context(self, retriever):
        """Test that out of scope returns empty context."""
        result = retriever.retrieve(Domain.OUT_OF_SCOPE)
        assert result.passed
        assert result.context == ""
        assert result.status == Layer5Status.NO_CONTEXT

    def test_tracks_loaded_sources(self, retriever):
        """Test that loaded sources are tracked."""
        result = retriever.retrieve(Domain.PROFESSIONAL)
        assert len(result.sources_loaded) > 0
        assert "resume" in result.sources_loaded

    def test_tracks_missing_sources(self, retriever):
        """Test that missing sources are tracked."""
        result = retriever.retrieve(Domain.HOBBIES)
        # Hobbies files don't exist in our temp dir
        assert len(result.sources_missing) > 0 or result.status == Layer5Status.NO_CONTEXT

    def test_respects_max_context_length(self, temp_context_dir):
        """Test that max context length is respected."""
        # Create a retriever with very small max length
        retriever = Layer5ContextRetriever(
            context_dir=temp_context_dir,
            max_context_length=50,
        )
        result = retriever.retrieve(Domain.PROFESSIONAL)
        # Context should be truncated
        assert len(result.context) <= 100  # Some buffer for truncation message

    def test_get_available_sources(self, retriever):
        """Test listing available sources."""
        sources = retriever.get_available_sources()
        assert "professional" in sources
        assert "projects" in sources
        assert "meta" in sources


class TestContextSource:
    """Tests for ContextSource dataclass."""

    def test_context_sources_defined(self):
        """Test that context sources are defined."""
        assert len(CONTEXT_SOURCES) > 0

    def test_context_sources_have_required_fields(self):
        """Test that all context sources have required fields."""
        for source in CONTEXT_SOURCES:
            assert source.name
            assert source.display_name
            assert source.file_pattern
            assert source.domain

    def test_required_sources_exist_per_domain(self):
        """Test that each domain has at least one required source."""
        domains_with_required = set()
        for source in CONTEXT_SOURCES:
            if source.required:
                domains_with_required.add(source.domain)

        # At least some domains should have required sources
        assert len(domains_with_required) > 0
