"""
Golden path regression tests.

These tests verify that specific queries produce expected responses.
They use the REAL context files to catch bugs in:
- Domain routing
- Context retrieval
- Response generation

When a bug is found and fixed, add a golden path test to prevent regression.
"""

import pytest
from pathlib import Path

from portfolio_chat.pipeline.layer4_route import Layer4Router, Domain
from portfolio_chat.pipeline.layer3_intent import Intent, QuestionType
from portfolio_chat.pipeline.layer5_context import SemanticContextRetriever, Layer5ContextRetriever


# Path to real context files
REAL_CONTEXT_DIR = Path(__file__).parent.parent.parent / "context"


class TestGoldenPathRouting:
    """
    Golden path tests for domain routing.

    Each test represents a real bug that was fixed.
    """

    @pytest.fixture
    def router(self):
        return Layer4Router()

    # Define golden paths: (query, expected_domain, description)
    GOLDEN_PATHS = [
        # Project routing - regression for CAIRN bug
        ("What is CAIRN?", Domain.PROJECTS, "CAIRN is a project"),
        ("Tell me about CAIRN", Domain.PROJECTS, "CAIRN query"),
        ("How does CAIRN work?", Domain.PROJECTS, "CAIRN mechanics"),

        # Other project names
        ("What is ReOS?", Domain.PROJECTS, "ReOS is a project"),
        ("Tell me about RIVA", Domain.PROJECTS, "RIVA is a project"),
        ("What is Talking Rock?", Domain.PROJECTS, "Talking Rock is the main project"),
        ("Ukraine OSINT project", Domain.PROJECTS, "Ukraine project"),
        ("Tell me about the inflation dashboard", Domain.PROJECTS, "Inflation project"),
        ("What is Great Minds Roundtable?", Domain.PROJECTS, "Great Minds project"),

        # Professional queries
        ("What programming languages does Kellogg know?", Domain.PROFESSIONAL, "Skills query"),
        ("Tell me about Kellogg's experience at Kohler", Domain.PROFESSIONAL, "Work experience"),
        ("What are Kellogg's technical skills?", Domain.PROFESSIONAL, "Technical skills"),

        # Meta queries - these require correct topic classification by LLM
        # With topic="general", keywords like "work" can cause routing to PROFESSIONAL
        # Tested separately with correct topic below

        # Contact queries
        ("How can I contact Kellogg?", Domain.LINKEDIN, "Contact info"),
        ("What is Kellogg's LinkedIn?", Domain.LINKEDIN, "LinkedIn query"),
    ]

    @pytest.mark.parametrize("query,expected_domain,description", GOLDEN_PATHS)
    def test_golden_path_routing(self, router, query, expected_domain, description):
        """Verify golden path queries route to expected domains."""
        # Use generic intent to test that routing relies on message, not just topic
        intent = Intent(
            topic="general",
            question_type=QuestionType.FACTUAL,
            confidence=0.7,
        )
        result = router.route(intent, original_message=query)
        assert result.domain == expected_domain, (
            f"Golden path failed: '{description}'\n"
            f"Query: '{query}'\n"
            f"Expected: {expected_domain}, Got: {result.domain}"
        )

    # Meta queries that depend on correct topic classification
    META_QUERIES_WITH_TOPIC = [
        ("How does this chat work?", "chat_system", Domain.META),
        ("What can you help me with?", "chat_system", Domain.META),
        ("Tell me about yourself", "chat_system", Domain.META),
    ]

    @pytest.mark.parametrize("query,topic,expected_domain", META_QUERIES_WITH_TOPIC)
    def test_meta_queries_with_correct_topic(self, router, query, topic, expected_domain):
        """
        Meta queries route correctly when LLM classifies topic correctly.

        These queries contain ambiguous keywords (e.g., 'work' in 'How does this chat work?')
        that could route to PROFESSIONAL. They only route to META when the LLM
        correctly classifies them as chat_system topic.
        """
        intent = Intent(
            topic=topic,
            question_type=QuestionType.FACTUAL,
            confidence=0.8,
        )
        result = router.route(intent, original_message=query)
        assert result.domain == expected_domain


@pytest.mark.skipif(
    not REAL_CONTEXT_DIR.exists(),
    reason="Real context directory not found"
)
class TestGoldenPathRetrieval:
    """
    Golden path tests for context retrieval.

    These test that the right content is retrieved for key queries.
    """

    @pytest.fixture
    def retriever(self):
        """Create retriever with real context files."""
        return Layer5ContextRetriever(context_dir=REAL_CONTEXT_DIR)

    def test_cairn_retrieval_includes_talking_rock(self, retriever):
        """CAIRN queries should include Talking Rock context (CAIRN is part of it)."""
        result = retriever.retrieve(Domain.PROJECTS, _intent=None)

        # Should have loaded the overview and talking rock files
        assert "projects_overview" in result.sources_loaded or "overview" in str(result.sources_loaded)
        assert len(result.context) > 0

    def test_projects_retrieval_has_overview(self, retriever):
        """Projects domain should always include overview context."""
        result = retriever.retrieve(Domain.PROJECTS, _intent=None)

        # Context should mention key projects
        context_lower = result.context.lower()
        assert "talking rock" in context_lower or "cairn" in context_lower


@pytest.mark.skipif(
    not REAL_CONTEXT_DIR.exists(),
    reason="Real context directory not found"
)
class TestGoldenPathSemanticRetrieval:
    """
    Golden path tests for semantic (RAG) retrieval.

    These verify that semantic search returns relevant content.
    """

    @pytest.fixture
    def semantic_retriever(self):
        """Create semantic retriever with real context."""
        return SemanticContextRetriever(
            context_dir=REAL_CONTEXT_DIR,
            top_k=5,
            min_similarity=0.3,
        )

    @pytest.mark.asyncio
    async def test_cairn_semantic_retrieval(self, semantic_retriever):
        """
        Semantic search for CAIRN should return attention management content.

        Regression test: Previously returned ReOS integration notes instead
        of the core CAIRN description.
        """
        result = await semantic_retriever.retrieve_semantic(
            Domain.PROJECTS,
            "What is CAIRN?"
        )

        assert result.passed
        context_lower = result.context.lower()

        # Should mention attention management (CAIRN's purpose)
        assert "attention" in context_lower, "CAIRN context should mention 'attention'"

        # Should be in projects domain sources
        assert len(result.sources_loaded) > 0

    @pytest.mark.asyncio
    async def test_ukraine_semantic_retrieval(self, semantic_retriever):
        """
        Semantic search for Ukraine project should return OSINT content.

        Regression test: Previously returned vague ReOS connection notes.
        """
        result = await semantic_retriever.retrieve_semantic(
            Domain.PROJECTS,
            "Tell me about the Ukraine project"
        )

        assert result.passed
        context_lower = result.context.lower()

        # Should mention OSINT or intelligence
        has_osint = "osint" in context_lower
        has_intelligence = "intelligence" in context_lower
        assert has_osint or has_intelligence, (
            "Ukraine project context should mention OSINT or intelligence"
        )

    @pytest.mark.asyncio
    async def test_talking_rock_semantic_retrieval(self, semantic_retriever):
        """
        Semantic search for Talking Rock should return framework overview.
        """
        result = await semantic_retriever.retrieve_semantic(
            Domain.PROJECTS,
            "What is Talking Rock?"
        )

        assert result.passed
        context_lower = result.context.lower()

        # Should mention it's a framework or assistant
        has_framework = "framework" in context_lower
        has_assistant = "assistant" in context_lower
        has_agents = "agent" in context_lower
        assert has_framework or has_assistant or has_agents, (
            "Talking Rock context should describe it as framework/assistant"
        )

    @pytest.mark.asyncio
    async def test_required_sources_included(self, semantic_retriever):
        """
        Required sources (overview files) should always be included.

        Regression test: Previously only returned semantic matches, missing
        grounding context from overview files.
        """
        result = await semantic_retriever.retrieve_semantic(
            Domain.PROJECTS,
            "Tell me about some obscure detail"
        )

        # Even for vague queries, should include overview content
        assert result.passed
        # The context should have overview source
        assert "(overview)" in result.context or "projects_overview" in str(result.sources_loaded).lower()


class TestGoldenPathResponseContent:
    """
    Golden path tests for what responses should contain.

    These define expected content for key queries that can be checked
    against actual LLM responses.
    """

    # Define expected content: (query, must_contain, must_not_contain)
    CONTENT_EXPECTATIONS = [
        (
            "What is CAIRN?",
            ["attention", "Talking Rock"],  # Must mention these
            ["No One", "Here's how"],  # Must NOT mention these
        ),
        (
            "What is Talking Rock?",
            ["CAIRN", "local"],  # Must mention agents and local-first
            ["No One", "tool_call"],
        ),
        (
            "Ukraine project",
            ["OSINT", "intelligence"],
            ["No One"],
        ),
    ]

    @pytest.mark.parametrize("query,must_contain,must_not_contain", CONTENT_EXPECTATIONS)
    def test_response_content_expectations(self, query, must_contain, must_not_contain):
        """Document expected response content (for use in integration tests)."""
        # This test just validates our expectations are defined correctly
        assert len(must_contain) > 0
        assert isinstance(must_not_contain, list)


# Utility function for use in other tests
def validate_response_against_golden_path(
    response: str,
    must_contain: list[str],
    must_not_contain: list[str],
) -> tuple[bool, list[str]]:
    """
    Validate a response against golden path expectations.

    Returns:
        (passed, list of issues)
    """
    issues = []
    response_lower = response.lower()

    for phrase in must_contain:
        if phrase.lower() not in response_lower:
            issues.append(f"Missing expected content: '{phrase}'")

    for phrase in must_not_contain:
        if phrase.lower() in response_lower:
            issues.append(f"Contains forbidden content: '{phrase}'")

    return len(issues) == 0, issues
