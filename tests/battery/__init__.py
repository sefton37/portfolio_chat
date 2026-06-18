"""
tests/battery — unified model-evaluation battery for portfolio_chat.

Evaluates classifier × generator model pairs across three axes:
- Performance: tokens/sec, TTFT, latency from Ollama instrumentation
- Quality: judge score (Claude), hallucination count (SemanticVerifier)
- Security: FP/FN counts from LAYER2_ATTACKS + escalation persona

Zero src/ changes (DOD-32): injection is post-construction attribute override,
identical to the pattern established in tests/benchmark/engine.py lines 527/532.
"""
