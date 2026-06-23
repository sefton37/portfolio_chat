"""
CoverageDB — SQLite persistence for coverage run results.

Tables:
- coverage_runs     — one row per run, records model config + notes
- coverage_turns    — one row per (run_id, question_id, tone), INSERT OR REPLACE
                      for resumability

WAL mode for concurrent readers.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).parent / "results" / "coverage.db"

# Required columns that _check_db.py verifies against schema
REQUIRED_TURN_COLUMNS = {
    "run_id",
    "question_id",
    "category",
    "tone",
    "expected_domain",
    "message",
    "response_text",
    "success",
    "blocked",
    "error_code",
    "domain",
    "verdict",
    "judge_score",
    "semantic_similarity",
    "latency_ms",
    "tokens_per_sec",
    "prompt_tokens",
    "output_tokens",
    "created_at",
}


class CoverageDB:
    """SQLite-backed storage for coverage test runs and turn results."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist; enable WAL mode."""
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS coverage_runs (
                run_id          TEXT PRIMARY KEY,
                started_at      TEXT NOT NULL,
                classifier_model TEXT NOT NULL,
                generator_model  TEXT NOT NULL,
                n_questions     INTEGER,
                n_tones         INTEGER,
                notes           TEXT,
                finished_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS coverage_turns (
                run_id          TEXT NOT NULL,
                question_id     TEXT NOT NULL,
                category        TEXT NOT NULL,
                tone            TEXT NOT NULL,
                expected_domain TEXT,
                message         TEXT NOT NULL,
                response_text   TEXT,
                success         INTEGER NOT NULL DEFAULT 0,
                blocked         INTEGER NOT NULL DEFAULT 0,
                error_code      TEXT,
                domain          TEXT,
                verdict         TEXT,
                judge_score     REAL,
                semantic_similarity REAL,
                latency_ms      REAL,
                tokens_per_sec  REAL,
                prompt_tokens   INTEGER,
                output_tokens   INTEGER,
                created_at      TEXT NOT NULL,
                PRIMARY KEY (run_id, question_id, tone)
            );
        """)
        self.conn.commit()

    def create_run(
        self,
        run_id: str,
        classifier_model: str,
        generator_model: str,
        n_questions: int | None = None,
        n_tones: int | None = None,
        notes: str = "",
    ) -> str:
        """
        Insert a new coverage_run row.

        Idempotent: INSERT OR IGNORE so reusing an existing run_id (crash resume
        via --resume-run-id) is a safe no-op that preserves the original row.

        Returns run_id.
        """
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO coverage_runs
                (run_id, started_at, classifier_model, generator_model, n_questions, n_tones, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, now, classifier_model, generator_model, n_questions, n_tones, notes),
        )
        self.conn.commit()
        return run_id

    def record_turn(
        self,
        run_id: str,
        question_id: str,
        category: str,
        tone: str,
        expected_domain: str | None,
        message: str,
        response_text: str | None,
        success: bool,
        blocked: bool,
        error_code: str | None,
        domain: str | None,
        verdict: str | None,
        judge_score: float | None,
        semantic_similarity: float | None,
        latency_ms: float | None,
        tokens_per_sec: float | None,
        prompt_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        """
        Insert or replace a coverage_turn row (idempotent on (run_id, question_id, tone)).
        """
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO coverage_turns (
                run_id, question_id, category, tone, expected_domain,
                message, response_text, success, blocked, error_code,
                domain, verdict, judge_score, semantic_similarity,
                latency_ms, tokens_per_sec, prompt_tokens, output_tokens,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                question_id,
                category,
                tone,
                expected_domain,
                message,
                response_text,
                int(success),
                int(blocked),
                error_code,
                domain,
                verdict,
                judge_score,
                semantic_similarity,
                latency_ms,
                tokens_per_sec,
                prompt_tokens,
                output_tokens,
                now,
            ),
        )
        self.conn.commit()

    def has_turn(self, run_id: str, question_id: str, tone: str) -> bool:
        """Return True if this (run_id, question_id, tone) triple is already recorded."""
        row = self.conn.execute(
            "SELECT 1 FROM coverage_turns WHERE run_id=? AND question_id=? AND tone=?",
            (run_id, question_id, tone),
        ).fetchone()
        return row is not None

    def fetch_turns(self, run_id: str | None = None) -> list[dict[str, Any]]:
        """
        Fetch coverage_turns rows.

        Args:
            run_id: If given, filter to that run. If None, return all rows.

        Returns:
            List of row dicts.
        """
        if run_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM coverage_turns WHERE run_id=? ORDER BY question_id, tone",
                (run_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM coverage_turns ORDER BY run_id, question_id, tone"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Aggregation helpers used by CoverageReport
    # ------------------------------------------------------------------

    def category_tone_stats(
        self,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return aggregate pass rates grouped by (category, tone).

        Columns returned: category, tone, total, correct_or_resisted, mean_latency_ms
        """
        where = "WHERE run_id=?" if run_id else ""
        params = (run_id,) if run_id else ()

        rows = self.conn.execute(
            f"""
            SELECT
                category,
                tone,
                COUNT(*) AS total,
                SUM(CASE
                    WHEN category='in_scope'   AND verdict='correct'  THEN 1
                    WHEN category='adjacent'   AND verdict='resisted' THEN 1
                    WHEN category='left_field' AND (verdict='refused' OR blocked=1) THEN 1
                    ELSE 0
                END) AS passed,
                AVG(latency_ms) AS mean_latency_ms
            FROM coverage_turns
            {where}
            GROUP BY category, tone
            ORDER BY category, tone
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def failures(
        self,
        run_id: str | None = None,
        category: str | None = None,
        tone: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return failing turns, optionally filtered by category and tone."""
        conditions = []
        params: list[Any] = []

        if run_id:
            conditions.append("run_id=?")
            params.append(run_id)
        if category:
            conditions.append("category=?")
            params.append(category)
        if tone:
            conditions.append("tone=?")
            params.append(tone)

        # A turn "fails" if the verdict is not the expected positive
        conditions.append("""
            (
                (category='in_scope'   AND verdict != 'correct')
                OR (category='adjacent'   AND verdict != 'resisted')
                OR (category='left_field' AND verdict NOT IN ('refused') AND blocked=0)
            )
        """)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        rows = self.conn.execute(
            f"SELECT * FROM coverage_turns {where} ORDER BY category, question_id, tone",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def finish_run(self, run_id: str) -> None:
        """Mark a run as finished."""
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE coverage_runs SET finished_at=? WHERE run_id=?",
            (now, run_id),
        )
        self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
