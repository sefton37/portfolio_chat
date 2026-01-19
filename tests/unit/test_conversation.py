"""Tests for conversation manager."""

import pytest
import time

from portfolio_chat.conversation.manager import (
    ConversationManager,
    Message,
    MessageRole,
)


@pytest.fixture
def manager():
    """Create a conversation manager with short TTL for testing."""
    return ConversationManager(max_turns=5, ttl_seconds=60)


class TestConversationManager:
    """Tests for ConversationManager."""

    @pytest.mark.asyncio
    async def test_creates_new_conversation(self, manager):
        """Test that new conversations are created."""
        conversation, is_new = await manager.get_or_create(None)
        assert is_new
        assert conversation.id
        assert len(conversation.messages) == 0

    @pytest.mark.asyncio
    async def test_retrieves_existing_conversation(self, manager):
        """Test that existing conversations are retrieved."""
        # Create a conversation
        conv1, _ = await manager.get_or_create(None)
        conv_id = conv1.id

        # Retrieve it
        conv2, is_new = await manager.get_or_create(conv_id)
        assert not is_new
        assert conv2.id == conv_id

    @pytest.mark.asyncio
    async def test_adds_messages(self, manager):
        """Test that messages are added correctly."""
        conversation, _ = await manager.get_or_create(None)
        conv_id = conversation.id

        # Add user message
        result = await manager.add_message(conv_id, "user", "Hello!")
        assert result

        # Add assistant message
        result = await manager.add_message(conv_id, "assistant", "Hi there!")
        assert result

        # Check history
        history = await manager.get_history(conv_id)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello!"
        assert history[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_respects_turn_limit(self, manager):
        """Test that turn limit is enforced."""
        conversation, _ = await manager.get_or_create(None)
        conv_id = conversation.id

        # Add max turns
        for i in range(5):
            await manager.add_message(conv_id, "user", f"Message {i}")
            await manager.add_message(conv_id, "assistant", f"Response {i}")

        # Try to add one more user message - should fail
        result = await manager.add_message(conv_id, "user", "One more")
        assert not result

        # Check turn count
        is_at_limit = await manager.check_turn_limit(conv_id)
        assert is_at_limit

    @pytest.mark.asyncio
    async def test_returns_empty_history_for_unknown(self, manager):
        """Test that unknown conversation returns empty history."""
        history = await manager.get_history("nonexistent")
        assert history == []

    @pytest.mark.asyncio
    async def test_delete_conversation(self, manager):
        """Test that conversations can be deleted."""
        conversation, _ = await manager.get_or_create(None)
        conv_id = conversation.id

        # Delete it
        result = await manager.delete_conversation(conv_id)
        assert result

        # Try to get it - should return new conversation
        _, is_new = await manager.get_or_create(conv_id)
        assert is_new

    @pytest.mark.asyncio
    async def test_generates_unique_ids(self, manager):
        """Test that generated IDs are unique."""
        ids = set()
        for _ in range(100):
            new_id = manager.generate_id()
            assert new_id not in ids
            ids.add(new_id)

    @pytest.mark.asyncio
    async def test_stats(self, manager):
        """Test that stats are tracked."""
        await manager.get_or_create(None)
        await manager.get_or_create(None)

        stats = manager.get_stats()
        assert stats["active_conversations"] == 2
        assert stats["max_turns"] == 5
        assert stats["ttl_seconds"] == 60


class TestMessage:
    """Tests for Message dataclass."""

    def test_to_dict(self):
        """Test Message to_dict conversion."""
        msg = Message(role=MessageRole.USER, content="Hello")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"

    def test_timestamp_set(self):
        """Test that timestamp is set automatically."""
        before = time.time()
        msg = Message(role=MessageRole.ASSISTANT, content="Hi")
        after = time.time()

        assert before <= msg.timestamp <= after
