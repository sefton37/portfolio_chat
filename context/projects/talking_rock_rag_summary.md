# Talking Rock Ecosystem: Technical Summary for RAG LLM

## Core Philosophy & Mission

> **Mission:** Center your data around you, not in a data center, so that your attention is centered on what you value. Local, zero trust AI. Small models and footprint, outsized impact and trust.

> **Vision:** AI that partners with you and your values, not to automate you. Intent always verified, permission always requested, all learning available to be audited and edited by you.

Talking Rock is Kellogg Brengel's ecosystem of sovereign AI tools — a demonstration that local-first, zero-trust AI development is not just philosophically superior but practically viable. The architecture embodies its philosophy: circuit breakers, approval gates, local-only operation, and auditable memory are structural commitments to non-coercion, not marketing claims.

The tagline captures the essence: **"Don't rent a data center. Center your data around you."**

## The Strategic Economic Insight

Talking Rock's competitive advantage emerges from a fundamental asymmetry: **cloud AI costs money per token, while local inference is essentially free after model download**. This means:

- Cloud services minimize verification passes, repo analysis, and safety checks (each costs them money)
- Talking Rock can verify every intent, classify every request, check every action without cost concerns
- Binary confidence, structured prompts, and multi-layer verification make 8B parameter models outperform 70B models used naively — because architecture multiplies capability

This isn't about privacy alone (though users get that). It's about economics enabling a different kind of AI — one that prioritizes thoroughness over speed, sovereignty over convenience.

## The Ecosystem

Talking Rock is not a single application — it's a family of tools that share philosophy, infrastructure, and constraints. Every member is local-first, zero-trust, and privacy-preserving.

### CAIRN: The Personal Attention Minder (Root Project — Active)

**Target: 8B parameter models on 16GB RAM (3B stretch goal)** | **2,033+ tests passing**

CAIRN is the heart of Talking Rock — a personal attention minder that helps you focus on what you value without overwhelming you. It's a mirror for self-reflection, not a surveillance tool. It never guilt-trips about unfinished work. All life data stays local.

**How CAIRN works:** You talk to CAIRN about your life — your projects, priorities, what you're waiting on, what's coming up. CAIRN surfaces what needs your attention based on what's blocking other work, what has deadlines, and what aligns with your stated priorities.

**The Play: 2-Tier Life Organization**
| Level | Timeframe | Example |
|-------|-----------|---------|
| **Acts** | Life narratives (months to years) | "Building my startup", "Learning music" |
| **Scenes** | Calendar events within acts | "Launch MVP meeting", "Record vocals session" |

Why just two levels? To remove the temptation to obscure responsibility in complexity.

**Conversation Lifecycle & Memory Architecture:**
CAIRN treats conversations as units of meaning with deliberate closure. When a conversation ends, a 4-stage compression pipeline extracts meaning:
1. Entity Extraction — people, tasks, decisions, waiting-ons
2. Narrative Compression — meaning synthesis (not transcript summary)
3. State Delta — changes to knowledge graph
4. Embedding Generation — semantic search via sentence transformers

Every extracted memory is shown to the user before being stored. You can edit, redirect, or reject any of it. Which memories influenced which decisions is traceable. Nothing is learned behind your back.

**Your Story** is a permanent, un-archivable record of who you are, built from accumulated conversation memories and used as identity context across all reasoning.

**Core Capabilities:**
- Smart surfacing — shows you the next thing, not everything
- Calendar integration — syncs with Thunderbird (including recurring events)
- Contact knowledge graph — knows who's involved in what
- Waiting-on tracking — knows what you're blocked on
- Document knowledge base — import PDFs, Word docs for semantic search
- Coherence Kernel — filters distractions based on stated identity and goals
- Health Pulse — monitors data freshness and calibration without nagging
- 3x2x3 Atomic Operations — every request classified by destination (stream/file/process), consumer (human/machine), and execution semantics (read/interpret/execute)
- 5-layer verification pipeline — Syntax, Semantic, Behavioral, Safety, Intent
- MCP tools system — extensible tool calling with structured results

**The Kernel Principle:** "If you can't verify it, decompose it." This single recursive rule governs all operations.

**Stack:** Python 3.12+, Textual TUI, Ollama, SQLite + FTS5 + WAL mode, FastAPI for RPC

### Lithium: Android Notification Manager (Active — MVP on Pixel)

**Kotlin, Jetpack Compose, Room + SQLCipher, ONNX Runtime**

Lithium is an Android notification manager designed for neurodivergent users — people who are sensitive to notification overload and need help managing the constant stream of interruptions from their phone.

Lithium observes all notifications, correlates them with app usage patterns and contacts, classifies them (7 categories, 50+ keyword patterns), analyzes patterns over 24-hour windows, and generates conservative suggestions. It never suppresses personal or transactional notifications without explicit user rules.

**Key features:**
- NotificationListenerService captures full metadata
- Usage correlation via UsageStatsManager
- Rule engine (<1ms hot path, first-match-wins, default ALLOW)
- SQLCipher AES-256 encryption at rest
- No INTERNET permission in main app — truly local
- AI worker via WorkManager (runs when charging + idle)

### Helm: Mobile Web UI for Cairn (Phases 1-3 Complete)

**Node.js, Express, WebSocket, Playwright tests**

Helm is a thin authenticated proxy that gives mobile access to Cairn. It does nothing without Cairn running — all agent, chat, and file operations are proxied through Cairn's RPC interface.

**Key features:**
- TLS with self-signed EC P-256 certificates
- PAM authentication via Cairn
- SSE→WebSocket bridge for streaming responses
- Two production dependencies (express, ws)
- Single self-contained HTML frontend (~2000 lines, no framework, no build step)
- Accessed via LAN or Tailscale

### ReOS: Natural Language Linux System Control (Phase 1 Complete)

**Python, Textual TUI (planned)**

ReOS enhances the command line without replacing it — natural language to safe, auditable shell commands. The Parse Gate analyzes intent and system state before proposing any command.

**Core principle: Never obstruct Linux.** Commands run with full terminal access, interactive prompts work normally.

**Capabilities:** Process monitoring, service management (systemd), package management (apt/dnf/pacman/zypper), container control (Docker/Podman), file operations with safety checks.

### RIVA: Agent Orchestrator for Project Management (Needs Clean-Slate Reimplementation)

**Python (planned)**

RIVA has pivoted from its original code verification role to become an agent orchestrator — managing development projects by creating and supervising agents, enforcing plan contracts, and recursively verifying that agents follow plans and meet acceptance criteria.

**Key philosophy:** Plans are contracts. RIVA orchestrates agents (Claude Code initially) that generate code — RIVA itself does not write code. Correctness over speed, because local inference makes verification free.

### NoLang (nol): Programming Language for LLM Generation (Active)

**Rust workspace**

A programming language designed for LLM generation, not human authorship. One computation = one representation. Fixed-width 64-bit instructions eliminate parsing ambiguity. De Bruijn indices remove the need for variable names (which are coin flips for LLMs).

NoLang is a strategic advantage for the Cairn ecosystem — enabling local models to generate verified, correct programs through structural verification built into the format itself.

### talkingrock-core (trcore): Shared Infrastructure

**Python library**

The single source of truth for all Talking Rock members — providers, atomic operations, database, security, config, and error types. Direction is inbound only: trcore depends on nothing in the ecosystem, everything depends on trcore.

## Shared Technical Constraints (All Members)

- **Local-first, Ollama-only inference** — no cloud LLM APIs, ever
- **SQLite + WAL mode** for all persistence
- **Privacy-first** — no third-party tracking, no data leaves the machine
- **Textual TUI** for developer tools (not web UI, not Tauri)
- **Zero-trust** — every API call authenticated, no shell access without verification
- **Fail-closed safety** — if LLM parsing fails, action is blocked, not guessed
- **3x2x3 atomic operations taxonomy** as shared vocabulary

## Safety Architecture: Non-Coercive by Design

Safety limits can be tuned but not disabled:
- Preview before changes — see exactly what will change
- Explicit approval required for all mutations
- Automatic backups of every modified file
- Configurable limits (iterations, runtime, auth attempts)
- Rate limiting and audit logging
- 5-layer verification pipeline (Syntax → Semantic → Behavioral → Safety → Intent)

**Privacy by architecture, not policy:** Because Talking Rock runs locally, there's no server to send data to. No tracking, no data collection, no training on user conversations. This isn't marketing — it's structural reality.

## Development Status (March 2026)

| Project | Status | Key Metric |
|---------|--------|------------|
| **CAIRN** | Active, production-quality | 2,033+ tests, schema v13, full conversation lifecycle |
| **Lithium** | MVP verified on Pixel 8 Pro | 56 source files, ~2,359 LOC, all UI screens functional |
| **Helm** | Phases 1-3 complete | Streaming chat, file management, authentication working |
| **ReOS** | Phase 1 complete | Scaffolding done, core pipeline implemented |
| **RIVA** | Needs clean-slate reimplementation | Pivoted from code verification to agent orchestrator |
| **NoLang** | Active development | Rust workspace with VM, verifier, assembler |
| **trcore** | Stable, installable | Shared by all Python members |

## The Larger Context

Talking Rock is part of Kellogg's broader demonstration that AI development can serve users rather than extract value from them. The project proves that:

1. **Sovereignty is practical** — local-first AI works on consumer hardware
2. **Architecture beats scale** — 8B models with structured verification outperform naive 70B usage
3. **Free inference changes everything** — when verification costs nothing, you verify everything
4. **Non-coercion is structural** — circuit breakers, approval gates, and local-only operation are architectural commitments, not policies
5. **A mirror, not a manager** — "How can this person see themselves clearly?" instead of "How can we capture what this person does?"

## Key Messages When Representing This Work

1. **Talking Rock competes on sovereignty, not capability** — proof of alignment and structural respect for user autonomy
2. **The economic insight is the key advantage** — local inference enables verification that cloud services can't afford
3. **CAIRN is a single-agent system** (not three agents) — focused on attention management, with separate tools for separate concerns
4. **The ecosystem approach is deliberate** — each tool solves one problem well, sharing infrastructure but not coupling
5. **The architecture embodies philosophy** — every technical decision reflects the values it claims to hold

## Repository Information

- **GitHub:** https://github.com/sefton37/cairn
- **Developer:** Kellogg Brengel (sefton37)
- **Primary Language:** Python (with Kotlin for Lithium, Rust for NoLang, Node.js for Helm)
- **License:** MIT — "Do whatever you want with it."

## System Requirements

**CAIRN (main project):**
- Linux (Ubuntu, Fedora, Mint, Arch, etc.)
- Python 3.12+
- 16GB RAM
- 10GB disk space
- No GPU required (GPU optional for faster inference)

---

*Updated March 2026*
