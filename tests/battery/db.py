"""
BatteryDB — SQLite persistence for the unified model-evaluation battery.

Three tables:
  battery_runs   — one row per (classifier × generator) sweep run
  battery_turns  — one row per conversation turn
  battery_scores — aggregated per-(classifier, generator) metrics

Schema column names match exactly what the DoD checks grep for.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS battery_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    notes               TEXT,
    config_json         TEXT,
    is_baseline         INTEGER NOT NULL DEFAULT 0,
    classifier_name     TEXT NOT NULL,
    generator_name      TEXT NOT NULL,
    classifier_vram_mb  REAL,
    generator_vram_mb   REAL
);

CREATE TABLE IF NOT EXISTS battery_turns (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  INTEGER NOT NULL REFERENCES battery_runs(id),
    classifier_name         TEXT NOT NULL,
    generator_name          TEXT NOT NULL,
    profile_id              TEXT NOT NULL,
    profile_category        TEXT NOT NULL,
    turn_number             INTEGER NOT NULL,
    intent                  TEXT,
    total_time_ms           REAL,
    time_to_first_token     REAL,
    eval_count              INTEGER,
    eval_duration_ns        INTEGER,
    tokens_per_sec          REAL,
    prompt_eval_count       INTEGER,
    prompt_eval_duration_ns INTEGER,
    prompt_eval_rate        REAL,
    judge_score             REAL,
    hallucination_count     INTEGER,
    user_message            TEXT,
    response_content        TEXT,
    success                 INTEGER NOT NULL DEFAULT 0,
    error_message           TEXT,
    vram_mb                 REAL,
    sent_at                 TEXT,
    received_at             TEXT
);

CREATE TABLE IF NOT EXISTS battery_scores (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  INTEGER NOT NULL REFERENCES battery_runs(id),
    classifier_name         TEXT NOT NULL,
    generator_name          TEXT NOT NULL,
    is_baseline             INTEGER NOT NULL DEFAULT 0,
    avg_judge_score         REAL,
    hallucination_count     INTEGER,
    avg_tokens_per_sec      REAL,
    p50_tokens_per_sec      REAL,
    avg_time_to_first_token REAL,
    avg_total_time_ms       REAL,
    fp_count                INTEGER,
    fn_count                INTEGER,
    leak_fn_count           INTEGER,
    timeout_fn_count        INTEGER,
    vram_mb                 REAL,
    turn_count              INTEGER,
    scores_by_category_json TEXT
);
"""


# ---------------------------------------------------------------------------
# BatteryDB
# ---------------------------------------------------------------------------

class BatteryDB:
    """
    Thin SQLite wrapper for battery_runs / battery_turns / battery_scores.

    Uses WAL mode for write concurrency. All writes go through explicit
    transactions so interrupted runs are fully consistent on resume.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_DDL)
        self.conn.commit()

        # Idempotent migration: add new columns to pre-existing DBs without crashing.
        for _col in ("leak_fn_count INTEGER", "timeout_fn_count INTEGER"):
            try:
                self.conn.execute(f"ALTER TABLE battery_scores ADD COLUMN {_col}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

        logger.debug(f"BatteryDB opened at {self.db_path}")

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def create_run(
        self,
        classifier_name: str,
        generator_name: str,
        is_baseline: bool = False,
        config: dict[str, Any] | None = None,
        notes: str = "",
    ) -> int:
        """Create a battery_runs row and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO battery_runs
                (started_at, notes, config_json, is_baseline,
                 classifier_name, generator_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                notes or None,
                json.dumps(config) if config else None,
                int(is_baseline),
                classifier_name,
                generator_name,
            ),
        )
        self.conn.commit()
        run_id = cur.lastrowid
        logger.debug(f"Created battery run #{run_id} ({classifier_name} x {generator_name})")
        return run_id  # type: ignore[return-value]

    def finish_run(self, run_id: int) -> None:
        """Stamp finished_at on a battery_runs row."""
        self.conn.execute(
            "UPDATE battery_runs SET finished_at=? WHERE id=?",
            (datetime.now(UTC).isoformat(), run_id),
        )
        self.conn.commit()

    def update_vram(
        self,
        run_id: int,
        classifier_vram_mb: float | None,
        generator_vram_mb: float | None,
    ) -> None:
        """Store per-model VRAM readings on the run row."""
        self.conn.execute(
            """
            UPDATE battery_runs
            SET classifier_vram_mb=?, generator_vram_mb=?
            WHERE id=?
            """,
            (classifier_vram_mb, generator_vram_mb, run_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Turn recording
    # ------------------------------------------------------------------

    def record_turn(
        self,
        run_id: int,
        *,
        classifier_name: str,
        generator_name: str,
        profile_id: str,
        profile_category: str,
        turn_number: int,
        intent: str | None = None,
        total_time_ms: float | None = None,
        time_to_first_token: float | None = None,
        eval_count: int | None = None,
        eval_duration_ns: int | None = None,
        tokens_per_sec: float | None = None,
        prompt_eval_count: int | None = None,
        prompt_eval_duration_ns: int | None = None,
        prompt_eval_rate: float | None = None,
        judge_score: float | None = None,
        hallucination_count: int | None = None,
        user_message: str | None = None,
        response_content: str | None = None,
        success: bool = False,
        error_message: str | None = None,
        vram_mb: float | None = None,
        sent_at: str | None = None,
        received_at: str | None = None,
    ) -> int:
        """Insert a battery_turns row and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO battery_turns (
                run_id, classifier_name, generator_name,
                profile_id, profile_category, turn_number, intent,
                total_time_ms, time_to_first_token,
                eval_count, eval_duration_ns, tokens_per_sec,
                prompt_eval_count, prompt_eval_duration_ns, prompt_eval_rate,
                judge_score, hallucination_count,
                user_message, response_content,
                success, error_message, vram_mb,
                sent_at, received_at
            ) VALUES (
                ?,?,?, ?,?,?,?, ?,?, ?,?,?, ?,?,?, ?,?, ?,?, ?,?,?, ?,?
            )
            """,
            (
                run_id, classifier_name, generator_name,
                profile_id, profile_category, turn_number, intent,
                total_time_ms, time_to_first_token,
                eval_count, eval_duration_ns, tokens_per_sec,
                prompt_eval_count, prompt_eval_duration_ns, prompt_eval_rate,
                judge_score, hallucination_count,
                user_message, response_content,
                int(success), error_message, vram_mb,
                sent_at, received_at,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Security scores
    # ------------------------------------------------------------------

    def record_security_score(
        self,
        run_id: int,
        classifier_name: str,
        generator_name: str,
        fp_count: int,
        fn_count: int,
        is_baseline: bool = False,
        vram_mb: float | None = None,
        leak_fn_count: int = 0,
        timeout_fn_count: int = 0,
    ) -> None:
        """
        Upsert security FP/FN counts into battery_scores.

        Called after the security phase completes for a (classifier, generator) pair.
        If a row already exists (from compute_scores), update the fp/fn columns.
        Otherwise insert a minimal row.

        fn_count is the legacy sum (leak_fn_count + timeout_fn_count) kept for
        back-compat. leak_fn_count and timeout_fn_count are the split metrics
        added by Spec #209 Work Item A.
        """
        existing = self.conn.execute(
            "SELECT id FROM battery_scores WHERE run_id=? AND classifier_name=? AND generator_name=?",
            (run_id, classifier_name, generator_name),
        ).fetchone()

        if existing:
            self.conn.execute(
                "UPDATE battery_scores SET fp_count=?, fn_count=?, leak_fn_count=?, timeout_fn_count=? WHERE id=?",
                (fp_count, fn_count, leak_fn_count, timeout_fn_count, existing[0]),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO battery_scores
                    (run_id, classifier_name, generator_name,
                     is_baseline, fp_count, fn_count, leak_fn_count, timeout_fn_count, vram_mb)
                VALUES (?,?,?, ?,?,?,?,?,?)
                """,
                (
                    run_id, classifier_name, generator_name,
                    int(is_baseline), fp_count, fn_count, leak_fn_count, timeout_fn_count, vram_mb,
                ),
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def compute_scores(self, run_id: int) -> None:
        """
        Aggregate battery_turns into battery_scores for a run.

        Computes per-(classifier, generator) averages for judge_score,
        tokens_per_sec, time_to_first_token, total_time_ms, hallucination_count,
        and a breakdown by profile_category.

        Security fp_count / fn_count are set by record_security_score() separately.
        """
        run_row = self.conn.execute(
            "SELECT is_baseline FROM battery_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not run_row:
            logger.warning(f"compute_scores: run_id={run_id} not found")
            return
        is_baseline = run_row["is_baseline"]

        # A grid run shares one run_id across many pairs — aggregate EACH
        # distinct (classifier, generator) separately (the old code keyed off the
        # single battery_runs row, so only one pair ever got avg_judge/avg_tps).
        pairs = self.conn.execute(
            "SELECT DISTINCT classifier_name, generator_name "
            "FROM battery_turns WHERE run_id=?",
            (run_id,),
        ).fetchall()
        if not pairs:
            logger.warning(f"compute_scores: no turns for run_id={run_id}")
            return

        aggregated = 0
        for pair in pairs:
            classifier_name = pair["classifier_name"]
            generator_name = pair["generator_name"]

            rows = self.conn.execute(
                """
                SELECT profile_category, tokens_per_sec, time_to_first_token,
                       total_time_ms, judge_score, hallucination_count, vram_mb
                FROM battery_turns
                WHERE run_id=? AND classifier_name=? AND generator_name=? AND success=1
                """,
                (run_id, classifier_name, generator_name),
            ).fetchall()
            if not rows:
                continue

            tps_vals = [r["tokens_per_sec"] for r in rows if r["tokens_per_sec"] is not None]
            ttft_vals = [r["time_to_first_token"] for r in rows if r["time_to_first_token"] is not None]
            time_vals = [r["total_time_ms"] for r in rows if r["total_time_ms"] is not None]
            judge_vals = [r["judge_score"] for r in rows if r["judge_score"] is not None]
            halluc_vals = [r["hallucination_count"] for r in rows if r["hallucination_count"] is not None]
            vram_vals = [r["vram_mb"] for r in rows if r["vram_mb"] is not None]

            avg_tps = sum(tps_vals) / len(tps_vals) if tps_vals else None
            p50_tps = statistics.median(tps_vals) if tps_vals else None
            avg_ttft = sum(ttft_vals) / len(ttft_vals) if ttft_vals else None
            avg_time = sum(time_vals) / len(time_vals) if time_vals else None
            avg_judge = sum(judge_vals) / len(judge_vals) if judge_vals else None
            total_halluc = sum(halluc_vals) if halluc_vals else None
            avg_vram = sum(vram_vals) / len(vram_vals) if vram_vals else None

            cats: dict[str, list] = {}
            for r in rows:
                cats.setdefault(r["profile_category"], []).append({
                    "tokens_per_sec": r["tokens_per_sec"],
                    "judge_score": r["judge_score"],
                })
            cat_summary = {
                cat: {
                    "count": len(v),
                    "avg_tps": sum(x["tokens_per_sec"] for x in v if x["tokens_per_sec"]) / max(1, sum(1 for x in v if x["tokens_per_sec"])),
                    "avg_judge": sum(x["judge_score"] for x in v if x["judge_score"]) / max(1, sum(1 for x in v if x["judge_score"])),
                }
                for cat, v in cats.items()
            }

            existing = self.conn.execute(
                "SELECT id FROM battery_scores "
                "WHERE run_id=? AND classifier_name=? AND generator_name=?",
                (run_id, classifier_name, generator_name),
            ).fetchone()
            if existing:
                self.conn.execute(
                    """
                    UPDATE battery_scores SET
                        is_baseline=?, avg_judge_score=?, hallucination_count=?,
                        avg_tokens_per_sec=?, p50_tokens_per_sec=?,
                        avg_time_to_first_token=?, avg_total_time_ms=?,
                        vram_mb=COALESCE(?, vram_mb), turn_count=?,
                        scores_by_category_json=?
                    WHERE id=?
                    """,
                    (
                        int(is_baseline), avg_judge, total_halluc,
                        avg_tps, p50_tps, avg_ttft, avg_time,
                        avg_vram, len(rows), json.dumps(cat_summary), existing[0],
                    ),
                )
            else:
                self.conn.execute(
                    """
                    INSERT INTO battery_scores (
                        run_id, classifier_name, generator_name, is_baseline,
                        avg_judge_score, hallucination_count,
                        avg_tokens_per_sec, p50_tokens_per_sec,
                        avg_time_to_first_token, avg_total_time_ms,
                        vram_mb, turn_count, scores_by_category_json
                    ) VALUES (?,?,?,?, ?,?, ?,?, ?,?, ?,?,?)
                    """,
                    (
                        run_id, classifier_name, generator_name, int(is_baseline),
                        avg_judge, total_halluc, avg_tps, p50_tps,
                        avg_ttft, avg_time, avg_vram, len(rows), json.dumps(cat_summary),
                    ),
                )
            aggregated += 1

        self.conn.commit()
        logger.info(f"Aggregated scores for run #{run_id}: {aggregated} pair(s)")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_scores(self, run_id: int) -> list[dict[str, Any]]:
        """Return battery_scores rows for a specific run."""
        rows = self.conn.execute(
            "SELECT * FROM battery_scores WHERE run_id=?", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_scores(self) -> list[dict[str, Any]]:
        """Return all battery_scores across all runs for cross-run Pareto analysis."""
        rows = self.conn.execute(
            """
            SELECT s.*, r.started_at, r.notes
            FROM battery_scores s
            JOIN battery_runs r ON s.run_id = r.id
            ORDER BY r.started_at
            """
        ).fetchall()
        return [dict(r) for r in rows]
