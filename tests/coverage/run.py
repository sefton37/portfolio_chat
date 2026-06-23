"""
Coverage harness CLI entry point.

Usage:
    python3 -m tests.coverage.run [OPTIONS]

Options:
    --generate-only         Merge parts into questions.json and exit.
    --dry-run               Run N questions (neutral only) into a TEMP db, print summary.
    --question-limit N      Max questions to run (used with --dry-run or --smoke).
    --smoke                 Run a small balanced set into the MAIN db.
    --report-only           Print report from MAIN db to stdout.
    --limit N               Max total turns (full run).
    --tones a,b,c           Comma-separated tone subset.
    --notes TEXT            Freeform notes stored in the run row.
    --resume-run-id RID     Reuse an existing run_id to resume a crashed full run.

No flags → full run: generate → run ALL × ALL 6 tones → REPORT.md.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import tempfile
import time
import uuid
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("coverage.run")

_REPO_ROOT = Path(__file__).parent.parent.parent
_MAIN_DB_PATH = Path(__file__).parent / "results" / "coverage.db"
_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
_PARTS_DIR = Path(__file__).parent / "parts"

# Smoke tier: at least 8 in_scope + 4 adjacent + 4 left_field (neutral only)
_SMOKE_MIN = {"in_scope": 8, "adjacent": 4, "left_field": 4}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Content coverage + tone robustness harness for portfolio_chat."
    )
    p.add_argument("--generate-only", action="store_true", help="Merge parts and exit.")
    p.add_argument("--dry-run", action="store_true", help="Run N questions into temp db, print summary.")
    p.add_argument("--question-limit", type=int, default=1, metavar="N", help="Max questions for --dry-run or --smoke.")
    p.add_argument("--smoke", action="store_true", help="Run balanced smoke set into MAIN db.")
    p.add_argument("--report-only", action="store_true", help="Print report from MAIN db to stdout.")
    p.add_argument("--limit", type=int, default=None, metavar="N", help="Max total turns for full run.")
    p.add_argument("--tones", type=str, default=None, metavar="TONES", help="Comma-separated tones to include.")
    p.add_argument("--notes", type=str, default="", help="Notes to store with the run.")
    p.add_argument("--resume-run-id", type=str, default=None, metavar="RID", help="Reuse an existing full-run run_id to resume after a crash.")
    return p.parse_args()


def _load_or_generate_questions(parts_dir: Path = _PARTS_DIR) -> list[dict]:
    """Load questions.json if fresh; otherwise generate it from parts."""
    from tests.coverage.questions import QuestionBank
    bank = QuestionBank()

    if _QUESTIONS_PATH.exists():
        return bank.load(_QUESTIONS_PATH)
    return bank.generate(parts_dir=parts_dir, out_path=_QUESTIONS_PATH)


def _select_smoke_questions(questions: list[dict]) -> list[dict]:
    """
    Select a balanced smoke subset:
    >= 8 in_scope, >= 4 adjacent, >= 4 left_field (sorted-deterministic).
    """
    by_cat: dict[str, list[dict]] = {}
    for q in questions:
        cat = q["category"]
        by_cat.setdefault(cat, []).append(q)

    selected: list[dict] = []
    for cat, min_count in _SMOKE_MIN.items():
        pool = sorted(by_cat.get(cat, []), key=lambda x: x["id"])
        selected.extend(pool[:min_count])

    return sorted(selected, key=lambda x: x["id"])


async def _run_full(
    questions: list[dict],
    tones: list[str] | None,
    limit: int | None,
    notes: str,
    resume_run_id: str | None = None,
) -> None:
    """Run ALL questions × tones into MAIN db."""
    from tests.coverage.db import CoverageDB
    from tests.coverage.report import CoverageReport
    from tests.coverage.runner import CoverageRunner

    db = CoverageDB(db_path=_MAIN_DB_PATH)
    runner = CoverageRunner()
    run_id = resume_run_id or f"run_{uuid.uuid4().hex[:8]}_{int(time.time())}"
    db.create_run(
        run_id=run_id,
        classifier_model="qwen2.5:3b",
        generator_model="qwen3:4b",
        n_questions=len(questions),
        n_tones=len(tones) if tones else 6,
        notes=notes or f"full run {run_id}",
    )

    try:
        await runner.run_battery(
            questions=questions,
            tones=tones,
            db=db,
            run_id=run_id,
            resume=True,
            limit=limit,
        )
    finally:
        await runner.close()

    db.finish_run(run_id)

    report = CoverageReport(db=db)
    md = report.build(run_id=run_id)
    print(md)
    print(f"\nReport written to: {Path(__file__).parent / 'results' / 'REPORT.md'}")
    db.close()


async def _run_smoke(
    questions: list[dict],
    question_limit: int | None = None,
) -> None:
    """Run balanced smoke set into MAIN db (neutral tone only)."""
    from tests.coverage.db import CoverageDB
    from tests.coverage.runner import CoverageRunner

    smoke_qs = _select_smoke_questions(questions)
    if question_limit:
        smoke_qs = smoke_qs[:question_limit]

    db = CoverageDB(db_path=_MAIN_DB_PATH)
    runner = CoverageRunner()
    run_id = f"smoke_{uuid.uuid4().hex[:8]}_{int(time.time())}"
    db.create_run(
        run_id=run_id,
        classifier_model="qwen2.5:3b",
        generator_model="qwen3:4b",
        n_questions=len(smoke_qs),
        n_tones=1,
        notes=f"smoke run {run_id}",
    )

    try:
        await runner.run_battery(
            questions=smoke_qs,
            tones=["neutral"],
            db=db,
            run_id=run_id,
            resume=True,
        )
    finally:
        await runner.close()

    db.finish_run(run_id)

    # Print quick summary
    turns = db.fetch_turns(run_id)
    total = len(turns)
    passed = sum(
        1 for t in turns
        if (
            (t["category"] == "in_scope" and t["verdict"] == "correct")
            or (t["category"] == "adjacent" and t["verdict"] == "resisted")
            or (t["category"] == "left_field" and t["verdict"] == "refused")
        )
    )
    print(f"Smoke run {run_id}: {passed}/{total} passed")
    print(f"DB: {_MAIN_DB_PATH}")
    db.close()


async def _run_dry(
    questions: list[dict],
    question_limit: int,
) -> None:
    """Run question_limit questions (neutral only) into a TEMP db. Print summary."""
    from tests.coverage.db import CoverageDB
    from tests.coverage.runner import CoverageRunner

    # Use first N questions (deterministic)
    subset = sorted(questions, key=lambda x: x["id"])[:question_limit]

    with tempfile.TemporaryDirectory(prefix="coverage_dry_") as tmpdir:
        db_path = Path(tmpdir) / "dry.db"
        db = CoverageDB(db_path=db_path)
        runner = CoverageRunner()
        run_id = f"dry_{uuid.uuid4().hex[:8]}"
        db.create_run(
            run_id=run_id,
            classifier_model="qwen2.5:3b",
            generator_model="qwen3:4b",
            n_questions=len(subset),
            n_tones=1,
            notes="dry run",
        )

        try:
            await runner.run_battery(
                questions=subset,
                tones=["neutral"],
                db=db,
                run_id=run_id,
                resume=False,
            )
        finally:
            await runner.close()

        turns = db.fetch_turns(run_id)
        print(f"[dry-run] {len(turns)} turn(s) completed")
        for t in turns:
            print(
                f"  {t['question_id']} / {t['tone']}: "
                f"verdict={t['verdict']} success={t['success']} "
                f"latency={t['latency_ms']:.0f}ms"
                if t['latency_ms'] else f"  {t['question_id']} / {t['tone']}: verdict={t['verdict']}"
            )
        db.close()


def _report_only() -> None:
    """Print report from MAIN db to stdout."""
    from tests.coverage.db import CoverageDB
    from tests.coverage.report import CoverageReport

    db = CoverageDB(db_path=_MAIN_DB_PATH)
    report = CoverageReport(db=db)
    # Always print all sections including tone_robustness and adversarial headers
    md = report.build()
    print(md)
    db.close()


def main() -> None:
    args = _parse_args()
    tones: list[str] | None = None
    if args.tones:
        tones = [t.strip() for t in args.tones.split(",") if t.strip()]

    # --generate-only
    if args.generate_only:
        from tests.coverage.questions import QuestionBank
        bank = QuestionBank()
        questions = bank.generate(parts_dir=_PARTS_DIR, out_path=_QUESTIONS_PATH)
        print(f"Generated questions.json: {len(questions)} questions")
        sys.exit(0)

    # --report-only
    if args.report_only:
        _report_only()
        sys.exit(0)

    # For all other modes, load/generate questions
    questions = _load_or_generate_questions()
    print(f"Loaded {len(questions)} questions")

    # --dry-run
    if args.dry_run:
        asyncio.run(_run_dry(questions, args.question_limit))
        sys.exit(0)

    # --smoke
    if args.smoke:
        asyncio.run(_run_smoke(questions, question_limit=args.question_limit if args.question_limit > 1 else None))
        sys.exit(0)

    # Default: full run
    asyncio.run(_run_full(questions, tones, args.limit, args.notes, args.resume_run_id))


if __name__ == "__main__":
    main()
