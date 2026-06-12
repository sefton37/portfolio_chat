"""Unit tests for contact message sweeper (DoD: Spec #182, Issue #286).

Each test traces to a specific DoD item:
  DoD-14  test_sends_new_message, test_email_contains_required_fields,
          test_reply_to_set_when_sender_email_present,
          test_reply_to_absent_when_no_sender_email,
          test_emailed_at_written_atomically
  DoD-15  test_idempotent_second_run_no_double_send
  DoD-16  test_sendmail_failure_leaves_file_unmarked_for_retry
  DoD-17  test_backlog_hwm_excludes_preexisting_files,
          test_hwm_file_created_on_first_run_if_absent,
          test_hwm_only_new_files_after_hwm_are_sent
  DoD-18  test_empty_message_skipped, test_whitespace_only_message_skipped,
          test_malformed_json_skipped_continues,
          test_missing_json_fields_skipped
  DoD-19  test_run_sweep_function_exists
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from portfolio_chat.contact.sweeper import CONTACT_RECIPIENT, ContactSweeper, run_sweep


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _write_contact(
    contacts_dir: Path,
    *,
    message: str = "Hello, please reach out!",
    timestamp: str = "2099-01-01T00:00:00Z",
    sender_name: str | None = "Visitor Name",
    sender_email: str | None = "visitor@example.com",
    context: str | None = None,
    ip_hash: str | None = None,
    conversation_id: str | None = None,
    emailed_at: str | None = None,
    malformed: bool = False,
    file_id: str = "abc123",
) -> Path:
    """Write a contact JSON file that matches the ContactMessage schema."""
    filepath = contacts_dir / f"2099-01-01_{file_id}.json"
    if malformed:
        filepath.write_text("not valid json")
        return filepath

    data: dict[str, object] = {
        "id": file_id,
        "timestamp": timestamp,
        "message": message,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "context": context,
        "ip_hash": ip_hash,
        "conversation_id": conversation_id,
    }
    if emailed_at is not None:
        data["emailed_at"] = emailed_at

    filepath.write_text(json.dumps(data, indent=2))
    return filepath


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContactSweeper:
    """Tests for ContactSweeper sweep logic."""

    # -- DoD-14: happy path --------------------------------------------------

    def test_sends_new_message(self, tmp_path: Path) -> None:
        """A new eligible message causes sender to be called exactly once."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        _write_contact(contacts_dir, file_id="msg001")

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sent, skipped = sweeper.sweep()

        assert sent == 1
        assert skipped == 0
        sender.assert_called_once()

    # -- DoD-15: idempotency -------------------------------------------------

    def test_idempotent_second_run_no_double_send(self, tmp_path: Path) -> None:
        """Running sweep twice does not send the same message twice (DoD-15)."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        _write_contact(contacts_dir, file_id="msg002")

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sweeper.sweep()
        sent, skipped = sweeper.sweep()

        assert sent == 0
        assert skipped == 1
        assert sender.call_count == 1  # never called a second time

    # -- DoD-16: retry on failure --------------------------------------------

    def test_sendmail_failure_leaves_file_unmarked_for_retry(self, tmp_path: Path) -> None:
        """When sender returns False the file is NOT marked so it retries (DoD-16)."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        filepath = _write_contact(contacts_dir, file_id="msg003")

        sender = MagicMock(return_value=False)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sent, skipped = sweeper.sweep()

        assert sent == 0
        sender.assert_called_once()

        # File must NOT contain emailed_at
        data = json.loads(filepath.read_text())
        assert "emailed_at" not in data

    # -- DoD-17: HWM / backlog protection ------------------------------------

    def test_backlog_hwm_excludes_preexisting_files(self, tmp_path: Path) -> None:
        """Files with timestamp at/before the HWM are not sent (DoD-17)."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        # Write HWM file at a known past timestamp
        hwm_file = contacts_dir / ".sweeper_hwm"
        hwm_file.write_text("2025-01-01T00:00:00Z")

        # File whose timestamp is BEFORE the HWM
        _write_contact(
            contacts_dir,
            file_id="old001",
            timestamp="2024-06-15T12:00:00Z",
        )

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sent, skipped = sweeper.sweep()

        assert sent == 0
        sender.assert_not_called()

    def test_hwm_file_created_on_first_run_if_absent(self, tmp_path: Path) -> None:
        """If .sweeper_hwm is absent it is created on first run (DoD-17)."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        hwm_file = contacts_dir / ".sweeper_hwm"
        assert not hwm_file.exists()

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)
        sweeper.sweep()

        assert hwm_file.exists()
        hwm_content = hwm_file.read_text().strip()
        assert len(hwm_content) > 0  # non-empty ISO-8601 string

    def test_hwm_only_new_files_after_hwm_are_sent(self, tmp_path: Path) -> None:
        """Only files with timestamp strictly after the HWM are sent (DoD-17)."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        hwm_file = contacts_dir / ".sweeper_hwm"
        hwm_file.write_text("2025-06-01T00:00:00Z")

        # Old file — timestamp at exactly the HWM boundary (not strictly after)
        _write_contact(
            contacts_dir,
            file_id="at_hwm",
            timestamp="2025-06-01T00:00:00Z",
            sender_email=None,
        )

        # New file — timestamp strictly after HWM
        _write_contact(
            contacts_dir,
            file_id="after_hwm",
            timestamp="2025-06-15T10:00:00Z",
            sender_email=None,
        )

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sent, skipped = sweeper.sweep()

        assert sent == 1
        assert sender.call_count == 1

    # -- DoD-18: robustness --------------------------------------------------

    def test_empty_message_skipped(self, tmp_path: Path) -> None:
        """A contact file whose message field is empty is skipped without error."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        _write_contact(contacts_dir, file_id="empty_msg", message="")

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sent, skipped = sweeper.sweep()

        assert sent == 0
        sender.assert_not_called()

    def test_whitespace_only_message_skipped(self, tmp_path: Path) -> None:
        """A contact file with only whitespace in message is skipped."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        _write_contact(contacts_dir, file_id="ws_msg", message="   \t\n  ")

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sent, skipped = sweeper.sweep()

        assert sent == 0
        sender.assert_not_called()

    def test_malformed_json_skipped_continues(self, tmp_path: Path) -> None:
        """A malformed JSON file is skipped and the sweep continues to valid files."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        # One bad file; give it an earlier prefix so glob ordering is stable
        bad = contacts_dir / "2099-01-01_bad.json"
        bad.write_text("not valid json")

        # One good file with a later timestamp to ensure it passes HWM
        _write_contact(contacts_dir, file_id="good001")

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sent, skipped = sweeper.sweep()

        assert sent == 1
        sender.assert_called_once()

    def test_missing_json_fields_skipped(self, tmp_path: Path) -> None:
        """A JSON file missing required fields (e.g. 'message') is skipped."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        # Write a JSON file that looks valid but lacks 'message'
        incomplete = contacts_dir / "2099-01-01_nofields.json"
        incomplete.write_text(json.dumps({"id": "nofields", "timestamp": "2099-01-01T00:00:00Z"}))

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)

        sent, skipped = sweeper.sweep()

        assert sent == 0
        sender.assert_not_called()

    # -- DoD-14: RFC-822 headers ---------------------------------------------

    def test_reply_to_set_when_sender_email_present(self, tmp_path: Path) -> None:
        """The RFC-822 string passed to sender contains Reply-To when sender_email present."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        _write_contact(
            contacts_dir,
            file_id="rt_present",
            sender_email="visitor@example.com",
        )

        captured: list[str] = []

        def capturing_sender(msg: str) -> bool:
            captured.append(msg)
            return True

        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=capturing_sender)
        sweeper.sweep()

        assert len(captured) == 1
        assert "Reply-To:" in captured[0]
        assert "visitor@example.com" in captured[0]

    def test_reply_to_absent_when_no_sender_email(self, tmp_path: Path) -> None:
        """The RFC-822 string passed to sender has NO Reply-To when sender_email is absent."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        _write_contact(
            contacts_dir,
            file_id="rt_absent",
            sender_email=None,
        )

        captured: list[str] = []

        def capturing_sender(msg: str) -> bool:
            captured.append(msg)
            return True

        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=capturing_sender)
        sweeper.sweep()

        assert len(captured) == 1
        assert "Reply-To:" not in captured[0]

    def test_email_contains_required_fields(self, tmp_path: Path) -> None:
        """The RFC-822 string includes id, timestamp, message text, and To: header."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        _write_contact(
            contacts_dir,
            file_id="req_fields",
            message="Please get in touch.",
            timestamp="2099-01-01T00:00:00Z",
        )

        captured: list[str] = []

        def capturing_sender(msg: str) -> bool:
            captured.append(msg)
            return True

        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=capturing_sender)
        sweeper.sweep()

        assert len(captured) == 1
        body = captured[0]

        assert f"To: {CONTACT_RECIPIENT}" in body
        assert "req_fields" in body          # contact id
        assert "2099-01-01T00:00:00Z" in body  # timestamp
        assert "Please get in touch." in body   # message text

    def test_emailed_at_written_atomically(self, tmp_path: Path) -> None:
        """After a successful send the file is valid JSON with all original fields plus emailed_at."""
        contacts_dir = tmp_path / "contacts"
        contacts_dir.mkdir()

        filepath = _write_contact(
            contacts_dir,
            file_id="atomic001",
            message="Test atomic write.",
            sender_name="Alice",
            sender_email="alice@example.com",
        )

        sender = MagicMock(return_value=True)
        sweeper = ContactSweeper(contacts_dir=contacts_dir, sender=sender)
        sweeper.sweep()

        # File must still parse as valid JSON
        data = json.loads(filepath.read_text())

        # Original fields must be preserved
        assert data["id"] == "atomic001"
        assert data["message"] == "Test atomic write."
        assert data["sender_name"] == "Alice"
        assert data["sender_email"] == "alice@example.com"

        # emailed_at must now be present and non-empty
        assert "emailed_at" in data
        assert isinstance(data["emailed_at"], str)
        assert len(data["emailed_at"]) > 0

    # -- DoD-19: run_sweep convenience function ------------------------------

    def test_run_sweep_function_exists(self) -> None:
        """run_sweep is importable and callable (DoD-19)."""
        # If the import at the top of this file succeeded, the symbol exists.
        # Verify it is callable without executing it (no real mail sending).
        assert callable(run_sweep)
