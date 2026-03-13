"""
SQLite database for tracking simulation results.

Stores profiles, conversations, individual turns, and analysis metadata.
Schema designed for easy querying of patterns across profiles and conversations.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS simulation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    profile_count INTEGER,
    total_turns INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES simulation_runs(id),
    profile_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    profile_category TEXT NOT NULL,
    conversation_id TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_turns INTEGER DEFAULT 0,
    successful_turns INTEGER DEFAULT 0,
    blocked_turns INTEGER DEFAULT 0,
    error_turns INTEGER DEFAULT 0,
    total_response_time_ms REAL DEFAULT 0,
    avg_response_time_ms REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_pk INTEGER NOT NULL REFERENCES conversations(id),
    turn_number INTEGER NOT NULL,
    -- Request
    user_message TEXT NOT NULL,
    intent_label TEXT NOT NULL,
    expected_domain TEXT,
    -- Response
    success INTEGER NOT NULL DEFAULT 0,
    response_content TEXT,
    response_domain TEXT,
    error_code TEXT,
    error_message TEXT,
    -- Metadata
    response_time_ms REAL,
    conversation_id_returned TEXT,
    layer_timings_json TEXT,
    request_id TEXT,
    -- Analysis
    domain_match INTEGER,  -- 1 if response_domain == expected_domain, 0 if mismatch, NULL if no expectation
    sent_at TEXT NOT NULL,
    received_at TEXT
);

CREATE TABLE IF NOT EXISTS analysis_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES simulation_runs(id),
    category TEXT NOT NULL,  -- 'routing', 'security', 'quality', 'performance', 'edge_case'
    severity TEXT NOT NULL,  -- 'info', 'warning', 'issue', 'critical'
    profile_id TEXT,
    turn_id INTEGER REFERENCES turns(id),
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_conversation ON turns(conversation_pk);
CREATE INDEX IF NOT EXISTS idx_turns_intent ON turns(intent_label);
CREATE INDEX IF NOT EXISTS idx_turns_domain ON turns(response_domain);
CREATE INDEX IF NOT EXISTS idx_conversations_run ON conversations(run_id);
CREATE INDEX IF NOT EXISTS idx_conversations_profile ON conversations(profile_id);
CREATE INDEX IF NOT EXISTS idx_findings_run ON analysis_findings(run_id);
CREATE INDEX IF NOT EXISTS idx_findings_category ON analysis_findings(category);
"""


class SimulationDB:
    """SQLite database for simulation tracking."""

    def __init__(self, db_path: str | Path = "simulation_results.db"):
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

    # -- Simulation runs --

    def create_run(self, profile_count: int, notes: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO simulation_runs (started_at, profile_count, notes) VALUES (?, ?, ?)",
            (self._now(), profile_count, notes),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    def finish_run(self, run_id: int, total_turns: int, total_errors: int):
        self.conn.execute(
            "UPDATE simulation_runs SET finished_at=?, total_turns=?, total_errors=? WHERE id=?",
            (self._now(), total_turns, total_errors, run_id),
        )
        self.conn.commit()

    # -- Conversations --

    def create_conversation(
        self, run_id: int, profile_id: str, profile_name: str, profile_category: str
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO conversations (run_id, profile_id, profile_name, profile_category, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, profile_id, profile_name, profile_category, self._now()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    def finish_conversation(
        self,
        conv_pk: int,
        conversation_id: str | None,
        total_turns: int,
        successful: int,
        blocked: int,
        errors: int,
        total_time_ms: float,
    ):
        avg_time = total_time_ms / total_turns if total_turns > 0 else 0
        self.conn.execute(
            "UPDATE conversations SET finished_at=?, conversation_id=?, total_turns=?, "
            "successful_turns=?, blocked_turns=?, error_turns=?, "
            "total_response_time_ms=?, avg_response_time_ms=? WHERE id=?",
            (self._now(), conversation_id, total_turns, successful, blocked, errors, total_time_ms, avg_time, conv_pk),
        )
        self.conn.commit()

    # -- Turns --

    def record_turn(
        self,
        conversation_pk: int,
        turn_number: int,
        user_message: str,
        intent_label: str,
        expected_domain: str | None,
        success: bool,
        response_content: str | None,
        response_domain: str | None,
        error_code: str | None,
        error_message: str | None,
        response_time_ms: float | None,
        conversation_id_returned: str | None,
        layer_timings_json: str | None,
        request_id: str | None,
    ) -> int:
        # Calculate domain match
        domain_match = None
        if expected_domain is not None and response_domain is not None:
            domain_match = 1 if response_domain.upper() == expected_domain.upper() else 0

        cur = self.conn.execute(
            "INSERT INTO turns (conversation_pk, turn_number, user_message, intent_label, "
            "expected_domain, success, response_content, response_domain, error_code, "
            "error_message, response_time_ms, conversation_id_returned, layer_timings_json, "
            "request_id, domain_match, sent_at, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_pk, turn_number, user_message, intent_label,
                expected_domain, 1 if success else 0, response_content, response_domain,
                error_code, error_message, response_time_ms, conversation_id_returned,
                layer_timings_json, request_id, domain_match,
                self._now(), self._now() if success else None,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    # -- Analysis findings --

    def add_finding(
        self,
        run_id: int,
        category: str,
        severity: str,
        title: str,
        detail: str,
        profile_id: str | None = None,
        turn_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO analysis_findings (run_id, category, severity, profile_id, turn_id, title, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, category, severity, profile_id, turn_id, title, detail, self._now()),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    # -- Query helpers --

    def get_run(self, run_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM simulation_runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_conversations(self, run_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM conversations WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_turns(self, conversation_pk: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM turns WHERE conversation_pk=? ORDER BY turn_number", (conversation_pk,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_turns_for_run(self, run_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT t.*, c.profile_id, c.profile_name, c.profile_category "
            "FROM turns t "
            "JOIN conversations c ON t.conversation_pk = c.id "
            "WHERE c.run_id = ? ORDER BY c.id, t.turn_number",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_findings(self, run_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM analysis_findings WHERE run_id=? ORDER BY severity DESC, category, id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
