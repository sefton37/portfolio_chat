"""Contact message sweeper — polls contacts_dir and emails unsent messages via sendmail.

Designed to run as a systemd timer unit. Does NOT import from portfolio_chat.config
to avoid triggering AnalyticsConfig/ConsentConfig which raise ValueError when
ADMIN_TOKEN/CONSENT_SECRET env vars are absent.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import formatdate
from pathlib import Path

logger = logging.getLogger(__name__)

# Exactly one occurrence of the recipient address — used everywhere via this constant.
CONTACT_RECIPIENT: str = os.getenv("CONTACT_RECIPIENT", "kellogg@brengel.com")

# From address for outbound mail — must NOT contain CONTACT_RECIPIENT.
_FROM_ADDRESS = "portfolio-chat@corellia.localdomain"

# Absolute path to sendmail binary.
SENDMAIL_PATH = "/usr/sbin/sendmail"

# Default contacts directory: four parent hops from this file reaches the project root.
# sweeper.py → contact/ → portfolio_chat/ → src/ → project_root
_DEFAULT_CONTACTS_DIR: Path = Path(__file__).parent.parent.parent.parent / "data" / "contacts"


def _sendmail(message_text: str) -> bool:
    """Send a pre-formatted RFC-822 message via /usr/sbin/sendmail.

    Returns True if sendmail exited 0, False otherwise.
    """
    result = subprocess.run(
        [SENDMAIL_PATH, "-t"],
        input=message_text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.error("sendmail failed (rc=%d): %s", result.returncode, result.stderr.strip())
    return result.returncode == 0


def _format_email(data: dict[str, object]) -> str:
    """Build an RFC-822 email string from a contact message dict."""
    contact_id = data.get("id", "")
    timestamp = data.get("timestamp", "")
    sender_name = data.get("sender_name") or ""
    sender_email = data.get("sender_email") or ""
    conversation_id = data.get("conversation_id") or ""
    message = data.get("message", "")
    context = data.get("context") or ""

    subject = f"Portfolio contact from {sender_name or 'visitor'}"

    lines: list[str] = [
        f"From: {_FROM_ADDRESS}",
        f"To: {CONTACT_RECIPIENT}",
        f"Subject: {subject}",
        f"Date: {formatdate(usegmt=True)}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
    ]

    if sender_email:
        lines.append(f"Reply-To: {sender_email}")

    lines.append("")  # blank line separating headers from body
    lines.append(f"id: {contact_id}")
    lines.append(f"timestamp: {timestamp}")
    lines.append(f"sender_name: {sender_name}")
    lines.append(f"sender_email: {sender_email}")
    lines.append(f"conversation_id: {conversation_id}")
    lines.append(f"message: {message}")
    lines.append(f"context: {context}")

    return "\n".join(lines)


def _write_emailed_at(filepath: Path, data: dict[str, object]) -> None:
    """Atomically update the contact JSON file to add emailed_at timestamp.

    Mirrors the os.open/os.fdopen/os.rename idiom from storage.py to keep
    permissions at 0o600 regardless of umask.
    """
    data["emailed_at"] = datetime.now(tz=UTC).isoformat()

    tmp_path = filepath.parent / (filepath.name + ".tmp")
    try:
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            # fdopen consumed fd; clean up tmp file and re-raise.
            with contextlib.suppress(OSError):
                os.unlink(str(tmp_path))
            raise
        os.rename(str(tmp_path), str(filepath))
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(str(tmp_path))
        raise


class ContactSweeper:
    """Sweeps the contacts directory and emails any unsent messages."""

    def __init__(
        self,
        contacts_dir: Path | None = None,
        sender: Callable[[str], bool] | None = None,
    ) -> None:
        self._contacts_dir: Path = contacts_dir or _DEFAULT_CONTACTS_DIR
        self._sender: Callable[[str], bool] = sender if sender is not None else _sendmail

    def _get_hwm(self) -> datetime:
        """Return the high-water mark as a tz-aware datetime.

        If the HWM file is absent it is created seeded to now (UTC), which
        causes all pre-existing files to be treated as already-seen backlog.
        """
        hwm_file = self._contacts_dir / ".sweeper_hwm"
        if not hwm_file.exists():
            now = datetime.now(tz=UTC)
            hwm_file.write_text(now.isoformat())
            return now

        raw = hwm_file.read_text().strip()
        # Normalize trailing Z → +00:00 for Python <3.11 fromisoformat compat.
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)

    def sweep(self) -> tuple[int, int]:
        """Process all JSON files in contacts_dir, emailing eligible messages.

        Returns:
            (sent, skipped) counts.
        """
        hwm = self._get_hwm()
        sent = 0
        skipped = 0

        json_files = sorted(self._contacts_dir.glob("*.json"))
        for filepath in json_files:
            try:
                with open(filepath, encoding="utf-8") as f:
                    data: dict[str, object] = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping %s: %s", filepath.name, exc)
                continue

            # Skip already-emailed files.
            if "emailed_at" in data:
                skipped += 1
                continue

            # Skip empty or whitespace-only messages.
            message = data.get("message")
            if not isinstance(message, str) or not message.strip():
                skipped += 1
                continue

            # Skip files that don't have a timestamp field.
            raw_ts = data.get("timestamp")
            if not isinstance(raw_ts, str):
                logger.warning("Skipping %s: missing or non-string timestamp", filepath.name)
                skipped += 1
                continue

            # Parse timestamp tz-aware.
            try:
                ts_str = raw_ts
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                file_ts = datetime.fromisoformat(ts_str)
            except ValueError as exc:
                logger.warning("Skipping %s: unparseable timestamp %r: %s", filepath.name, raw_ts, exc)
                skipped += 1
                continue

            # Skip files at or before the HWM.
            if file_ts <= hwm:
                skipped += 1
                continue

            # Build and send the email.
            email_text = _format_email(data)
            if not self._sender(email_text):
                logger.error("Failed to send email for %s; will retry next run", filepath.name)
                continue

            # Mark as sent.
            try:
                _write_emailed_at(filepath, data)
            except OSError as exc:
                logger.error("Could not write emailed_at for %s: %s", filepath.name, exc)

            sent += 1

        return sent, skipped


def run_sweep(contacts_dir: Path | None = None) -> None:
    """Convenience entry point — create a sweeper and run it once."""
    sweeper = ContactSweeper(contacts_dir=contacts_dir)
    sent, skipped = sweeper.sweep()
    logger.info("Sweep complete: sent=%d skipped=%d", sent, skipped)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_sweep()
