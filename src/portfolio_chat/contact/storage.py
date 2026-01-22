"""
Contact message storage using JSON files.

Stores visitor messages in a local directory for review.
Each message is stored as a separate JSON file for easy browsing.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from portfolio_chat.config import PATHS

logger = logging.getLogger(__name__)


@dataclass
class ContactMessage:
    """A contact message from a visitor."""

    id: str
    timestamp: str
    message: str
    sender_name: str | None = None
    sender_email: str | None = None
    context: str | None = None  # Conversation summary
    ip_hash: str | None = None  # Anonymized IP for spam detection
    conversation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ContactStorage:
    """
    JSON file-based storage for contact messages.

    Each message is stored as a separate file:
    data/contacts/2024-01-15_abc123.json
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        """
        Initialize contact storage.

        Args:
            storage_dir: Directory to store contact messages.
                        Defaults to data/contacts under project root.
        """
        self.storage_dir = storage_dir or PATHS.BASE_DIR / "data" / "contacts"
        self._ensure_dir_exists()

    def _ensure_dir_exists(self) -> None:
        """Create storage directory if it doesn't exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # Create .gitkeep to preserve directory in git
        gitkeep = self.storage_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    def _generate_id(self) -> str:
        """Generate a unique message ID."""
        import uuid
        return uuid.uuid4().hex[:12]

    def _get_filename(self, message_id: str, timestamp: datetime) -> str:
        """Generate filename for a message."""
        date_str = timestamp.strftime("%Y-%m-%d")
        return f"{date_str}_{message_id}.json"

    async def store(
        self,
        message: str,
        sender_name: str | None = None,
        sender_email: str | None = None,
        context: str | None = None,
        ip_hash: str | None = None,
        conversation_id: str | None = None,
    ) -> ContactMessage:
        """
        Store a new contact message.

        Args:
            message: The message content (required).
            sender_name: Optional sender name.
            sender_email: Optional sender email.
            context: Optional conversation context/summary.
            ip_hash: Anonymized IP for spam detection.
            conversation_id: Optional conversation ID for context.

        Returns:
            The stored ContactMessage with generated ID.
        """
        now = datetime.utcnow()
        message_id = self._generate_id()

        contact = ContactMessage(
            id=message_id,
            timestamp=now.isoformat() + "Z",
            message=message,
            sender_name=sender_name,
            sender_email=sender_email,
            context=context,
            ip_hash=ip_hash,
            conversation_id=conversation_id,
        )

        # Write to file with restrictive permissions (owner read/write only)
        filename = self._get_filename(message_id, now)
        filepath = self.storage_dir / filename

        try:
            # Use os.open with explicit mode to ensure secure permissions
            # regardless of system umask. Contact messages may contain
            # sensitive information like email addresses.
            fd = os.open(filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(contact.to_dict(), f, indent=2, ensure_ascii=False)
            except Exception:
                # If fdopen or write fails, fd is already closed by fdopen
                raise
            logger.info(f"Stored contact message {message_id} from {ip_hash or 'unknown'}")
        except OSError as e:
            logger.error(f"Failed to store contact message: {e}")
            raise

        return contact

    async def list_recent(self, limit: int = 50) -> list[ContactMessage]:
        """
        List recent contact messages.

        Args:
            limit: Maximum number of messages to return.

        Returns:
            List of ContactMessage objects, newest first.
        """
        messages: list[ContactMessage] = []

        try:
            # Get all JSON files, sorted by name (date prefix) descending
            files = sorted(
                self.storage_dir.glob("*.json"),
                key=lambda p: p.name,
                reverse=True,
            )

            for filepath in files[:limit]:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        messages.append(ContactMessage(**data))
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Failed to read contact file {filepath}: {e}")
                    continue

        except OSError as e:
            logger.error(f"Failed to list contact messages: {e}")

        return messages

    async def get(self, message_id: str) -> ContactMessage | None:
        """
        Get a specific contact message by ID.

        Args:
            message_id: The message ID.

        Returns:
            ContactMessage if found, None otherwise.
        """
        # Search for file with matching ID
        for filepath in self.storage_dir.glob(f"*_{message_id}.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return ContactMessage(**data)
            except (json.JSONDecodeError, TypeError, OSError) as e:
                logger.warning(f"Failed to read contact file {filepath}: {e}")

        return None

    def count(self) -> int:
        """Return total count of stored messages."""
        return len(list(self.storage_dir.glob("*.json")))
