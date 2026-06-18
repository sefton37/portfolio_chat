"""
Unit tests for the battery harness pure-logic functions.

Tests tokens/sec calculation, Pareto frontier computation, FP/FN tallying,
and BatteryDB schema integrity. These tests do NOT make network calls.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.battery.db import BatteryDB
from tests.battery.engine import (
    InstrumentedOllamaClient,
    LAYER2_ATTACKS,
    _response_blocked,
)
from tests.battery.report import _compute_pareto, _recommended_pair


# ---------------------------------------------------------------------------
# tokens_per_sec calculation
# ---------------------------------------------------------------------------

class TestTokensPerSec:
    """Test InstrumentedOllamaClient._capture_perf tokens/sec calculation."""

    def _make_client(self) -> InstrumentedOllamaClient:
        return InstrumentedOllamaClient(url="http://localhost:11434", default_model="test")

    def test_tokens_per_sec_basic(self):
        """eval_count=100 tokens over 1 second = 100 tokens/sec."""
        client = self._make_client()
        client._capture_perf({
            "eval_count": 100,
            "eval_duration": 1_000_000_000,  # 1 second in nanoseconds
            "prompt_eval_count": 20,
            "prompt_eval_duration": 200_000_000,  # 0.2 seconds
        })
        assert abs(client.last_tokens_per_sec - 100.0) < 0.01

    def test_tokens_per_sec_fractional(self):
        """50 tokens over 0.5 seconds = 100 tokens/sec."""
        client = self._make_client()
        client._capture_perf({
            "eval_count": 50,
            "eval_duration": 500_000_000,  # 0.5 seconds
        })
        assert abs(client.last_tokens_per_sec - 100.0) < 0.01

    def test_tokens_per_sec_null_on_zero_duration(self):
        """Zero eval_duration should not produce division-by-zero."""
        client = self._make_client()
        client._capture_perf({
            "eval_count": 10,
            "eval_duration": 0,
        })
        assert client.last_tokens_per_sec is None

    def test_tokens_per_sec_null_on_missing_fields(self):
        """Missing eval fields should produce None, not raise."""
        client = self._make_client()
        client._capture_perf({})
        assert client.last_tokens_per_sec is None
        assert client.last_eval_count is None

    def test_prompt_eval_rate(self):
        """prompt_eval_count / prompt_eval_duration should compute prompt_eval_rate."""
        client = self._make_client()
        client._capture_perf({
            "eval_count": 10,
            "eval_duration": 100_000_000,
            "prompt_eval_count": 200,
            "prompt_eval_duration": 1_000_000_000,  # 1 second
        })
        assert abs(client.last_prompt_eval_rate - 200.0) < 0.01

    def test_reset_perf(self):
        """_reset_perf should clear all fields to None."""
        client = self._make_client()
        client._capture_perf({
            "eval_count": 5,
            "eval_duration": 100_000_000,
        })
        assert client.last_eval_count == 5
        client._reset_perf()
        assert client.last_eval_count is None
        assert client.last_tokens_per_sec is None


# ---------------------------------------------------------------------------
# Pareto frontier
# ---------------------------------------------------------------------------

class TestParetoFrontier:
    """Test the Pareto-dominance computation in report.py."""

    def _row(
        self,
        classifier: str,
        generator: str,
        judge: float | None = 0.5,
        tps: float | None = 50.0,
        fn: int | None = 0,
    ) -> dict:
        return {
            "classifier_name": classifier,
            "generator_name": generator,
            "avg_judge_score": judge,
            "avg_tokens_per_sec": tps,
            "fn_count": fn,
        }

    def test_single_row_is_pareto(self):
        """A single row is always on the Pareto frontier."""
        rows = [self._row("clf", "gen")]
        flags = _compute_pareto(rows)
        assert flags == [True]

    def test_dominated_row_not_pareto(self):
        """Row A with lower judge+tps and higher fn is dominated by row B."""
        rows = [
            self._row("clf", "gen_a", judge=0.3, tps=30.0, fn=3),  # worse on all
            self._row("clf", "gen_b", judge=0.7, tps=70.0, fn=1),  # better on all
        ]
        flags = _compute_pareto(rows)
        assert flags[0] is False  # gen_a dominated
        assert flags[1] is True   # gen_b on frontier

    def test_tradeoff_both_pareto(self):
        """Row A: fast but insecure vs. Row B: slow but secure — both on frontier."""
        rows = [
            self._row("clf", "gen_a", judge=0.5, tps=100.0, fn=5),  # fast, insecure
            self._row("clf", "gen_b", judge=0.5, tps=30.0, fn=0),   # slow, secure
        ]
        flags = _compute_pareto(rows)
        assert flags[0] is True
        assert flags[1] is True

    def test_empty_rows(self):
        """Empty input returns empty flags."""
        assert _compute_pareto([]) == []

    def test_three_rows_with_one_dominated(self):
        """Three rows, one dominated."""
        rows = [
            self._row("clf", "gen_a", judge=0.4, tps=40.0, fn=4),  # dominated
            self._row("clf", "gen_b", judge=0.8, tps=80.0, fn=0),  # dominates gen_a
            self._row("clf", "gen_c", judge=0.5, tps=50.0, fn=2),  # dominates gen_a
        ]
        flags = _compute_pareto(rows)
        assert flags[0] is False  # gen_a dominated
        assert flags[1] is True   # gen_b on frontier
        # gen_c: gen_b has higher judge+tps and lower fn → gen_c is dominated by gen_b
        assert flags[2] is False


# ---------------------------------------------------------------------------
# Recommended pairing
# ---------------------------------------------------------------------------

class TestRecommendedPairing:
    """Test the composite scoring heuristic for recommended pair selection."""

    def _row(self, classifier: str, generator: str, judge: float | None, tps: float | None, fn: int) -> dict:
        return {
            "classifier_name": classifier,
            "generator_name": generator,
            "avg_judge_score": judge,
            "avg_tokens_per_sec": tps,
            "fn_count": fn,
        }

    def test_empty_returns_none(self):
        assert _recommended_pair([]) is None

    def test_single_row_returned(self):
        row = self._row("clf", "gen", 0.8, 60.0, 0)
        result = _recommended_pair([row])
        assert result is not None
        assert result["generator_name"] == "gen"

    def test_higher_composite_wins(self):
        """Row with higher judge*tps/(fn+1) is recommended."""
        rows = [
            self._row("clf", "gen_a", 0.9, 100.0, 0),  # 0.9*100/(0+1) = 90.0
            self._row("clf", "gen_b", 0.5, 50.0, 0),   # 0.5*50/(0+1) = 25.0
        ]
        result = _recommended_pair(rows)
        assert result is not None
        assert result["generator_name"] == "gen_a"

    def test_high_fn_penalizes_score(self):
        """High fn_count reduces composite score."""
        rows = [
            self._row("clf", "gen_a", 0.9, 100.0, 9),  # 0.9*100/10 = 9.0
            self._row("clf", "gen_b", 0.5, 60.0, 0),   # 0.5*60/1 = 30.0
        ]
        result = _recommended_pair(rows)
        assert result is not None
        assert result["generator_name"] == "gen_b"

    def test_null_judge_uses_default(self):
        """NULL judge_score should not raise; falls back to neutral default."""
        rows = [
            self._row("clf", "gen_a", None, 100.0, 0),
            self._row("clf", "gen_b", 0.8, 60.0, 0),
        ]
        result = _recommended_pair(rows)
        assert result is not None  # should not raise


# ---------------------------------------------------------------------------
# FP/FN tally
# ---------------------------------------------------------------------------

class TestFpFnTally:
    """Test that BatteryDB.record_security_score correctly stores fp/fn counts."""

    def test_security_score_upsert(self):
        """record_security_score writes and updates fp/fn in battery_scores."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = BatteryDB(Path(tmpdir) / "test.db")
            run_id = db.create_run("clf", "gen", is_baseline=False)

            # First write
            db.record_security_score(run_id, "clf", "gen", fp_count=2, fn_count=3)
            scores = db.get_scores(run_id)
            assert len(scores) == 1
            assert scores[0]["fp_count"] == 2
            assert scores[0]["fn_count"] == 3

            # Update (upsert path)
            db.record_security_score(run_id, "clf", "gen", fp_count=1, fn_count=1)
            scores = db.get_scores(run_id)
            assert len(scores) == 1
            assert scores[0]["fp_count"] == 1
            assert scores[0]["fn_count"] == 1

    def test_multiple_pairs_separate_rows(self):
        """Different (classifier, generator) pairs get separate battery_scores rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = BatteryDB(Path(tmpdir) / "test.db")
            run_id = db.create_run("clf_a", "gen_a", is_baseline=False)

            db.record_security_score(run_id, "clf_a", "gen_a", fp_count=0, fn_count=2)
            db.record_security_score(run_id, "clf_b", "gen_b", fp_count=1, fn_count=0)

            scores = db.get_scores(run_id)
            assert len(scores) == 2
            classifiers = {s["classifier_name"] for s in scores}
            assert "clf_a" in classifiers
            assert "clf_b" in classifiers


# ---------------------------------------------------------------------------
# BatteryDB schema
# ---------------------------------------------------------------------------

class TestBatteryDBSchema:
    """Smoke test that BatteryDB creates all expected tables and columns."""

    def test_tables_exist(self):
        """All three battery tables should be created on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = BatteryDB(Path(tmpdir) / "test.db")
            tables = {
                row[0] for row in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "battery_runs" in tables
            assert "battery_turns" in tables
            assert "battery_scores" in tables

    def test_tokens_per_sec_column_exists(self):
        """battery_turns must have tokens_per_sec column (DOD-7)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = BatteryDB(Path(tmpdir) / "test.db")
            cols = {
                row[1] for row in db.conn.execute(
                    "PRAGMA table_info(battery_turns)"
                ).fetchall()
            }
            assert "tokens_per_sec" in cols
            assert "eval_count" in cols

    def test_fp_fn_columns_exist(self):
        """battery_scores must have fp_count and fn_count columns (DOD-12)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = BatteryDB(Path(tmpdir) / "test.db")
            cols = {
                row[1] for row in db.conn.execute(
                    "PRAGMA table_info(battery_scores)"
                ).fetchall()
            }
            assert "fp_count" in cols
            assert "fn_count" in cols

    def test_is_baseline_column_exists(self):
        """battery_runs must have is_baseline column (DOD-13)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = BatteryDB(Path(tmpdir) / "test.db")
            cols = {
                row[1] for row in db.conn.execute(
                    "PRAGMA table_info(battery_runs)"
                ).fetchall()
            }
            assert "is_baseline" in cols

    def test_create_run_returns_int(self):
        """create_run should return a positive integer run_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = BatteryDB(Path(tmpdir) / "test.db")
            run_id = db.create_run("clf", "gen", is_baseline=True)
            assert isinstance(run_id, int)
            assert run_id > 0

    def test_is_baseline_stored(self):
        """is_baseline=True should be stored as 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = BatteryDB(Path(tmpdir) / "test.db")
            run_id = db.create_run("clf", "gen", is_baseline=True)
            row = db.conn.execute(
                "SELECT is_baseline FROM battery_runs WHERE id=?", (run_id,)
            ).fetchone()
            assert row[0] == 1


# ---------------------------------------------------------------------------
# LAYER2_ATTACKS import
# ---------------------------------------------------------------------------

class TestLayer2AttacksImport:
    """Verify LAYER2_ATTACKS imports correctly from the security test class."""

    def test_layer2_attacks_is_list(self):
        """LAYER2_ATTACKS should be a non-empty list of strings."""
        assert isinstance(LAYER2_ATTACKS, list)
        assert len(LAYER2_ATTACKS) > 0
        assert all(isinstance(a, str) for a in LAYER2_ATTACKS)

    def test_layer2_attacks_count(self):
        """LAYER2_ATTACKS should carry a meaningful corpus from test_injection.py.

        Asserted as a floor, not a magic number, so reclassifying an attack
        between the L1-blocked and L2-needed sets doesn't break this test.
        """
        assert len(LAYER2_ATTACKS) >= 8


# ---------------------------------------------------------------------------
# _response_blocked — the false-positive / false-negative detector
# (regression guard for the audit red-team finding: a blocked legit turn must
#  NOT be recorded as success, or fp_count is structurally always 0)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, success=True, error_code=None, blocked=False, content="ok"):
        self.success = success
        self.error_code = error_code
        self.blocked = blocked
        self.content = content


class TestResponseBlocked:
    def test_clean_response_not_blocked(self):
        assert _response_blocked(_FakeResponse(success=True)) is False

    def test_error_code_means_blocked(self):
        # The over-blocking case: pipeline returns blocked_input without raising.
        assert _response_blocked(_FakeResponse(success=False, error_code="blocked_input")) is True

    def test_success_false_means_blocked(self):
        assert _response_blocked(_FakeResponse(success=False)) is True

    def test_blocked_flag_means_blocked(self):
        assert _response_blocked(_FakeResponse(blocked=True)) is True

    def test_fp_query_counts_blocked_legit_turn(self, tmp_path):
        """End-to-end at the DB layer: a non-adversarial turn recorded as a block
        (success=0, error_message set) must be counted by the FP query — proving
        the FP axis is live, not inert."""
        db = BatteryDB(str(tmp_path / "fp.db"))
        run_id = db.create_run(
            classifier_name="c", generator_name="g", is_baseline=False, config={}
        )
        # A legitimate (recruiter) persona turn that got blocked.
        db.record_turn(
            run_id=run_id, classifier_name="c", generator_name="g",
            profile_id="recruiter", profile_category="recruiter", turn_number=1,
            intent="ask", total_time_ms=1.0, time_to_first_token=None,
            eval_count=None, eval_duration_ns=None, tokens_per_sec=None,
            prompt_eval_count=None, prompt_eval_duration_ns=None, prompt_eval_rate=None,
            judge_score=None, hallucination_count=None,
            user_message="What is Kellogg's experience?", response_content=None,
            success=0, error_message="blocked:blocked_input",
            vram_mb=None, sent_at="t", received_at="t",
        )
        n = db.conn.execute(
            "SELECT COUNT(*) FROM battery_turns WHERE run_id=? AND success=0 "
            "AND error_message IS NOT NULL AND profile_category NOT IN ('adversarial')",
            (run_id,),
        ).fetchone()[0]
        assert n == 1, "blocked legitimate turn must be counted as a false positive"
