"""
SQLite database for tracking benchmark results.

Extends the simulation DB pattern with model comparison support and deeper
metrics capture. Stores benchmark runs, per-model results, and aggregated
scores for side-by-side model comparison.

Schema design:
  benchmark_runs  -- one row per invocation of the benchmark runner
  models          -- one row per model tested within a run
  results         -- one row per scenario × model
  model_scores    -- aggregated metrics per model, computed after all scenarios run
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, quantiles


SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    notes TEXT,
    config_json TEXT  -- serialized run config (models, panels, etc.)
);

CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES benchmark_runs(id),
    model_name TEXT NOT NULL,  -- e.g. "mistral:7b", "claude-sonnet-4-20250514"
    model_type TEXT NOT NULL,  -- "ollama" or "anthropic"
    role TEXT NOT NULL         -- "generator", "classifier", "full_pipeline"
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES benchmark_runs(id),
    model_id INTEGER NOT NULL REFERENCES models(id),
    scenario_id TEXT NOT NULL,  -- from Panel scenario ID
    voice TEXT,                 -- voice type
    domain_expected TEXT,
    -- Request
    user_message TEXT,
    intent TEXT,
    system_prompt TEXT,   -- full system prompt sent to LLM
    user_prompt TEXT,     -- full formatted user message (with context, spotlighting)
    -- Response
    success INTEGER NOT NULL DEFAULT 0,
    response_content TEXT,
    response_domain TEXT,  -- what domain was routed to
    blocked INTEGER NOT NULL DEFAULT 0,
    blocked_at_layer TEXT,
    error_message TEXT,
    -- Tool behavior
    tool_call_expected INTEGER,  -- 1 if scenario expects tool, 0 if not, NULL if either
    tool_call_fired INTEGER,     -- 1 if tool actually fired
    tool_call_correct INTEGER,   -- 1 if behavior matches expectation
    -- Quality assertions
    must_contain_passed INTEGER,      -- 1 if all must_contain keywords found
    must_not_contain_passed INTEGER,  -- 1 if no must_not_contain keywords found
    -- Performance
    total_time_ms REAL,
    layer_timings_json TEXT,  -- per-layer breakdown as JSON
    -- Token usage (Claude only, NULL for Ollama)
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_usd REAL,  -- calculated from token counts
    -- Timestamps
    sent_at TEXT,
    received_at TEXT
);

CREATE TABLE IF NOT EXISTS model_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES benchmark_runs(id),
    model_id INTEGER NOT NULL REFERENCES models(id),
    -- Accuracy
    domain_accuracy REAL,       -- % correct domain routing
    tool_accuracy REAL,         -- % correct tool behavior
    assertion_pass_rate REAL,   -- % scenarios passing all assertions
    -- Quality
    avg_response_length REAL,
    hallucination_count INTEGER,  -- detected hallucinations
    -- Performance
    avg_time_ms REAL,
    p50_time_ms REAL,
    p95_time_ms REAL,
    max_time_ms REAL,
    -- Cost (Claude only, NULL for Ollama)
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    total_cost_usd REAL,
    -- Security
    false_positive_blocks INTEGER,  -- legitimate queries blocked
    false_negative_passes INTEGER,  -- attacks that should have been blocked
    -- Breakdowns (JSON)
    scores_by_voice_json TEXT,   -- {"professional": {"accuracy": 0.9, ...}, ...}
    scores_by_domain_json TEXT   -- {"portfolio": {"accuracy": 0.95, ...}, ...}
);

CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_model ON results(model_id);
CREATE INDEX IF NOT EXISTS idx_results_scenario ON results(scenario_id);
CREATE INDEX IF NOT EXISTS idx_results_voice ON results(voice);
CREATE INDEX IF NOT EXISTS idx_results_domain ON results(domain_expected);
CREATE INDEX IF NOT EXISTS idx_models_run ON models(run_id);
CREATE INDEX IF NOT EXISTS idx_scores_run ON model_scores(run_id);
CREATE INDEX IF NOT EXISTS idx_scores_model ON model_scores(model_id);
"""


class BenchmarkDB:
    """SQLite database for benchmark tracking and model comparison."""

    def __init__(self, db_path: str | Path = "benchmark_results.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- Benchmark runs --

    def create_run(self, config: dict, notes: str = "") -> int:
        """Create a new benchmark run and return its ID."""
        cur = self.conn.execute(
            "INSERT INTO benchmark_runs (started_at, notes, config_json) VALUES (?, ?, ?)",
            (self._now(), notes, json.dumps(config)),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    def finish_run(self, run_id: int):
        """Mark a run as finished by recording finished_at."""
        self.conn.execute(
            "UPDATE benchmark_runs SET finished_at=? WHERE id=?",
            (self._now(), run_id),
        )
        self.conn.commit()

    # -- Models --

    def add_model(
        self,
        run_id: int,
        model_name: str,
        model_type: str,
        role: str,
    ) -> int:
        """Register a model under a run and return its ID."""
        cur = self.conn.execute(
            "INSERT INTO models (run_id, model_name, model_type, role) VALUES (?, ?, ?, ?)",
            (run_id, model_name, model_type, role),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    # -- Results --

    def record_result(
        self,
        run_id: int,
        model_id: int,
        scenario_id: str,
        voice: str | None = None,
        domain_expected: str | None = None,
        # Request
        user_message: str | None = None,
        intent: str | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        # Response
        success: bool = False,
        response_content: str | None = None,
        response_domain: str | None = None,
        blocked: bool = False,
        blocked_at_layer: str | None = None,
        error_message: str | None = None,
        # Tool behavior
        tool_call_expected: int | None = None,
        tool_call_fired: int | None = None,
        tool_call_correct: int | None = None,
        # Quality assertions
        must_contain_passed: int | None = None,
        must_not_contain_passed: int | None = None,
        # Performance
        total_time_ms: float | None = None,
        layer_timings_json: str | None = None,
        # Token usage
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
        # Timestamps
        sent_at: str | None = None,
        received_at: str | None = None,
    ) -> int:
        """Record a single scenario result for one model. Returns the new row ID."""
        cur = self.conn.execute(
            "INSERT INTO results ("
            "    run_id, model_id, scenario_id, voice, domain_expected,"
            "    user_message, intent, system_prompt, user_prompt,"
            "    success, response_content, response_domain,"
            "    blocked, blocked_at_layer, error_message,"
            "    tool_call_expected, tool_call_fired, tool_call_correct,"
            "    must_contain_passed, must_not_contain_passed,"
            "    total_time_ms, layer_timings_json,"
            "    input_tokens, output_tokens, estimated_cost_usd,"
            "    sent_at, received_at"
            ") VALUES ("
            "    ?, ?, ?, ?, ?,"
            "    ?, ?, ?, ?,"
            "    ?, ?, ?,"
            "    ?, ?, ?,"
            "    ?, ?, ?,"
            "    ?, ?,"
            "    ?, ?,"
            "    ?, ?, ?,"
            "    ?, ?"
            ")",
            (
                run_id, model_id, scenario_id, voice, domain_expected,
                user_message, intent, system_prompt, user_prompt,
                1 if success else 0, response_content, response_domain,
                1 if blocked else 0, blocked_at_layer, error_message,
                tool_call_expected, tool_call_fired, tool_call_correct,
                must_contain_passed, must_not_contain_passed,
                total_time_ms, layer_timings_json,
                input_tokens, output_tokens, estimated_cost_usd,
                sent_at or self._now(), received_at,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    # -- Score aggregation --

    def compute_scores(self, run_id: int):
        """
        Aggregate raw results into model_scores for all models in a run.

        Computes accuracy, timing percentiles, cost totals, security counts,
        and per-voice/per-domain breakdowns. Existing score rows for this run
        are deleted and replaced so this method is safe to call multiple times.
        """
        # Wipe any existing scores for this run so re-runs stay clean.
        self.conn.execute("DELETE FROM model_scores WHERE run_id=?", (run_id,))
        self.conn.commit()

        model_rows = self.conn.execute(
            "SELECT id FROM models WHERE run_id=?", (run_id,)
        ).fetchall()

        for model_row in model_rows:
            model_id = model_row["id"]
            rows = self.conn.execute(
                "SELECT * FROM results WHERE run_id=? AND model_id=?",
                (run_id, model_id),
            ).fetchall()

            if not rows:
                continue

            rows = [dict(r) for r in rows]

            # -- Domain accuracy --
            domain_rows = [r for r in rows if r["domain_expected"] is not None and r["response_domain"] is not None]
            if domain_rows:
                correct = sum(
                    1 for r in domain_rows
                    if r["response_domain"].upper() == r["domain_expected"].upper()
                )
                domain_accuracy = correct / len(domain_rows)
            else:
                domain_accuracy = None

            # -- Tool accuracy --
            tool_rows = [r for r in rows if r["tool_call_expected"] is not None]
            if tool_rows:
                tool_correct = sum(1 for r in tool_rows if r["tool_call_correct"] == 1)
                tool_accuracy = tool_correct / len(tool_rows)
            else:
                tool_accuracy = None

            # -- Assertion pass rate --
            # A scenario passes all assertions when both must_contain and
            # must_not_contain checks passed (or were not applicable).
            assertion_rows = [
                r for r in rows
                if r["must_contain_passed"] is not None or r["must_not_contain_passed"] is not None
            ]
            if assertion_rows:
                all_passed = sum(
                    1 for r in assertion_rows
                    if (r["must_contain_passed"] is None or r["must_contain_passed"] == 1)
                    and (r["must_not_contain_passed"] is None or r["must_not_contain_passed"] == 1)
                )
                assertion_pass_rate = all_passed / len(assertion_rows)
            else:
                assertion_pass_rate = None

            # -- Response length --
            lengths = [
                len(r["response_content"])
                for r in rows
                if r["response_content"] is not None
            ]
            avg_response_length = sum(lengths) / len(lengths) if lengths else None

            # -- Timing --
            times = [r["total_time_ms"] for r in rows if r["total_time_ms"] is not None]
            if times:
                avg_time_ms = sum(times) / len(times)
                p50_time_ms = median(times)
                max_time_ms = max(times)
                # quantiles requires at least 1 data point; p95 needs enough data.
                if len(times) >= 20:
                    p95_time_ms = quantiles(times, n=20)[18]  # 95th percentile
                elif len(times) >= 2:
                    # Fall back to max for small sample sizes.
                    p95_time_ms = max(times)
                else:
                    p95_time_ms = times[0]
            else:
                avg_time_ms = None
                p50_time_ms = None
                p95_time_ms = None
                max_time_ms = None

            # -- Token usage and cost --
            input_tokens_vals = [r["input_tokens"] for r in rows if r["input_tokens"] is not None]
            output_tokens_vals = [r["output_tokens"] for r in rows if r["output_tokens"] is not None]
            cost_vals = [r["estimated_cost_usd"] for r in rows if r["estimated_cost_usd"] is not None]

            total_input_tokens = sum(input_tokens_vals) if input_tokens_vals else None
            total_output_tokens = sum(output_tokens_vals) if output_tokens_vals else None
            total_cost_usd = sum(cost_vals) if cost_vals else None

            # -- Security counts --
            # False positive: a legitimate query (not blocked expected) that got blocked.
            # Convention: if blocked=1 and tool_call_expected=0 (or no attack expected),
            # that is a false positive. We use blocked=1 and success=0 and
            # blocked_at_layer is not NULL as a proxy.
            false_positive_blocks = sum(
                1 for r in rows
                if r["blocked"] == 1 and r["success"] == 0 and r["error_message"] is not None
                and "attack" not in (r["scenario_id"] or "").lower()
                and "injection" not in (r["scenario_id"] or "").lower()
                and "malicious" not in (r["scenario_id"] or "").lower()
            )
            # False negative: an attack scenario that was not blocked.
            false_negative_passes = sum(
                1 for r in rows
                if r["blocked"] == 0
                and (
                    "attack" in (r["scenario_id"] or "").lower()
                    or "injection" in (r["scenario_id"] or "").lower()
                    or "malicious" in (r["scenario_id"] or "").lower()
                )
            )

            # -- Per-voice breakdown --
            voices = {r["voice"] for r in rows if r["voice"] is not None}
            scores_by_voice: dict[str, dict] = {}
            for voice in sorted(voices):
                vrows = [r for r in rows if r["voice"] == voice]
                vdomain = [
                    r for r in vrows
                    if r["domain_expected"] is not None and r["response_domain"] is not None
                ]
                scores_by_voice[voice] = {
                    "total": len(vrows),
                    "success_rate": sum(1 for r in vrows if r["success"] == 1) / len(vrows),
                    "domain_accuracy": (
                        sum(
                            1 for r in vdomain
                            if r["response_domain"].upper() == r["domain_expected"].upper()
                        ) / len(vdomain)
                        if vdomain else None
                    ),
                    "avg_time_ms": (
                        sum(r["total_time_ms"] for r in vrows if r["total_time_ms"] is not None)
                        / max(1, sum(1 for r in vrows if r["total_time_ms"] is not None))
                        if any(r["total_time_ms"] is not None for r in vrows) else None
                    ),
                }

            # -- Per-domain breakdown --
            domains = {r["domain_expected"] for r in rows if r["domain_expected"] is not None}
            scores_by_domain: dict[str, dict] = {}
            for domain in sorted(domains):
                drows = [r for r in rows if r["domain_expected"] == domain]
                drouted = [r for r in drows if r["response_domain"] is not None]
                scores_by_domain[domain] = {
                    "total": len(drows),
                    "success_rate": sum(1 for r in drows if r["success"] == 1) / len(drows),
                    "domain_accuracy": (
                        sum(
                            1 for r in drouted
                            if r["response_domain"].upper() == domain.upper()
                        ) / len(drouted)
                        if drouted else None
                    ),
                    "avg_time_ms": (
                        sum(r["total_time_ms"] for r in drows if r["total_time_ms"] is not None)
                        / max(1, sum(1 for r in drows if r["total_time_ms"] is not None))
                        if any(r["total_time_ms"] is not None for r in drows) else None
                    ),
                }

            self.conn.execute(
                "INSERT INTO model_scores ("
                "    run_id, model_id,"
                "    domain_accuracy, tool_accuracy, assertion_pass_rate,"
                "    avg_response_length, hallucination_count,"
                "    avg_time_ms, p50_time_ms, p95_time_ms, max_time_ms,"
                "    total_input_tokens, total_output_tokens, total_cost_usd,"
                "    false_positive_blocks, false_negative_passes,"
                "    scores_by_voice_json, scores_by_domain_json"
                ") VALUES ("
                "    ?, ?,"
                "    ?, ?, ?,"
                "    ?, ?,"
                "    ?, ?, ?, ?,"
                "    ?, ?, ?,"
                "    ?, ?,"
                "    ?, ?"
                ")",
                (
                    run_id, model_id,
                    domain_accuracy, tool_accuracy, assertion_pass_rate,
                    avg_response_length, 0,  # hallucination_count: placeholder (requires external detection)
                    avg_time_ms, p50_time_ms, p95_time_ms, max_time_ms,
                    total_input_tokens, total_output_tokens, total_cost_usd,
                    false_positive_blocks, false_negative_passes,
                    json.dumps(scores_by_voice), json.dumps(scores_by_domain),
                ),
            )

        self.conn.commit()

    # -- Query helpers --

    def get_results(self, run_id: int, model_id: int | None = None) -> list[dict]:
        """Return raw results for a run, optionally filtered to one model."""
        if model_id is not None:
            rows = self.conn.execute(
                "SELECT r.*, m.model_name, m.model_type, m.role "
                "FROM results r JOIN models m ON r.model_id = m.id "
                "WHERE r.run_id=? AND r.model_id=? ORDER BY r.id",
                (run_id, model_id),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT r.*, m.model_name, m.model_type, m.role "
                "FROM results r JOIN models m ON r.model_id = m.id "
                "WHERE r.run_id=? ORDER BY m.id, r.id",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_scores(self, run_id: int) -> list[dict]:
        """Return aggregated model_scores for a run, joined with model info."""
        rows = self.conn.execute(
            "SELECT s.*, m.model_name, m.model_type, m.role "
            "FROM model_scores s JOIN models m ON s.model_id = m.id "
            "WHERE s.run_id=? ORDER BY m.id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_comparison(self, run_id: int) -> list[dict]:
        """
        Return side-by-side model scores for a run.

        Each entry is a model_scores row augmented with model metadata and
        with scores_by_voice_json / scores_by_domain_json decoded to dicts
        for convenient programmatic access.
        """
        rows = self.get_scores(run_id)
        for row in rows:
            try:
                row["scores_by_voice"] = json.loads(row["scores_by_voice_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                row["scores_by_voice"] = {}
            try:
                row["scores_by_domain"] = json.loads(row["scores_by_domain_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                row["scores_by_domain"] = {}
        return rows
