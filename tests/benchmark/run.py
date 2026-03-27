#!/usr/bin/env python3
"""
CLI runner for the portfolio chat benchmark suite.

Usage:
    # Run default benchmark (mistral:7b against all panels)
    python -m tests.benchmark.run

    # Compare multiple models
    python -m tests.benchmark.run --models "mistral:7b,llama3.1:8b"

    # Include an Anthropic model
    python -m tests.benchmark.run --models "mistral:7b,claude-sonnet-4-20250514:anthropic"

    # Run only specific voice panels
    python -m tests.benchmark.run --panels "professional,terse,antagonistic"

    # Skip the tool-call panel
    python -m tests.benchmark.run --no-tools

    # Generate a report from an existing DB without re-running
    python -m tests.benchmark.run --report-only --db tests/benchmark/results/benchmark_20260318_143022.db --run-id 1

    # List available Ollama models
    python -m tests.benchmark.run --list-models

    # List available voice panels with scenario counts
    python -m tests.benchmark.run --list-panels
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path so portfolio_chat and tests packages are importable
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from tests.benchmark.db import BenchmarkDB
from tests.benchmark.engine import BenchmarkConfig, BenchmarkEngine, ModelSpec
from tests.benchmark.report import BenchmarkReport


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Portfolio Chat Benchmark — compare generator models side-by-side.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Model selection
    parser.add_argument(
        "--models",
        default="mistral:7b",
        help=(
            "Comma-separated models to benchmark as generators. "
            "Format: name:provider (provider defaults to 'ollama'). "
            "Example: \"mistral:7b,claude-sonnet-4-20250514:anthropic\" "
            "(default: mistral:7b)"
        ),
    )

    # Panel selection
    parser.add_argument(
        "--panels",
        default="",
        help=(
            "Comma-separated voice panels to run (default: all). "
            "Example: \"professional,terse,antagonistic\""
        ),
    )

    # Tool panel toggle — mutually exclusive flags
    tool_group = parser.add_mutually_exclusive_group()
    tool_group.add_argument(
        "--include-tools",
        dest="include_tools",
        action="store_true",
        default=True,
        help="Include tool panel (default)",
    )
    tool_group.add_argument(
        "--no-tools",
        dest="include_tools",
        action="store_false",
        help="Exclude tool panel",
    )

    # Infrastructure
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API base URL (default: http://localhost:11434)",
    )

    # Output
    parser.add_argument(
        "--output",
        default="",
        help="Output directory for results (default: tests/benchmark/results/)",
    )

    # Timing
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between scenarios in seconds (default: 0.5)",
    )

    # Metadata
    parser.add_argument(
        "--notes",
        default="",
        help="Notes to attach to this benchmark run",
    )

    # Report-only mode
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip benchmark, generate report from existing DB",
    )
    parser.add_argument(
        "--db",
        default="",
        help="Path to existing DB (for --report-only)",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=0,
        help="Run ID to report on (for --report-only, default: most recent)",
    )

    # Verbosity
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )

    # Informational exits
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available Ollama models and exit",
    )
    parser.add_argument(
        "--list-panels",
        action="store_true",
        help="List available voice panels with scenario counts and exit",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Model spec parsing
# ---------------------------------------------------------------------------

def parse_model_specs(models_arg: str) -> list[ModelSpec]:
    """
    Parse a comma-separated model string into a list of ModelSpec objects.

    Rules:
      "mistral:7b"                         -> ModelSpec("mistral:7b", "ollama")
      "llama3.1:8b"                        -> ModelSpec("llama3.1:8b", "ollama")
      "claude-sonnet-4-20250514:anthropic" -> ModelSpec("claude-sonnet-4-20250514", "anthropic")

    The provider is the LAST colon-delimited segment when it matches a known
    provider keyword ("ollama" or "anthropic"); otherwise the whole token is
    the model name and "ollama" is assumed.
    """
    known_providers = {"ollama", "anthropic"}
    specs: list[ModelSpec] = []

    for entry in models_arg.split(","):
        entry = entry.strip()
        if not entry:
            continue

        parts = entry.rsplit(":", 1)
        if len(parts) == 2 and parts[1].lower() in known_providers:
            model_name, provider = parts[0], parts[1].lower()
        else:
            model_name, provider = entry, "ollama"

        specs.append(ModelSpec(name=model_name, provider=provider))

    if not specs:
        print("ERROR: --models produced no valid model specs.", file=sys.stderr)
        sys.exit(1)

    return specs


# ---------------------------------------------------------------------------
# Informational exit helpers
# ---------------------------------------------------------------------------

def list_ollama_models(ollama_url: str) -> None:
    """Query Ollama /api/tags and print available models, then exit."""
    import urllib.request
    import urllib.error

    url = ollama_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as exc:
        print(f"ERROR: Could not reach Ollama at {url}: {exc}", file=sys.stderr)
        sys.exit(1)

    models = data.get("models", [])
    if not models:
        print("No models found in Ollama.")
        sys.exit(0)

    print(f"\nAvailable Ollama models ({len(models)}):")
    print(f"  {'NAME':<40}  {'SIZE':>12}  MODIFIED")
    print(f"  {'-'*40}  {'-'*12}  {'-'*20}")
    for m in sorted(models, key=lambda x: x.get("name", "")):
        name = m.get("name", "")
        size = m.get("size", 0)
        modified = m.get("modified_at", "")[:19].replace("T", " ")
        size_gb = f"{size / 1e9:.2f} GB" if size else "unknown"
        print(f"  {name:<40}  {size_gb:>12}  {modified}")
    print()
    sys.exit(0)


def list_panels() -> None:
    """Print all available voice panels with scenario counts, then exit."""
    from tests.benchmark.panels import build_all_panels

    panels = build_all_panels()

    print(f"\nAvailable voice panels ({len(panels)}):")
    print(f"  {'PANEL':<20}  {'SCENARIOS':>9}  {'TOOL SCENARIOS':>14}")
    print(f"  {'-'*20}  {'-'*9}  {'-'*14}")

    total_scenarios = 0
    total_tool = 0
    for panel in panels:
        tool_count = sum(
            1 for s in panel.scenarios
            if s.expect_tool_call or s.expect_no_tool_call
        )
        count = len(panel.scenarios)
        total_scenarios += count
        total_tool += tool_count
        print(f"  {panel.voice.value:<20}  {count:>9}  {tool_count:>14}")

    print(f"  {'TOTAL':<20}  {total_scenarios:>9}  {total_tool:>14}")
    print()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------

def resolve_output_dir(output_arg: str) -> Path:
    if output_arg:
        output_dir = Path(output_arg)
    else:
        output_dir = Path(__file__).parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


# ---------------------------------------------------------------------------
# Benchmark execution
# ---------------------------------------------------------------------------

async def run_benchmark(args: argparse.Namespace) -> tuple[int, BenchmarkDB, Path]:
    """Execute the benchmark and return (run_id, db, output_dir)."""
    output_dir = resolve_output_dir(args.output)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_path = output_dir / f"benchmark_{timestamp}.db"

    model_specs = parse_model_specs(args.models)

    panels: list[str] | None = None
    if args.panels:
        panels = [p.strip() for p in args.panels.split(",") if p.strip()]

    config = BenchmarkConfig(
        generator_models=model_specs,
        panels=panels,
        include_tool_panel=args.include_tools,
        ollama_url=args.ollama_url,
        delay_between_scenarios=args.delay,
        db_path=str(db_path),
        output_dir=str(output_dir),
    )

    engine = BenchmarkEngine(config)
    notes = args.notes or (
        f"Benchmark: {', '.join(str(m) for m in model_specs)}"
    )
    run_id = await engine.run(notes=notes)

    if run_id < 0:
        print("ERROR: Benchmark produced no results — check panel/model selection.", file=sys.stderr)
        sys.exit(1)

    # Open a fresh DB handle from the same file for the report step
    db = BenchmarkDB(db_path)
    return run_id, db, output_dir


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(db: BenchmarkDB, run_id: int, output_dir: Path) -> None:
    """Generate markdown report and JSON summary, then print terminal summary."""
    report = BenchmarkReport(db, run_id=run_id)

    # Terminal summary first so the user sees results immediately
    report.print_terminal_summary()

    # Markdown report
    report_path = output_dir / f"report_run{run_id}.md"
    report.generate(output_path=report_path)
    print(f"\nFull report written to: {report_path}")

    # JSON summary
    summary_path = output_dir / f"summary_run{run_id}.json"
    summary = report.generate_json_summary()
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"JSON summary written to: {summary_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # --- informational exits ---
    if args.list_models:
        list_ollama_models(args.ollama_url)  # exits

    if args.list_panels:
        list_panels()  # exits

    # --- report-only mode ---
    if args.report_only:
        if not args.db:
            print("ERROR: --db is required with --report-only", file=sys.stderr)
            sys.exit(1)
        db_path = Path(args.db)
        if not db_path.exists():
            print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
            sys.exit(1)

        db = BenchmarkDB(db_path)

        # Resolve run_id: use provided value, else find the most recent run
        run_id = args.run_id
        if not run_id:
            row = db.conn.execute(
                "SELECT id FROM benchmark_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                print("ERROR: No benchmark runs found in database.", file=sys.stderr)
                db.close()
                sys.exit(1)
            run_id = row["id"]
            logger.info(f"No --run-id specified; using most recent run: {run_id}")

        output_dir = db_path.parent
        generate_report(db, run_id, output_dir)
        db.close()
        return

    # --- full benchmark run ---
    run_id, db, output_dir = asyncio.run(run_benchmark(args))
    generate_report(db, run_id, output_dir)
    db.close()


if __name__ == "__main__":
    main()
