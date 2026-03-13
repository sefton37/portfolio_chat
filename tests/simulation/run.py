#!/usr/bin/env python3
"""
CLI runner for the portfolio chat conversation simulation.

Usage:
    # Run full simulation against running server
    python -m tests.simulation.run

    # Custom server URL and output
    python -m tests.simulation.run --url http://localhost:8001 --output results/

    # Run specific profiles only
    python -m tests.simulation.run --profiles hiring_manager,security_researcher

    # Analyze a previous run
    python -m tests.simulation.run --analyze-only --db results/sim.db --run-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

from tests.simulation.analysis import SimulationAnalyzer, generate_report, print_summary
from tests.simulation.db import SimulationDB
from tests.simulation.engine import EngineConfig, SimulationEngine
from tests.simulation.profiles import build_profiles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portfolio Chat Conversation Simulator")

    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL for portfolio_chat server")
    parser.add_argument("--output", default="", help="Output directory for results (default: tests/simulation/results/)")
    parser.add_argument("--profiles", default="", help="Comma-separated profile IDs to run (default: all)")
    parser.add_argument("--delay-turns", type=float, default=1.0, help="Seconds between turns")
    parser.add_argument("--delay-profiles", type=float, default=3.0, help="Seconds between profiles")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds")
    parser.add_argument("--analyze-only", action="store_true", help="Skip simulation, only analyze existing DB")
    parser.add_argument("--db", default="", help="Path to existing database (for --analyze-only)")
    parser.add_argument("--run-id", type=int, default=0, help="Run ID to analyze (for --analyze-only)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--notes", default="", help="Notes to attach to this run")

    return parser.parse_args()


async def run_simulation(args: argparse.Namespace) -> tuple[int, SimulationDB, Path]:
    """Execute the simulation and return (run_id, db, output_dir)."""
    # Set up output directory
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = Path(__file__).parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_path = output_dir / f"simulation_{timestamp}.db"

    # Build profile list
    all_profiles = build_profiles()
    if args.profiles:
        selected_ids = set(args.profiles.split(","))
        profiles = [p for p in all_profiles if p.id in selected_ids]
        if not profiles:
            print(f"No matching profiles found. Available: {', '.join(p.id for p in all_profiles)}")
            sys.exit(1)
    else:
        profiles = all_profiles

    # Configure engine
    config = EngineConfig(
        base_url=args.url,
        request_timeout=args.timeout,
        delay_between_turns=args.delay_turns,
        delay_between_profiles=args.delay_profiles,
        db_path=str(db_path),
    )

    engine = SimulationEngine(config)
    notes = args.notes or f"Full simulation with {len(profiles)} profiles"
    run_id = await engine.run(profiles=profiles, notes=notes)

    return run_id, engine.db, output_dir  # type: ignore


def analyze_and_report(db: SimulationDB, run_id: int, output_dir: Path):
    """Run analysis and generate reports."""
    analyzer = SimulationAnalyzer(db)
    result = analyzer.analyze(run_id)

    # Print terminal summary
    print_summary(result)

    # Generate markdown report
    report_path = output_dir / f"report_run{run_id}.md"
    report = generate_report(result, output_path=report_path)
    print(f"Full report written to: {report_path}")

    return result


def main():
    args = parse_args()

    # Set up logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.analyze_only:
        # Analyze existing database
        if not args.db:
            print("--db is required with --analyze-only")
            sys.exit(1)
        db_path = Path(args.db)
        if not db_path.exists():
            print(f"Database not found: {db_path}")
            sys.exit(1)
        db = SimulationDB(db_path)
        run_id = args.run_id or 1
        output_dir = db_path.parent
        analyze_and_report(db, run_id, output_dir)
        db.close()
    else:
        # Run simulation + analysis
        run_id, db, output_dir = asyncio.run(run_simulation(args))
        if db:
            analyze_and_report(db, run_id, output_dir)
            db.close()


if __name__ == "__main__":
    main()
