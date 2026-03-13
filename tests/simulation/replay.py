#!/usr/bin/env python3
"""
Replay real conversations from portfolio_chat logs through the current system.

Extracts user messages from historical conversation logs, replays them
against the live server, and compares domain routing and response quality.

Usage:
    python -m tests.simulation.replay --url http://127.0.0.1:8001
    python -m tests.simulation.replay --url http://127.0.0.1:8001 --date 2026-01-23
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

from tests.simulation.db import SimulationDB

logger = logging.getLogger(__name__)


@dataclass
class OriginalTurn:
    """A turn from the original conversation log."""
    user_message: str
    original_domain: str | None = None
    original_response: str | None = None
    original_response_time_ms: float | None = None
    original_blocked: bool = False


@dataclass
class ReplayConversation:
    """A conversation to replay."""
    conv_id: str
    date: str
    ip_hash: str
    turns: list[OriginalTurn] = field(default_factory=list)


@dataclass
class ReplayResult:
    """Result of replaying a single turn."""
    success: bool = False
    new_domain: str | None = None
    new_response: str | None = None
    new_response_time_ms: float | None = None
    new_blocked: bool = False
    error_code: str | None = None
    error_message: str | None = None
    domain_changed: bool = False
    conversation_id: str | None = None


def load_conversations(
    data_dir: Path,
    date_filter: str | None = None,
) -> list[ReplayConversation]:
    """Load conversations from the data directory."""
    conversations = []

    for conv_file in sorted(data_dir.rglob("*.json")):
        try:
            with open(conv_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        conv_date = data.get("started_at", "")[:10]
        if date_filter and conv_date != date_filter:
            continue

        messages = data.get("messages", [])
        if not messages:
            continue

        conv = ReplayConversation(
            conv_id=data.get("id", conv_file.stem),
            date=conv_date,
            ip_hash=data.get("ip_hash", "unknown"),
        )

        # Extract user turns with their original responses
        for i, msg in enumerate(messages):
            if msg["role"] != "user":
                continue

            # Find the assistant response that follows
            original_domain = None
            original_response = None
            original_time = None
            original_blocked = False

            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                assistant_msg = messages[i + 1]
                original_domain = assistant_msg.get("domain")
                original_response = assistant_msg.get("content")
                original_time = assistant_msg.get("response_time_ms")
            elif data.get("blocked_at_layer"):
                original_blocked = True

            conv.turns.append(OriginalTurn(
                user_message=msg["content"],
                original_domain=original_domain,
                original_response=original_response,
                original_response_time_ms=original_time,
                original_blocked=original_blocked,
            ))

        if conv.turns:
            conversations.append(conv)

    return conversations


async def replay_conversation(
    client: httpx.AsyncClient,
    conv: ReplayConversation,
    delay_between_turns: float = 1.0,
) -> list[tuple[OriginalTurn, ReplayResult]]:
    """Replay a single conversation and return paired results."""
    results = []
    conversation_id = None
    # Use a unique simulated IP per original conversation
    simulated_ip = f"10.1.0.{hash(conv.conv_id) % 254 + 1}"

    for turn in conv.turns:
        payload: dict = {"message": turn.user_message}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        headers = {
            "Content-Type": "application/json",
            "CF-Connecting-IP": simulated_ip,
        }

        start_time = time.time()
        result = ReplayResult()

        try:
            resp = await client.post("/chat", json=payload, headers=headers)
            elapsed_ms = (time.time() - start_time) * 1000

            if resp.status_code == 429:
                result.error_code = "RATE_LIMITED"
                result.error_message = "Rate limited"
                result.new_response_time_ms = elapsed_ms
            else:
                data = resp.json()
                result.success = data.get("success", False)
                result.new_response = data.get("response", {}).get("content") if data.get("response") else None
                result.new_domain = data.get("response", {}).get("domain") if data.get("response") else None
                result.new_response_time_ms = data.get("metadata", {}).get("response_time_ms", elapsed_ms)
                result.conversation_id = data.get("metadata", {}).get("conversation_id")
                result.new_blocked = not data.get("success", False) and data.get("error", {}).get("code") in ("BLOCKED_INPUT",)

                if data.get("error"):
                    result.error_code = data["error"].get("code")
                    result.error_message = data["error"].get("message")

                if result.conversation_id and not conversation_id:
                    conversation_id = result.conversation_id

        except httpx.TimeoutException:
            result.error_code = "TIMEOUT"
            result.error_message = "Request timed out"
            result.new_response_time_ms = (time.time() - start_time) * 1000
        except Exception as e:
            result.error_code = "ERROR"
            result.error_message = str(e)[:200]
            result.new_response_time_ms = (time.time() - start_time) * 1000

        # Track domain changes
        if turn.original_domain and result.new_domain:
            result.domain_changed = turn.original_domain.lower() != result.new_domain.lower()

        results.append((turn, result))

        if len(conv.turns) > 1:
            await asyncio.sleep(delay_between_turns)

    return results


def print_report(
    all_results: list[tuple[ReplayConversation, list[tuple[OriginalTurn, ReplayResult]]]],
):
    """Print a comparison report."""
    total_turns = 0
    successful_new = 0
    successful_old = 0
    domain_changes = 0
    domain_comparable = 0
    faster_count = 0
    slower_count = 0
    time_diffs = []
    errors_new = 0
    blocked_new = 0
    domain_change_details = []

    for conv, results in all_results:
        for orig, replay in results:
            total_turns += 1

            if replay.success:
                successful_new += 1
            elif replay.new_blocked or replay.error_code == "BLOCKED_INPUT":
                blocked_new += 1
            elif replay.error_code:
                errors_new += 1

            if orig.original_response and not orig.original_blocked:
                successful_old += 1

            if orig.original_domain and replay.new_domain:
                domain_comparable += 1
                if orig.original_domain.lower() != replay.new_domain.lower():
                    domain_changes += 1
                    domain_change_details.append({
                        "conv": conv.conv_id[:8],
                        "date": conv.date,
                        "message": orig.user_message[:70],
                        "old": orig.original_domain,
                        "new": replay.new_domain,
                    })

            if orig.original_response_time_ms and replay.new_response_time_ms:
                diff = replay.new_response_time_ms - orig.original_response_time_ms
                time_diffs.append(diff)
                if diff < -500:  # >500ms faster
                    faster_count += 1
                elif diff > 500:  # >500ms slower
                    slower_count += 1

    avg_time_diff = sum(time_diffs) / len(time_diffs) if time_diffs else 0

    print()
    print("=" * 70)
    print("  REPLAY COMPARISON — Historical vs Current System")
    print("=" * 70)
    print(f"  Conversations: {len(all_results)}  |  Turns: {total_turns}")
    print(f"  Original success: {successful_old}/{total_turns} ({100*successful_old/total_turns:.0f}%)")
    print(f"  Current success:  {successful_new}/{total_turns} ({100*successful_new/total_turns:.0f}%)")
    print(f"  Current blocked:  {blocked_new}  |  Current errors: {errors_new}")
    print()
    print(f"  Domain routing changes: {domain_changes}/{domain_comparable} "
          f"({100*domain_changes/domain_comparable:.0f}% changed)" if domain_comparable else "  No domain data to compare")
    print()
    if time_diffs:
        print(f"  Avg time change: {avg_time_diff:+.0f}ms")
        print(f"  Faster (>500ms): {faster_count}  |  Slower (>500ms): {slower_count}")
    print("=" * 70)

    if domain_change_details:
        print()
        print("  DOMAIN ROUTING CHANGES (old → new):")
        print("  " + "-" * 66)
        for d in domain_change_details[:30]:
            print(f"  [{d['date']}] {d['old']:>15} → {d['new']:<15} | {d['message']}")
        if len(domain_change_details) > 30:
            print(f"  ... and {len(domain_change_details) - 30} more")

    print()
    return {
        "total_turns": total_turns,
        "successful_old": successful_old,
        "successful_new": successful_new,
        "blocked_new": blocked_new,
        "errors_new": errors_new,
        "domain_changes": domain_changes,
        "domain_comparable": domain_comparable,
        "avg_time_diff_ms": avg_time_diff,
        "domain_change_details": domain_change_details,
    }


def generate_markdown_report(
    all_results: list[tuple[ReplayConversation, list[tuple[OriginalTurn, ReplayResult]]]],
    stats: dict,
    output_path: Path,
):
    """Generate a markdown report."""
    lines = [
        "# Replay Comparison Report",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Summary",
        "",
        "| Metric | Original | Current |",
        "|--------|----------|---------|",
        f"| Conversations | {len(all_results)} | {len(all_results)} |",
        f"| Total turns | {stats['total_turns']} | {stats['total_turns']} |",
        f"| Successful | {stats['successful_old']} | {stats['successful_new']} |",
        f"| Blocked | — | {stats['blocked_new']} |",
        f"| Errors | — | {stats['errors_new']} |",
        "",
        "## Domain Routing Changes",
        "",
        f"**Changed:** {stats['domain_changes']}/{stats['domain_comparable']} "
        f"({100*stats['domain_changes']/stats['domain_comparable']:.0f}%)" if stats['domain_comparable'] else "No domain data",
        "",
    ]

    if stats["domain_change_details"]:
        lines += [
            "| Date | Old Domain | New Domain | Message |",
            "|------|-----------|-----------|---------|",
        ]
        for d in stats["domain_change_details"]:
            msg = d["message"].replace("|", "\\|")
            lines.append(f"| {d['date']} | {d['old']} | {d['new']} | {msg} |")
        lines.append("")

    # Per-conversation detail
    lines += ["## Conversation Details", ""]
    for conv, results in all_results:
        has_changes = any(r.domain_changed for _, r in results)
        has_errors = any(r.error_code for _, r in results)
        if not has_changes and not has_errors:
            continue

        lines.append(f"### Conv {conv.conv_id[:8]} ({conv.date})")
        lines.append("")
        lines.append("| Turn | Message | Old Domain | New Domain | Status |")
        lines.append("|------|---------|-----------|-----------|--------|")

        for orig, replay in results:
            msg = orig.user_message[:60].replace("|", "\\|")
            old_d = orig.original_domain or "—"
            new_d = replay.new_domain or replay.error_code or "—"
            status = "changed" if replay.domain_changed else ("error" if replay.error_code else "same")
            flag = " **" if replay.domain_changed else ""
            lines.append(f"| {msg} | {old_d} | {new_d} | {status}{flag} |")

        lines.append("")

    output_path.write_text("\n".join(lines))
    print(f"Report written to: {output_path}")


async def main():
    parser = argparse.ArgumentParser(description="Replay historical conversations")
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--date", default="", help="Filter to specific date (YYYY-MM-DD)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between turns")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", default="", help="Output directory")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    data_dir = Path(__file__).parent.parent.parent / "data" / "conversations"
    output_dir = Path(args.output) if args.output else Path(__file__).parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load conversations
    conversations = load_conversations(data_dir, date_filter=args.date or None)
    total_turns = sum(len(c.turns) for c in conversations)
    logger.info(f"Loaded {len(conversations)} conversations with {total_turns} turns")

    if not conversations:
        print("No conversations found.")
        return

    # Replay
    client = httpx.AsyncClient(base_url=args.url, timeout=args.timeout)
    all_results = []

    try:
        for i, conv in enumerate(conversations, 1):
            logger.info(f"[{i}/{len(conversations)}] Replaying conv {conv.conv_id[:8]} "
                       f"({conv.date}, {len(conv.turns)} turns)")

            results = await replay_conversation(client, conv, delay_between_turns=args.delay)
            all_results.append((conv, results))

            for orig, replay in results:
                status = "OK" if replay.success else f"ERR:{replay.error_code}"
                domain_note = ""
                if replay.domain_changed:
                    domain_note = f" [CHANGED: {orig.original_domain}→{replay.new_domain}]"
                logger.info(f"  {status} | {orig.user_message[:50]}...{domain_note}")

            # Small delay between conversations
            if i < len(conversations):
                await asyncio.sleep(0.5)

    finally:
        await client.aclose()

    # Report
    stats = print_report(all_results)
    report_path = output_dir / f"replay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    generate_markdown_report(all_results, stats, report_path)


if __name__ == "__main__":
    asyncio.run(main())
