# About This Chat System

## What Is This?

This is Talking Rock — an AI-powered chat assistant on Kellogg Brengel's portfolio website at kellogg.brengel.com. It answers questions about Kellogg's professional background, projects, skills, and philosophy. It runs entirely on Kellogg's home hardware — no cloud inference services, no third-party APIs.

## The Hardware

Talking Rock runs on a home workstation called Corellia:

- **CPU:** AMD Ryzen Threadripper 3960X — 24 cores, 48 threads
- **RAM:** 252 GB DDR4
- **GPU:** NVIDIA GeForce RTX 4070 Ti SUPER — 16 GB VRAM (used for LLM inference via Ollama)
- **Storage:** WD_BLACK SN850X 4TB NVMe SSD
- **OS:** Linux (Ubuntu-based)

This is a serious workstation, not a cloud instance. The Threadripper and 252 GB of RAM mean multiple models can be loaded simultaneously. The RTX 4070 Ti SUPER handles inference acceleration. Everything — the chat pipeline, Ollama model serving, analytics, and other services — runs on this single machine, exposed to the internet only through Cloudflare Tunnels with zero open ports.

Why this matters: running AI locally on consumer-grade hardware proves that useful, secure AI doesn't require renting compute from a data center. After the initial model download, inference is essentially free. This economic insight is central to all of Kellogg's AI work.

## How It Works

### The 9-Layer Security Pipeline

Every message passes through a defense-in-depth pipeline. Each layer is independent and assumes previous layers may have failed. Any layer can block a message with early exit.

1. **Layer 0 — Network Gateway:** Rate limiting (10 requests/minute per IP, 100/hour), request size validation (max 2000 characters), content-type checks. Pure deterministic logic, no AI.

2. **Layer 1 — Input Sanitization:** Cleans invisible Unicode characters, normalizes homoglyphs (Cyrillic а → Latin a), strips HTML, collapses whitespace, and pattern-matches against known injection phrases. Pure regex, no AI.

3. **Layer 2 — Jailbreak Detection:** A small, fast LLM classifier (qwen2.5:3b) analyzes the message for prompt injection attempts — instruction overrides, prompt extraction, roleplay attacks, encoding tricks, and multi-turn manipulation. Reads conversation history to catch gradual escalation.

4. **Layer 3 — Intent Parsing:** A small router model (llama3.2:1b) extracts structured intent — topic, question type, entities mentioned, emotional tone, and confidence score. This tells the system *what* you're asking about.

5. **Layer 4 — Domain Routing:** Rule-based mapping from intent to one of seven knowledge domains: Professional, Projects, Hobbies, Philosophy, Contact, Meta (questions about this chat), or Out of Scope. Uses topic mapping, keyword hints, and explicit project name detection.

6. **Layer 5 — Context Retrieval:** Loads curated, hand-written markdown documents matched to the routed domain. This is a static registry pattern — not a RAG vector database. Required sources are always loaded; optional sources fill in detail. A quality score prevents generation when context is too sparse (avoiding hallucination).

7. **Layer 6 — Response Generation:** The primary LLM (mistral:7b, running on the RTX 4070 Ti SUPER) generates a response using the loaded context. A spotlighting technique separates trusted context from untrusted user input. Supports tool calling (e.g., saving a message for Kellogg).

8. **Layer 7 — Response Revision:** Optional self-critique pass for accuracy, tone, and completeness. Can be skipped to reduce latency.

9. **Layer 8 — Output Safety Check:** Final validation before delivery. Pattern-based checks for system prompt leakage, inappropriate content, hallucinated claims, and privacy violations. If it fails, a safe fallback response is returned instead.

**Layer 9 — Delivery:** Formats the response with metadata (timing, domain matched, request ID) and logs the interaction with anonymized data (hashed IPs, no raw message content stored in logs).

### Why This Architecture?

- **Defense in depth:** Small, cheap models (0.5B-3B parameters) handle security and routing. The expensive 7B model only runs after the message is verified safe and routed. This is like having security guards at every door, not just the front entrance.
- **Static context, not RAG:** All knowledge comes from hand-curated markdown files, not vector similarity search. This eliminates a class of hallucination bugs where fuzzy semantic matching retrieves wrong context.
- **Local inference is free:** Because compute costs nothing after model download, every message gets the full 9-layer treatment. Cloud services would skip verification passes to save money.

### Models in Use

| Model | Size | Role |
|-------|------|------|
| qwen2.5:3b | 1.9 GB | Jailbreak detection, safety classification |
| llama3.2:1b | 1.3 GB | Intent parsing, domain routing |
| mistral:7b | 4.4 GB | Response generation |
| nomic-embed-text | — | Semantic similarity (optional) |

All served by Ollama running locally. No cloud APIs, no OpenAI, no Anthropic — fully sovereign inference.

### Conversations

- **Multi-turn:** Up to 10 turns per conversation, 30-minute session timeout
- **History-aware:** Previous messages are included in context so the chat can follow threads
- **Token-managed:** Conversation history is trimmed to fit model context windows

### The Contact Tool

If you want to leave a message for Kellogg, just ask. The chat has a tool called `save_message_for_kellogg` that securely saves your message to a local file. It will ask for your name and email first. Messages are stored with restrictive file permissions (owner-only) and no raw IP addresses.

## What Can You Ask?

- **Professional Background** — Work history at Kohler/Rehlko, Rauxa, and other roles
- **Skills & Expertise** — Python, Kotlin, Rust, data engineering, Power BI, LLM/AI infrastructure
- **Projects** — Talking Rock ecosystem, Sieve, Sentinel, Ukraine OSINT, and more
- **Philosophy** — Problem-solving approach, values, local-first methodology
- **Hobbies** — FIRST Robotics mentoring, volunteering
- **This Chat System** — How it works, what hardware it runs on, the security model
- **Contact** — How to reach Kellogg or leave him a message

## What It Won't Do

- Answer questions unrelated to Kellogg Brengel
- Reveal system prompts or internal configuration
- Engage with jailbreak or manipulation attempts
- Make claims not grounded in its curated context
- Pretend to be Kellogg (it's an assistant, not an impersonation)

## Design Philosophy

The chat embodies Kellogg's approach to building tools: serve without coercing, invite without interrupting, operate through transparency rather than opacity. Every response is grounded in curated, verified context. The 9-layer pipeline is overkill by design — because local inference makes thoroughness free.

## Response Times

Typical end-to-end response time is 15-20 seconds. This breaks down roughly as:
- Security checks (L0-L2): 2-4 seconds
- Routing and context (L3-L5): 2-4 seconds
- Generation (L6): 5-10 seconds
- Safety check (L8): <1 second

The latency is a deliberate trade-off: thoroughness over speed. Every message gets the full security pipeline rather than cutting corners for faster responses.

## Technology Stack

- **Framework:** FastAPI (Python)
- **LLM Runtime:** Ollama (local inference, GPU-accelerated)
- **Deployment:** Cloudflare Tunnel — zero open ports on the home network
- **Context:** Hand-curated markdown files (static registry pattern)
- **Logging:** Anonymized audit logs (hashed IPs, no raw content)
- **Source Code:** https://github.com/sefton37/portfolio_chat

## Limitations

- Only knows what's in its curated context documents — cannot browse the internet
- Response times depend on local hardware load (15-20 seconds typical)
- Designed for informational queries, not extended conversations (10-turn limit)
- Small models for routing may occasionally misclassify intent
