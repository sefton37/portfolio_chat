"""
tests.coverage — Content-coverage and tone-robustness test harness.

Drives the chat orchestrator in-process against a question battery.
Leak-safe: ContactStorage is always rooted at a temp dir; analytics_storage=None.
"""
