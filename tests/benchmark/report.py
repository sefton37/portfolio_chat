"""
Benchmark report generator.

Produces comprehensive markdown reports from benchmark results to help decide
which model to use and where performance can be improved. Also supports
machine-readable JSON summaries and concise terminal output.

Sections:
  1. Executive Summary
  2. Model Comparison Table
  3. Voice Robustness Matrix
  4. Domain Accuracy Heatmap
  5. Tool Call Analysis
  6. Performance Deep Dive
  7. Security Analysis
  8. Failure Catalog
  9. Prompt Analysis
  10. Recommendations
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import median, stdev
from typing import Any

from .db import BenchmarkDB


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pct(value: float | None, decimals: int = 0) -> str:
    """Format a 0-1 float as a percentage string, or 'N/A' if None."""
    if value is None:
        return "N/A"
    fmt = f".{decimals}%" if decimals else ".0%"
    return format(value, fmt)


def _ms_to_s(ms: float | None) -> str:
    """Convert milliseconds to a human-readable seconds string."""
    if ms is None:
        return "N/A"
    return f"{ms / 1000:.2f}s"


def _cost(usd: float | None) -> str:
    """Format a cost in USD."""
    if usd is None:
        return "$0.00"
    return f"${usd:.4f}"


def _trunc(text: str | None, length: int = 120) -> str:
    """Truncate text and escape pipe characters for markdown tables."""
    if not text:
        return ""
    text = text.replace("|", "\\|").replace("\n", " ").strip()
    if len(text) > length:
        return text[:length] + "..."
    return text


def _ascii_bar(value: float, max_value: float, width: int = 20) -> str:
    """Render a simple ASCII bar for histograms."""
    if max_value == 0:
        return " " * width
    filled = int(round(value / max_value * width))
    return "#" * filled + "." * (width - filled)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class BenchmarkReport:
    """
    Generate comprehensive reports from benchmark results.

    Usage:
        db = BenchmarkDB("benchmark_results.db")
        report = BenchmarkReport(db, run_id=1)
        markdown = report.generate()
        report.print_terminal_summary()
    """

    def __init__(self, db: BenchmarkDB, run_id: int):
        self.db = db
        self.run_id = run_id

        # Load all data once; sections reference these cached attributes.
        self._run = self._load_run()
        self._models = self._load_models()       # list[dict] — model metadata
        self._scores = self._load_scores()       # model_id -> score dict
        self._results = self._load_results()     # list[dict] — raw results
        self._results_by_model: dict[int, list[dict]] = defaultdict(list)
        for r in self._results:
            self._results_by_model[r["model_id"]].append(r)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_run(self) -> dict:
        row = self.db.conn.execute(
            "SELECT * FROM benchmark_runs WHERE id=?", (self.run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No benchmark run with id={self.run_id}")
        return dict(row)

    def _load_models(self) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT * FROM models WHERE run_id=? ORDER BY id", (self.run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _load_scores(self) -> dict[int, dict]:
        """Return model_id -> score dict, with voice/domain JSON decoded."""
        rows = self.db.get_comparison(self.run_id)
        return {r["model_id"]: r for r in rows}

    def _load_results(self) -> list[dict]:
        return self.db.get_results(self.run_id)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    def _model_label(self, model: dict) -> str:
        """Short display label for a model (name + role if non-trivial)."""
        name = model["model_name"]
        role = model["role"]
        if role != "full_pipeline":
            return f"{name} ({role})"
        return name

    def _all_voices(self) -> list[str]:
        voices: set[str] = set()
        for r in self._results:
            if r["voice"]:
                voices.add(r["voice"])
        return sorted(voices)

    def _all_domains(self) -> list[str]:
        domains: set[str] = set()
        for r in self._results:
            if r["domain_expected"]:
                domains.add(r["domain_expected"])
        return sorted(domains)

    def _winning_model(self) -> dict | None:
        """
        Pick the model with the best combined score across domain accuracy,
        tool accuracy, and assertion pass rate. Returns None if no scores exist.
        """
        if not self._scores:
            return None

        best_model_id = None
        best_combined = -1.0

        for mid, score in self._scores.items():
            parts = [
                score.get("domain_accuracy") or 0.0,
                score.get("tool_accuracy") or 0.0,
                score.get("assertion_pass_rate") or 0.0,
            ]
            combined = sum(parts) / len(parts)
            if combined > best_combined:
                best_combined = combined
                best_model_id = mid

        if best_model_id is None:
            return None

        return next((m for m in self._models if m["id"] == best_model_id), None)

    def _failure_results(self, model_id: int) -> list[dict]:
        """Return results for a model where at least one assertion failed or the request errored."""
        rows = self._results_by_model.get(model_id, [])
        failed = []
        for r in rows:
            assertion_fail = (
                r["must_contain_passed"] == 0
                or r["must_not_contain_passed"] == 0
            )
            errored = r["success"] == 0 and r["error_message"]
            if assertion_fail or errored:
                failed.append(r)
        return failed

    # ------------------------------------------------------------------
    # Section generators
    # ------------------------------------------------------------------

    def _section_executive_summary(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 1. Executive Summary")
        lines.append("")

        run = self._run
        started = run.get("started_at", "unknown")
        finished = run.get("finished_at", "in progress")
        notes = run.get("notes", "")
        config: dict[str, Any] = {}
        try:
            config = json.loads(run.get("config_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

        scenario_ids = {r["scenario_id"] for r in self._results}
        model_names = [m["model_name"] for m in self._models]

        lines.append("### Run Metadata")
        lines.append("")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| Run ID | {self.run_id} |")
        lines.append(f"| Started | {started} |")
        lines.append(f"| Finished | {finished} |")
        lines.append(f"| Models tested | {len(self._models)} |")
        lines.append(f"| Scenarios | {len(scenario_ids)} |")
        lines.append(f"| Total results | {len(self._results)} |")
        if notes:
            lines.append(f"| Notes | {_trunc(notes, 80)} |")
        lines.append("")

        # Winner
        winner = self._winning_model()
        if winner:
            score = self._scores.get(winner["id"], {})
            combined_parts = [
                score.get("domain_accuracy") or 0.0,
                score.get("tool_accuracy") or 0.0,
                score.get("assertion_pass_rate") or 0.0,
            ]
            combined = sum(combined_parts) / len(combined_parts)
            lines.append(f"### Recommended Model")
            lines.append("")
            lines.append(
                f"**{self._model_label(winner)}** — combined score {_pct(combined)} "
                f"(domain {_pct(score.get('domain_accuracy'))}, "
                f"tool {_pct(score.get('tool_accuracy'))}, "
                f"assertions {_pct(score.get('assertion_pass_rate'))})"
            )
            lines.append("")

        # Key findings
        lines.append("### Key Findings")
        lines.append("")
        findings = self._derive_key_findings()
        for finding in findings:
            lines.append(f"- {finding}")
        lines.append("")

        return lines

    def _derive_key_findings(self) -> list[str]:
        """Generate 3-5 key findings from scores data."""
        findings: list[str] = []

        if not self._scores:
            return ["No score data available — run compute_scores() on this benchmark run."]

        # Best and worst domain accuracy
        acc_ranked = sorted(
            [(mid, s) for mid, s in self._scores.items() if s.get("domain_accuracy") is not None],
            key=lambda x: x[1]["domain_accuracy"],
            reverse=True,
        )
        if acc_ranked:
            best_mid, best_s = acc_ranked[0]
            best_model = next((m for m in self._models if m["id"] == best_mid), None)
            worst_mid, worst_s = acc_ranked[-1]
            worst_model = next((m for m in self._models if m["id"] == worst_mid), None)
            if best_model and worst_model and best_mid != worst_mid:
                findings.append(
                    f"Domain accuracy ranges from {_pct(worst_s['domain_accuracy'])} "
                    f"({self._model_label(worst_model)}) to "
                    f"{_pct(best_s['domain_accuracy'])} ({self._model_label(best_model)})."
                )
            elif best_model:
                findings.append(
                    f"Best domain accuracy: {_pct(best_s['domain_accuracy'])} ({self._model_label(best_model)})."
                )

        # Latency gap
        time_ranked = sorted(
            [(mid, s) for mid, s in self._scores.items() if s.get("avg_time_ms") is not None],
            key=lambda x: x[1]["avg_time_ms"],
        )
        if len(time_ranked) >= 2:
            fastest_mid, fastest_s = time_ranked[0]
            slowest_mid, slowest_s = time_ranked[-1]
            fastest_model = next((m for m in self._models if m["id"] == fastest_mid), None)
            slowest_model = next((m for m in self._models if m["id"] == slowest_mid), None)
            if fastest_model and slowest_model:
                ratio = slowest_s["avg_time_ms"] / fastest_s["avg_time_ms"]
                findings.append(
                    f"Largest latency gap: {self._model_label(slowest_model)} is "
                    f"{ratio:.1f}x slower than {self._model_label(fastest_model)} "
                    f"({_ms_to_s(slowest_s['avg_time_ms'])} vs {_ms_to_s(fastest_s['avg_time_ms'])} avg)."
                )

        # Security summary
        total_fp = sum(s.get("false_positive_blocks") or 0 for s in self._scores.values())
        total_fn = sum(s.get("false_negative_passes") or 0 for s in self._scores.values())
        if total_fp + total_fn > 0:
            findings.append(
                f"Security: {total_fp} false positive block(s) and {total_fn} false negative pass(es) across all models."
            )

        # Tool call accuracy summary
        tool_ranked = sorted(
            [(mid, s) for mid, s in self._scores.items() if s.get("tool_accuracy") is not None],
            key=lambda x: x[1]["tool_accuracy"],
            reverse=True,
        )
        if tool_ranked:
            best_mid, best_s = tool_ranked[0]
            best_model = next((m for m in self._models if m["id"] == best_mid), None)
            if best_model:
                findings.append(
                    f"Best tool call accuracy: {_pct(best_s['tool_accuracy'])} ({self._model_label(best_model)})."
                )

        # Models failing across the board
        universal_fail_scenarios = self._find_universal_failures()
        if universal_fail_scenarios:
            findings.append(
                f"{len(universal_fail_scenarios)} scenario(s) failed for every model — likely a pipeline issue, not a model issue."
            )

        return findings[:5]  # Cap at 5

    def _find_universal_failures(self) -> list[str]:
        """Return scenario IDs that failed for every model in this run."""
        if not self._models:
            return []

        # A result "fails" if success=0 or an assertion failed
        fail_sets: list[set[str]] = []
        for model in self._models:
            mid = model["id"]
            rows = self._results_by_model.get(mid, [])
            failed_ids: set[str] = set()
            for r in rows:
                if (
                    r["success"] == 0
                    or r["must_contain_passed"] == 0
                    or r["must_not_contain_passed"] == 0
                ):
                    failed_ids.add(r["scenario_id"])
            fail_sets.append(failed_ids)

        if not fail_sets:
            return []

        universal = fail_sets[0]
        for s in fail_sets[1:]:
            universal = universal & s
        return sorted(universal)

    # ------------------------------------------------------------------

    def _section_model_comparison(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 2. Model Comparison")
        lines.append("")

        if not self._scores:
            lines.append("*No score data. Run `db.compute_scores(run_id)` first.*")
            lines.append("")
            return lines

        headers = ["Metric"] + [self._model_label(m) for m in self._models]
        separator = ["-" * max(len(h), 6) for h in headers]

        def row(label: str, values: list[str]) -> str:
            cells = [label] + values
            return "| " + " | ".join(cells) + " |"

        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(separator) + " |")

        def col_val(mid: int, key: str, fmt_fn=None) -> str:
            score = self._scores.get(mid)
            if score is None:
                return "N/A"
            val = score.get(key)
            if fmt_fn:
                return fmt_fn(val)
            return str(val) if val is not None else "N/A"

        metrics: list[tuple[str, str, Any]] = [
            ("Domain Accuracy", "domain_accuracy", _pct),
            ("Tool Accuracy", "tool_accuracy", _pct),
            ("Assertion Pass Rate", "assertion_pass_rate", _pct),
            ("Avg Response Time", "avg_time_ms", _ms_to_s),
            ("P50 Response Time", "p50_time_ms", _ms_to_s),
            ("P95 Response Time", "p95_time_ms", _ms_to_s),
            ("Max Response Time", "max_time_ms", _ms_to_s),
            ("Avg Response Length", "avg_response_length", lambda v: f"{v:.0f} chars" if v is not None else "N/A"),
            ("Total Input Tokens", "total_input_tokens", lambda v: f"{v:,}" if v is not None else "N/A"),
            ("Total Output Tokens", "total_output_tokens", lambda v: f"{v:,}" if v is not None else "N/A"),
            ("Total Cost", "total_cost_usd", _cost),
            ("Hallucinations Detected", "hallucination_count", lambda v: str(v) if v is not None else "N/A"),
            ("False Positive Blocks", "false_positive_blocks", lambda v: str(v) if v is not None else "N/A"),
            ("False Negative Passes", "false_negative_passes", lambda v: str(v) if v is not None else "N/A"),
        ]

        for label, key, fmt in metrics:
            values = [col_val(m["id"], key, fmt) for m in self._models]
            lines.append(row(label, values))

        lines.append("")
        return lines

    # ------------------------------------------------------------------

    def _section_voice_robustness(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 3. Voice Robustness Matrix")
        lines.append("")
        lines.append(
            "Success rate per voice type per model. "
            "Low scores on specific voices reveal prompt or style sensitivity."
        )
        lines.append("")

        voices = self._all_voices()
        if not voices:
            lines.append("*No voice data in this run.*")
            lines.append("")
            return lines

        if not self._scores:
            lines.append("*No score data. Run `db.compute_scores(run_id)` first.*")
            lines.append("")
            return lines

        headers = ["Voice"] + [self._model_label(m) for m in self._models]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["-" * max(len(h), 6) for h in headers]) + " |")

        for voice in voices:
            cells = [voice]
            for model in self._models:
                score = self._scores.get(model["id"], {})
                by_voice: dict = score.get("scores_by_voice") or {}
                vdata = by_voice.get(voice)
                if vdata and vdata.get("domain_accuracy") is not None:
                    cells.append(_pct(vdata["domain_accuracy"]))
                elif vdata and vdata.get("success_rate") is not None:
                    cells.append(_pct(vdata["success_rate"]) + "*")
                else:
                    cells.append("N/A")
            lines.append("| " + " | ".join(cells) + " |")

        lines.append("")
        lines.append("_\\* = success rate used when domain accuracy not available_")
        lines.append("")
        return lines

    # ------------------------------------------------------------------

    def _section_domain_heatmap(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 4. Domain Accuracy Heatmap")
        lines.append("")
        lines.append("Domain routing accuracy per domain per model.")
        lines.append("")

        domains = self._all_domains()
        if not domains:
            lines.append("*No domain data in this run.*")
            lines.append("")
            return lines

        if not self._scores:
            lines.append("*No score data. Run `db.compute_scores(run_id)` first.*")
            lines.append("")
            return lines

        headers = ["Domain"] + [self._model_label(m) for m in self._models]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["-" * max(len(h), 6) for h in headers]) + " |")

        for domain in domains:
            cells = [domain]
            for model in self._models:
                score = self._scores.get(model["id"], {})
                by_domain: dict = score.get("scores_by_domain") or {}
                ddata = by_domain.get(domain)
                if ddata and ddata.get("domain_accuracy") is not None:
                    cells.append(_pct(ddata["domain_accuracy"]))
                else:
                    cells.append("N/A")
            lines.append("| " + " | ".join(cells) + " |")

        lines.append("")
        return lines

    # ------------------------------------------------------------------

    def _section_tool_call_analysis(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 5. Tool Call Analysis")
        lines.append("")

        tool_results = [r for r in self._results if r["tool_call_expected"] is not None]
        if not tool_results:
            lines.append("*No tool-call scenarios in this run.*")
            lines.append("")
            return lines

        # Per-model summary
        headers = ["Model", "Scenarios", "Correct", "Accuracy", "False Activations", "False Suppressions"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["-" * 10] * len(headers)) + " |")

        for model in self._models:
            mid = model["id"]
            rows = [r for r in self._results_by_model.get(mid, []) if r["tool_call_expected"] is not None]
            if not rows:
                lines.append(f"| {self._model_label(model)} | 0 | — | — | — | — |")
                continue

            correct = sum(1 for r in rows if r["tool_call_correct"] == 1)
            accuracy = correct / len(rows)

            # False activation: tool fired but was not expected (expected=0, fired=1)
            false_act = sum(1 for r in rows if r["tool_call_expected"] == 0 and r["tool_call_fired"] == 1)
            # False suppression: tool not fired but was expected (expected=1, fired=0)
            false_sup = sum(1 for r in rows if r["tool_call_expected"] == 1 and r["tool_call_fired"] == 0)

            lines.append(
                f"| {self._model_label(model)} "
                f"| {len(rows)} "
                f"| {correct} "
                f"| {_pct(accuracy)} "
                f"| {false_act} "
                f"| {false_sup} |"
            )

        lines.append("")

        # Specific failures (first 20)
        failures = [r for r in tool_results if r["tool_call_correct"] == 0]
        if failures:
            lines.append("### Tool Call Failures")
            lines.append("")
            lines.append("| Model | Scenario | Expected | Fired | Message |")
            lines.append("|-------|----------|----------|-------|---------|")
            for r in failures[:20]:
                model = next((m for m in self._models if m["id"] == r["model_id"]), None)
                model_label = self._model_label(model) if model else str(r["model_id"])
                expected = "yes" if r["tool_call_expected"] == 1 else "no"
                fired = "yes" if r["tool_call_fired"] == 1 else "no"
                lines.append(
                    f"| {model_label} "
                    f"| {r['scenario_id']} "
                    f"| {expected} "
                    f"| {fired} "
                    f"| {_trunc(r['user_message'], 80)} |"
                )
            if len(failures) > 20:
                lines.append(f"")
                lines.append(f"*...and {len(failures) - 20} more failures not shown.*")
        else:
            lines.append("*No tool call failures in this run.*")

        lines.append("")
        return lines

    # ------------------------------------------------------------------

    def _section_performance_deep_dive(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 6. Performance Deep Dive")
        lines.append("")

        # Per-model timing
        lines.append("### Per-Model Timing (seconds)")
        lines.append("")
        headers = ["Model", "Avg", "P50", "P95", "Max", "Min", "StdDev", "Count"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["-" * 8] * len(headers)) + " |")

        for model in self._models:
            mid = model["id"]
            rows = self._results_by_model.get(mid, [])
            times = sorted([r["total_time_ms"] for r in rows if r["total_time_ms"] is not None])
            if not times:
                lines.append(f"| {self._model_label(model)} | — | — | — | — | — | — | 0 |")
                continue

            avg = sum(times) / len(times)
            p50 = times[len(times) // 2]
            p95 = times[int(len(times) * 0.95)] if len(times) >= 2 else times[-1]
            mx = times[-1]
            mn = times[0]
            sd = stdev(times) if len(times) >= 2 else 0.0

            lines.append(
                f"| {self._model_label(model)} "
                f"| {avg / 1000:.2f} "
                f"| {p50 / 1000:.2f} "
                f"| {p95 / 1000:.2f} "
                f"| {mx / 1000:.2f} "
                f"| {mn / 1000:.2f} "
                f"| {sd / 1000:.2f} "
                f"| {len(times)} |"
            )

        lines.append("")

        # Per-layer timing breakdown (if available)
        layer_data_exists = any(
            r.get("layer_timings_json") for r in self._results
        )
        if layer_data_exists:
            lines.append("### Per-Layer Timing Breakdown")
            lines.append("")
            # Aggregate layer timings per model
            for model in self._models:
                mid = model["id"]
                rows = self._results_by_model.get(mid, [])
                layer_totals: dict[str, list[float]] = defaultdict(list)
                for r in rows:
                    if r.get("layer_timings_json"):
                        try:
                            lt = json.loads(r["layer_timings_json"])
                            if isinstance(lt, dict):
                                for layer, ms in lt.items():
                                    if isinstance(ms, (int, float)):
                                        layer_totals[layer].append(float(ms))
                        except (json.JSONDecodeError, TypeError):
                            pass

                if layer_totals:
                    lines.append(f"**{self._model_label(model)}**")
                    lines.append("")
                    lines.append("| Layer | Avg (ms) | Count |")
                    lines.append("|-------|----------|-------|")
                    for layer in sorted(layer_totals):
                        vals = layer_totals[layer]
                        avg_ms = sum(vals) / len(vals)
                        lines.append(f"| {layer} | {avg_ms:.0f} | {len(vals)} |")
                    lines.append("")

        # Latency distribution histogram (ASCII)
        lines.append("### Latency Distribution (all models combined)")
        lines.append("")
        all_times = [r["total_time_ms"] for r in self._results if r["total_time_ms"] is not None]
        if all_times:
            lines.extend(self._ascii_histogram(all_times, buckets=10))
        else:
            lines.append("*No timing data available.*")
        lines.append("")

        # Slowest scenarios
        lines.append("### Slowest Scenarios (top 10)")
        lines.append("")
        timed = [r for r in self._results if r["total_time_ms"] is not None]
        timed.sort(key=lambda r: r["total_time_ms"], reverse=True)
        if timed:
            lines.append("| Model | Scenario | Time | Domain | Message |")
            lines.append("|-------|----------|------|--------|---------|")
            for r in timed[:10]:
                model = next((m for m in self._models if m["id"] == r["model_id"]), None)
                model_label = self._model_label(model) if model else str(r["model_id"])
                lines.append(
                    f"| {model_label} "
                    f"| {r['scenario_id']} "
                    f"| {_ms_to_s(r['total_time_ms'])} "
                    f"| {r['domain_expected'] or 'N/A'} "
                    f"| {_trunc(r['user_message'], 70)} |"
                )
        else:
            lines.append("*No timing data available.*")

        lines.append("")
        return lines

    def _ascii_histogram(self, values: list[float], buckets: int = 10) -> list[str]:
        """Render an ASCII histogram for a list of millisecond values."""
        if not values:
            return []

        mn = min(values)
        mx = max(values)
        if mn == mx:
            return [f"All values: {_ms_to_s(mn)}"]

        bucket_size = (mx - mn) / buckets
        counts = [0] * buckets
        for v in values:
            idx = min(int((v - mn) / bucket_size), buckets - 1)
            counts[idx] += 1

        max_count = max(counts)
        lines = ["```"]
        for i, count in enumerate(counts):
            lo = mn + i * bucket_size
            hi = lo + bucket_size
            bar = _ascii_bar(count, max_count, width=30)
            lines.append(f"  {_ms_to_s(lo):>7} - {_ms_to_s(hi):>7}  {bar}  {count}")
        lines.append("```")
        return lines

    # ------------------------------------------------------------------

    def _section_security_analysis(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 7. Security Analysis")
        lines.append("")

        if not self._scores:
            lines.append("*No score data available.*")
            lines.append("")
            return lines

        headers = ["Model", "False Pos. Blocks", "False Neg. Passes"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["-" * 18] * len(headers)) + " |")

        for model in self._models:
            score = self._scores.get(model["id"], {})
            fp = score.get("false_positive_blocks")
            fn = score.get("false_negative_passes")
            lines.append(
                f"| {self._model_label(model)} "
                f"| {fp if fp is not None else 'N/A'} "
                f"| {fn if fn is not None else 'N/A'} |"
            )

        lines.append("")
        lines.append("_False positive: legitimate query blocked. False negative: attack scenario not blocked._")
        lines.append("")

        # Blocked results detail
        blocked_results = [r for r in self._results if r["blocked"] == 1]
        if blocked_results:
            lines.append("### Blocked Requests")
            lines.append("")
            lines.append("| Model | Scenario | Layer | Message |")
            lines.append("|-------|----------|-------|---------|")
            for r in blocked_results[:30]:
                model = next((m for m in self._models if m["id"] == r["model_id"]), None)
                model_label = self._model_label(model) if model else str(r["model_id"])
                layer = r.get("blocked_at_layer") or "unknown"
                lines.append(
                    f"| {model_label} "
                    f"| {r['scenario_id']} "
                    f"| {layer} "
                    f"| {_trunc(r['user_message'], 80)} |"
                )
            if len(blocked_results) > 30:
                lines.append(f"")
                lines.append(f"*...and {len(blocked_results) - 30} more blocked requests not shown.*")
            lines.append("")

        # Attack scenarios that passed
        attack_ids = [
            r for r in self._results
            if r["blocked"] == 0 and (
                "attack" in (r["scenario_id"] or "").lower()
                or "injection" in (r["scenario_id"] or "").lower()
                or "malicious" in (r["scenario_id"] or "").lower()
            )
        ]
        if attack_ids:
            lines.append("### Attack Scenarios That Passed (False Negatives)")
            lines.append("")
            lines.append("| Model | Scenario | Response Preview |")
            lines.append("|-------|----------|-----------------|")
            for r in attack_ids[:20]:
                model = next((m for m in self._models if m["id"] == r["model_id"]), None)
                model_label = self._model_label(model) if model else str(r["model_id"])
                preview = _trunc(r.get("response_content"), 100)
                lines.append(f"| {model_label} | {r['scenario_id']} | {preview} |")
            lines.append("")

        return lines

    # ------------------------------------------------------------------

    def _section_failure_catalog(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 8. Failure Catalog")
        lines.append("")
        lines.append(
            "Every scenario that failed assertions or produced an error, grouped by model. "
            "Use this to understand exactly what broke and why."
        )
        lines.append("")

        any_failures = False
        for model in self._models:
            failures = self._failure_results(model["id"])
            if not failures:
                continue

            any_failures = True
            lines.append(f"### {self._model_label(model)} — {len(failures)} failure(s)")
            lines.append("")

            for r in failures:
                lines.append(f"#### Scenario: `{r['scenario_id']}`")
                lines.append("")

                # Metadata row
                voice = r.get("voice") or "N/A"
                domain = r.get("domain_expected") or "N/A"
                routed = r.get("response_domain") or "N/A"
                lines.append(f"| Field | Value |")
                lines.append(f"|-------|-------|")
                lines.append(f"| Voice | {voice} |")
                lines.append(f"| Expected Domain | {domain} |")
                lines.append(f"| Routed Domain | {routed} |")
                lines.append(f"| Success | {'yes' if r['success'] == 1 else 'no'} |")

                if r.get("must_contain_passed") == 0:
                    lines.append(f"| must_contain | FAILED |")
                if r.get("must_not_contain_passed") == 0:
                    lines.append(f"| must_not_contain | FAILED |")
                if r.get("error_message"):
                    lines.append(f"| Error | {_trunc(r['error_message'], 100)} |")

                lines.append("")

                # User message
                if r.get("user_message"):
                    lines.append(f"**User message:**")
                    lines.append(f"```")
                    lines.append(r["user_message"])
                    lines.append(f"```")
                    lines.append("")

                # Response
                if r.get("response_content"):
                    lines.append(f"**Response:**")
                    lines.append(f"```")
                    # Trim very long responses to 500 chars
                    content = r["response_content"]
                    if len(content) > 500:
                        content = content[:500] + "\n[... truncated ...]"
                    lines.append(content)
                    lines.append(f"```")
                    lines.append("")

            lines.append("")

        if not any_failures:
            lines.append("*No failures recorded in this run.*")
            lines.append("")

        return lines

    # ------------------------------------------------------------------

    def _section_prompt_analysis(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 9. Prompt Analysis")
        lines.append("")

        for model in self._models:
            mid = model["id"]
            rows = self._results_by_model.get(mid, [])
            if not rows:
                continue

            sys_lengths = [len(r["system_prompt"]) for r in rows if r.get("system_prompt")]
            user_lengths = [len(r["user_prompt"]) for r in rows if r.get("user_prompt")]
            input_tokens = [r["input_tokens"] for r in rows if r.get("input_tokens") is not None]
            output_tokens = [r["output_tokens"] for r in rows if r.get("output_tokens") is not None]

            lines.append(f"### {self._model_label(model)}")
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")

            if sys_lengths:
                lines.append(f"| Avg system prompt length | {sum(sys_lengths) / len(sys_lengths):.0f} chars |")
                lines.append(f"| Max system prompt length | {max(sys_lengths)} chars |")
            if user_lengths:
                lines.append(f"| Avg user prompt length | {sum(user_lengths) / len(user_lengths):.0f} chars |")
                lines.append(f"| Max user prompt length | {max(user_lengths)} chars |")
            if input_tokens:
                lines.append(f"| Avg input tokens | {sum(input_tokens) / len(input_tokens):.0f} |")
                lines.append(f"| Total input tokens | {sum(input_tokens):,} |")
            if output_tokens:
                lines.append(f"| Avg output tokens | {sum(output_tokens) / len(output_tokens):.0f} |")
                lines.append(f"| Total output tokens | {sum(output_tokens):,} |")

            # Token efficiency: output tokens per successful result
            successful_rows = [r for r in rows if r["success"] == 1 and r.get("output_tokens") is not None]
            if successful_rows:
                avg_out = sum(r["output_tokens"] for r in successful_rows) / len(successful_rows)
                lines.append(f"| Avg output tokens (successful) | {avg_out:.0f} |")

            lines.append("")

        # Most expensive scenarios by total token count
        token_rows = [
            r for r in self._results
            if r.get("input_tokens") is not None and r.get("output_tokens") is not None
        ]
        if token_rows:
            token_rows.sort(key=lambda r: (r["input_tokens"] or 0) + (r["output_tokens"] or 0), reverse=True)
            lines.append("### Most Expensive Scenarios (by token count)")
            lines.append("")
            lines.append("| Model | Scenario | Input Tokens | Output Tokens | Cost |")
            lines.append("|-------|----------|-------------|--------------|------|")
            for r in token_rows[:15]:
                model = next((m for m in self._models if m["id"] == r["model_id"]), None)
                model_label = self._model_label(model) if model else str(r["model_id"])
                lines.append(
                    f"| {model_label} "
                    f"| {r['scenario_id']} "
                    f"| {r['input_tokens']:,} "
                    f"| {r['output_tokens']:,} "
                    f"| {_cost(r.get('estimated_cost_usd'))} |"
                )
            lines.append("")

        return lines

    # ------------------------------------------------------------------

    def _section_recommendations(self) -> list[str]:
        lines: list[str] = []
        lines.append("## 10. Recommendations")
        lines.append("")

        if not self._scores:
            lines.append("*Compute scores first with `db.compute_scores(run_id)`.*")
            lines.append("")
            return lines

        # Best model per role
        lines.append("### Best Model by Role")
        lines.append("")

        roles = {m["role"] for m in self._models}
        for role in sorted(roles):
            role_models = [m for m in self._models if m["role"] == role]
            if not role_models:
                continue

            scored = []
            for model in role_models:
                score = self._scores.get(model["id"], {})
                parts = [v for v in [
                    score.get("domain_accuracy"),
                    score.get("tool_accuracy"),
                    score.get("assertion_pass_rate"),
                ] if v is not None]
                combined = sum(parts) / len(parts) if parts else 0.0
                scored.append((model, combined, score))

            scored.sort(key=lambda x: x[1], reverse=True)
            if scored:
                best_model, best_score, best_s = scored[0]
                latency = _ms_to_s(best_s.get("avg_time_ms"))
                cost = _cost(best_s.get("total_cost_usd"))
                lines.append(
                    f"- **{role}**: `{best_model['model_name']}` — "
                    f"combined {_pct(best_score)}, avg latency {latency}, cost {cost}"
                )

        lines.append("")

        # Prompt improvement opportunities
        lines.append("### Prompt Improvement Opportunities")
        lines.append("")

        # Domains with consistent low accuracy
        low_domain_recs: list[str] = []
        for model in self._models:
            score = self._scores.get(model["id"], {})
            by_domain = score.get("scores_by_domain") or {}
            for domain, ddata in by_domain.items():
                acc = ddata.get("domain_accuracy")
                if acc is not None and acc < 0.7:
                    low_domain_recs.append(
                        f"Domain `{domain}` has {_pct(acc)} accuracy on `{model['model_name']}` — "
                        f"consider sharpening routing prompt for this domain."
                    )

        if low_domain_recs:
            for rec in low_domain_recs[:5]:
                lines.append(f"- {rec}")
        else:
            lines.append("- No single domain consistently underperforms across all models.")

        lines.append("")

        # Voice sensitivity
        lines.append("### Voice Sensitivity Issues")
        lines.append("")
        low_voice_recs: list[str] = []
        for model in self._models:
            score = self._scores.get(model["id"], {})
            by_voice = score.get("scores_by_voice") or {}
            for voice, vdata in by_voice.items():
                acc = vdata.get("domain_accuracy") or vdata.get("success_rate")
                if acc is not None and acc < 0.6:
                    low_voice_recs.append(
                        f"Voice `{voice}` has {_pct(acc)} accuracy on `{model['model_name']}` — "
                        f"model may struggle with this communication style."
                    )

        if low_voice_recs:
            for rec in low_voice_recs[:5]:
                lines.append(f"- {rec}")
        else:
            lines.append("- No voice types consistently failing across all models.")

        lines.append("")

        # Universal failures (pipeline issues)
        universal = self._find_universal_failures()
        lines.append("### Pipeline-Level Issues (All Models Failed)")
        lines.append("")
        if universal:
            lines.append("These scenarios failed for every model — the issue is likely in the pipeline, not model quality:")
            lines.append("")
            for sid in universal:
                lines.append(f"- `{sid}`")
        else:
            lines.append("- No scenarios failed for all models. Pipeline appears healthy.")

        lines.append("")

        return lines

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, output_path: Path | None = None) -> str:
        """
        Generate the full markdown benchmark report.

        Args:
            output_path: If provided, write the report to this path.

        Returns:
            The complete report as a markdown string.
        """
        lines: list[str] = []

        lines.append(f"# Benchmark Report — Run #{self.run_id}")
        lines.append("")
        lines.append("---")
        lines.append("")

        lines.extend(self._section_executive_summary())
        lines.extend(self._section_model_comparison())
        lines.extend(self._section_voice_robustness())
        lines.extend(self._section_domain_heatmap())
        lines.extend(self._section_tool_call_analysis())
        lines.extend(self._section_performance_deep_dive())
        lines.extend(self._section_security_analysis())
        lines.extend(self._section_failure_catalog())
        lines.extend(self._section_prompt_analysis())
        lines.extend(self._section_recommendations())

        lines.append("---")
        lines.append(f"*Generated by BenchmarkReport — Run #{self.run_id}*")

        report = "\n".join(lines)

        if output_path:
            Path(output_path).write_text(report)

        return report

    def generate_json_summary(self) -> dict:
        """
        Generate a machine-readable summary of benchmark results.

        Returns a dict suitable for programmatic comparison, CI gates,
        or archiving alongside the markdown report.
        """
        run = self._run
        winner = self._winning_model()

        models_summary = []
        for model in self._models:
            score = self._scores.get(model["id"], {})
            models_summary.append({
                "model_id": model["id"],
                "model_name": model["model_name"],
                "model_type": model["model_type"],
                "role": model["role"],
                "domain_accuracy": score.get("domain_accuracy"),
                "tool_accuracy": score.get("tool_accuracy"),
                "assertion_pass_rate": score.get("assertion_pass_rate"),
                "avg_time_ms": score.get("avg_time_ms"),
                "p95_time_ms": score.get("p95_time_ms"),
                "total_cost_usd": score.get("total_cost_usd"),
                "false_positive_blocks": score.get("false_positive_blocks"),
                "false_negative_passes": score.get("false_negative_passes"),
                "hallucination_count": score.get("hallucination_count"),
                "failure_count": len(self._failure_results(model["id"])),
            })

        return {
            "run_id": self.run_id,
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "notes": run.get("notes"),
            "scenario_count": len({r["scenario_id"] for r in self._results}),
            "result_count": len(self._results),
            "model_count": len(self._models),
            "winner": {
                "model_name": winner["model_name"],
                "model_id": winner["id"],
            } if winner else None,
            "universal_failures": self._find_universal_failures(),
            "models": models_summary,
        }

    def print_terminal_summary(self):
        """
        Print a concise benchmark summary to the terminal.

        Covers winner, per-model accuracy/latency/cost, and top failures.
        """
        width = 70
        print(f"\n{'=' * width}")
        print(f"  BENCHMARK RUN #{self.run_id}")
        print(f"{'=' * width}")

        run = self._run
        print(f"  Started:  {run.get('started_at', 'unknown')}")
        print(f"  Finished: {run.get('finished_at', 'in progress')}")
        scenario_ids = {r["scenario_id"] for r in self._results}
        print(f"  Models:   {len(self._models)}  |  Scenarios: {len(scenario_ids)}  |  Results: {len(self._results)}")

        winner = self._winning_model()
        if winner:
            score = self._scores.get(winner["id"], {})
            parts = [v for v in [
                score.get("domain_accuracy"),
                score.get("tool_accuracy"),
                score.get("assertion_pass_rate"),
            ] if v is not None]
            combined = sum(parts) / len(parts) if parts else 0.0
            print(f"\n  WINNER: {self._model_label(winner)} (combined {_pct(combined)})")

        if self._scores:
            print(f"\n  {'Model':<30} {'Domain':>8} {'Tool':>8} {'Assert':>8} {'Avg':>8} {'Cost':>10}")
            print(f"  {'-' * 30} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 10}")
            for model in self._models:
                score = self._scores.get(model["id"], {})
                label = self._model_label(model)
                if len(label) > 30:
                    label = label[:27] + "..."
                print(
                    f"  {label:<30} "
                    f"{_pct(score.get('domain_accuracy')):>8} "
                    f"{_pct(score.get('tool_accuracy')):>8} "
                    f"{_pct(score.get('assertion_pass_rate')):>8} "
                    f"{_ms_to_s(score.get('avg_time_ms')):>8} "
                    f"{_cost(score.get('total_cost_usd')):>10}"
                )
        else:
            print("\n  No score data. Run db.compute_scores(run_id) to aggregate.")

        # Universal failures
        universal = self._find_universal_failures()
        if universal:
            print(f"\n  PIPELINE ISSUES (failed all models): {len(universal)}")
            for sid in universal[:5]:
                print(f"    - {sid}")
            if len(universal) > 5:
                print(f"    ... and {len(universal) - 5} more")

        # Per-model failure counts
        print(f"\n  Failure counts:")
        for model in self._models:
            fail_count = len(self._failure_results(model["id"]))
            label = self._model_label(model)
            if len(label) > 35:
                label = label[:32] + "..."
            print(f"    {label:<35} {fail_count} failure(s)")

        print(f"\n{'=' * width}\n")
