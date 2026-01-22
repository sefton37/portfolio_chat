"""
Layer 4: Domain Routing

Maps parsed intent to one of the allowed domains for context retrieval.
Uses rule-based routing with LLM fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from portfolio_chat.pipeline.layer3_intent import Intent, QuestionType

logger = logging.getLogger(__name__)


class Domain(Enum):
    """Allowed domains for the portfolio chat."""

    PROFESSIONAL = "professional"  # Work history, skills, experience
    PROJECTS = "projects"  # Portfolio work, technical projects, GitHub
    HOBBIES = "hobbies"  # FIRST robotics, food bank volunteering, interests
    PHILOSOPHY = "philosophy"  # Problem-solving approach, values, working style
    LINKEDIN = "linkedin"  # Professional networking, career inquiries
    META = "meta"  # Questions about this chat system itself
    OUT_OF_SCOPE = "out_of_scope"  # Anything else


class Layer4Status(Enum):
    """Status codes for Layer 4 routing."""

    ROUTED = "routed"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass
class Layer4Result:
    """Result of Layer 4 domain routing."""

    status: Layer4Status
    passed: bool
    domain: Domain
    confidence: float = 0.0
    error_message: str | None = None


class Layer4Router:
    """
    Domain router - maps intent to domain.

    Uses rule-based routing based on extracted intent topic.
    Falls back to OUT_OF_SCOPE for unclear intents.
    """

    # Topic to domain mapping
    TOPIC_DOMAIN_MAP: dict[str, Domain] = {
        # Professional domain
        "work_experience": Domain.PROFESSIONAL,
        "skills": Domain.PROFESSIONAL,
        "education": Domain.PROFESSIONAL,
        "achievements": Domain.PROFESSIONAL,
        "career": Domain.PROFESSIONAL,
        "resume": Domain.PROFESSIONAL,
        "experience": Domain.PROFESSIONAL,
        # Projects domain
        "projects": Domain.PROJECTS,
        "portfolio": Domain.PROJECTS,
        "github": Domain.PROJECTS,
        "code": Domain.PROJECTS,
        "technical": Domain.PROJECTS,
        # Hobbies domain
        "hobbies": Domain.HOBBIES,
        "volunteering": Domain.HOBBIES,
        "first_robotics": Domain.HOBBIES,
        "interests": Domain.HOBBIES,
        "personal": Domain.HOBBIES,
        # Philosophy domain
        "philosophy": Domain.PHILOSOPHY,
        "approach": Domain.PHILOSOPHY,
        "values": Domain.PHILOSOPHY,
        "working_style": Domain.PHILOSOPHY,
        "problem_solving": Domain.PHILOSOPHY,
        # LinkedIn/Contact domain
        "contact": Domain.LINKEDIN,
        "linkedin": Domain.LINKEDIN,
        "networking": Domain.LINKEDIN,
        "connect": Domain.LINKEDIN,
        "hire": Domain.LINKEDIN,
        "hiring": Domain.LINKEDIN,
        "message": Domain.LINKEDIN,
        "email": Domain.LINKEDIN,
        "reach_out": Domain.LINKEDIN,
        "leave_message": Domain.LINKEDIN,
        "send_message": Domain.LINKEDIN,
        # Meta domain
        "chat_system": Domain.META,
        "about_chat": Domain.META,
        "how_does_this_work": Domain.META,
    }

    # Keywords that suggest specific domains
    KEYWORD_HINTS: dict[str, Domain] = {
        "kohler": Domain.PROFESSIONAL,
        "work": Domain.PROFESSIONAL,
        "job": Domain.PROFESSIONAL,
        "python": Domain.PROFESSIONAL,
        "programming": Domain.PROFESSIONAL,
        "engineer": Domain.PROFESSIONAL,
        "project": Domain.PROJECTS,
        "github": Domain.PROJECTS,
        "portfolio": Domain.PROJECTS,
        "built": Domain.PROJECTS,
        "created": Domain.PROJECTS,
        "robot": Domain.HOBBIES,
        "first": Domain.HOBBIES,
        "lego": Domain.HOBBIES,
        "volunteer": Domain.HOBBIES,
        "food bank": Domain.HOBBIES,
        "approach": Domain.PHILOSOPHY,
        "think": Domain.PHILOSOPHY,
        "philosophy": Domain.PHILOSOPHY,
        "values": Domain.PHILOSOPHY,
        "linkedin": Domain.LINKEDIN,
        "contact": Domain.LINKEDIN,
        "reach": Domain.LINKEDIN,
        "connect": Domain.LINKEDIN,
        "message": Domain.LINKEDIN,
        "email": Domain.LINKEDIN,
        "tell kellogg": Domain.LINKEDIN,
        "tell kel": Domain.LINKEDIN,
        "leave a message": Domain.LINKEDIN,
        "send": Domain.LINKEDIN,
        "chat": Domain.META,
        "system": Domain.META,
        "ai": Domain.META,
        "bot": Domain.META,
    }

    def __init__(self) -> None:
        """Initialize router."""
        pass

    def route(
        self,
        intent: Intent,
        original_message: str | None = None,
    ) -> Layer4Result:
        """
        Route intent to a domain.

        Args:
            intent: Parsed intent from Layer 3.
            original_message: Original message for keyword fallback.

        Returns:
            Layer4Result with the matched domain.
        """
        # Handle greetings specially
        if intent.question_type == QuestionType.GREETING:
            return Layer4Result(
                status=Layer4Status.ROUTED,
                passed=True,
                domain=Domain.META,  # Greetings are handled by meta
                confidence=1.0,
            )

        # First, try direct topic mapping
        topic_lower = intent.topic.lower().replace(" ", "_")
        if topic_lower in self.TOPIC_DOMAIN_MAP:
            domain = self.TOPIC_DOMAIN_MAP[topic_lower]
            return Layer4Result(
                status=Layer4Status.ROUTED,
                passed=True,
                domain=domain,
                confidence=intent.confidence,
            )

        # Try keyword hints from entities and original message
        keyword_matches: dict[Domain, int] = {}

        # Check entities
        for entity in intent.entities:
            entity_lower = entity.lower()
            for keyword, domain in self.KEYWORD_HINTS.items():
                if keyword in entity_lower:
                    keyword_matches[domain] = keyword_matches.get(domain, 0) + 1

        # Check original message if provided
        if original_message:
            message_lower = original_message.lower()
            for keyword, domain in self.KEYWORD_HINTS.items():
                if keyword in message_lower:
                    keyword_matches[domain] = keyword_matches.get(domain, 0) + 1

        # Use domain with most keyword matches
        if keyword_matches:
            best_domain = max(keyword_matches, key=keyword_matches.get)  # type: ignore
            match_count = keyword_matches[best_domain]
            confidence = min(0.8, intent.confidence + (match_count * 0.1))

            return Layer4Result(
                status=Layer4Status.ROUTED,
                passed=True,
                domain=best_domain,
                confidence=confidence,
            )

        # Fallback: if general topic and no hints, default to PROFESSIONAL
        if intent.topic == "general" and intent.confidence >= 0.5:
            return Layer4Result(
                status=Layer4Status.ROUTED,
                passed=True,
                domain=Domain.PROFESSIONAL,
                confidence=0.5,
            )

        # No clear routing - mark as out of scope
        logger.info(f"Message routed to OUT_OF_SCOPE: topic={intent.topic}")
        return Layer4Result(
            status=Layer4Status.OUT_OF_SCOPE,
            passed=True,  # Still passes - the domain will handle the response
            domain=Domain.OUT_OF_SCOPE,
            confidence=0.0,
            error_message="I'm designed to answer questions about Kellogg's work and projects. For other topics, I'd recommend a general AI assistant.",
        )

    @staticmethod
    def get_domain_description(domain: Domain) -> str:
        """Get a human-readable description of a domain."""
        descriptions = {
            Domain.PROFESSIONAL: "professional background, work experience, and skills",
            Domain.PROJECTS: "projects, portfolio work, and technical implementations",
            Domain.HOBBIES: "hobbies, volunteering, and personal interests",
            Domain.PHILOSOPHY: "problem-solving approach and working philosophy",
            Domain.LINKEDIN: "professional networking and contact information",
            Domain.META: "this chat system",
            Domain.OUT_OF_SCOPE: "topics outside my knowledge area",
        }
        return descriptions.get(domain, "unknown domain")
