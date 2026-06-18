#!/usr/bin/env python3
"""
CLI entry point for the portfolio_chat model-evaluation battery.

Usage:
    # Dry-run smoke check (DOD-24)
    python3 -m tests.battery.run --tier smoke --models mistral:latest --classifier mistral:latest --dry-run

    # Real smoke run as baseline (satisfies DOD-25/26/27/28/29/30)
    python3 -m tests.battery.run --tier smoke --models mistral:latest --classifier mistral:latest --baseline

    # Full run across all profiles
    python3 -m tests.battery.run --tier full --models mistral:latest --classifier mistral:latest

    # Convenience alias for smoke tier
    python3 -m tests.battery.run --smoke --models mistral:latest --classifier mistral:latest

    # Report-only from existing DB
    python3 -m tests.battery.run --report-only --db tests/battery/results/battery_20260618_120000.db

    # Verbose logging
    python3 -m tests.battery.run --smoke --models mistral:latest -v
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path so both src/ and tests/ packages resolve.
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from tests.battery.db import BatteryDB
from tests.battery.engine import BatteryConfig, BatteryEngine
from tests.battery.report import BatteryReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Portfolio Chat Battery — evaluate classifier × generator model pairs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Model selection
    parser.add_argument(
        "--models",
        default="mistral:latest",
        help="Comma-separated generator model names (default: mistral:latest)",
    )
    parser.add_argument(
        "--classifier",
        default="mistral:latest",
        help="Comma-separated classifier model names (default: mistral:latest)",
    )

    # Tier selection (DOD-22: --smoke flag)
    tier_group = parser.add_mutually_exclusive_group()
    tier_group.add_argument(
        "--smoke",
        action="store_const",
        dest="tier",
        const="smoke",
        help="Run smoke subset (2 profiles, 2 attacks) — shorthand for --tier smoke",
    )
    tier_group.add_argument(
        "--tier",
        default="smoke",
        choices=["smoke", "full"],
        help="Run tier: smoke (fastest, satisfies DoD) or full (all profiles+attacks)",
    )

    # Dry-run (DOD-24)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the run plan without executing any LLM calls",
    )

    # Baseline flag
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Tag this run as is_baseline=1 in battery_runs",
    )

    # Output
    parser.add_argument(
        "--output",
        default="",
        help="Output directory for DB and reports (default: tests/battery/results/)",
    )

    # Infrastructure
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API base URL (default: http://localhost:11434)",
    )

    # Notes
    parser.add_argument(
        "--notes",
        default="",
        help="Notes to attach to this battery run",
    )

    # Report-only mode
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip run, generate report from existing DB",
    )
    parser.add_argument(
        "--db",
        default="",
        help="Path to existing battery DB (for --report-only)",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=0,
        help="Run ID to report on (for --report-only, default: most recent)",
    )

    # Dev-mode isolation (default OFF = dev-mode ON)
    parser.add_argument(
        "--allow-production-side-effects",
        action="store_true",
        dest="allow_production_side_effects",
        default=False,
        help=(
            "Disable dev-mode isolation. When set, ContactStorage writes to the "
            "production data/contacts/ directory and analytics are enabled. "
            "Default: OFF (dev-mode ON — contacts isolated to a throwaway temp dir)."
        ),
    )

    # Verbosity
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


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
# Battery execution
# ---------------------------------------------------------------------------

async def run_battery(args: argparse.Namespace) -> tuple[int, BatteryDB, Path]:
    """Execute the battery and return (run_id, db, output_dir)."""
    output_dir = resolve_output_dir(args.output)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_path = output_dir / f"battery_{timestamp}.db"

    # Parse comma-separated model lists
    generator_models = [m.strip() for m in args.models.split(",") if m.strip()]
    classifier_models = [m.strip() for m in args.classifier.split(",") if m.strip()]

    # Determine effective tier (--smoke sets tier="smoke" via const; --tier default is also "smoke")
    tier = args.tier or "smoke"

    config = BatteryConfig(
        classifier_models=classifier_models,
        generator_models=generator_models,
        ollama_url=args.ollama_url,
        tier=tier,
        dry_run=args.dry_run,
        run_baseline=args.baseline,
        db_path=str(db_path),
        output_dir=str(output_dir),
        notes=args.notes,
        allow_production_side_effects=args.allow_production_side_effects,
    )

    engine = BatteryEngine(config)
    notes = args.notes or (
        f"battery: tier={tier} classifier={','.join(classifier_models)} "
        f"generator={','.join(generator_models)}"
    )
    run_id = await engine.run(notes=notes)

    if run_id < 0:
        # Dry-run — no DB written
        return run_id, None, output_dir  # type: ignore[return-value]

    db = BatteryDB(db_path)
    return run_id, db, output_dir


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(db: BatteryDB, run_id: int, output_dir: Path) -> Path:
    """Generate markdown report and print terminal summary."""
    report = BatteryReport(db, run_id=run_id)
    report.print_terminal_summary()
    report_path = report.generate(output_dir=output_dir)
    print(f"\nFull report written to: {report_path}")
    return report_path


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

    # --- report-only mode ---
    if args.report_only:
        if not args.db:
            print("ERROR: --db is required with --report-only", file=sys.stderr)
            sys.exit(1)
        db_path = Path(args.db)
        if not db_path.exists():
            print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
            sys.exit(1)

        db = BatteryDB(db_path)
        run_id = args.run_id
        if not run_id:
            row = db.conn.execute(
                "SELECT id FROM battery_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                print("ERROR: No battery runs found in database.", file=sys.stderr)
                sys.exit(1)
            run_id = row["id"]
            logger.info(f"Using most recent run: {run_id}")

        output_dir = db_path.parent
        generate_report(db, run_id, output_dir)
        return

    # --- full battery run (or dry-run) ---
    run_id, db, output_dir = asyncio.run(run_battery(args))

    if args.dry_run:
        # Dry-run already printed its plan in BatteryEngine._print_dry_run_plan()
        return

    if run_id < 0 or db is None:
        print("ERROR: Battery produced no results.", file=sys.stderr)
        sys.exit(1)

    generate_report(db, run_id, output_dir)


if __name__ == "__main__":
    main()
