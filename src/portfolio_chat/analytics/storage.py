"""
Conversation log storage using JSON files.

Stores conversation logs in a local directory organized by date.
Each conversation is stored as a separate JSON file for easy browsing.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from portfolio_chat.config import PATHS

logger = logging.getLogger(__name__)


@dataclass
class ConversationMessage:
    """A single message in a conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: str
    domain: str | None = None
    response_time_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class ConversationLog:
    """A complete conversation log."""

    id: str
    started_at: str
    last_activity: str
    ip_hash: str
    total_turns: int = 0
    domains_used: list[str] = field(default_factory=list)
    total_response_time_ms: float = 0.0
    blocked_at_layer: str | None = None
    messages: list[ConversationMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["messages"] = [m.to_dict() if isinstance(m, ConversationMessage) else m for m in self.messages]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationLog:
        """Create from dictionary."""
        messages = [
            ConversationMessage(**m) if isinstance(m, dict) else m
            for m in data.get("messages", [])
        ]
        return cls(
            id=data["id"],
            started_at=data["started_at"],
            last_activity=data["last_activity"],
            ip_hash=data["ip_hash"],
            total_turns=data.get("total_turns", 0),
            domains_used=data.get("domains_used", []),
            total_response_time_ms=data.get("total_response_time_ms", 0.0),
            blocked_at_layer=data.get("blocked_at_layer"),
            messages=messages,
        )


class ConversationStorage:
    """
    JSON file-based storage for conversation logs.

    Each conversation is stored as a separate file organized by date:
    data/conversations/2024-01-15/conv_abc123.json
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        """
        Initialize conversation storage.

        Args:
            storage_dir: Directory to store conversation logs.
                        Defaults to data/conversations under project root.
        """
        self.storage_dir = storage_dir or PATHS.BASE_DIR / "data" / "conversations"
        self._ensure_dir_exists()
        # In-memory cache for active conversations
        self._active_conversations: dict[str, ConversationLog] = {}

    def _ensure_dir_exists(self) -> None:
        """Create storage directory if it doesn't exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = self.storage_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    def _get_date_dir(self, timestamp: datetime) -> Path:
        """Get directory for a specific date."""
        date_str = timestamp.strftime("%Y-%m-%d")
        date_dir = self.storage_dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        return date_dir

    def _get_filepath(self, conversation_id: str, timestamp: datetime) -> Path:
        """Get filepath for a conversation."""
        date_dir = self._get_date_dir(timestamp)
        return date_dir / f"conv_{conversation_id}.json"

    def _find_conversation_file(self, conversation_id: str) -> Path | None:
        """Find a conversation file by ID across all date directories."""
        for date_dir in sorted(self.storage_dir.iterdir(), reverse=True):
            if date_dir.is_dir() and not date_dir.name.startswith("."):
                filepath = date_dir / f"conv_{conversation_id}.json"
                if filepath.exists():
                    return filepath
        return None

    async def log_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        ip_hash: str,
        domain: str | None = None,
        response_time_ms: float | None = None,
        blocked_at_layer: str | None = None,
    ) -> ConversationLog:
        """
        Log a message to a conversation.

        Creates a new conversation log if one doesn't exist for this ID.

        Args:
            conversation_id: The conversation ID.
            role: Message role ("user" or "assistant").
            content: Message content.
            ip_hash: Anonymized IP hash.
            domain: Domain used for routing (assistant messages only).
            response_time_ms: Response time in milliseconds.
            blocked_at_layer: If blocked, which layer blocked it.

        Returns:
            Updated ConversationLog.
        """
        now = datetime.utcnow()
        timestamp = now.isoformat() + "Z"

        # Check in-memory cache first
        if conversation_id in self._active_conversations:
            conv_log = self._active_conversations[conversation_id]
        else:
            # Try to load from disk
            conv_log = await self.get(conversation_id)
            if conv_log is None:
                # Create new conversation log
                conv_log = ConversationLog(
                    id=conversation_id,
                    started_at=timestamp,
                    last_activity=timestamp,
                    ip_hash=ip_hash,
                )
            self._active_conversations[conversation_id] = conv_log

        # Add message
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=timestamp,
            domain=domain,
            response_time_ms=response_time_ms,
        )
        conv_log.messages.append(message)

        # Update metadata
        conv_log.last_activity = timestamp
        if role == "assistant":
            conv_log.total_turns += 1
            if domain and domain not in conv_log.domains_used:
                conv_log.domains_used.append(domain)
            if response_time_ms:
                conv_log.total_response_time_ms += response_time_ms

        if blocked_at_layer:
            conv_log.blocked_at_layer = blocked_at_layer

        # Persist to disk
        await self._save(conv_log, now)

        return conv_log

    async def _save(self, conv_log: ConversationLog, timestamp: datetime) -> None:
        """Save a conversation log to disk."""
        # Use the started_at timestamp for file organization
        started = datetime.fromisoformat(conv_log.started_at.replace("Z", "+00:00"))
        filepath = self._get_filepath(conv_log.id, started)

        try:
            fd = os.open(filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(conv_log.to_dict(), f, indent=2, ensure_ascii=False)
            except Exception:
                raise
            logger.debug(f"Saved conversation log {conv_log.id}")
        except OSError as e:
            logger.error(f"Failed to save conversation log: {e}")
            raise

    async def get(self, conversation_id: str) -> ConversationLog | None:
        """
        Get a specific conversation by ID.

        Args:
            conversation_id: The conversation ID.

        Returns:
            ConversationLog if found, None otherwise.
        """
        # Check cache first
        if conversation_id in self._active_conversations:
            return self._active_conversations[conversation_id]

        # Search on disk
        filepath = self._find_conversation_file(conversation_id)
        if filepath is None:
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return ConversationLog.from_dict(data)
        except (json.JSONDecodeError, TypeError, OSError) as e:
            logger.warning(f"Failed to read conversation file {filepath}: {e}")
            return None

    async def list_recent(
        self,
        limit: int = 50,
        offset: int = 0,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[ConversationLog]:
        """
        List recent conversations.

        Args:
            limit: Maximum number of conversations to return.
            offset: Number of conversations to skip.
            start_date: Filter to conversations after this date.
            end_date: Filter to conversations before this date.

        Returns:
            List of ConversationLog objects, newest first (sorted by last_activity).
        """
        conversations: list[ConversationLog] = []

        try:
            # Get all date directories
            date_dirs = [d for d in self.storage_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]

            # Filter by date range
            if start_date:
                start_str = start_date.strftime("%Y-%m-%d")
                date_dirs = [d for d in date_dirs if d.name >= start_str]
            if end_date:
                end_str = end_date.strftime("%Y-%m-%d")
                date_dirs = [d for d in date_dirs if d.name <= end_str]

            # Collect all conversation files
            all_files: list[Path] = []
            for date_dir in date_dirs:
                all_files.extend(date_dir.glob("conv_*.json"))

            # Load all conversations to sort by actual timestamp
            all_conversations: list[ConversationLog] = []
            for filepath in all_files:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        all_conversations.append(ConversationLog.from_dict(data))
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Failed to read conversation file {filepath}: {e}")
                    continue

            # Sort by last_activity descending (most recent first)
            all_conversations.sort(key=lambda c: c.last_activity, reverse=True)

            # Apply offset and limit
            conversations = all_conversations[offset : offset + limit]

        except OSError as e:
            logger.error(f"Failed to list conversations: {e}")

        return conversations

    async def count(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """
        Count total conversations.

        Args:
            start_date: Filter to conversations after this date.
            end_date: Filter to conversations before this date.

        Returns:
            Total count of conversations.
        """
        total = 0

        try:
            date_dirs = [d for d in self.storage_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]

            if start_date:
                start_str = start_date.strftime("%Y-%m-%d")
                date_dirs = [d for d in date_dirs if d.name >= start_str]
            if end_date:
                end_str = end_date.strftime("%Y-%m-%d")
                date_dirs = [d for d in date_dirs if d.name <= end_str]

            for date_dir in date_dirs:
                total += len(list(date_dir.glob("conv_*.json")))

        except OSError as e:
            logger.error(f"Failed to count conversations: {e}")

        return total

    def clear_cache(self, conversation_id: str | None = None) -> None:
        """
        Clear the in-memory cache.

        Args:
            conversation_id: Optional ID to clear specific conversation.
                           If None, clears all cached conversations.
        """
        if conversation_id:
            self._active_conversations.pop(conversation_id, None)
        else:
            self._active_conversations.clear()
