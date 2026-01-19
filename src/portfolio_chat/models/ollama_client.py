"""
Async Ollama client with retry logic and custom exception hierarchy.

Pattern from talking_rock: Custom exception hierarchy with recoverability flags,
retry with exponential backoff via tenacity.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from portfolio_chat.config import MODELS

logger = logging.getLogger(__name__)


# Exception hierarchy with recoverability flags
class OllamaError(RuntimeError):
    """Base exception for Ollama operations."""

    recoverable: bool = False


class OllamaConnectionError(OllamaError):
    """Network connectivity issues - recoverable."""

    recoverable: bool = True


class OllamaTimeoutError(OllamaError):
    """Request timeout - recoverable."""

    recoverable: bool = True


class OllamaModelError(OllamaError):
    """Model loading/execution error - not recoverable."""

    recoverable: bool = False


class OllamaResponseError(OllamaError):
    """Invalid response from Ollama - not recoverable."""

    recoverable: bool = False


class AsyncOllamaClient:
    """Async HTTP client for Ollama API with retry logic."""

    def __init__(
        self,
        url: str | None = None,
        default_model: str | None = None,
    ) -> None:
        """
        Initialize Ollama client.

        Args:
            url: Ollama server URL. Defaults to config.
            default_model: Default model to use. Falls back to config.
        """
        self.url = (url or MODELS.OLLAMA_URL).rstrip("/")
        self.default_model = default_model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> AsyncOllamaClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    def _resolve_model(self, model: str | None) -> str:
        """Resolve model name from explicit, default, or config."""
        if model:
            return model
        if self.default_model:
            return self.default_model
        return MODELS.GENERATOR_MODEL

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((OllamaConnectionError, OllamaTimeoutError)),
        reraise=True,
    )
    async def chat_text(
        self,
        system: str,
        user: str,
        model: str | None = None,
        timeout: float | None = None,
        temperature: float = 0.7,
    ) -> str:
        """
        Send a chat request and get a text response.

        Args:
            system: System prompt.
            user: User message.
            model: Model to use. Falls back to default/config.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature.

        Returns:
            The generated text response.

        Raises:
            OllamaConnectionError: Network connectivity issues.
            OllamaTimeoutError: Request timeout.
            OllamaModelError: Model loading/execution error.
            OllamaResponseError: Invalid response format.
        """
        resolved_model = self._resolve_model(model)
        effective_timeout = timeout or MODELS.GENERATOR_TIMEOUT

        client = await self._get_client()

        payload = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        try:
            response = await client.post(
                f"{self.url}/api/chat",
                json=payload,
                timeout=effective_timeout,
            )
        except httpx.ConnectError as e:
            logger.warning(f"Connection error to Ollama: {e}")
            raise OllamaConnectionError(f"Failed to connect to Ollama: {e}") from e
        except httpx.TimeoutException as e:
            logger.warning(f"Timeout calling Ollama: {e}")
            raise OllamaTimeoutError(f"Ollama request timed out: {e}") from e
        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling Ollama: {e}")
            raise OllamaConnectionError(f"HTTP error: {e}") from e

        if response.status_code == 404:
            raise OllamaModelError(f"Model not found: {resolved_model}")

        if response.status_code != 200:
            error_text = response.text[:500]
            logger.error(f"Ollama error response: {response.status_code} - {error_text}")
            raise OllamaModelError(f"Ollama returned status {response.status_code}: {error_text}")

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise OllamaResponseError(f"Invalid JSON response: {e}") from e

        message = data.get("message", {})
        content = message.get("content", "")

        if not content:
            raise OllamaResponseError("Empty response from Ollama")

        return content

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((OllamaConnectionError, OllamaTimeoutError)),
        reraise=True,
    )
    async def chat_json(
        self,
        system: str,
        user: str,
        model: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Send a chat request expecting JSON output.

        Args:
            system: System prompt (should instruct JSON output).
            user: User message.
            model: Model to use.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            OllamaResponseError: If response is not valid JSON.
        """
        resolved_model = self._resolve_model(model)
        effective_timeout = timeout or MODELS.CLASSIFIER_TIMEOUT

        client = await self._get_client()

        payload = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.0,  # Deterministic for classification
            },
        }

        try:
            response = await client.post(
                f"{self.url}/api/chat",
                json=payload,
                timeout=effective_timeout,
            )
        except httpx.ConnectError as e:
            logger.warning(f"Connection error to Ollama: {e}")
            raise OllamaConnectionError(f"Failed to connect to Ollama: {e}") from e
        except httpx.TimeoutException as e:
            logger.warning(f"Timeout calling Ollama: {e}")
            raise OllamaTimeoutError(f"Ollama request timed out: {e}") from e
        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling Ollama: {e}")
            raise OllamaConnectionError(f"HTTP error: {e}") from e

        if response.status_code == 404:
            raise OllamaModelError(f"Model not found: {resolved_model}")

        if response.status_code != 200:
            error_text = response.text[:500]
            raise OllamaModelError(f"Ollama returned status {response.status_code}: {error_text}")

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise OllamaResponseError(f"Invalid JSON response from Ollama: {e}") from e

        content = data.get("message", {}).get("content", "")

        if not content:
            raise OllamaResponseError("Empty response from Ollama")

        # Parse the JSON content
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from model output: {content[:200]}")
            raise OllamaResponseError(f"Model output is not valid JSON: {e}") from e

    async def chat_with_history(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        timeout: float | None = None,
        temperature: float = 0.7,
    ) -> str:
        """
        Send a chat request with conversation history.

        Args:
            system: System prompt.
            messages: List of message dicts with 'role' and 'content'.
            model: Model to use.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature.

        Returns:
            The generated text response.
        """
        resolved_model = self._resolve_model(model)
        effective_timeout = timeout or MODELS.GENERATOR_TIMEOUT

        client = await self._get_client()

        all_messages = [{"role": "system", "content": system}] + messages

        payload = {
            "model": resolved_model,
            "messages": all_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        try:
            response = await client.post(
                f"{self.url}/api/chat",
                json=payload,
                timeout=effective_timeout,
            )
        except httpx.ConnectError as e:
            raise OllamaConnectionError(f"Failed to connect to Ollama: {e}") from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(f"Ollama request timed out: {e}") from e
        except httpx.HTTPError as e:
            raise OllamaConnectionError(f"HTTP error: {e}") from e

        if response.status_code == 404:
            raise OllamaModelError(f"Model not found: {resolved_model}")

        if response.status_code != 200:
            error_text = response.text[:500]
            raise OllamaModelError(f"Ollama returned status {response.status_code}: {error_text}")

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise OllamaResponseError(f"Invalid JSON response: {e}") from e

        content = data.get("message", {}).get("content", "")

        if not content:
            raise OllamaResponseError("Empty response from Ollama")

        return content

    async def chat_stream(
        self,
        system: str,
        user: str,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Send a chat request and stream the response.

        Args:
            system: System prompt.
            user: User message.
            model: Model to use.

        Yields:
            Chunks of the generated response.
        """
        resolved_model = self._resolve_model(model)
        client = await self._get_client()

        payload = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
        }

        try:
            async with client.stream(
                "POST",
                f"{self.url}/api/chat",
                json=payload,
                timeout=MODELS.GENERATOR_TIMEOUT,
            ) as response:
                if response.status_code == 404:
                    raise OllamaModelError(f"Model not found: {resolved_model}")

                if response.status_code != 200:
                    text = await response.aread()
                    raise OllamaModelError(
                        f"Ollama returned status {response.status_code}: {text[:500]}"
                    )

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

        except httpx.ConnectError as e:
            raise OllamaConnectionError(f"Failed to connect to Ollama: {e}") from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(f"Ollama request timed out: {e}") from e

    async def health_check(self) -> bool:
        """
        Check if Ollama is reachable.

        Returns:
            True if Ollama is reachable, False otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get(f"{self.url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """
        List available models.

        Returns:
            List of model names.
        """
        client = await self._get_client()

        try:
            response = await client.get(f"{self.url}/api/tags", timeout=10.0)
        except httpx.HTTPError as e:
            raise OllamaConnectionError(f"Failed to list models: {e}") from e

        if response.status_code != 200:
            raise OllamaResponseError(f"Failed to list models: {response.status_code}")

        data = response.json()
        models = data.get("models", [])
        return [m.get("name", "") for m in models if m.get("name")]
