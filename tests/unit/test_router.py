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
