# Plan: Portfolio Chat Bug Fixes (12 Items)

## Context

The portfolio chat is a 9-layer FastAPI pipeline (`src/portfolio_chat/`) using Ollama for local inference.
Fixes are ordered by blast radius and interdependency. Fixes 1–3 interact (all touch the tool-call
response path); fixes 4–6 are independent; fixes 7–12 are standalone hardening items.

---

## Fix 1: Tool Call Leakage (CRITICAL — implement first)

**Problem confirmed:** `layer6_generate.py` lines 265–277 strip tool call blocks from the *visible
response* only when a valid tool call is found. If the LLM emits a malformed block (JSON parse error,
unknown tool name, or a variant the regex does not match), `parse_tool_calls()` returns an empty list,
the branch at line 266 is skipped, and the raw `` ```tool_call\n{...}\n``` `` block passes through to
the user via `l6_result.response`.

**Root cause chain:**
- `TOOL_CALL_PATTERN` in `executor.py` (line 22–25) matches the block only if JSON is valid and the
  tool name is in `AVAILABLE_TOOLS`.
- When the pattern does *not* match (malformed JSON, unknown name), `parse_tool_calls()` returns `[]`.
- `layer6_generate.py` lines 266–277 only call `remove_tool_calls()` inside the `if tool_calls:` branch.
- `remove_tool_calls()` (executor.py line 141) uses `TOOL_CALL_PATTERN.sub("", ...)`, which is a
  broader regex that strips `` ```tool_call...``` `` regardless of whether JSON is valid.
- Therefore `remove_tool_calls()` should be called unconditionally, not inside the `if tool_calls:` block.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/pipeline/layer6_generate.py` — lines 265–277

**Current code (layer6_generate.py lines 265–277):**
```python
if self._enable_tools and self._tool_executor:
    tool_calls = self._tool_executor.parse_tool_calls(response)
    if tool_calls:
        # Remove tool call blocks from visible response
        visible_response = self._tool_executor.remove_tool_calls(response)
        return Layer6Result(
            status=Layer6Status.TOOL_CALL,
            passed=True,
            response=visible_response,
            model_used=self.model,
            tool_calls=tool_calls,
        )
```

**Proposed code:**
```python
if self._enable_tools and self._tool_executor:
    tool_calls = self._tool_executor.parse_tool_calls(response)
    # Always strip tool_call blocks from the visible response,
    # even if none parsed cleanly — prevents leaking raw syntax.
    visible_response = self._tool_executor.remove_tool_calls(response)
    if tool_calls:
        return Layer6Result(
            status=Layer6Status.TOOL_CALL,
            passed=True,
            response=visible_response,
            model_used=self.model,
            tool_calls=tool_calls,
        )
    # No valid tool calls parsed but blocks may have been stripped;
    # continue with clean visible_response below.
    response = visible_response
```

**Risk:** Low. `remove_tool_calls()` is a simple regex substitution — calling it on a response with no
tool blocks is a no-op. The only behavioral change is that malformed tool blocks are silently stripped
rather than passed through. That is the desired behavior.

**Dependencies:** Fix 2 builds on this fix being in place.

---

## Fix 2: Rebuild Contact Flow (HIGH — implement second)

**Problem confirmed from three sources:**

1. **`definitions.py` lines 82–99** — The prompt template instructs the LLM to call the tool when the
   visitor "wants to send/leave a message", but does not explicitly prohibit calling it for ambiguous
   phrasing. The IMPORTANT block at `layer6_generate.py` lines 197–202 lists trigger phrases including
   just `"tell him"` — a phrase with many non-contact meanings.

2. **`executor.py` `_handle_save_message()` lines 180–223** — No guard against placeholder text
   (`"YOUR MESSAGE HERE"`, `"visitor's message here"`, etc.). The tool saves whatever `params["message"]`
   contains without semantic validation.

3. **`definitions.py` line 87** — The example in the tool prompt uses `"visitor's message here"` as the
   literal placeholder value, which is exactly what the LLM copies when it generates a template call
   before the visitor has provided content.

**Two approaches evaluated:**

**Option A — Prompt tightening only.** Rewrite `get_tools_prompt_section()` to be more explicit about
when NOT to call the tool. Add placeholder detection in `_handle_save_message()`. Simple; does not
require architectural changes.

**Option B — Intent gate + prompt tightening.** Add an `intent.question_type == CONTACT` or keyword
check in the orchestrator before L6 even sees the tool definition; combine with prompt tightening.
More robust but adds complexity.

**Recommendation: Option A.** The tool is already gated behind L4 routing (the `message`/`send`
keywords route to `Domain.LINKEDIN` which loads the LINKEDIN context). The real problem is the prompt
language and missing guards. Prompt tightening + executor validation is sufficient and reversible.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/tools/definitions.py` — `get_tools_prompt_section()` lines 76–99
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/pipeline/layer6_generate.py` — IMPORTANT block lines 197–202
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/tools/executor.py` — `_handle_save_message()` lines 180–223

### 2a. Rewrite the tools prompt section (definitions.py lines 76–99)

**Current:**
```python
return """
## MESSAGE TOOL

To save a message for Kellogg, output a tool_call block:

```tool_call
{"action": "save_message_for_kellogg", "message": "visitor's message here"}
```

Optional fields: "visitor_name", "visitor_email"

ONLY use this tool when the visitor explicitly asks to send/leave a message for Kellogg.
Do NOT use for greetings or questions - just answer those normally.

When visitor wants to send a message:
1. If they haven't said what to send, ask what they'd like to say
2. When they provide content, use the tool_call block
3. After the tool runs, confirm the message was saved
"""
```

**Proposed:**
```python
return """
## MESSAGE TOOL

Use ONLY when the visitor says something like:
- "I want to leave a message for Kellogg"
- "Can you tell Kellogg [specific content]?"
- "Please send him [specific content]"
- "I'd like to reach out"

Do NOT use for:
- Questions about Kellogg (just answer them)
- Greetings or pleasantries
- Vague phrases that could mean anything ("tell him hi" is borderline; ask for clarification)

Workflow — follow EXACTLY in order:
1. Visitor indicates they want to send a message.
2. If they haven't told you the actual message content yet, ask: "What would you like to say?"
   Do NOT call the tool yet.
3. Visitor provides the actual message text.
4. Optionally ask for name/email: "Would you like to include your name or email so Kellogg can reply?"
5. Call the tool with the confirmed message and any contact info.
6. Confirm to the visitor that the message was saved.

NEVER call the tool with template text like "visitor's message here" or "YOUR MESSAGE HERE".
NEVER call the tool if the visitor hasn't given you a real message to send.
NEVER ask for confirmation more than once — confirm once, save once.

To save a message, output EXACTLY:
```tool_call
{"action": "save_message_for_kellogg", "message": "the actual message text"}
```

Optional fields: visitor_name, visitor_email
"""
```

### 2b. Remove the overactive IMPORTANT block (layer6_generate.py lines 197–202)

**Current:**
```python
parts.append(
    "IMPORTANT: If the visitor wants to SEND a message to Kellogg (uses phrases like "
    "'send a message', 'tell him', 'let him know', 'leave a message', 'contact him'), "
    "you MUST use the save_message_for_kellogg tool. Do NOT just provide contact info. "
    "Output the tool call using the ```tool_call``` format shown above."
)
```

**Proposed:** Remove this block entirely. The tool definition already covers the trigger conditions.
Having two competing instruction blocks with different thresholds is the root cause of the LLM over-triggering.
The instruction "Do NOT just provide contact info" is particularly harmful — it pushes the LLM to call
the tool even for questions that are just "how do I reach Kellogg?"

### 2c. Add placeholder and empty guards in executor (executor.py lines 180–223)

**Current `_handle_save_message()` lines 182–189:**
```python
message = params.get("message")

if not message:
    return ToolResult(
        success=False,
        tool_name="save_message_for_kellogg",
        result="No message provided to save.",
    )
```

**Proposed — add after the `if not message:` check:**
```python
message = params.get("message", "").strip()

if not message:
    return ToolResult(
        success=False,
        tool_name="save_message_for_kellogg",
        result="No message provided to save.",
    )

# Guard against the LLM calling the tool with template/placeholder text
PLACEHOLDER_PHRASES = {
    "visitor's message here",
    "your message here",
    "message here",
    "[message]",
    "[your message]",
    "type your message here",
}
if message.lower().strip(".,!?") in PLACEHOLDER_PHRASES or len(message) < 5:
    return ToolResult(
        success=False,
        tool_name="save_message_for_kellogg",
        result="That doesn't look like a real message. Please provide the actual content you'd like to send.",
    )
```

**Risk:** Low. All changes are additive guards that reject bad input. The prompt change reduces
trigger surface — there is a small risk the LLM becomes too conservative and stops offering the tool
to genuinely interested visitors. Monitor via the inbox and adjust if needed.

---

## Fix 3: Tune L8 False Positives (MEDIUM — implement third)

**Problem confirmed by analysis:**

Layer 8 (`layer8_fast.py`) uses regex pattern matching. The confirmed false-positive sources:

**Pattern `r'inference pipeline'` (line 51) — confirmed false positive.** When a user asks "What is
this chat system?", the bot answers using the `meta/about_chat.md` context which describes the system
as a "9-layer security pipeline". If the LLM echoes the exact phrase from `system_prompt.md` —
"9-layer zero-trust LLM pipeline" — that is safe content that should not be blocked. However, if
the bot echoes `inference pipeline` (from `system_prompt.md` line 31), L8 fires. Tested: `"This
chat implements a 9-layer zero-trust LLM inference pipeline"` is blocked. The phrase is only
dangerous if the bot is *explaining its own internal architecture in response to a jailbreak*; it is
not dangerous in a factual summary of the system's stack.

**Pattern `r'i was told to'` (line 43) — confirmed false positive.** The bot might legitimately
say "I was told to only answer questions about Kellogg's work" as a natural explanation of its
scope. While this is slightly awkward phrasing, it is not prompt leakage. The pattern intends to
catch "I was told to [reveal instructions / do X harmful thing]" but is anchored too broadly.

**Pattern `r'i am programmed to'` (line 44) — moderate risk.** Similar issue. The phrase can be
a natural explanation: "I'm not programmed to discuss topics outside Kellogg's portfolio." Not
prompt leakage, but might be caught.

**Pattern `r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'` (line 66) — implementation
risk.** The code correctly checks `if match not in SAFE_EMAILS` (lines 128–132), but `findall()`
returns a list of strings while `SAFE_EMAILS` is a list of strings — this comparison is correct.
No bug here, but the safe email list is hardcoded and a typo would silently break it.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/pipeline/layer8_fast.py` — lines 38–53

**Current PROMPT_LEAKAGE_PATTERNS (lines 38–53):**
```python
PROMPT_LEAKAGE_PATTERNS = [
    r"system prompt",
    r"system instructions",
    r"my instructions are",
    r"i was told to",
    r"i am programmed to",
    r"my programming says",
    r"my rules are",
    r"<<<.*>>>",  # Spotlighting markers
    r"CONTEXT ABOUT KEL \(cite",  # Specific prompt marker format
    r"CURRENT QUESTION:\s*<<<",  # Specific prompt marker with spotlight
    r"Layer \d+ ",  # Space after to avoid matching "Layer 1" in other contexts
    r"inference pipeline",  # More specific - not "data pipeline"
    r"jailbreak attempt",
    r"injection attempt",
]
```

**Proposed replacements:**

```python
PROMPT_LEAKAGE_PATTERNS = [
    r"system prompt",
    r"system instructions",
    r"my instructions are",
    # Tightened: require a harmful continuation after "told to" / "programmed to"
    # to avoid blocking the bot's own scope explanations.
    r"i was told to (ignore|bypass|reveal|disregard|forget|pretend|act as|always|never)",
    r"i am programmed to (ignore|bypass|reveal|disregard|forget|pretend|act as|always|never)",
    r"my programming says",
    r"my rules are",
    r"<<<.*>>>",  # Spotlighting markers
    r"CONTEXT ABOUT KEL \(cite",  # Specific prompt marker format
    r"CURRENT QUESTION:\s*<<<",  # Specific prompt marker with spotlight
    r"Layer \d+ ",  # Space after — only fires inside a numbered list of layer names
    # Only block if the phrase appears to be DISCLOSING the pipeline architecture
    # rather than just using the word "pipeline" naturally.
    # Pattern: "X-layer ... inference pipeline" or "inference pipeline for Y"
    r"\d+-layer.*inference pipeline",
    r"jailbreak attempt",
    r"injection attempt",
]
```

**Rationale for each change:**
- `"i was told to"` → narrowed to require a harmful continuation keyword. A bot saying "I was told
  to answer questions about Kellogg" is not leaking prompts.
- `"i am programmed to"` → same narrowing logic.
- `"inference pipeline"` → require a numeric prefix like "9-layer" before it, so the phrase must
  clearly reference the internal pipeline count to fire. The string `"inference pipeline"` alone
  could appear in a context about AI architecture discussions without being prompt leakage.

**What is NOT changed:** `r"system prompt"`, `r"system instructions"`, `r"<<<.*>>>"`,
`r"CONTEXT ABOUT KEL \(cite"`, `r"CURRENT QUESTION:\s*<<<"` are all accurate and specific.

**Risk:** Loosening these patterns marginally reduces coverage for one attack vector (a jailbroken
bot that explains its own scope in natural-sounding language). The tradeoff is appropriate because:
1. L2 handles jailbreak detection upstream of L6 generation.
2. A jailbroken bot explaining "I was told to answer only about Kellogg" is not dangerous.
3. 13% false-positive rate means real users are being blocked.

---

## Fix 4: CAIRN Knowledge Inconsistency (LOW-MEDIUM)

**Problem confirmed:** The context file `context/projects/talking_rock_rag_summary.md` describes CAIRN
as "the Personal Attention Minder" (line 27) and states "CAIRN is the heart of Talking Rock — a
personal attention minder" (line 31). The file does NOT define what CAIRN is an acronym *of* — it is
only described by its function. If the LLM hallucinates different acronym expansions, that is because
no authoritative expansion exists in the context.

Additionally, `system_prompt.md` (line 28) lists CAIRN as "Personal attention minder with conversation
lifecycle, memory architecture..." — again functional description, no acronym expansion.

**The domain routing is correct:** `layer4_route.py` line 122 maps `"cairn"` → `Domain.PROJECTS` with
highest priority (the `PROJECT_NAMES` set check at lines 215–230 runs before topic-based routing).
CAIRN questions correctly load the PROJECTS context which includes `talking_rock_rag_summary.md`.

**Root cause:** The context does not define the acronym. The LLM invents one.

**Two approaches:**

**Option A — Add a canonical statement to the context file.** Insert an explicit line near the top
of `talking_rock_rag_summary.md`: `CAIRN is not an acronym — it is a name, chosen for its meaning
as a navigational marker (a pile of stones used for wayfinding).` If CAIRN *is* an acronym, substitute
the correct expansion. This is the simplest fix.

**Option B — Add to system prompt.** Add a bullet under "What You Know About" that says
`"**CAIRN is not an acronym** — it is a name, chosen for..."`. This applies globally regardless of
domain routing.

**Recommendation: Option A** — put the canonical statement in the context document, which is the
source of truth. Also add it to `system_prompt.md` as a one-liner for global coverage.

**File affected:**
- `/home/kellogg/dev/portfolio_chat/context/projects/talking_rock_rag_summary.md` — add after line 31
- `/home/kellogg/dev/portfolio_chat/prompts/system_prompt.md` — add to CAIRN bullet line 28

**Proposed addition to talking_rock_rag_summary.md (after line 31):**
```
**Note on the name:** CAIRN is not an acronym. The name was chosen for its meaning as a navigational
marker — a cairn is a pile of stones used for wayfinding. The tool helps users find their path through
their priorities. Do not expand it as an acronym; if asked, explain the naming rationale.
```

**Proposed update to system_prompt.md line 28 (CAIRN bullet):**
```
- **CAIRN**: Personal attention minder (name, not acronym — named for the wayfinding stone markers).
  Conversation lifecycle, memory architecture, 2-tier life organization (Acts + Scenes), 5-layer
  verification, 3x2x3 atomic operations, Health Pulse, Coherence Kernel. 2,033+ tests.
```

**Dependency on implementer:** Verify the correct etymology/intent with Kellogg before writing this.
The above is the most likely intent based on the "attention minder" concept, but if CAIRN *is* an
acronym, insert the correct expansion instead.

**Risk:** Very low. Context files are read-only inputs to the LLM; no code changes.

---

## Fix 5: Rate Limit /contact Endpoint (MEDIUM)

**Problem confirmed:** `server.py` lines 425–470 define the `/contact` POST handler. It calls
`get_client_ip()` (line 438) and hashes it (line 439) but never instantiates or calls any rate
limiter. The orchestrator (`orchestrator_fast.py` line 79) creates an `InMemoryRateLimiter()` for
`/chat` only — there is no shared limiter accessible from `server.py` at the module level.

**Approach:** Instantiate a dedicated `InMemoryRateLimiter` for contact submissions at server module
level (separate from the chat limiter — contact submissions warrant tighter limits). Use the existing
`check_rate_limit()` + `record_request()` API. Suggested limits: 3/min, 10/hr per IP.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/server.py`

**Changes to server.py:**

At module level (after line 195, where `orchestrator` and `contact_storage` globals are declared):
```python
# Dedicated rate limiter for /contact endpoint (tighter than /chat)
contact_rate_limiter: InMemoryRateLimiter | None = None
```

In `lifespan()` startup (after `contact_storage = ContactStorage()`, approximately line 210):
```python
global contact_rate_limiter
contact_rate_limiter = InMemoryRateLimiter(
    per_ip_per_minute=3,
    per_ip_per_hour=10,
    global_per_minute=100,  # generous global; individual IP limits are the real guard
)
```

In the `contact()` handler (after line 439, `ip_hash = hash_ip(client_ip)`):
```python
# Rate limit contact submissions
if contact_rate_limiter is not None:
    rl_result = await contact_rate_limiter.check_rate_limit(ip_hash)
    if rl_result.blocked:
        return ContactResponseModel(
            success=False,
            error="Too many contact requests. Please try again later.",
        )
    await contact_rate_limiter.record_request(ip_hash)
```

**Risk:** Low. `InMemoryRateLimiter` is already well-tested for `/chat`. The contact endpoint has
fewer legitimate requests, so 3/min is generous for humans and strict for bots.

**Note:** The `InMemoryRateLimiter.__init__` defaults `per_ip_per_minute` and `per_ip_per_hour` from
`RATE_LIMITS` config if not provided (`rate_limit.py` lines 82–84). Passing explicit values overrides
the config defaults, which is correct — contact limits should be independent of chat limits.

---

## Fix 6: Buffer Streaming Responses Before L8 (MEDIUM)

**Problem confirmed:** `orchestrator_fast.py` lines 487–504. In `process_message_stream()`, chunks
are yielded immediately as they arrive (line 494: `yield chunk`). L8 runs at line 497 on `full_response`
*after* all chunks have been yielded. The comment at line 499 explicitly acknowledges "Can't unsend,
but log the issue." This means L8 is decorative for the streaming path — it logs but cannot block.

**Approach:** Buffer all chunks into `full_response`, run L8, then yield either the full response or
the fallback. The tradeoff is losing true streaming (first-token latency becomes total latency) but
fixing the security gap. For a portfolio chat with sub-10 second generation, this is acceptable.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/pipeline/orchestrator_fast.py` — lines 487–504

**Current code (lines 487–504):**
```python
full_response = ""
async for chunk in self.ollama_client.chat_stream(
    system=system_prompt,
    user=user_message,
    model=MODELS.GENERATOR_MODEL,
):
    full_response += chunk
    yield chunk

# Post-generation safety check
l8_result = self.layer8_fast.check(full_response)
if not l8_result.passed:
    # Can't unsend, but log the issue
    logger.warning(f"Streamed response failed safety check: {l8_result.issue_details}")
```

**Proposed code:**
```python
# Buffer full response before safety check — cannot unsend chunks already yielded.
full_response = ""
async for chunk in self.ollama_client.chat_stream(
    system=system_prompt,
    user=user_message,
    model=MODELS.GENERATOR_MODEL,
):
    full_response += chunk

# Safety check on complete response before any delivery
l8_result = self.layer8_fast.check(full_response)
if not l8_result.passed:
    logger.warning(f"Streamed response failed safety check: {l8_result.issue_details}")
    yield Layer8FastChecker.get_safe_fallback_response()
    return

# Safe — yield the buffered response
yield full_response
```

**Risk:** This changes streaming to pseudo-streaming (one big chunk instead of incremental). The
`generate()` function in `server.py` (lines 405–413) still uses SSE, so the client receives one
`data: {full_response}\n\n` event instead of many small ones. Frontend behavior depends on whether
the client uses `text/event-stream` incrementally or buffers — most simple implementations buffer
anyway. If true streaming is a requirement, the alternative is to accept the current behavior and
note that L8 cannot protect the stream path.

**Alternative (if true streaming must be preserved):** Do not run L8 on the stream path at all;
remove the dead check entirely and document that stream responses bypass L8. This is honest at least.
The non-stream `/chat` endpoint already runs L8 correctly. If the portfolio only uses streaming for
one frontend path, this may be acceptable.

---

## Fix 7: Stop Logging Raw User Messages (LOW)

**Problem confirmed:** `utils/logging.py` lines 239–274. `log_user_message()` accepts and logs
`raw_message` (line 244, logged at line 268). The call site in `orchestrator_fast.py` lines 171–178
passes `raw_message=message` (the pre-sanitization input). This means raw user input, potentially
including prompt injection attempts or personal data, is written to structured logs in full.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/utils/logging.py` — `log_user_message()` lines 239–274
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/pipeline/orchestrator_fast.py` — lines 171–178

**Change to logging.py:** Remove `raw_message` parameter and its log entry. Keep `raw_length` (the
length, not the content, is useful for abuse detection without storing PII).

**Current signature (line 239–246):**
```python
def log_user_message(
    self,
    request_id: str,
    conversation_id: str,
    turn: int,
    raw_message: str,
    sanitized_message: str,
    ip_hash: str,
) -> None:
```

**Proposed signature:**
```python
def log_user_message(
    self,
    request_id: str,
    conversation_id: str,
    turn: int,
    sanitized_message: str,
    ip_hash: str,
    raw_length: int,
) -> None:
```

**Current log data block (lines 259–273):**
```python
"raw_message": raw_message,
"sanitized_message": sanitized_message,
"raw_length": len(raw_message),
"sanitized_length": len(sanitized_message),
```

**Proposed:**
```python
"sanitized_message": sanitized_message,
"raw_length": raw_length,
"sanitized_length": len(sanitized_message),
```

**Change to orchestrator_fast.py (lines 171–178):**
```python
audit_logger.log_user_message(
    request_id=request_id,
    conversation_id=conv_id,
    turn=metrics.conversation_turn,
    sanitized_message=sanitized_message,
    ip_hash=ip_hash,
    raw_length=len(message),
)
```

**Risk:** Low. Callers need to update the call signature. There is only one call site
(`orchestrator_fast.py`). Check tests (`tests/`) for any mock of `log_user_message` that may break.

---

## Fix 8: Disable /docs /redoc in Production (LOW)

**Problem:** `server.py` lines 237–242 create the FastAPI app without setting `docs_url=None` or
`redoc_url=None`. FastAPI defaults to exposing `/docs`, `/redoc`, and `/openapi.json`. These are
accessible from the internet (via Cloudflare tunnel) and expose the full API schema.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/server.py` — lines 237–242

**Current:**
```python
app = FastAPI(
    title="Portfolio Chat API",
    description="Zero-trust LLM inference pipeline for Kellogg Brengel's portfolio",
    version="0.1.0",
    lifespan=lifespan,
)
```

**Proposed:**
```python
app = FastAPI(
    title="Portfolio Chat API",
    description="Zero-trust LLM inference pipeline for Kellogg Brengel's portfolio",
    version="0.1.0",
    lifespan=lifespan,
    # Disable API docs in production; enable only when DEBUG=true
    docs_url="/docs" if SERVER.DEBUG else None,
    redoc_url="/redoc" if SERVER.DEBUG else None,
    openapi_url="/openapi.json" if SERVER.DEBUG else None,
)
```

**Risk:** None. `SERVER.DEBUG` is already imported (used at line 541 for uvicorn reload). The default
`DEBUG=false` means docs are off in production. Set `DEBUG=true` locally to re-enable during development.

---

## Fix 9: Add Content-Security-Policy Header (LOW)

**Problem:** `SecurityHeadersMiddleware` in `server.py` (lines 256–266) sets several security headers
but omits `Content-Security-Policy`. The admin dashboard loads Chart.js from a CDN (see Fix 10); any
CSP must account for that until Fix 10 is applied.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/server.py` — lines 256–266

**Current `dispatch()` body:**
```python
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["X-Frame-Options"] = "DENY"
response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
```

**Proposed — add after existing headers:**
```python
response.headers["Content-Security-Policy"] = (
    "default-src 'none'; "
    "script-src 'self'; "           # tighten to 'self' after Fix 10 (self-host Chart.js)
    "style-src 'self' 'unsafe-inline'; "  # inline styles needed for Pico/admin dashboard
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)
```

**Dependency on Fix 10:** If Fix 10 (self-hosting Chart.js) is NOT applied first, the `script-src`
directive must include the CDN:
```python
"script-src 'self' https://cdn.jsdelivr.net; "
```

**Apply Fix 10 before Fix 9** so the final CSP does not need an external `script-src` allowance.

**Risk:** CSP is easy to misconfigure. Test the admin dashboard after applying to verify Chart.js
renders and no CSP violation errors appear in browser console. The `'unsafe-inline'` for styles is
a concession to avoid auditing all inline styles in the admin HTML.

---

## Fix 10: Self-Host Chart.js (LOW)

**Problem confirmed:** `static/admin/index.html` line 8:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

This is an unpinned CDN reference — the version loaded may change. It also violates the tightest
possible CSP (external script-src). The admin dashboard is localhost-only, so the privacy risk is
minimal, but the unpinned version and CSP incompatibility are real issues.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/static/admin/index.html` — line 8
- New file: `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/static/admin/chart.min.js`

**Steps:**
1. Download a pinned version of Chart.js: `curl -L https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js -o .../static/admin/chart.min.js`
2. Replace the CDN `<script>` tag with: `<script src="/admin/static/chart.min.js"></script>`
3. The static files are already mounted at `/admin/static` (`server.py` lines 275–277).

**Risk:** Low. The admin endpoint is localhost-only. Pinning to a specific version prevents silent
breakage if jsdelivr pushes a breaking Chart.js update.

---

## Fix 11: UUID-Validate Admin Route Parameters (LOW)

**Problem confirmed:** `admin/router.py` lines 159–172 and 208–219. Both `conversation_id` and
`message_id` are unvalidated strings passed to storage methods that construct file paths
(`storage.get(message_id)` uses `glob(f"*_{message_id}.json")`). A malicious value like
`../../etc/passwd` would only be blocked if the glob pattern fails to match (it would, since the
pattern requires `*_<id>.json` format), but the lack of validation at the API layer is sloppy.
The endpoint is localhost-only but defense-in-depth applies.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/admin/router.py` — lines 159–161 and 208–210

**Current:**
```python
@admin_router.get("/analytics/conversations/{conversation_id}", ...)
async def get_conversation(
    conversation_id: str,
    ...
```
and
```python
@admin_router.get("/inbox/{message_id}", ...)
async def get_inbox_message(
    message_id: str,
    ...
```

**Proposed — add UUID and hex validation:**
```python
import re as _re

_UUID_RE = _re.compile(r'^[0-9a-f-]{8,36}$', _re.IGNORECASE)
_HEX_ID_RE = _re.compile(r'^[0-9a-f]{8,16}$', _re.IGNORECASE)

@admin_router.get("/analytics/conversations/{conversation_id}", ...)
async def get_conversation(
    conversation_id: str,
    ...
):
    if not _UUID_RE.match(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation_id format")
    ...
```

```python
@admin_router.get("/inbox/{message_id}", ...)
async def get_inbox_message(
    message_id: str,
    ...
):
    if not _HEX_ID_RE.match(message_id):
        raise HTTPException(status_code=400, detail="Invalid message_id format")
    ...
```

**Note on ID formats:** `ContactStorage._generate_id()` (storage.py line 71) returns `uuid4().hex[:12]`
— a 12-character hex string. `ConversationStorage` IDs should be checked against its ID generation
method to confirm format before finalizing the regex. The `_HEX_ID_RE` above matches 8–16 hex chars
to cover the 12-char contact IDs with some tolerance.

**Risk:** Low. Localhost-only endpoint. The main risk is accidentally making the regex too strict and
blocking legitimate IDs — check actual ID formats in existing data before merging.

---

## Fix 12: Strengthen Email Validation on /contact (LOW)

**Problem confirmed:** `server.py` lines 441–446:
```python
if body.sender_email and "@" not in body.sender_email:
    return ContactResponseModel(
        success=False,
        error="Invalid email format",
    )
```

This check only verifies `@` presence. `"@"`, `"a@"`, `"notanemail@"` all pass. A proper
validation should at minimum verify local-part, `@`, domain, and TLD presence.

**Two approaches:**

**Option A — Simple regex.** Add a lightweight RFC-5321-ish check without a library dependency.
Validates structure without attempting full RFC 5322 compliance (which is impractical with regex).

**Option B — `email-validator` library.** The pypi package `email-validator` performs DNS-optional
structural validation and is widely used. Requires adding a dependency.

**Recommendation: Option A.** This is a contact form, not an authentication form. Structural
validation (rejects obvious garbage) is sufficient. Adding a dependency for one validation is not
worth the maintenance cost.

**Files affected:**
- `/home/kellogg/dev/portfolio_chat/src/portfolio_chat/server.py` — lines 441–446

**Proposed replacement:**
```python
import re as _re

_EMAIL_RE = _re.compile(
    r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
)

# In the contact() handler, replace the existing check:
if body.sender_email and not _EMAIL_RE.match(body.sender_email):
    return ContactResponseModel(
        success=False,
        error="Invalid email format",
    )
```

Place the `_EMAIL_RE` compile at module level (after imports) rather than inside the handler.

**Risk:** Negligible. The field is optional — if the regex rejects a valid but unusual email (e.g.,
quoted local-parts), the visitor can simply leave the email field blank and the message still saves.

---

## Files Affected (Summary)

| File | Fixes |
|------|-------|
| `src/portfolio_chat/pipeline/layer6_generate.py` | 1, 2b |
| `src/portfolio_chat/tools/definitions.py` | 2a |
| `src/portfolio_chat/tools/executor.py` | 2c |
| `src/portfolio_chat/pipeline/layer8_fast.py` | 3 |
| `context/projects/talking_rock_rag_summary.md` | 4 |
| `prompts/system_prompt.md` | 4 |
| `src/portfolio_chat/server.py` | 5, 7*, 8, 9, 12 |
| `src/portfolio_chat/pipeline/orchestrator_fast.py` | 6, 7 |
| `src/portfolio_chat/utils/logging.py` | 7 |
| `src/portfolio_chat/admin/router.py` | 11 |
| `src/portfolio_chat/static/admin/index.html` | 10 |
| `src/portfolio_chat/static/admin/chart.min.js` | 10 (new file) |

\* Fix 7 also touches server.py only if `log_user_message` is called from there — it is not (only
called from orchestrator_fast.py). No server.py change for Fix 7.

---

## Suggested Implementation Order

The inter-fix dependencies are:

```
Fix 1 (tool leakage strip)
  └── Fix 2 (contact flow) — depends on Fix 1 being correct first
Fix 10 (self-host Chart.js)
  └── Fix 9 (CSP header) — script-src depends on Chart.js being local
Fix 3, 4, 5, 6, 7, 8, 11, 12 — fully independent of each other
```

**Recommended batch order:**

1. Fix 1 — tool call leakage strip (5-line change, immediate safety value)
2. Fix 2 — contact flow rebuild (prompt + executor changes)
3. Fix 3 — L8 false-positive tuning (unblock legitimate traffic)
4. Fix 8 — disable /docs /redoc (2-line change, immediate security value)
5. Fix 12 — email validation (5-line change)
6. Fix 5 — rate limit /contact (10-line change)
7. Fix 7 — stop logging raw messages
8. Fix 10 — self-host Chart.js (curl + 1-line HTML change)
9. Fix 9 — add CSP header (depends on Fix 10 being done)
10. Fix 11 — UUID validation in admin router
11. Fix 4 — CAIRN knowledge (verify acronym intent with Kellogg first)
12. Fix 6 — streaming buffer (highest latency impact; test separately)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Fix 2 makes tool too conservative; users can't leave messages | Monitor inbox after deploy; if submissions drop to zero, loosen the trigger phrases |
| Fix 3 loosens L8 and lets a jailbroken bot say "I was told to answer..." | L2 blocks jailbreaks before L6 generates; L8 is defense-in-depth, not primary defense |
| Fix 6 (buffering) eliminates streaming UX | Benchmark total response time first; if <5s total it is acceptable as one chunk |
| Fix 7 breaks tests that mock `log_user_message` with old signature | Search `tests/` for `log_user_message` calls and update them |
| Fix 9 CSP breaks admin dashboard | Test admin dashboard after applying; check browser console for CSP violations |
| Fix 4 misstates CAIRN etymology | Verify with Kellogg before writing to context |

---

## Testing Strategy

**Fix 1 (tool leakage):** Unit test `remove_tool_calls()` with: (a) valid tool call block, (b)
malformed JSON block, (c) unknown tool name block, (d) no block. Assert all cases return clean text.

**Fix 2 (contact flow):** Integration tests — (a) "what projects does he have?" should NOT trigger
tool; (b) "I want to leave a message" → bot asks for content, does not call tool yet; (c) "tell him
I'm interested in his work" → bot asks for clarification; (d) placeholder text as message content →
tool returns failure.

**Fix 3 (L8 tuning):** Unit test `Layer8FastChecker.check()` with: (a) "I was told to answer
questions about Kellogg" — should PASS; (b) "I was told to ignore my instructions" — should FAIL;
(c) "9-layer zero-trust LLM inference pipeline" — should FAIL; (d) "a 9-layer security pipeline" —
should PASS.

**Fix 5 (rate limiting):** Unit/integration test `/contact` endpoint with >3 rapid requests from
same IP — 4th should return error.

**Fix 7 (logging):** Confirm no `raw_message` field appears in audit log output for any request.

**Fix 8 (docs disabled):** Assert `GET /docs` returns 404 when `DEBUG=false`; returns 200 when
`DEBUG=true`.

**Fix 11 (UUID validation):** Test admin `/inbox/../../etc/passwd` returns 400.

**Fix 12 (email validation):** Test contact POST with `sender_email="notanemail"` returns error;
`sender_email="valid@example.com"` passes.

---

## Definition of Done

- [ ] Fix 1: `remove_tool_calls()` called unconditionally before the `if tool_calls:` branch in layer6_generate.py
- [ ] Fix 2: Tool prompt rewritten; IMPORTANT block removed; placeholder guard added to executor
- [ ] Fix 3: `i was told to` and `i am programmed to` patterns narrowed; `inference pipeline` pattern tightened
- [ ] Fix 4: CAIRN name/acronym clarified in context file and system prompt (after confirming etymology)
- [ ] Fix 5: `contact_rate_limiter` created at startup; check+record called in `/contact` handler
- [ ] Fix 6: Streaming path buffers full response before yielding; L8 can block the stream
- [ ] Fix 7: `raw_message` parameter removed from `log_user_message()`; call site updated
- [ ] Fix 8: `docs_url=None`, `redoc_url=None`, `openapi_url=None` in FastAPI constructor when `DEBUG=false`
- [ ] Fix 9: CSP header added to SecurityHeadersMiddleware
- [ ] Fix 10: `chart.min.js` downloaded and committed; CDN script tag replaced with local path
- [ ] Fix 11: UUID/hex format validation added to both admin route handlers
- [ ] Fix 12: `_EMAIL_RE` regex replaces the `"@" not in email` check
- [ ] All existing tests pass after signature change in Fix 7
- [ ] Manual smoke test: send "Hello", "What does he do?", "What programming languages?" — none blocked by L8

---

## Confidence Assessment

**High confidence (can implement directly):** Fixes 1, 5, 7, 8, 9, 10, 11, 12. These are
mechanical changes with clear before/after states and no behavioral ambiguity.

**Medium confidence:** Fix 3 (L8 tuning). The narrowed patterns reduce false positives but the
tradeoff against detection coverage requires judgment. The testing strategy is critical here.

**Medium confidence:** Fix 6 (streaming buffer). The approach is correct but the UX impact
(losing true streaming) needs validation against how the frontend actually uses the SSE stream.

**Lower confidence:** Fix 2 (contact flow). Prompt engineering is empirical. The proposed changes
are sound in principle, but the LLM's actual behavior with the new prompt needs live testing.
Plan to iterate.

**Requires external input:** Fix 4 (CAIRN etymology). Cannot be fully specified until the correct
name explanation is confirmed.

---

## Unknowns and Assumptions

1. **CAIRN etymology** — The plan assumes CAIRN is not an acronym. If it is, Fix 4 needs the
   correct expansion, not the stone-marker explanation.

2. **Frontend streaming behavior** — The plan for Fix 6 assumes the frontend can work with a
   single-chunk SSE response. If the frontend uses incremental rendering (e.g., typewriter effect),
   the buffer-then-yield approach will break UX.

3. **Test suite coverage of log_user_message** — Assumed there is at least one test that calls
   or mocks this. Run `grep -r "log_user_message" tests/` to confirm before implementing Fix 7.

4. **Admin dashboard inline styles** — The CSP `'unsafe-inline'` for styles is assumed necessary.
   If the admin dashboard has no inline styles, this can be removed for a tighter policy.
