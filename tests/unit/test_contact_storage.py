"""Unit tests for contact message storage."""

import json
import tempfile
from pathlib import Path

import pytest

from portfolio_chat.contact.storage import (
    ContactMessage,
    ContactStorage,
)


class TestContactMessage:
    """Tests for ContactMessage dataclass."""

    def test_required_fields(self):
        """Test ContactMessage with required fields only."""
        message = ContactMessage(
            id="abc123",
            timestamp="2024-01-15T10:30:00Z",
            message="Hello, I'd like to connect!",
        )

        assert message.id == "abc123"
        assert message.timestamp == "2024-01-15T10:30:00Z"
        assert message.message == "Hello, I'd like to connect!"

    def test_optional_fields(self):
        """Test ContactMessage with all fields."""
        message = ContactMessage(
            id="abc123",
            timestamp="2024-01-15T10:30:00Z",
            message="Hello!",
            sender_name="John Doe",
            sender_email="john@example.com",
            context="Conversation about Python",
            ip_hash="hash123",
            conversation_id="conv-456",
        )

        assert message.sender_name == "John Doe"
        assert message.sender_email == "john@example.com"
        assert message.context == "Conversation about Python"
        assert message.ip_hash == "hash123"
        assert message.conversation_id == "conv-456"

    def test_to_dict(self):
        """Test to_dict conversion."""
        message = ContactMessage(
            id="abc123",
            timestamp="2024-01-15T10:30:00Z",
            message="Hello!",
            sender_name="John",
        )

        d = message.to_dict()

        assert d["id"] == "abc123"
        assert d["timestamp"] == "2024-01-15T10:30:00Z"
        assert d["message"] == "Hello!"
        assert d["sender_name"] == "John"
        assert d["sender_email"] is None

    def test_default_values(self):
        """Test default values for optional fields."""
        message = ContactMessage(
            id="id",
            timestamp="ts",
            message="msg",
        )

        assert message.sender_name is None
        assert message.sender_email is None
        assert message.context is None
        assert message.ip_hash is None
        assert message.conversation_id is None


class TestContactStorage:
    """Tests for ContactStorage."""

    @pytest.mark.asyncio
    async def test_store_message(self, contact_storage):
        """Test storing a message."""
        result = await contact_storage.store(
            message="Hello, I'm interested in your work!",
            sender_name="John Doe",
            sender_email="john@example.com",
            ip_hash="hash123",
            conversation_id="conv-456",
        )

        assert result.id  # Should have generated ID
        assert result.timestamp  # Should have timestamp
        assert result.message == "Hello, I'm interested in your work!"
        assert result.sender_name == "John Doe"

    @pytest.mark.asyncio
    async def test_store_creates_file(self, contact_storage):
        """Test that storing creates a file."""
        result = await contact_storage.store(message="Test message")

        # File should exist
        files = list(contact_storage.storage_dir.glob("*.json"))
        assert len(files) == 1

        # Read file content
        with open(files[0]) as f:
            data = json.load(f)

        assert data["message"] == "Test message"
        assert data["id"] == result.id

    @pytest.mark.asyncio
    async def test_store_minimal_message(self, contact_storage):
        """Test storing with only required message field."""
        result = await contact_storage.store(message="Just a message")

        assert result.message == "Just a message"
        assert result.sender_name is None
        assert result.sender_email is None

    @pytest.mark.asyncio
    async def test_list_recent_empty(self, contact_storage):
        """Test listing recent messages when empty."""
        messages = await contact_storage.list_recent()

        assert messages == []

    @pytest.mark.asyncio
    async def test_list_recent_single(self, contact_storage):
        """Test listing with one message."""
        await contact_storage.store(message="Test message")

        messages = await contact_storage.list_recent()

        assert len(messages) == 1
        assert messages[0].message == "Test message"

    @pytest.mark.asyncio
    async def test_list_recent_multiple(self, contact_storage):
        """Test listing multiple messages."""
        await contact_storage.store(message="Message 1")
        await contact_storage.store(message="Message 2")
        await contact_storage.store(message="Message 3")

        messages = await contact_storage.list_recent()

        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_list_recent_limit(self, contact_storage):
        """Test limiting recent messages."""
        for i in range(5):
            await contact_storage.store(message=f"Message {i}")

        messages = await contact_storage.list_recent(limit=3)

        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_get_message(self, contact_storage):
        """Test getting a specific message."""
        stored = await contact_storage.store(message="Find this message")

        retrieved = await contact_storage.get(stored.id)

        assert retrieved is not None
        assert retrieved.id == stored.id
        assert retrieved.message == "Find this message"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, contact_storage):
        """Test getting a message that doesn't exist."""
        retrieved = await contact_storage.get("nonexistent-id")

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_count_empty(self, contact_storage):
        """Test counting when empty."""
        count = contact_storage.count()

        assert count == 0

    @pytest.mark.asyncio
    async def test_count_with_messages(self, contact_storage):
        """Test counting messages."""
        await contact_storage.store(message="Message 1")
        await contact_storage.store(message="Message 2")

        count = contact_storage.count()

        assert count == 2

    @pytest.mark.asyncio
    async def test_filename_format(self, contact_storage):
        """Test that filename follows expected format."""
        result = await contact_storage.store(message="Test")

        files = list(contact_storage.storage_dir.glob("*.json"))
        assert len(files) == 1

        filename = files[0].name
        # Should be in format: YYYY-MM-DD_<id>.json
        parts = filename.replace(".json", "").split("_")
        assert len(parts) == 2
        assert len(parts[0].split("-")) == 3  # Date parts
        assert parts[1] == result.id

    @pytest.mark.asyncio
    async def test_creates_gitkeep(self, temp_storage_dir):
        """Test that .gitkeep is created."""
        storage = ContactStorage(storage_dir=temp_storage_dir / "contacts")

        gitkeep = storage.storage_dir / ".gitkeep"
        assert gitkeep.exists()


class TestContactStorageEdgeCases:
    """Edge case tests for ContactStorage."""

    @pytest.mark.asyncio
    async def test_unicode_message(self, contact_storage):
        """Test storing message with unicode characters."""
        result = await contact_storage.store(
            message="Hello! 你好 こんにちは 🎉"
        )

        retrieved = await contact_storage.get(result.id)
        assert retrieved.message == "Hello! 你好 こんにちは 🎉"

    @pytest.mark.asyncio
    async def test_long_message(self, contact_storage):
        """Test storing a long message."""
        long_message = "A" * 10000
        result = await contact_storage.store(message=long_message)

        retrieved = await contact_storage.get(result.id)
        assert retrieved.message == long_message

    @pytest.mark.asyncio
    async def test_special_characters_in_message(self, contact_storage):
        """Test storing message with special characters."""
        message = 'Test with "quotes" and <html> and \n newlines'
        result = await contact_storage.store(message=message)

        retrieved = await contact_storage.get(result.id)
        assert retrieved.message == message

    @pytest.mark.asyncio
    async def test_handles_malformed_json_file(self, contact_storage):
        """Test handling of malformed JSON files in directory."""
        # Create a malformed JSON file
        malformed_file = contact_storage.storage_dir / "2024-01-15_bad.json"
        malformed_file.write_text("not valid json")

        # Store a valid message
        await contact_storage.store(message="Valid message")

        # list_recent should skip malformed file
        messages = await contact_storage.list_recent()
        assert len(messages) == 1
        assert messages[0].message == "Valid message"

    @pytest.mark.asyncio
    async def test_unique_ids(self, contact_storage):
        """Test that generated IDs are unique."""
        ids = set()
        for _ in range(100):
            result = await contact_storage.store(message="Test")
            assert result.id not in ids
            ids.add(result.id)
