"""
Regression tests for FastPipelineOrchestrator analytics_storage initialization.

Spec #231 / Issue #332 — DOD-4: explicit None passed to analytics_storage must
NOT be coerced to a real store by the `or` fallback in orchestrator_fast.py:83.

Tests:
  - test_explicit_none_disables_analytics (TDD/RED): guards the fix
  - test_omitted_arg_creates_real_store (GREEN): guards the production path
"""

from __future__ import annotations

import os

# Set required env vars before any portfolio_chat import so that the module-level
# singletons (ANALYTICS, CONSENT) can be instantiated without raising ValueError.
# os.environ.setdefault leaves the var alone if already present (e.g. DoD runner
# passes them on the command line), so this is safe to call unconditionally.
_SECRET = "x" * 32
os.environ.setdefault("CONSENT_SECRET", _SECRET)
os.environ.setdefault("ADMIN_TOKEN", _SECRET)
os.environ.setdefault("ANALYTICS_ENABLED", "true")

from unittest.mock import MagicMock  # noqa: E402 — must follow env setup

from portfolio_chat.analytics.storage import ConversationStorage as AnalyticsStorage  # noqa: E402
from portfolio_chat.pipeline.orchestrator_fast import FastPipelineOrchestrator  # noqa: E402


def _make_minimal_collaborators() -> dict:
    """Return MagicMock substitutes for every collaborator the constructor touches.

    DOD-4 explicitly permits mocked collaborators; the analytics store itself
    is what's under test, so only that arg varies between the two tests.
    """
    return {
        "rate_limiter": MagicMock(),
        "conversation_manager": MagicMock(),
        "ollama_client": MagicMock(),
        "contact_storage": MagicMock(),
    }


def test_explicit_none_disables_analytics() -> None:
    """Passing analytics_storage=None explicitly must result in orch.analytics_storage is None.

    Original bug (orchestrator_fast.py:83):
        self.analytics_storage = analytics_storage or (AnalyticsStorage() if ANALYTICS.ENABLED else None)
    The `or` coercion turned an explicit None into a real store when ANALYTICS.ENABLED is true.
    The fix replaces that line with a sentinel-based check so explicit None is respected.

    Maps to Spec #231 DOD-4. Module-level (not class-nested) so the DoD node ID
    `...::test_explicit_none_disables_analytics` resolves directly.
    """
    collaborators = _make_minimal_collaborators()

    orch = FastPipelineOrchestrator(**collaborators, analytics_storage=None)

    assert orch.analytics_storage is None, (
        "Expected analytics_storage to be None when explicitly passed None, "
        f"but got {type(orch.analytics_storage)!r}. "
        "The `or` coercion in orchestrator_fast.py:83 must be replaced with "
        "a sentinel-based check so that explicit None is respected."
    )


def test_omitted_arg_creates_real_store() -> None:
    """Omitting analytics_storage with ANALYTICS_ENABLED=true must create a real store.

    This verifies the production path: when the caller does not supply an
    analytics store and analytics is enabled, the orchestrator wires one up
    automatically.  This test must PASS today and must KEEP passing after
    the explicit-None fix is applied.

    Maps to Spec #231 DOD-5.
    """
    collaborators = _make_minimal_collaborators()

    # analytics_storage is intentionally omitted — default is used
    orch = FastPipelineOrchestrator(**collaborators)

    assert orch.analytics_storage is not None, (
        "Expected analytics_storage to be a real store when arg is omitted "
        "and ANALYTICS_ENABLED=true, but got None."
    )
    assert isinstance(orch.analytics_storage, AnalyticsStorage), (
        f"Expected analytics_storage to be an AnalyticsStorage instance, "
        f"but got {type(orch.analytics_storage)!r}."
    )
