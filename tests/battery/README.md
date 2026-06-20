# Model-Eval Battery (`tests/battery`)

Leak-safe, multi-turn × multi-model evaluator for the portfolio_chat pipeline.
Reuses the 12 simulation personas in-process and injects models into the live
orchestrator (`layer2_combined.client` + `layer6.model`) with **zero `src/`
changes**. Captures per-layer latency, tokens/sec, and VRAM; quality via a Claude
judge (`claude-sonnet-4-6`, NULL without `ANTHROPIC_API_KEY`); hallucination via
`semantic_verify`; security FP/FN; and emits a Pareto leaderboard.

The FAST pipeline makes exactly **two** LLM calls per turn: the L2+L3 combined
classifier and the L6 generator. All other layers are deterministic (<5 ms).

## Running

```bash
# default smoke tier
.venv/bin/python -m tests.battery --tier smoke
# full grid (resumable); pin classifier / generator set
.venv/bin/python -m tests.battery --tier full --classifier qwen2.5:3b --models "qwen3:4b,gemma3:4b"
```

Runs in **dev-mode by default** (`analytics_storage=None` + `ContactStorage` to a
temp dir) so it never writes to `data/contacts/` or triggers the contact-sweeper
emails. Results (DBs, reports, JSON) land in `results/` and are **gitignored** —
they are large/binary artifacts, like `tests/simulation/results/`.

## Headline findings (40-pair grid, 2026-06-20)

Full report: `results/FINAL_REPORT_40pairs.md` (gitignored). Epic #29 · Issue #292 · Spec #196.

- **The generator dominates quality; the classifier is interchangeable** (0.62–0.63
  flat across all four classifiers — even a 0.5b classifier yields the same
  downstream answer quality as mistral 7b). Choose the classifier purely for
  VRAM/latency economy.
- **`qwen3:4b` is the Pareto winner** — judge 0.695 @ 157 tok/s @ 2.8 GB, ≈ the
  `qwen3:14b` ceiling (0.705) at 1/3 the VRAM and 2.6× the speed. It beats the prior
  live `mistral:7b` generator on quality, speed **and** VRAM.
- **Security is model-independent** (28/40 pairs exactly fp=0 / fn=8). The ~8
  consistent bypasses are a guard-layer/prompt issue, **not** fixable by a model swap.

| Generator | Judge | tok/s | VRAM (MB) |
|---|---|---|---|
| qwen3:14b | 0.705 | 60 | 8900 |
| **qwen3:4b** ★ | **0.695** | **157** | **2761** |
| gemma3:12b | 0.670 | 60 | 7448 |
| phi4:14b | 0.655 | 59 | 8919 |
| gemma3:4b | 0.640 | 123 | 2661 |
| mistral:latest (7b) | 0.625 | 113 | 4482 |
| qwen2.5:3b | 0.568 | 169 | 1992 |

## Deployed config

**2026-06-20:** live prod swapped off all-`mistral:latest` to the winners —
`CLASSIFIER_MODEL=qwen2.5:3b`, `GENERATOR_MODEL=qwen3:4b` (via the env-file +
`systemctl restart portfolio-chat`; ops runbook `portfolio-chat.md`). State-fidelity
verified against the Ollama journal: a real `/chat` turn loaded `qwen2.5:3b` +
`qwen3:4b` + `nomic-embed-text` and zero `mistral`.

## Known caveats / follow-ups (not yet implemented)

1. **Security false-negatives (fn≈8) are unaddressed.** ~8 attack prompts bypass the
   deterministic guard layers (L1/L4/L7/L8) + system prompt regardless of model. This
   is the only finding that points at real product work, and it needs a spec — a model
   swap does nothing for it.
2. **TTFT is schema'd but never populated.** The battery measures the *non-streaming*
   orchestrator path; production serves via `/chat/stream`. The first-token latency
   users actually feel is unmeasured — closing this means driving the streaming path.
3. **Cold-load latency under trickle traffic.** The "all three models resident → no
   GPU swap-thrash" advantage only holds while traffic is warm. On a low-traffic
   portfolio site the models unload between visits (Ollama keep-alive), so the first
   visit after idle pays a cold load (~5 s classifier + ~16 s generator observed).
   Mitigations (longer keep-alive, a warmup ping, or accepting cold latency) are a
   product trade-off, not yet decided.
4. **`llama3.1:8b` generator is a data anomaly** (NULL tok/s + 0.22–0.25 judge across
   all classifiers) — a measurement/generation failure, excluded from the leaderboard;
   worth a clean re-run to close, low priority since it is not a candidate.
