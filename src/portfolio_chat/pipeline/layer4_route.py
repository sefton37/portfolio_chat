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
        # Out of scope
        "out_of_scope": Domain.OUT_OF_SCOPE,
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
        # Specific project names - must route to PROJECTS
        "talking rock": Domain.PROJECTS,
        "talkingrock": Domain.PROJECTS,
        "cairn": Domain.PROJECTS,
        "reos": Domain.PROJECTS,
        "riva": Domain.PROJECTS,
        "ukraine": Domain.PROJECTS,
        "osint": Domain.PROJECTS,
        "inflation": Domain.PROJECTS,
        "dashboard": Domain.PROJECTS,
        "great minds": Domain.PROJECTS,
        "roundtable": Domain.PROJECTS,
        "robot": Domain.HOBBIES,
        "first": Domain.HOBBIES,
        "lego": Domain.HOBBIES,
        "volunteer": Domain.HOBBIES,
        "food bank": Domain.HOBBIES,
        "approach": Domain.PHILOSOPHY,
        "think": Domain.PHILOSOPHY,
        "philosophy": Domain.PHILOSOPHY,
        "values": Domain.PHILOSOPHY,
        # Philosophy phrase hints
        "opinion on": Domain.PHILOSOPHY,
        "think about": Domain.PHILOSOPHY,
        "approach to": Domain.PHILOSOPHY,
        "philosophy on": Domain.PHILOSOPHY,
        "argument against": Domain.PHILOSOPHY,
        "argument for": Domain.PHILOSOPHY,
        "what's the point": Domain.PHILOSOPHY,
        "why should": Domain.PHILOSOPHY,
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
        "impressive": Domain.PROFESSIONAL,
        "experience": Domain.PROFESSIONAL,
        "background": Domain.PROFESSIONAL,
        "what does he do": Domain.PROFESSIONAL,
        "what does this person do": Domain.PROFESSIONAL,
        "get in touch": Domain.LINKEDIN,
        "chat": Domain.META,
        "chatbot": Domain.META,
        "bot": Domain.META,
        "this ai": Domain.META,
        "this system": Domain.META,
        "what is this": Domain.META,
        "how does this": Domain.META,
        "what do you do": Domain.META,
        "hardware": Domain.META,
        "server": Domain.META,
        "specs": Domain.META,
        "gpu": Domain.META,
        "cpu": Domain.META,
        "threadripper": Domain.META,
        "running on": Domain.META,
        "corellia": Domain.META,
        "what machine": Domain.META,
        "what computer": Domain.META,
        "pipeline": Domain.META,
        "security layer": Domain.META,
        "how do you work": Domain.META,
        # Project-specific keywords
        "lithium": Domain.PROJECTS,
        "helm": Domain.PROJECTS,
        "nolang": Domain.PROJECTS,
        "sieve": Domain.PROJECTS,
        "sentinel": Domain.PROJECTS,
        "trcore": Domain.PROJECTS,
        "prefect": Domain.PROJECTS,
        "rogue routine": Domain.PROJECTS,
        "rogueroutine": Domain.PROJECTS,
        "abend": Domain.PROJECTS,
        "nol": Domain.PROJECTS,
        "repository": Domain.PROJECTS,
        "repo": Domain.PROJECTS,
        "source code": Domain.PROJECTS,
        "open source": Domain.PROJECTS,
        "sefton37": Domain.PROJECTS,
        "local-first": Domain.PHILOSOPHY,
        "local first": Domain.PHILOSOPHY,
    }

    # Explicit contact phrases that confirm LINKEDIN intent.
    # Used to prevent broad keyword matches (e.g. "send", "message") from
    # pulling unrelated OOS queries into the LINKEDIN domain.
    CONTACT_PHRASES = {
        "tell kellogg", "tell kel", "leave a message", "get in touch",
        "contact him", "reach out to", "reach kellogg", "send kellogg",
        "send him a", "message kellogg", "message him",
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

        # Handle minimal/ambiguous input — very short messages with no clear intent
        # e.g., "ok", "hm", "sure", "yeah", "hm ok" — route to META for a gentle prompt
        if original_message and len(original_message.strip()) < 10 and intent.topic in ("general", "out_of_scope"):
            return Layer4Result(
                status=Layer4Status.ROUTED,
                passed=True,
                domain=Domain.META,
                confidence=0.5,
            )

        # Deterministic OUT_OF_SCOPE guard — these are never about Kellogg regardless
        # of what the classifier says. Catches salary, password, cover letter, weather, etc.
        ALWAYS_OUT_OF_SCOPE = {
            "reset my password", "my password", "forgot password",
            "cover letter", "write a cover", "help me write",
            "weather in", "what's the weather", "temperature in",
            "salary expectation", "salary range", "compensation",
            "what does he make", "how much does he", "what's his salary",
            "relocation", "willing to relocate", "open to relocation",
            "my homework", "do my homework", "help me with my assignment",
        }
        if original_message:
            message_lower = original_message.lower()
            for phrase in ALWAYS_OUT_OF_SCOPE:
                if phrase in message_lower:
                    return Layer4Result(
                        status=Layer4Status.OUT_OF_SCOPE,
                        passed=True,
                        domain=Domain.OUT_OF_SCOPE,
                        confidence=0.95,
                        error_message="I'm designed to answer questions about Kellogg's work and projects. For other topics, I'd recommend a general AI assistant.",
                    )

        # FIRST: Check for specific project names (highest priority)
        # This must come before topic mapping to prevent misrouting
        # e.g., "What is CAIRN?" shouldn't go to META just because LLM classified it as "chat_system"
        PROJECT_NAMES = {
            "cairn", "reos", "riva", "talking rock", "talkingrock",
            "ukraine", "osint", "inflation dashboard", "great minds", "roundtable",
            "lithium", "helm", "nolang", "sieve", "sentinel", "perfidy", "embermind",
            "trcore", "talkingrock-core",
        }
        if original_message:
            message_lower = original_message.lower()
            for project_name in PROJECT_NAMES:
                if project_name in message_lower:
                    return Layer4Result(
                        status=Layer4Status.ROUTED,
                        passed=True,
                        domain=Domain.PROJECTS,
                        confidence=0.9,
                    )

        # Build keyword matches from entities and original message
        # We do this BEFORE topic mapping so we can override weak LLM classifications
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

        # Try direct topic mapping from intent — but treat out_of_scope as "soft"
        # The small classifier model often over-classifies as out_of_scope.
        # If keywords suggest an on-topic domain, override the classifier.
        topic_lower = intent.topic.lower().replace(" ", "_")
        if topic_lower in self.TOPIC_DOMAIN_MAP:
            mapped_domain = self.TOPIC_DOMAIN_MAP[topic_lower]

            if mapped_domain == Domain.OUT_OF_SCOPE and keyword_matches:
                # Classifier said out_of_scope but keywords suggest otherwise — override,
                # but only if the best matching domain is not LINKEDIN driven purely by
                # broad keywords like "send" or "message". Require an explicit contact
                # phrase before overriding OOS with LINKEDIN.
                best_domain = max(keyword_matches, key=keyword_matches.get)  # type: ignore
                match_count = keyword_matches[best_domain]

                if best_domain == Domain.LINKEDIN:
                    # Only override OOS→LINKEDIN when the message contains an explicit
                    # contact phrase. Broad keywords alone are not sufficient.
                    has_contact_intent = original_message and any(
                        phrase in original_message.lower()
                        for phrase in self.CONTACT_PHRASES
                    )
                    if not has_contact_intent:
                        # Fall through to OOS — no real contact intent detected.
                        pass
                    else:
                        logger.info(
                            f"Overriding out_of_scope classification: explicit contact phrase "
                            f"detected, routing to {best_domain.value}"
                        )
                        return Layer4Result(
                            status=Layer4Status.ROUTED,
                            passed=True,
                            domain=best_domain,
                            confidence=min(0.7, 0.4 + (match_count * 0.1)),
                        )
                else:
                    logger.info(
                        f"Overriding out_of_scope classification: keywords suggest {best_domain.value} "
                        f"({match_count} matches)"
                    )
                    return Layer4Result(
                        status=Layer4Status.ROUTED,
                        passed=True,
                        domain=best_domain,
                        confidence=min(0.7, 0.4 + (match_count * 0.1)),
                    )

            return Layer4Result(
                status=Layer4Status.ROUTED if mapped_domain != Domain.OUT_OF_SCOPE else Layer4Status.OUT_OF_SCOPE,
                passed=True,
                domain=mapped_domain,
                confidence=intent.confidence,
                error_message="I'm designed to answer questions about Kellogg's work and projects. For other topics, I'd recommend a general AI assistant." if mapped_domain == Domain.OUT_OF_SCOPE else None,
            )

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

        # Fallback: if general topic and no keyword hints, default to PROFESSIONAL
        # Most ambiguous questions on a portfolio site are professional in nature.
        # Truly off-topic questions (weather, salary, cover letters) should be caught
        # by the classifier's out_of_scope topic before reaching here.
        if intent.topic == "general":
            return Layer4Result(
                status=Layer4Status.ROUTED,
                passed=True,
                domain=Domain.PROFESSIONAL,
                confidence=0.4,
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

    def route_from_message(self, message: str) -> Layer4Result:
        """
        Route directly from message text without a classifier-produced intent.

        Used when USE_COMBINED_CLASSIFIER is false. Builds a synthetic Intent
        from keyword analysis and delegates to the standard route() method.

        Args:
            message: The sanitized user message.

        Returns:
            Layer4Result with the matched domain.
        """
        message_stripped = message.strip()
        message_lower = message_stripped.lower()

        # Detect greetings
        greetings = {"hi", "hello", "hey", "howdy", "greetings", "yo", "sup", "hiya"}
        first_word = message_lower.split()[0] if message_lower.split() else ""
        if first_word in greetings and len(message_stripped) < 20:
            synthetic_intent = Intent(
                topic="greeting",
                question_type=QuestionType.GREETING,
                confidence=0.9,
            )
            return self.route(intent=synthetic_intent, original_message=message)

        # Detect contact intent via explicit phrases
        has_contact = any(phrase in message_lower for phrase in self.CONTACT_PHRASES)
        if has_contact:
            synthetic_intent = Intent(
                topic="message",
                question_type=QuestionType.AMBIGUOUS,
                confidence=0.7,
            )
            return self.route(intent=synthetic_intent, original_message=message)

        # Check keyword matches to infer a topic
        keyword_matches: dict[Domain, int] = {}
        for keyword, domain in self.KEYWORD_HINTS.items():
            if keyword in message_lower:
                keyword_matches[domain] = keyword_matches.get(domain, 0) + 1

        # Infer topic from best keyword domain
        if keyword_matches:
            best_domain = max(keyword_matches, key=keyword_matches.get)  # type: ignore
            topic_reverse = {
                Domain.PROFESSIONAL: "work_experience",
                Domain.PROJECTS: "projects",
                Domain.HOBBIES: "hobbies",
                Domain.PHILOSOPHY: "philosophy",
                Domain.LINKEDIN: "contact",
                Domain.META: "chat_system",
            }
            topic = topic_reverse.get(best_domain, "general")
        else:
            topic = "general"

        synthetic_intent = Intent(
            topic=topic,
            question_type=QuestionType.AMBIGUOUS,
            confidence=0.6,
        )
        return self.route(intent=synthetic_intent, original_message=message)

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
