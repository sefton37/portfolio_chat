"""Integration tests for the API endpoints."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from portfolio_chat.server import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_status(self, client):
        """Test that health endpoint returns a status."""
        # Note: This will fail if orchestrator isn't initialized
        # In a real test, we'd mock the orchestrator
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


class TestRootEndpoint:
    """Tests for / endpoint."""

    def test_root_returns_api_info(self, client):
        """Test that root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["name"] == "Portfolio Chat API"


class TestChatEndpoint:
    """Tests for /chat endpoint."""

    def test_rejects_empty_message(self, client):
        """Test that empty message is rejected by Pydantic validation."""
        response = client.post(
            "/chat",
            json={"message": ""},
        )
        # Pydantic validation should reject empty string
        assert response.status_code == 422

    def test_rejects_too_long_message(self, client):
        """Test that too-long message is rejected."""
        response = client.post(
            "/chat",
            json={"message": "a" * 10000},
        )
        # Should be rejected by Pydantic (max_length=SECURITY.MAX_INPUT_LENGTH, default 2000)
        assert response.status_code == 422

    def test_requires_message_field(self, client):
        """Test that message field is required."""
        response = client.post(
            "/chat",
            json={},
        )
        assert response.status_code == 422

    def test_accepts_valid_request_format(self, client):
        """Test that valid request format is accepted."""
        # This will fail without Ollama but validates the request format
        response = client.post(
            "/chat",
            json={"message": "Hello"},
        )
        # Should get either success or internal error (no Ollama in test)
        assert response.status_code in [200, 503]

    def test_accepts_conversation_id(self, client):
        """Test that conversation_id is accepted."""
        response = client.post(
            "/chat",
            json={
                "message": "Hello",
                "conversation_id": "test-conv-123",
            },
        )
        # Format is valid
        assert response.status_code in [200, 503]

    def test_response_has_correct_structure(self, client):
        """Test that response has correct structure."""
        response = client.post(
            "/chat",
            json={"message": "Hello"},
        )

        if response.status_code == 200:
            data = response.json()
            assert "success" in data
            assert "metadata" in data

            if data["success"]:
                assert "response" in data
                assert "content" in data["response"]
                assert "domain" in data["response"]
            else:
                assert "error" in data
                assert "code" in data["error"]
                assert "message" in data["error"]


class TestRequestHeaders:
    """Tests for request header handling."""

    def test_returns_request_id_header(self, client):
        """Test that X-Request-ID header is returned."""
        response = client.get("/health")
        assert "X-Request-ID" in response.headers

    def test_returns_response_time_header(self, client):
        """Test that X-Response-Time header is returned."""
        response = client.get("/health")
        assert "X-Response-Time" in response.headers


class TestCORS:
    """Tests for CORS handling."""

    def test_cors_allows_configured_origin(self, client):
        """Test that CORS allows configured production origin."""
        response = client.options(
            "/chat",
            headers={
                "Origin": "https://kellogg.brengel.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        # CORS middleware should allow the production origin
        assert response.status_code in [200, 405]  # 405 if OPTIONS not explicitly handled

    def test_cors_rejects_disallowed_origin(self, client):
        """Test that CORS rejects origins not in the allowed list."""
        response = client.options(
            "/chat",
            headers={
                "Origin": "http://malicious-site.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        # Disallowed origin should be rejected (400) or not get CORS headers
        assert response.status_code == 400 or "access-control-allow-origin" not in response.headers
