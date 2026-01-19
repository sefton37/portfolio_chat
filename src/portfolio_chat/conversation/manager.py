"""
Conversation manager for multi-turn support.

Provides in-memory conversation storage with TTL and automatic pruning.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from portfolio_chat.config import CONVERSATION


class MessageRole(Enum):
    """Role of a message in the conversation."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """A message in a conversation."""

    role: MessageRole
    content: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str]:
        """Convert to dict for Ollama API."""
        return {
            "role": self.role.value,
            "content": self.content,
        }


@dataclass
class Conversation:
    """A conversation with message history."""

    id: str
    messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    def add_message(self, role: MessageRole, content: str) -> None:
        """Add a message to the conversation."""
        self.messages.append(Message(role=role, content=content))
        self.last_activity = time.time()

    def get_history(self) -> list[dict[str, str]]:
        """Get message history as list of dicts for Ollama."""
        return [msg.to_dict() for msg in self.messages]

    def is_expired(self, ttl: int) -> bool:
        """Check if conversation has expired."""
        return time.time() - self.last_activity > ttl

    @property
    def turn_count(self) -> int:
        """Count conversation turns (user messages)."""
        return sum(1 for msg in self.messages if msg.role == MessageRole.USER)


class ConversationManager:
    """
    Manages multi-turn conversations with automatic cleanup.

    Features:
    - In-memory storage with TTL
    - Maximum turns per conversation
    - Automatic pruning of expired conversations
    - Thread-safe with asyncio locks
    """

    def __init__(
        self,
        max_turns: int | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        """
        Initialize conversation manager.

        Args:
            max_turns: Maximum turns per conversation.
            ttl_seconds: Time-to-live for conversations.
        """
        self.max_turns = max_turns or CONVERSATION.MAX_TURNS
        self.ttl_seconds = ttl_seconds or CONVERSATION.TTL_SECONDS

        self._conversations: dict[str, Conversation] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 60.0  # Cleanup every minute

    def generate_id(self) -> str:
        """Generate a unique conversation ID."""
        return str(uuid.uuid4())

    async def get_or_create(self, conversation_id: str | None) -> tuple[Conversation, bool]:
        """
        Get existing conversation or create new one.

        Args:
            conversation_id: Optional conversation ID.

        Returns:
            Tuple of (conversation, is_new).
        """
        async with self._lock:
            # Periodic cleanup
            now = time.time()
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired()
                self._last_cleanup = now

            # Create new conversation if no ID provided
            if not conversation_id:
                conv_id = self.generate_id()
                conversation = Conversation(id=conv_id)
                self._conversations[conv_id] = conversation
                return conversation, True

            # Get existing conversation
            if conversation_id in self._conversations:
                conversation = self._conversations[conversation_id]

                # Check if expired
                if conversation.is_expired(self.ttl_seconds):
                    del self._conversations[conversation_id]
                    conv_id = self.generate_id()
                    conversation = Conversation(id=conv_id)
                    self._conversations[conv_id] = conversation
                    return conversation, True

                return conversation, False

            # Create new conversation with provided ID if it doesn't exist
            # (client may have expired or invalid ID)
            conv_id = self.generate_id()
            conversation = Conversation(id=conv_id)
            self._conversations[conv_id] = conversation
            return conversation, True

    async def get_history(self, conversation_id: str) -> list[dict[str, str]]:
        """
        Get conversation history.

        Args:
            conversation_id: Conversation ID.

        Returns:
            List of message dicts or empty list if not found.
        """
        async with self._lock:
            if conversation_id not in self._conversations:
                return []

            conversation = self._conversations[conversation_id]
            if conversation.is_expired(self.ttl_seconds):
                del self._conversations[conversation_id]
                return []

            return conversation.get_history()

    async def add_message(
        self,
        conversation_id: str,
        role: str | MessageRole,
        content: str,
    ) -> bool:
        """
        Add a message to a conversation.

        Args:
            conversation_id: Conversation ID.
            role: Message role ("user" or "assistant").
            content: Message content.

        Returns:
            True if message was added, False if conversation not found or at max turns.
        """
        async with self._lock:
            if conversation_id not in self._conversations:
                return False

            conversation = self._conversations[conversation_id]

            # Check if expired
            if conversation.is_expired(self.ttl_seconds):
                del self._conversations[conversation_id]
                return False

            # Convert string role to enum
            if isinstance(role, str):
                role = MessageRole(role)

            # Check turn limit (only count user messages)
            if role == MessageRole.USER and conversation.turn_count >= self.max_turns:
                return False

            conversation.add_message(role, content)
            return True

    async def check_turn_limit(self, conversation_id: str) -> bool:
        """
        Check if conversation has reached turn limit.

        Args:
            conversation_id: Conversation ID.

        Returns:
            True if at or over limit, False otherwise.
        """
        async with self._lock:
            if conversation_id not in self._conversations:
                return False

            conversation = self._conversations[conversation_id]
            return conversation.turn_count >= self.max_turns

    def _cleanup_expired(self) -> None:
        """Remove expired conversations. Called with lock held."""
        expired = [
            conv_id
            for conv_id, conv in self._conversations.items()
            if conv.is_expired(self.ttl_seconds)
        ]

        for conv_id in expired:
            del self._conversations[conv_id]

    async def cleanup_expired(self) -> int:
        """
        Public method to trigger cleanup.

        Returns:
            Number of conversations removed.
        """
        async with self._lock:
            initial_count = len(self._conversations)
            self._cleanup_expired()
            return initial_count - len(self._conversations)

    def get_stats(self) -> dict[str, int]:
        """Get manager statistics."""
        return {
            "active_conversations": len(self._conversations),
            "max_turns": self.max_turns,
            "ttl_seconds": self.ttl_seconds,
        }

    async def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation.

        Args:
            conversation_id: Conversation ID.

        Returns:
            True if deleted, False if not found.
        """
        async with self._lock:
            if conversation_id in self._conversations:
                del self._conversations[conversation_id]
                return True
            return False
