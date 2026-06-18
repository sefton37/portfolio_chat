"""
BatteryReport — markdown report generator for the model-evaluation battery.

Sections:
  1. Executive Summary
  2. Pareto Analysis (DOD-20, DOD-29)
  3. Security Matrix
  4. Latency Distribution
  5. VRAM Budget
  6. Recommended Pairing (DOD-21, DOD-30)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.battery.db import BatteryDB


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt(val: float | None, decimals: int = 2, suffix: str = "") -> str:
    """Format a nullable float."""
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}{suffix}"


def _trunc(text: str | None, length: int = 80) -> str:
    """Truncate and escape text for markdown tables."""
    if not text:
        return ""
    text = text.replace("|", "\\|").replace("\n", " ").strip()
    return text[:length] + "..." if len(text) > length else text


# ---------------------------------------------------------------------------
# Pareto frontier helpers
# ---------------------------------------------------------------------------

def _compute_pareto(rows: list[dict[str, Any]]) -> list[bool]:
    """
    Compute Pareto-dominance flags for a list of battery_scores rows.

    A row is Pareto-optimal if no other row simultaneously has:
    - higher avg_judge_score (or both null)
    - higher avg_tokens_per_sec
    - lower fn_count

    Returns a list of booleans (same length as rows) — True = Pareto frontier.
    """
    n = len(rows)
    dominated = [False] * n

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            ri = rows[i]
            rj = rows[j]
            # Check if rj dominates ri on all three axes
            judge_ok = (
                (rj.get("avg_judge_score") or 0.0) >= (ri.get("avg_judge_score") or 0.0)
            )
            tps_ok = (
                (rj.get("avg_tokens_per_sec") or 0.0) >= (ri.get("avg_tokens_per_sec") or 0.0)
            )
            fn_ok = (
                (rj.get("fn_count") or 0) <= (ri.get("fn_count") or 0)
            )
            # Strictly better on at least one axis
            judge_better = (rj.get("avg_judge_score") or 0.0) > (ri.get("avg_judge_score") or 0.0)
            tps_better = (rj.get("avg_tokens_per_sec") or 0.0) > (ri.get("avg_tokens_per_sec") or 0.0)
            fn_better = (rj.get("fn_count") or 0) < (ri.get("fn_count") or 0)

            if judge_ok and tps_ok and fn_ok and (judge_better or tps_better or fn_better):
                dominated[i] = True
                break

    return [not d for d in dominated]


def _recommended_pair(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Select the recommended classifier+generator pairing.

    Heuristic: highest composite score =
        avg_judge_score * avg_tokens_per_sec / (fn_count + 1)

    Falls back to highest tokens_per_sec when judge_score is NULL.
    """
    if not rows:
        return None

    def composite(row: dict[str, Any]) -> float:
        judge = row.get("avg_judge_score") or 0.5  # neutral default
        tps = row.get("avg_tokens_per_sec") or 0.0
        fn = (row.get("fn_count") or 0)
        return judge * tps / (fn + 1)

    return max(rows, key=composite)


# ---------------------------------------------------------------------------
# BatteryReport
# ---------------------------------------------------------------------------

class BatteryReport:
    """
    Generate comprehensive markdown reports from battery_scores data.

    Usage:
        db = BatteryDB("battery.db")
        report = BatteryReport(db, run_id=1)
        path = report.generate("tests/battery/results/")
        report.print_terminal_summary()
    """

    def __init__(self, db: BatteryDB, run_id: int) -> None:
        self.db = db
        self.run_id = run_id
        self._scores = self.db.get_scores(run_id)
        self._all_scores = self.db.get_all_scores()

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def _section_executive_summary(self, run_row: dict[str, Any]) -> list[str]:
        lines: list[str] = ["## 1. Executive Summary", ""]
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| Run ID | {self.run_id} |")
        lines.append(f"| Started | {run_row.get('started_at', 'unknown')} |")
        lines.append(f"| Finished | {run_row.get('finished_at', 'in progress')} |")
        lines.append(f"| Classifier | {run_row.get('classifier_name', 'N/A')} |")
        lines.append(f"| Generator | {run_row.get('generator_name', 'N/A')} |")
        lines.append(f"| Baseline | {'yes' if run_row.get('is_baseline') else 'no'} |")
        if run_row.get("notes"):
            lines.append(f"| Notes | {_trunc(run_row['notes'])} |")
        lines.append("")
        return lines

    def _section_pareto(self) -> list[str]:
        """
        ## Pareto Analysis — Pareto frontier across all battery_scores rows.

        Satisfies DOD-20 (Pareto section) and DOD-29 (## Pareto heading).
        """
        lines: list[str] = ["## Pareto Analysis", ""]
        lines.append(
            "Pareto-optimal rows marked with `*` (not dominated on judge_score, "
            "tokens_per_sec, and fn_count simultaneously)."
        )
        lines.append("")

        scores = self._all_scores if self._all_scores else self._scores
        if not scores:
            lines.append("*No scores available.*")
            lines.append("")
            return lines

        pareto_flags = _compute_pareto(scores)

        # Table header
        headers = [
            "P*", "Classifier", "Generator", "Judge Score",
            "Tokens/sec", "Avg Time (ms)", "VRAM MB", "FN", "FP",
        ]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["-" * max(len(h), 4) for h in headers]) + " |")

        for row, is_pareto in zip(scores, pareto_flags):
            marker = "*" if is_pareto else ""
            lines.append(
                f"| {marker}"
                f" | {row.get('classifier_name', 'N/A')}"
                f" | {row.get('generator_name', 'N/A')}"
                f" | {_fmt(row.get('avg_judge_score'))}"
                f" | {_fmt(row.get('avg_tokens_per_sec'))}"
                f" | {_fmt(row.get('avg_total_time_ms'), 0)}"
                f" | {_fmt(row.get('vram_mb'), 0)}"
                f" | {row.get('fn_count', 'N/A')}"
                f" | {row.get('fp_count', 'N/A')}"
                f" |"
            )

        lines.append("")
        return lines

    def _section_security_matrix(self) -> list[str]:
        """## 3. Security Matrix — FP/FN per (classifier, generator) pair."""
        lines: list[str] = ["## 3. Security Matrix", ""]
        scores = self._scores
        if not scores:
            lines.append("*No security scores available.*")
            lines.append("")
            return lines

        headers = ["Classifier", "Generator", "FP Count", "FN Count"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["-" * 12] * len(headers)) + " |")

        for row in scores:
            lines.append(
                f"| {row.get('classifier_name', 'N/A')}"
                f" | {row.get('generator_name', 'N/A')}"
                f" | {row.get('fp_count', 'N/A')}"
                f" | {row.get('fn_count', 'N/A')}"
                f" |"
            )

        lines.append("")
        lines.append(
            "_FP: legitimate query blocked. FN: attack not blocked by classifier._"
        )
        lines.append("")
        return lines

    def _section_latency(self) -> list[str]:
        """## 4. Latency Distribution."""
        lines: list[str] = ["## 4. Latency Distribution", ""]
        scores = self._scores
        if not scores:
            lines.append("*No latency data available.*")
            lines.append("")
            return lines

        headers = ["Classifier", "Generator", "Avg TPS", "P50 TPS", "Avg TTFT (s)", "Avg Time (ms)"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["-" * 12] * len(headers)) + " |")

        for row in scores:
            lines.append(
                f"| {row.get('classifier_name', 'N/A')}"
                f" | {row.get('generator_name', 'N/A')}"
                f" | {_fmt(row.get('avg_tokens_per_sec'))}"
                f" | {_fmt(row.get('p50_tokens_per_sec'))}"
                f" | {_fmt(row.get('avg_time_to_first_token'))}"
                f" | {_fmt(row.get('avg_total_time_ms'), 0)}"
                f" |"
            )

        lines.append("")
        return lines

    def _section_vram(self) -> list[str]:
        """## 5. VRAM Budget."""
        lines: list[str] = ["## 5. VRAM Budget", ""]
        scores = self._scores
        if not scores:
            lines.append("*No VRAM data available.*")
            lines.append("")
            return lines

        # Pull from battery_runs for per-model VRAM
        run_row = self.db.conn.execute(
            "SELECT classifier_vram_mb, generator_vram_mb, classifier_name, generator_name "
            "FROM battery_runs WHERE id=?",
            (self.run_id,),
        ).fetchone()

        if run_row:
            lines.append(f"| Model | Role | VRAM (MB) |")
            lines.append(f"|-------|------|-----------|")
            lines.append(
                f"| {run_row['classifier_name']} | classifier | {_fmt(run_row['classifier_vram_mb'], 0)} |"
            )
            lines.append(
                f"| {run_row['generator_name']} | generator | {_fmt(run_row['generator_vram_mb'], 0)} |"
            )
        else:
            lines.append("*No per-model VRAM data recorded.*")

        lines.append("")
        return lines

    def _section_recommended_pairing(self) -> list[str]:
        """
        ## 6. Recommended Pairing (DOD-21, DOD-30)

        Emits a `**Recommended pair:** ...` line for automated grep checks.
        """
        lines: list[str] = ["## 6. Recommended Pairing", ""]

        scores = self._all_scores if self._all_scores else self._scores
        best = _recommended_pair(scores)

        if best:
            classifier = best.get("classifier_name", "unknown")
            generator = best.get("generator_name", "unknown")
            judge = _fmt(best.get("avg_judge_score"))
            tps = _fmt(best.get("avg_tokens_per_sec"))
            fn = best.get("fn_count", "N/A")
            lines.append(
                f"**Recommended pair:** {classifier} + {generator} "
                f"(score/latency/security composite)"
            )
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Classifier | {classifier} |")
            lines.append(f"| Generator | {generator} |")
            lines.append(f"| Avg Judge Score | {judge} |")
            lines.append(f"| Avg Tokens/sec | {tps} |")
            lines.append(f"| FN Count | {fn} |")
        else:
            lines.append("*No scores available to compute recommended pairing.*")

        lines.append("")
        return lines

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, output_dir: str | Path | None = None) -> Path:
        """
        Generate the full markdown report and write to output_dir.

        Returns the path to the generated report file.
        """
        from datetime import datetime

        # Load run metadata
        run_row_raw = self.db.conn.execute(
            "SELECT * FROM battery_runs WHERE id=?", (self.run_id,)
        ).fetchone()
        run_row: dict[str, Any] = dict(run_row_raw) if run_row_raw else {}

        lines: list[str] = []
        lines.append(f"# Battery Report — Run #{self.run_id}")
        lines.append("")
        lines.append("---")
        lines.append("")

        lines.extend(self._section_executive_summary(run_row))
        lines.extend(self._section_pareto())
        lines.extend(self._section_security_matrix())
        lines.extend(self._section_latency())
        lines.extend(self._section_vram())
        lines.extend(self._section_recommended_pairing())

        lines.append("---")
        lines.append(f"*Generated by BatteryReport — Run #{self.run_id}*")

        report_text = "\n".join(lines)

        # Resolve output path
        if output_dir is None:
            output_dir = Path(__file__).parent / "results"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"battery_report_run{self.run_id}_{timestamp}.md"
        report_path.write_text(report_text)

        logger.info(f"Report written to: {report_path}")
        return report_path

    def print_terminal_summary(self) -> None:
        """Print a concise summary to the terminal."""
        import logging as _logging
        logger = _logging.getLogger(__name__)

        width = 72
        print(f"\n{'=' * width}")
        print(f"  BATTERY RUN #{self.run_id}")
        print(f"{'=' * width}")

        scores = self._scores
        if not scores:
            print("  No scores available.")
            print(f"{'=' * width}\n")
            return

        headers = f"  {'Classifier':<20} {'Generator':<20} {'TPS':>8} {'Judge':>7} {'FN':>4} {'FP':>4}"
        print(headers)
        print(f"  {'-' * 64}")

        for row in scores:
            clf = (row.get("classifier_name") or "N/A")[:20]
            gen = (row.get("generator_name") or "N/A")[:20]
            tps = _fmt(row.get("avg_tokens_per_sec"))
            judge = _fmt(row.get("avg_judge_score"))
            fn = str(row.get("fn_count", "N/A"))
            fp = str(row.get("fp_count", "N/A"))
            print(f"  {clf:<20} {gen:<20} {tps:>8} {judge:>7} {fn:>4} {fp:>4}")

        best = _recommended_pair(scores)
        if best:
            print(f"\n  Recommended pair: {best.get('classifier_name')} + {best.get('generator_name')}")

        print(f"\n{'=' * width}\n")


import logging  # noqa: E402 — must import after class definition for logger refs
logger = logging.getLogger(__name__)
