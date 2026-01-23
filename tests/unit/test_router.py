"""Tests for domain routing (Layer 4)."""

import pytest

from portfolio_chat.pipeline.layer3_intent import (
    Intent,
    QuestionType,
    EmotionalTone,
)
from portfolio_chat.pipeline.layer4_route import (
    Layer4Router,
    Domain,
    Layer4Status,
)


@pytest.fixture
def router():
    """Create a router instance."""
    return Layer4Router()


class TestLayer4Router:
    """Tests for Layer4Router."""

    def test_routes_work_experience_to_professional(self, router):
        """Test that work experience routes to professional domain."""
        intent = Intent(
            topic="work_experience",
            question_type=QuestionType.EXPERIENCE,
            confidence=0.9,
        )
        result = router.route(intent)
        assert result.domain == Domain.PROFESSIONAL
        assert result.status == Layer4Status.ROUTED

    def test_routes_skills_to_professional(self, router):
        """Test that skills routes to professional domain."""
        intent = Intent(
            topic="skills",
            question_type=QuestionType.FACTUAL,
            confidence=0.9,
        )
        result = router.route(intent)
        assert result.domain == Domain.PROFESSIONAL

    def test_routes_projects_to_projects(self, router):
        """Test that projects routes to projects domain."""
        intent = Intent(
            topic="projects",
            question_type=QuestionType.FACTUAL,
            entities=["portfolio", "github"],
            confidence=0.9,
        )
        result = router.route(intent)
        assert result.domain == Domain.PROJECTS

    def test_routes_hobbies_to_hobbies(self, router):
        """Test that hobbies routes to hobbies domain."""
        intent = Intent(
            topic="hobbies",
            question_type=QuestionType.EXPERIENCE,
            confidence=0.9,
        )
        result = router.route(intent)
        assert result.domain == Domain.HOBBIES

    def test_routes_philosophy_to_philosophy(self, router):
        """Test that philosophy routes to philosophy domain."""
        intent = Intent(
            topic="philosophy",
            question_type=QuestionType.OPINION,
            confidence=0.9,
        )
        result = router.route(intent)
        assert result.domain == Domain.PHILOSOPHY

    def test_routes_contact_to_linkedin(self, router):
        """Test that contact routes to linkedin domain."""
        intent = Intent(
            topic="contact",
            question_type=QuestionType.FACTUAL,
            confidence=0.9,
        )
        result = router.route(intent)
        assert result.domain == Domain.LINKEDIN

    def test_routes_chat_system_to_meta(self, router):
        """Test that chat system questions route to meta domain."""
        intent = Intent(
            topic="chat_system",
            question_type=QuestionType.FACTUAL,
            confidence=0.9,
        )
        result = router.route(intent)
        assert result.domain == Domain.META

    def test_routes_greeting_to_meta(self, router):
        """Test that greetings route to meta domain."""
        intent = Intent(
            topic="general",
            question_type=QuestionType.GREETING,
            confidence=1.0,
        )
        result = router.route(intent)
        assert result.domain == Domain.META

    def test_uses_keyword_hints(self, router):
        """Test that keyword hints are used for routing."""
        intent = Intent(
            topic="general",
            question_type=QuestionType.FACTUAL,
            entities=["Python", "programming"],
            confidence=0.5,
        )
        result = router.route(intent, original_message="What Python projects have you done?")
        assert result.domain == Domain.PROFESSIONAL

    def test_routes_unknown_to_out_of_scope(self, router):
        """Test that unknown topics route to out of scope."""
        intent = Intent(
            topic="weather",
            question_type=QuestionType.FACTUAL,
            confidence=0.9,
        )
        result = router.route(intent)
        assert result.domain == Domain.OUT_OF_SCOPE
        assert result.status == Layer4Status.OUT_OF_SCOPE

    def test_low_confidence_general_routes_to_professional(self, router):
        """Test that low confidence general routes to professional by default."""
        intent = Intent(
            topic="general",
            question_type=QuestionType.AMBIGUOUS,
            confidence=0.6,
        )
        result = router.route(intent)
        assert result.domain == Domain.PROFESSIONAL

    def test_get_domain_description(self):
        """Test domain description retrieval."""
        desc = Layer4Router.get_domain_description(Domain.PROFESSIONAL)
        assert "professional" in desc.lower()

        desc = Layer4Router.get_domain_description(Domain.PROJECTS)
        assert "project" in desc.lower()


class TestProjectNameRouting:
    """
    Regression tests for project name routing.

    These tests ensure specific project names route to PROJECTS domain
    regardless of how the LLM classifies the topic. This prevents bugs
    like CAIRN routing to META because it contains 'ai'.
    """

    @pytest.fixture
    def router(self):
        return Layer4Router()

    @pytest.mark.parametrize("project_name,query", [
        ("cairn", "What is CAIRN?"),
        ("cairn", "Tell me about cairn"),
        ("reos", "What is ReOS?"),
        ("reos", "How does reos work?"),
        ("riva", "What is RIVA?"),
        ("talking rock", "What is Talking Rock?"),
        ("talkingrock", "Tell me about talkingrock"),
        ("ukraine", "Tell me about the Ukraine project"),
        ("osint", "What is the OSINT reader?"),
        ("inflation", "Tell me about the inflation dashboard"),
        ("great minds", "What is Great Minds Roundtable?"),
    ])
    def test_project_name_routes_to_projects(self, router, project_name, query):
        """Project names must route to PROJECTS domain."""
        # Even with a generic or wrong topic, project names should win
        intent = Intent(
            topic="general",
            question_type=QuestionType.FACTUAL,
            confidence=0.7,
        )
        result = router.route(intent, original_message=query)
        assert result.domain == Domain.PROJECTS, f"'{query}' should route to PROJECTS"

    @pytest.mark.parametrize("project_name,query,wrong_topic", [
        ("cairn", "What is CAIRN?", "chat_system"),  # LLM thinks it's about AI/chat
        ("reos", "Tell me about ReOS", "chat_system"),
        ("riva", "What is RIVA?", "chat_system"),
        ("ukraine", "Ukraine project details", "general"),
    ])
    def test_project_name_overrides_wrong_topic(self, router, project_name, query, wrong_topic):
        """
        Project names must take priority over topic classification.

        This is a regression test for the bug where 'What is CAIRN?' was
        classified as topic='chat_system' and routed to META instead of PROJECTS.
        """
        intent = Intent(
            topic=wrong_topic,
            question_type=QuestionType.FACTUAL,
            confidence=0.8,
        )
        result = router.route(intent, original_message=query)
        assert result.domain == Domain.PROJECTS, (
            f"'{query}' with topic='{wrong_topic}' should still route to PROJECTS"
        )

    def test_cairn_routes_despite_ai_keyword(self, router):
        """
        CAIRN contains 'ai' but should route to PROJECTS, not META.

        This tests the keyword conflict resolution: 'cairn' (PROJECTS)
        should take priority over 'ai' (META) being a substring.
        """
        intent = Intent(
            topic="chat_system",  # LLM saw 'AI' and classified as chat
            question_type=QuestionType.FACTUAL,
            entities=["CAIRN"],
            confidence=0.8,
        )
        result = router.route(intent, original_message="What is CAIRN?")
        assert result.domain == Domain.PROJECTS

    def test_project_routing_is_case_insensitive(self, router):
        """Project name matching should be case-insensitive."""
        queries = [
            "What is CAIRN?",
            "What is cairn?",
            "What is Cairn?",
            "UKRAINE project",
            "ukraine project",
        ]
        for query in queries:
            intent = Intent(topic="general", question_type=QuestionType.FACTUAL, confidence=0.7)
            result = router.route(intent, original_message=query)
            assert result.domain == Domain.PROJECTS, f"'{query}' should route to PROJECTS"

    def test_non_project_still_routes_normally(self, router):
        """Queries without project names should use normal routing."""
        intent = Intent(
            topic="skills",
            question_type=QuestionType.FACTUAL,
            confidence=0.9,
        )
        result = router.route(intent, original_message="What programming languages do you know?")
        assert result.domain == Domain.PROFESSIONAL
