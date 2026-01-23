"""
Tests for response quality and character consistency.

These tests ensure:
1. Responses don't echo internal instructions
2. Responses don't contain forbidden phrases
3. Responses maintain character consistency
4. Factual accuracy in describing projects
"""

import pytest
import re


class TestForbiddenPhrases:
    """
    Tests that responses don't contain internal terminology or instruction echoing.

    These are regression tests for bugs where the LLM would echo parts of
    its system prompt or tool instructions in responses.
    """

    # Phrases that should NEVER appear in user-facing responses
    FORBIDDEN_PHRASES = [
        # Internal philosophy terminology (removed from prompts)
        '"No One"',
        "'No One'",
        "No One philosophy",
        "No One presence",

        # Tool instruction echoing
        "Here's how it works:",
        "After using the tool",
        "tool_call block",
        "WHEN TO USE",
        "WHEN NOT TO USE",
        "WRONG - DO NOT",
        "CORRECT EXAMPLES",

        # System prompt leakage
        "You are Talking Rock, an AI assistant on Kellogg's",  # Full prompt opening
        "CORE PRINCIPLES:",
        "GUIDELINES:",
        "THE TEST:",
        "What You Don't Do",
        "The Organizing Principle",

        # Meta-instructions
        "As per my instructions",
        "According to my system prompt",
        "I was told to",
        "My guidelines say",
    ]

    # Phrases that are OK in context but suspicious if repeated
    SUSPICIOUS_PATTERNS = [
        r"```tool_call",  # Should only appear when actually calling tool
        r"\{\"action\":",  # JSON tool format in prose
    ]

    def test_forbidden_phrases_list_is_comprehensive(self):
        """Sanity check that we have forbidden phrases defined."""
        assert len(self.FORBIDDEN_PHRASES) > 10

    @pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
    def test_forbidden_phrase_detection(self, phrase):
        """Each forbidden phrase should be detectable."""
        test_response = f"Some text {phrase} more text"
        assert phrase in test_response

    def check_response_quality(self, response: str) -> list[str]:
        """
        Check a response for quality issues.

        Returns list of problems found.
        """
        problems = []

        for phrase in self.FORBIDDEN_PHRASES:
            if phrase.lower() in response.lower():
                problems.append(f"Contains forbidden phrase: '{phrase}'")

        for pattern in self.SUSPICIOUS_PATTERNS:
            matches = re.findall(pattern, response)
            if len(matches) > 1:  # One might be legitimate, multiple is suspicious
                problems.append(f"Suspicious pattern repeated: '{pattern}'")

        return problems


class TestCharacterConsistency:
    """
    Tests for maintaining consistent AI persona.

    The assistant should:
    - Refer to Kellogg in third person
    - Not claim to be Kellogg
    - Not claim personal experiences
    """

    # Phrases indicating the AI is claiming to BE Kellogg (not allowed)
    FIRST_PERSON_PROJECT_CLAIMS = [
        "I built",
        "I created",
        "I developed",
        "my project",
        "my experience includes",
        "I worked at",
        "when I was at Kohler",
    ]

    # Acceptable first-person usage (referring to self as assistant)
    ACCEPTABLE_FIRST_PERSON = [
        "I can help",
        "I can tell you",
        "I'm here to",
        "I don't have information",
        "I'm Talking Rock",
    ]

    def check_character_consistency(self, response: str) -> list[str]:
        """
        Check response for character consistency issues.

        Returns list of problems found.
        """
        problems = []
        response_lower = response.lower()

        for phrase in self.FIRST_PERSON_PROJECT_CLAIMS:
            if phrase.lower() in response_lower:
                # Check it's not part of a quote or example
                if f'"{phrase}' not in response and f"'{phrase}" not in response:
                    problems.append(f"AI claiming personal experience: '{phrase}'")

        return problems


class TestFactualAccuracy:
    """
    Tests for factual accuracy about projects.

    These catch bugs like describing CAIRN as "containing" Talking Rock
    when it's actually the other way around.
    """

    # Known facts that should be correct
    PROJECT_FACTS = {
        "talking_rock_contains_cairn": {
            "correct": ["CAIRN is part of Talking Rock", "Talking Rock includes CAIRN", "CAIRN, one of Talking Rock's agents"],
            "incorrect": ["CAIRN contains Talking Rock", "Talking Rock is part of CAIRN", "CAIRN includes Talking Rock"],
        },
        "talking_rock_agents": {
            "correct": ["three agents", "CAIRN, ReOS, and RIVA", "CAIRN, ReOS, RIVA"],
            "incorrect": ["four agents", "two agents", "CAIRN, ReOS, RIVA, and"],
        },
        "ukraine_is_osint": {
            "correct": ["OSINT", "open-source intelligence", "intelligence analysis"],
            "incorrect": [],  # No known incorrect variations
        },
    }

    def check_factual_accuracy(self, response: str, topic: str) -> list[str]:
        """
        Check response for factual accuracy issues.

        Returns list of problems found.
        """
        problems = []
        response_lower = response.lower()

        # Check for known incorrect statements
        for fact_name, fact_data in self.PROJECT_FACTS.items():
            for incorrect in fact_data.get("incorrect", []):
                if incorrect.lower() in response_lower:
                    problems.append(f"Factual error ({fact_name}): contains '{incorrect}'")

        return problems


class TestResponseQualityIntegration:
    """
    Integration tests combining all quality checks.
    """

    @pytest.fixture
    def quality_checker(self):
        """Create instances of all quality check classes."""
        return {
            "forbidden": TestForbiddenPhrases(),
            "character": TestCharacterConsistency(),
            "factual": TestFactualAccuracy(),
        }

    def run_all_checks(self, response: str, quality_checker: dict) -> list[str]:
        """Run all quality checks on a response."""
        all_problems = []
        all_problems.extend(quality_checker["forbidden"].check_response_quality(response))
        all_problems.extend(quality_checker["character"].check_character_consistency(response))
        all_problems.extend(quality_checker["factual"].check_factual_accuracy(response, "general"))
        return all_problems

    def test_good_response_passes(self, quality_checker):
        """A well-formed response should pass all checks."""
        good_response = """
        CAIRN is an attention management agent that's part of Kellogg's Talking Rock project.
        It helps with life organization and runs on consumer hardware. Kellogg designed it
        to serve without coercion, operating through invitation rather than extraction.
        """
        problems = self.run_all_checks(good_response, quality_checker)
        assert len(problems) == 0, f"Good response had problems: {problems}"

    def test_instruction_echoing_detected(self, quality_checker):
        """Response echoing instructions should be caught."""
        bad_response = """
        CAIRN is a project. Here's how it works:
        After using the tool, you'll see confirmation.
        """
        problems = self.run_all_checks(bad_response, quality_checker)
        assert len(problems) > 0
        assert any("Here's how it works" in p for p in problems)

    def test_no_one_reference_detected(self, quality_checker):
        """Response mentioning 'No One' philosophy should be caught."""
        bad_response = """
        CAIRN embodies the "No One" philosophy - presence without imposition.
        """
        problems = self.run_all_checks(bad_response, quality_checker)
        assert len(problems) > 0
        assert any("No One" in p for p in problems)

    def test_first_person_claim_detected(self, quality_checker):
        """Response with AI claiming to be Kellogg should be caught."""
        bad_response = """
        I built CAIRN to help with attention management. When I was at Kohler,
        I developed similar systems.
        """
        problems = self.run_all_checks(bad_response, quality_checker)
        assert len(problems) > 0

    def test_factual_inversion_detected(self, quality_checker):
        """Response with inverted facts should be caught."""
        bad_response = """
        CAIRN contains Talking Rock as one of its components.
        """
        problems = self.run_all_checks(bad_response, quality_checker)
        assert len(problems) > 0
        assert any("Factual error" in p for p in problems)
