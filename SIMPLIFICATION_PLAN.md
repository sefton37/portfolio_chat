# Plan: Pipeline Simplification for Latency and Reliability

## Context

The current production path is `orchestrator_fast.py` using `FastPipelineOrchestrator`. It
already collapses the original 9 layers into an effective 5-stage hot path:

```
L0: rate limit / request size validation        ~5ms
L1: regex sanitization                          ~1ms
L2+L3: combined LLM security+intent (qwen2.5:3b) ~500ms–2s
L4: rule-based domain routing                   ~1ms
L5: static file context load / semantic embed   ~200ms (embed path)
L6: response generation (mistral:7b)            ~3–8s
L8: pattern-based output safety check           ~1ms
```

Measured p50 is ~9s. The two sequential LLM calls are the sole bottleneck. The only on-path LLM
calls that matter are L2+L3 (classifier) and L6 (generator). Everything else is under 5ms.

### Known problems carried into this plan

1. ~280 false-positive blocks — L2 classifier over-fires on skeptical/demanding tone
2. Tool call leakage — malformed `\`\`\`tool_call\`\`\`` blocks reach users
3. Contact flow over-triggering — `save_message_for_kellogg` called on non-contact intent
4. L7 (revision) and LLM-mode L8 are dead code — already removed from fast path
5. `orchestrator.py` is also dead code — the server imports only `FastPipelineOrchestrator`

The path to <3s p50 has two viable approaches. Both are analyzed below.

---

## Approaches

### Approach A — Eliminate the classifier entirely (1 LLM call)

Remove L2+L3 combined classifier. Fold all security into:
- L1 (expanded regex patterns) for hard jailbreak syntax
- L6 system prompt (the generator already refuses to cooperate with jailbreaks)
- L8 fast checker (catches prompt-leakage in output)

L4 routing becomes keyword+entity driven only. The intent fields the classifier previously
produced (topic, question_type) are replaced by the domain the L4 keyword router infers
directly from the raw message. This eliminates the 500ms–2s classifier call entirely.

**Hot path:** L0(5ms) → L1(1ms) → L4(1ms) → L5(200ms) → L6(3–8s) → L8(1ms) = **3.2–8.2s**

Estimated p50: ~3.5–4s (depending on L6 generation time for the specific query).

**Security posture:** The generator model (mistral:7b) is significantly more resistant to
jailbreaks than a dedicated 3B classifier — it has been trained with RLHF against adversarial
prompts. The spotlighting technique in `_format_user_message()` already wraps user input in
`<<<USER_MESSAGE>>>` delimiters. L1 still blocks the narrow set of hard syntactic patterns.
The loss is structured security logging of intent and jailbreak reason codes.

**Trade-offs:**
- Latency gain: ~1–2s (removes the 500ms–2s classifier call)
- False positives: Drops to near-zero (no dedicated classifier to over-block)
- Security: Slightly lower theoretical depth-of-defense, but practical risk is low because
  mistral:7b has strong built-in refusal behavior
- L4 routing accuracy degrades for ambiguous messages (currently the classifier's topic output
  is used as routing input; without it, keyword-only routing has higher uncertainty)
- Audit trail loses: `jailbreak_reason`, `intent.question_type`, `intent.entities`, `emotional_tone`
- Most vulnerable to: a visitor phrasing a question so oddly that keyword routing misfires

### Approach B — Keep the classifier but make it faster (1 LLM call, improved)

Keep L2+L3 combined classifier but reduce its latency by switching to a smaller, faster model
or by running it concurrently with L5 context retrieval.

**Sub-variant B1 — Concurrency:** Fire the classifier (L2+L3) and the context pre-load (L5) in
parallel. L5 can load all domains speculatively or the most likely domain can be guessed from
L1 keyword scan. Wait for both; combine results.

**Hot path:** L0(5ms) → L1(1ms) → [L2+L3 || L5](max of ~1s classifier, ~200ms context) → L6(3–8s) → L8(1ms)

Estimated p50: ~4–5s (L2 still dominates if routing guess is wrong; L5 parallel cuts ~200ms).

**Sub-variant B2 — Smaller/faster classifier model:** Switch classifier from `qwen2.5:3b` to
`qwen2.5:0.5b` or `phi3.5:mini`. Reduces classifier from ~1–2s to ~200–400ms.

Hot path estimated p50: ~3.5–4.5s

**Trade-offs:**
- Retains structured intent + jailbreak audit trail
- Retains the ability to tune false positives through prompt engineering
- Concurrency adds real complexity to the orchestrator
- Speculative domain guessing for L5 parallel load is fragile (wrong guess = wasted work)
- Smaller model (`0.5b`) has worse classification accuracy — likely increases false positives
- The 280 false positives are a classifier quality problem, not a model size problem;
  reducing model size may make it worse

### Approach C — Keep classifier, fix false positives, add streaming (recommended)

Keep the classifier but fix the root causes of both the false-positive problem and the
perceived latency, without restructuring the pipeline at all.

**Latency fix via streaming:** The generator is already capable of streaming
(`process_message_stream()` exists in `orchestrator_fast.py`). The UI receives the first token
in ~1s instead of waiting 3–8s for the full response. Measured time-to-first-token on
mistral:7b is ~800ms–1.5s. This changes the *user experience* of latency without changing p50
wall-clock time.

**False positive fix:** Expand SAFE examples in `COMBINED_SYSTEM_PROMPT` and tighten the
`manipulation` definition, as already specified in `BENCHMARK_FIXES_PLAN.md`.

**Tool call leakage fix:** Move `remove_tool_calls()` outside the `if tool_calls:` guard in
`layer6_generate.py`, as already specified in `FIXES_PLAN.md`.

**Dead code removal:** Delete `orchestrator.py`, `layer2_jailbreak.py`, `layer3_intent.py`
(the standalone versions), `layer7_revise.py`, `layer8_safety.py`.

**Trade-offs:**
- No latency improvement in wall-clock p50 (still ~9s end-to-end)
- Streaming dramatically improves perceived latency — the widget starts showing text in ~1s
- No structural risk — no changes to routing or security architecture
- Fixes the two immediate quality problems (false positives, tool leakage)
- The classifier false positive problem persists at some level unless prompt is re-tuned

---

## Recommendation

**Implement Approach C (streaming + fixes) as the immediate deliverable, then evaluate
Approach A (drop classifier) behind a feature flag in a follow-on cycle.**

The rationale:

1. **Streaming is the highest-leverage latency change.** A portfolio chat widget that starts
   showing text after 1 second feels fast even if total generation takes 5 seconds. The
   existing `process_message_stream()` method already does this correctly. What is missing is
   the frontend and server wiring to use it by default.

2. **The false positive problem has a known prompt fix.** `BENCHMARK_FIXES_PLAN.md` already
   defines the exact prompt changes needed. This should be done regardless of which structural
   approach is chosen.

3. **Approach A is a real simplification but carries routing risk.** The L4 keyword router is
   quite good (200+ keyword entries, project name guards, contact phrase guards), but it was
   designed to consume intent signals from the classifier. Removing that input needs to be
   validated against the benchmark suite before deploying to production.

4. **The clean path is: fix → validate → simplify.** Fix the immediate bugs, validate with
   the benchmark, then eliminate the classifier in a separate change that can be toggled via
   the `USE_COMBINED_CLASSIFIER` flag that already exists in `config.py`.

---

## Implementation Steps

### Phase 1: Immediate fixes (no structural change)

These are all drawn from `FIXES_PLAN.md` and `BENCHMARK_FIXES_PLAN.md`, which already contain
the exact code. This phase is bug-fixing, not redesign.

**Step 1.1 — Fix tool call leakage**
File: `src/portfolio_chat/pipeline/layer6_generate.py`

Move `visible_response = self._tool_executor.remove_tool_calls(response)` to run
unconditionally before the `if tool_calls:` branch. The exact change is specified in
`FIXES_PLAN.md` Fix 1 with a before/after diff.

**Step 1.2 — Fix false-positive blocking**
File: `src/portfolio_chat/pipeline/layer2_combined.py`

Replace `COMBINED_SYSTEM_PROMPT` with the expanded version from `BENCHMARK_FIXES_PLAN.md`
Issue 1, which adds 12 SAFE examples and tightens the `manipulation` definition. Also change
line 193 `is_safe = response.get("safe", False)` to `response.get("safe", True)` (fail-open).
Note: the current code at line 193 already reads `True` — confirm this is already in place
before editing.

**Step 1.3 — Fix contact flow over-triggering**
File: `src/portfolio_chat/tools/definitions.py`
File: `src/portfolio_chat/pipeline/layer6_generate.py`

Replace `get_tools_prompt_section()` with the tightened version from `FIXES_PLAN.md` Fix 2a.
Remove the IMPORTANT block at `_format_user_message()` lines ~197–202 (Fix 2b).
Confirm placeholder guards in `executor.py` `_handle_save_message()` are in place (Fix 2c).

**Step 1.4 — Enable streaming by default**
File: `src/portfolio_chat/server.py`

The server already has a streaming endpoint (`/chat/stream`) and `process_message_stream()` is
implemented. Check whether the frontend widget is calling the streaming endpoint. If it is
calling the non-streaming `/chat` endpoint, update the frontend to use SSE streaming. This is
the highest-impact latency change with zero risk to the pipeline.

File to check: confirm which endpoint the frontend JS calls. The Astro portfolio site at
`/home/kellogg/dev/portfolio/` likely has the chat widget JavaScript.

### Phase 2: Dead code removal

**Step 2.1 — Delete dead pipeline files**

The following files are not imported by `orchestrator_fast.py` (confirmed by reading imports)
and are not referenced by `server.py`:

- `src/portfolio_chat/pipeline/orchestrator.py` — `server.py` imports only `FastPipelineOrchestrator`
- `src/portfolio_chat/pipeline/layer2_jailbreak.py` — not imported by fast orchestrator
- `src/portfolio_chat/pipeline/layer3_intent.py` — partially; the `Intent` and `QuestionType`
  dataclasses are still imported by `layer2_combined.py` and `layer4_route.py`. Do NOT delete
  this file; only delete `Layer3IntentParser` class if the file needs slimming.
- `src/portfolio_chat/pipeline/layer7_revise.py` — not imported by fast orchestrator
- `src/portfolio_chat/pipeline/layer8_safety.py` — `Layer8SafetyChecker` is not used by fast
  path; `Layer8FastChecker` in `layer8_fast.py` is the active one

Before deleting, verify no test files import the dead modules directly (some unit tests do).
Tests for dead modules should be deleted alongside the modules.

**Step 2.2 — Update unit tests**

Tests in `tests/unit/` that test deleted modules must be removed:
- `test_layer2_jailbreak.py` — tests `Layer2JailbreakDetector`, delete if module is deleted
- `test_layer7_revise.py` — tests `Layer7Reviser`, delete if module is deleted
- `test_orchestrator.py` — currently tests `PipelineOrchestrator` (the slow path). Replace
  with tests for `FastPipelineOrchestrator` or update to test the new orchestrator.

### Phase 3: Classifier elimination (Approach A, behind feature flag)

This phase is gated on Phase 1 benchmark validation. Do not start until the false-positive
fixes are confirmed to work by re-running the benchmark suite.

**Step 3.1 — Expand L4 keyword routing for standalone use**

File: `src/portfolio_chat/pipeline/layer4_route.py`

L4 currently receives an `Intent` object from the classifier. Without the classifier,
`Layer4Router.route()` must accept a raw message string as its primary input. The keyword
matching in `route()` already uses `original_message` as a fallback. A new method signature:

```python
def route_from_message(self, message: str) -> Layer4Result:
    """Route directly from message text without a classifier-produced intent."""
```

This method would: run the keyword scan against `message`, check project names, check
contact phrases, check the `ALWAYS_OUT_OF_SCOPE` list. It returns a `Layer4Result` with a
synthetic `Intent` that has `topic="general"` and `question_type=AMBIGUOUS` when no keyword
wins, defaulting to `Domain.PROFESSIONAL`.

**Step 3.2 — Update orchestrator to skip classifier when flag is off**

File: `src/portfolio_chat/pipeline/orchestrator_fast.py`

Add a config branch: when `PIPELINE.USE_COMBINED_CLASSIFIER` is `false`, skip the
`layer2_combined.classify()` call entirely and call `layer4.route_from_message()` directly.

```python
if PIPELINE.USE_COMBINED_CLASSIFIER:
    combined_result = await self.layer2_combined.classify(...)
    # existing path
else:
    # No classifier: route from message directly
    l4_result = self.layer4.route_from_message(sanitized_message)
    # No intent object; domain is determined by keyword routing
```

**Step 3.3 — Validate against benchmark**

Run `tests/benchmark/engine.py` with `USE_COMBINED_CLASSIFIER=false`. The target metric is
zero legitimate questions routed to `OUT_OF_SCOPE` that should reach `PROFESSIONAL`, `PROJECTS`,
or `PHILOSOPHY`.

**Step 3.4 — Update L1 to catch hard jailbreak syntax**

File: `src/portfolio_chat/pipeline/layer1_sanitize.py`

When the classifier is removed, L1 becomes the sole pre-generation block for syntactic
jailbreaks. Review current L1 patterns. Add patterns for:
- `ignore (your|all|previous) instructions`
- `forget (your|all|previous) (instructions|rules|guidelines)`
- `you are now [A-Z]` (roleplay attack syntax)
- `pretend you (have no|are without) (restrictions|rules|guidelines)`

These are the same patterns the classifier catches but in regex form. They are narrow enough
to have no legitimate interpretations.

---

## Files Affected

### Phase 1 (modify)

| File | Change |
|------|--------|
| `src/portfolio_chat/pipeline/layer6_generate.py` | Move `remove_tool_calls()` outside `if tool_calls:` guard |
| `src/portfolio_chat/pipeline/layer2_combined.py` | Replace `COMBINED_SYSTEM_PROMPT`; confirm fail-open default |
| `src/portfolio_chat/tools/definitions.py` | Rewrite `get_tools_prompt_section()` |
| `src/portfolio_chat/pipeline/layer6_generate.py` | Remove overactive IMPORTANT block in `_format_user_message()` |
| `src/portfolio_chat/tools/executor.py` | Confirm placeholder/fabrication guards (may already be present) |

### Phase 2 (delete)

| File | Action |
|------|--------|
| `src/portfolio_chat/pipeline/orchestrator.py` | Delete (dead code, slow path) |
| `src/portfolio_chat/pipeline/layer2_jailbreak.py` | Delete (superseded by layer2_combined) |
| `src/portfolio_chat/pipeline/layer7_revise.py` | Delete (never executed on fast path) |
| `src/portfolio_chat/pipeline/layer8_safety.py` | Delete (superseded by layer8_fast) |
| `tests/unit/test_layer2_jailbreak.py` | Delete alongside module |
| `tests/unit/test_layer7_revise.py` | Delete alongside module |
| `tests/unit/test_orchestrator.py` | Replace with `test_orchestrator_fast.py` |

### Phase 3 (create/modify)

| File | Change |
|------|--------|
| `src/portfolio_chat/pipeline/layer4_route.py` | Add `route_from_message()` method |
| `src/portfolio_chat/pipeline/layer1_sanitize.py` | Add hard jailbreak syntax patterns |
| `src/portfolio_chat/pipeline/orchestrator_fast.py` | Add `USE_COMBINED_CLASSIFIER=false` branch |

---

## Security Maintenance With Fewer Layers

The concern is: if we remove the dedicated jailbreak classifier (Phase 3), does the system
remain zero-trust?

**What the classifier actually provides today:**
1. Blocks ~20 genuine jailbreak attempts per benchmark run (true positives)
2. Blocks ~280 legitimate queries (false positives — over 93% of all blocks)
3. Produces intent signals used by L4 routing (topic, question_type)

**What replaces each function:**

| Classifier function | Replacement |
|---------------------|-------------|
| Roleplay attack detection (`you are now DAN`) | L1 regex (narrow, zero false positives) |
| Instruction override (`ignore your instructions`) | L1 regex |
| Prompt extraction (`show me your system prompt`) | L1 regex + L6 system prompt refusal |
| Manipulation (hypothetical framing) | L6 built-in RLHF refusal behavior |
| Encoding tricks (base64 decode) | L1 regex |
| Intent routing signals | L4 keyword router (already strong) |

**What does not change:**
- Cloudflare WAF/DDoS protection at the edge (not part of this pipeline)
- L0 rate limiting
- L1 regex sanitization
- L5 spotlighting (untrusted user input wrapped in delimiters)
- L6 system prompt with explicit refusal instructions
- L8 fast pattern check on output (prompt leakage, private info, inappropriate content)
- All audit logging

The system was never zero-trust by virtue of the 3B classifier alone. It is zero-trust because
every input is treated as potentially hostile from L0 through L8, and the generator is
instructed to refuse adversarial requests. The classifier adds a layer of defense-in-depth but
its 93% false positive rate means it is currently doing more harm than good.

---

## Risks and Mitigations

### Risk 1 — Streaming buffering breaks L8 output safety
L8 must run on the complete response. The current `process_message_stream()` implementation
already handles this correctly (lines 488–507 of `orchestrator_fast.py`): it buffers all
chunks, runs L8, then either yields the original chunks or the fallback. This is the correct
approach. Do not change this. Confirm in code review that the streaming path matches this
description before enabling streaming in the frontend.

### Risk 2 — Removing classifier breaks L4 routing for ambiguous messages
Without the classifier's topic signal, L4 falls back to pure keyword matching. The L4 keyword
table has 100+ entries and handles most cases well. The risk is ambiguous messages with no
keywords that previously got classified as a specific topic. The mitigation is the
`USE_COMBINED_CLASSIFIER` feature flag — deploy Phase 3 to staging, run the benchmark, confirm
routing accuracy before cutting over in production.

### Risk 3 — Phase 2 deletion breaks tests that import dead modules
Several unit tests import from `layer2_jailbreak.py` and `orchestrator.py`. Deleting modules
without updating tests will break the test suite. Mitigation: delete test files alongside
their modules. Check `conftest.py` — it imports `Layer3IntentParser` at line 210, which would
break if `layer3_intent.py` is deleted. Do NOT delete `layer3_intent.py`; only the
`Layer3IntentParser` class is dead, but the `Intent`, `QuestionType`, and `EmotionalTone`
dataclasses in that file are still imported by `layer2_combined.py` and `layer4_route.py`.

### Risk 4 — Streaming endpoint not used by frontend
The streaming benefit is only realized if the chat widget connects to `/chat/stream` via SSE.
If the portfolio frontend uses the non-streaming `/chat` endpoint, the user experience does not
improve. Verify the frontend integration before claiming this latency win. The Astro site at
`/home/kellogg/dev/portfolio/` should be checked for the chat widget JS.

### Risk 5 — Tool call changes break the contact flow entirely
The `save_message_for_kellogg` tool is the only interactive feature. Over-tightening the tool
prompt could make the model never call it, even for clear contact intent. Mitigation: after
changing `definitions.py`, run the contact flow scenarios from the benchmark suite explicitly
(e.g., "Can I leave Kellogg a message? My name is Alice and I'd like him to know I'm interested
in hiring him."). Confirm the tool fires exactly once.

---

## Testing Strategy

### Phase 1 tests

After each fix, run targeted tests before moving to the next:

**Step 1.1 (tool leakage):**
- `tests/unit/test_layer6_generate.py` — add a test case where the LLM returns a malformed
  tool block (invalid JSON) and assert the visible response contains no raw `` ```tool_call` ``
  blocks.

**Step 1.2 (false positives):**
- Re-run `tests/benchmark/engine.py` targeting the 10 queries identified in
  `BENCHMARK_FIXES_PLAN.md` (skeptical, demanding, off-topic messages). Assert zero blocks.
- `tests/unit/test_layer2_jailbreak.py` is for the old `Layer2JailbreakDetector`; add a new
  `tests/unit/test_layer2_combined.py` with cases for each SAFE example in the new prompt.

**Step 1.3 (contact flow):**
- `tests/unit/test_tools.py` — add cases for placeholder message rejection
- Add integration test: user says "hi" followed by "tell him I'm interested" — assert tool NOT
  called on the first message, called on the second only if content is present.

**Step 1.4 (streaming):**
- `tests/integration/test_api.py` — add SSE test hitting `/chat/stream` and asserting tokens
  arrive incrementally before the full response is complete.

### Phase 2 tests

After deleting dead modules, run the full unit suite: `pytest tests/unit/ -x`. Any import
errors from deleted files must be resolved before proceeding.

### Phase 3 tests

- Run the full benchmark suite with `USE_COMBINED_CLASSIFIER=false`
- Key assertions:
  - Zero legitimate queries blocked at L1 that would previously have passed L2
  - Routing accuracy for `PROFESSIONAL`, `PROJECTS`, `PHILOSOPHY`, `META` domains within 5%
    of classifier-assisted baseline
  - `OUT_OF_SCOPE` accuracy: weather/password/cover-letter queries still correctly rejected

---

## Definition of Done

- [ ] Tool call leakage test passes: malformed `\`\`\`tool_call\`\`\`` blocks never reach users
- [ ] Benchmark re-run shows ≤10 false-positive blocks (down from ~280)
- [ ] Contact flow: `save_message_for_kellogg` tool fires on explicit contact intent and NOT on
      casual mentions of "tell him"
- [ ] Streaming endpoint verified functional end-to-end (server → cloudflare → browser widget)
- [ ] Dead code removed: `orchestrator.py`, `layer2_jailbreak.py`, `layer7_revise.py`,
      `layer8_safety.py` deleted and test suite passes
- [ ] p50 latency measured after streaming: time-to-first-token ≤1.5s in test environment
- [ ] Phase 3 (classifier removal) gated behind `USE_COMBINED_CLASSIFIER=false` flag, validated
      by benchmark before production cutover

---

## Confidence Assessment

**Phase 1 (fixes):** High confidence. Root causes are confirmed in existing plan documents.
Changes are small and targeted. The false-positive prompt fix is empirical — confidence is
"very likely better" not "guaranteed to zero."

**Phase 2 (dead code removal):** High confidence. Import graph confirms these files are not
used by the production path. Risk is only test suite breakage, which is mechanical to fix.

**Phase 3 (classifier removal):** Medium confidence. L4 keyword routing is strong but has not
been benchmarked in standalone mode. The `USE_COMBINED_CLASSIFIER` flag and benchmark gate are
the appropriate mitigations. Do not skip them.

---

## Unknowns and Assumptions Requiring Validation

1. **Frontend streaming status.** Is the chat widget JS using `/chat/stream` or `/chat`? This
   determines whether Phase 1 Step 1.4 is a frontend change or just a documentation note.
   Check `/home/kellogg/dev/portfolio/` for the widget implementation.

2. **Current false-positive count after recent prompt changes.** `BENCHMARK_FIXES_PLAN.md`
   reports 280 false positives from a historical benchmark. The current `layer2_combined.py`
   already has an updated `COMBINED_SYSTEM_PROMPT` with a `NEVER BLOCK` section and 14 SAFE
   examples. The benchmark may have improved since that document was written. Re-run the
   benchmark before assuming the 280 number is current.

3. **qwen2.5:3b vs qwen2.5:0.5b classifier latency.** The plan assumes 500ms–2s for
   `qwen2.5:3b`. If the actual p50 classifier time is closer to 500ms, Approach A's latency
   win shrinks. Run `pytest tests/benchmark/engine.py` with timing enabled to get actual
   per-layer timing data.

4. **Streaming SSE buffering at Cloudflare.** Cloudflare Tunnel may buffer SSE responses before
   sending to the client, negating the streaming UX benefit. Test streaming end-to-end through
   the tunnel, not just against localhost:8000.
