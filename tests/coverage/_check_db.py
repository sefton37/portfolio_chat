"""
DOD DB checks against tests/coverage/results/coverage.db.

Subcommands:
    exists          — print 'db_ok' if db file + both tables exist
    schema          — print 'schema_ok' if coverage_turns has required columns
    in_scope_correct — print 'correct=R/T' for neutral in_scope turns
    left_field_refused — print 'refused=R/T' for neutral left_field turns

Usage:
    python3 tests/coverage/_check_db.py exists
    python3 tests/coverage/_check_db.py schema
    python3 tests/coverage/_check_db.py in_scope_correct
    python3 tests/coverage/_check_db.py left_field_refused
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_DB_PATH = Path(__file__).parent / "results" / "coverage.db"

_REQUIRED_COLS = {
    "run_id", "question_id", "category", "tone", "expected_domain",
    "message", "response_text", "success", "blocked", "error_code",
    "domain", "verdict", "judge_score", "semantic_similarity",
    "latency_ms", "tokens_per_sec", "prompt_tokens", "output_tokens",
    "created_at",
}


def cmd_exists() -> None:
    if not _DB_PATH.exists():
        print(f"FAIL: {_DB_PATH} does not exist")
        sys.exit(1)
    conn = sqlite3.connect(str(_DB_PATH))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    if "coverage_runs" not in tables:
        print("FAIL: table 'coverage_runs' not found")
        sys.exit(1)
    if "coverage_turns" not in tables:
        print("FAIL: table 'coverage_turns' not found")
        sys.exit(1)
    print("db_ok")


def cmd_schema() -> None:
    if not _DB_PATH.exists():
        print(f"FAIL: {_DB_PATH} does not exist")
        sys.exit(1)
    conn = sqlite3.connect(str(_DB_PATH))
    cursor = conn.execute("PRAGMA table_info(coverage_turns)")
    cols = {row[1] for row in cursor.fetchall()}
    conn.close()
    missing = _REQUIRED_COLS - cols
    if missing:
        print(f"FAIL: missing columns: {sorted(missing)}")
        sys.exit(1)
    print("schema_ok")


def cmd_in_scope_correct() -> None:
    if not _DB_PATH.exists():
        print(f"FAIL: {_DB_PATH} does not exist — run --smoke first")
        sys.exit(1)
    conn = sqlite3.connect(str(_DB_PATH))
    row = conn.execute(
        """
        SELECT COUNT(*) as total,
               SUM(CASE WHEN verdict='correct' THEN 1 ELSE 0 END) as correct
        FROM coverage_turns
        WHERE category='in_scope' AND tone='neutral'
        """
    ).fetchone()
    conn.close()
    total = row[0] if row else 0
    correct = row[1] if (row and row[1] is not None) else 0
    print(f"correct={correct}/{total}")


def cmd_left_field_refused() -> None:
    if not _DB_PATH.exists():
        print(f"FAIL: {_DB_PATH} does not exist — run --smoke first")
        sys.exit(1)
    conn = sqlite3.connect(str(_DB_PATH))
    row = conn.execute(
        """
        SELECT COUNT(*) as total,
               SUM(CASE WHEN verdict='refused' OR blocked=1 THEN 1 ELSE 0 END) as refused
        FROM coverage_turns
        WHERE category='left_field' AND tone='neutral'
        """
    ).fetchone()
    conn.close()
    total = row[0] if row else 0
    refused = row[1] if (row and row[1] is not None) else 0
    print(f"refused={refused}/{total}")


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} {{exists|schema|in_scope_correct|left_field_refused}}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "exists":
        cmd_exists()
    elif cmd == "schema":
        cmd_schema()
    elif cmd == "in_scope_correct":
        cmd_in_scope_correct()
    elif cmd == "left_field_refused":
        cmd_left_field_refused()
    else:
        print(f"Unknown subcommand: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
