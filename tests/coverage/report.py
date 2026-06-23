"""
CoverageReport — reads CoverageDB, aggregates results, renders Markdown.

Headline section: tone_robustness table — rows=tones, cols=pass rates + latency.

Report sections:
1. Overall pass rate per category
2. tone_robustness table (per-tone breakdown vs neutral baseline) — includes 'adversarial'
3. in_scope coverage gaps (failed question_ids)
4. adjacent fabrications (failed turns)
5. left_field compliance failures (failed turns)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tests.coverage.db import CoverageDB

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).parent / "results" / "coverage.db"
_DEFAULT_REPORT_PATH = Path(__file__).parent / "results" / "REPORT.md"

_ALL_TONES = ["neutral", "adversarial", "anxious", "angry", "aloof", "wordy"]
_CATEGORIES = ["in_scope", "adjacent", "left_field"]


class CoverageReport:
    """Reads CoverageDB and renders a Markdown coverage report."""

    def __init__(self, db: CoverageDB | None = None, db_path: Path | str | None = None) -> None:
        if db is not None:
            self._db = db
        else:
            path = Path(db_path) if db_path else _DEFAULT_DB_PATH
            self._db = CoverageDB(db_path=path)

    def build(
        self,
        run_id: str | None = None,
        out_path: Path | str | None = None,
    ) -> str:
        """
        Build the Markdown report and write it to disk.

        Args:
            run_id:   Filter to specific run. If None, uses all turns.
            out_path: Where to write REPORT.md. Defaults to results/REPORT.md.

        Returns:
            The full Markdown string.
        """
        out_path = Path(out_path) if out_path else _DEFAULT_REPORT_PATH
        out_path.parent.mkdir(parents=True, exist_ok=True)

        sections: list[str] = []

        sections.append("# Coverage Report\n")

        # --- Overall pass rates ---
        sections.append("## Overall Pass Rate by Category\n")
        sections.append(self._build_overall_section(run_id))

        # --- tone_robustness (headline) ---
        sections.append("## tone_robustness\n")
        sections.append(
            "_Per-tone pass rates compared to neutral baseline. "
            "Includes adversarial, anxious, angry, aloof, and wordy tones._\n"
        )
        sections.append(self._build_tone_robustness_table(run_id))

        # --- Coverage gaps ---
        sections.append("## in_scope Coverage Gaps\n")
        sections.append(self._build_in_scope_gaps(run_id))

        # --- Adjacent fabrications ---
        sections.append("## adjacent Fabrications\n")
        sections.append(self._build_adjacent_failures(run_id))

        # --- Left-field compliance failures ---
        sections.append("## left_field Compliance Failures\n")
        sections.append(self._build_left_field_failures(run_id))

        markdown = "\n".join(sections)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        return markdown

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_overall_section(self, run_id: str | None) -> str:
        stats = self._db.category_tone_stats(run_id)
        if not stats:
            return "_No data recorded yet._\n"

        # Aggregate per category (all tones combined)
        totals: dict[str, dict[str, int]] = {}
        for row in stats:
            cat = row["category"]
            if cat not in totals:
                totals[cat] = {"total": 0, "passed": 0}
            totals[cat]["total"] += row["total"]
            totals[cat]["passed"] += row["passed"]

        lines = ["| Category | Total Turns | Passed | Pass Rate |", "|---|---|---|---|"]
        for cat in _CATEGORIES:
            if cat in totals:
                t = totals[cat]["total"]
                p = totals[cat]["passed"]
                rate = f"{100 * p / t:.1f}%" if t > 0 else "N/A"
                lines.append(f"| {cat} | {t} | {p} | {rate} |")
        return "\n".join(lines) + "\n"

    def _build_tone_robustness_table(self, run_id: str | None) -> str:
        """
        Build the tone_robustness table.

        Rows = tones (neutral first, then adversarial + others alphabetically).
        Cols = in_scope correct%, adjacent resisted%, left_field refused%, mean latency.
        """
        stats = self._db.category_tone_stats(run_id)

        # Index stats by (category, tone)
        idx: dict[tuple[str, str], dict[str, Any]] = {}
        for row in stats:
            idx[(row["category"], row["tone"])] = row

        # Determine tone ordering: neutral first, adversarial second, rest sorted
        present_tones: set[str] = {row["tone"] for row in stats}
        tone_order = ["neutral", "adversarial"] + sorted(
            t for t in present_tones if t not in {"neutral", "adversarial"}
        )
        # Fall back to all standard tones if no data
        if not tone_order:
            tone_order = _ALL_TONES

        header = (
            "| Tone | in_scope correct% | adjacent resisted% | "
            "left_field refused% | mean latency (ms) |"
        )
        sep = "|---|---|---|---|---|"
        lines = [header, sep]

        for tone in tone_order:
            def _pct(cat: str) -> str:
                row = idx.get((cat, tone))
                if not row:
                    return "N/A"
                t = row["total"]
                p = row["passed"]
                return f"{100 * p / t:.1f}%" if t > 0 else "N/A"

            def _lat(tone_: str) -> str:
                lats = [
                    row["mean_latency_ms"]
                    for row in stats
                    if row["tone"] == tone_ and row["mean_latency_ms"] is not None
                ]
                if not lats:
                    return "N/A"
                return f"{sum(lats) / len(lats):.0f}"

            lines.append(
                f"| {tone} | {_pct('in_scope')} | {_pct('adjacent')} | "
                f"{_pct('left_field')} | {_lat(tone)} |"
            )

        return "\n".join(lines) + "\n"

    def _build_in_scope_gaps(self, run_id: str | None) -> str:
        """List in_scope question_ids that failed on neutral tone."""
        failures = self._db.failures(run_id=run_id, category="in_scope", tone="neutral")
        if not failures:
            return "_No in_scope neutral failures found._\n"

        lines = ["| question_id | domain | verdict | judge_score |", "|---|---|---|---|"]
        for f in failures:
            lines.append(
                f"| {f['question_id']} | {f.get('domain') or 'N/A'} "
                f"| {f.get('verdict') or 'N/A'} "
                f"| {f.get('judge_score') or 'N/A'} |"
            )
        return "\n".join(lines) + "\n"

    def _build_adjacent_failures(self, run_id: str | None) -> str:
        """List adjacent turns that fabricated (verdict='fabricated')."""
        all_fails = self._db.failures(run_id=run_id, category="adjacent")
        failures = [f for f in all_fails if f.get("verdict") == "fabricated"]
        if not failures:
            return "_No adjacent fabrication failures found._\n"

        lines = ["| question_id | tone | response_text (truncated) |", "|---|---|---|"]
        for f in failures:
            resp = (f.get("response_text") or "")[:120].replace("\n", " ")
            lines.append(f"| {f['question_id']} | {f['tone']} | {resp} |")
        return "\n".join(lines) + "\n"

    def _build_left_field_failures(self, run_id: str | None) -> str:
        """List left_field turns where the bot complied (verdict='answered')."""
        all_fails = self._db.failures(run_id=run_id, category="left_field")
        failures = [f for f in all_fails if f.get("verdict") == "answered"]
        if not failures:
            return "_No left_field compliance failures found._\n"

        lines = ["| question_id | tone | response_text (truncated) |", "|---|---|---|"]
        for f in failures:
            resp = (f.get("response_text") or "")[:120].replace("\n", " ")
            lines.append(f"| {f['question_id']} | {f['tone']} | {resp} |")
        return "\n".join(lines) + "\n"
