"""
Async Ollama client with retry logic and custom exception hierarchy.

Pattern from talking_rock: Custom exception hierarchy with recoverability flags,
retry with exponential backoff via tenacity.
"""

from __future__ import annotations

import json
import logging
import time
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
from portfolio_chat.utils.logging import audit_logger, request_id_var

logger = logging.getLogger(__name__)


def _get_metrics() -> dict | None:
    """Lazy import metrics to avoid circular imports."""
    try:
        from portfolio_chat.server import METRICS
        return METRICS
    except ImportError:
        return None


def _approx_tokens(text: str) -> int:
    """Rough approximation of token count (4 chars per token)."""
    return len(text) // 4


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
        layer: str | None = None,
        purpose: str | None = None,
    ) -> str:
        """
        Send a chat request and get a text response.

        Args:
            system: System prompt.
            user: User message.
            model: Model to use. Falls back to default/config.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature.
            layer: Which pipeline layer is calling (for metrics).
            purpose: Purpose of the call (for metrics).

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
        start_time = time.time()
        request_id = request_id_var.get()
        success = False
        error_msg = None
        content = ""

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

            if response.status_code == 404:
                error_msg = f"Model not found: {resolved_model}"
                raise OllamaModelError(error_msg)

            if response.status_code != 200:
                error_text = response.text[:500]
                error_msg = f"Ollama returned status {response.status_code}: {error_text}"
                logger.error(f"Ollama error response: {response.status_code} - {error_text}")
                raise OllamaModelError(error_msg)

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON response: {e}"
                raise OllamaResponseError(error_msg) from e

            message = data.get("message", {})
            content = message.get("content", "")

            if not content:
                error_msg = "Empty response from Ollama"
                raise OllamaResponseError(error_msg)

            success = True
            return content

        except httpx.ConnectError as e:
            error_msg = f"Failed to connect to Ollama: {e}"
            logger.warning(f"Connection error to Ollama: {e}")
            raise OllamaConnectionError(error_msg) from e
        except httpx.TimeoutException as e:
            error_msg = f"Ollama request timed out: {e}"
            logger.warning(f"Timeout calling Ollama: {e}")
            raise OllamaTimeoutError(error_msg) from e
        except httpx.HTTPError as e:
            error_msg = f"HTTP error: {e}"
            logger.error(f"HTTP error calling Ollama: {e}")
            raise OllamaConnectionError(error_msg) from e
        finally:
            duration_ms = (time.time() - start_time) * 1000

            # Record metrics
            prom_metrics = _get_metrics()
            if prom_metrics and layer and purpose:
                prom_metrics["ollama_calls"].labels(
                    model=resolved_model,
                    layer=layer,
                    purpose=purpose,
                ).observe(duration_ms / 1000)

            # Log LLM call
            if request_id and layer:
                audit_logger.log_llm_call(
                    request_id=request_id,
                    layer=layer,
                    model=resolved_model,
                    purpose=purpose or "text_generation",
                    prompt_tokens_approx=_approx_tokens(system + user),
                    response_tokens_approx=_approx_tokens(content),
                    duration_ms=duration_ms,
                    success=success,
                    error=error_msg,
                )

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
        layer: str | None = None,
        purpose: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a chat request expecting JSON output.

        Args:
            system: System prompt (should instruct JSON output).
            user: User message.
            model: Model to use.
            timeout: Request timeout in seconds.
            layer: Which pipeline layer is calling (for metrics).
            purpose: Purpose of the call (for metrics).

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            OllamaResponseError: If response is not valid JSON.
        """
        resolved_model = self._resolve_model(model)
        effective_timeout = timeout or MODELS.CLASSIFIER_TIMEOUT
        start_time = time.time()
        request_id = request_id_var.get()
        success = False
        error_msg = None
        content = ""

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

            if response.status_code == 404:
                error_msg = f"Model not found: {resolved_model}"
                raise OllamaModelError(error_msg)

            if response.status_code != 200:
                error_text = response.text[:500]
                error_msg = f"Ollama returned status {response.status_code}: {error_text}"
                raise OllamaModelError(error_msg)

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON response from Ollama: {e}"
                raise OllamaResponseError(error_msg) from e

            content = data.get("message", {}).get("content", "")

            if not content:
                error_msg = "Empty response from Ollama"
                raise OllamaResponseError(error_msg)

            # Parse the JSON content, stripping markdown code blocks if present
            cleaned_content = self._strip_markdown_json(content)
            try:
                result = json.loads(cleaned_content)
                success = True
                return result
            except json.JSONDecodeError as e:
                error_msg = f"Model output is not valid JSON: {e}"
                logger.warning(f"Failed to parse JSON from model output: {content[:200]}")
                raise OllamaResponseError(error_msg) from e

        except httpx.ConnectError as e:
            error_msg = f"Failed to connect to Ollama: {e}"
            logger.warning(f"Connection error to Ollama: {e}")
            raise OllamaConnectionError(error_msg) from e
        except httpx.TimeoutException as e:
            error_msg = f"Ollama request timed out: {e}"
            logger.warning(f"Timeout calling Ollama: {e}")
            raise OllamaTimeoutError(error_msg) from e
        except httpx.HTTPError as e:
            error_msg = f"HTTP error: {e}"
            logger.error(f"HTTP error calling Ollama: {e}")
            raise OllamaConnectionError(error_msg) from e
        finally:
            duration_ms = (time.time() - start_time) * 1000

            # Record metrics
            prom_metrics = _get_metrics()
            if prom_metrics and layer and purpose:
                prom_metrics["ollama_calls"].labels(
                    model=resolved_model,
                    layer=layer,
                    purpose=purpose,
                ).observe(duration_ms / 1000)

            # Log LLM call
            if request_id and layer:
                audit_logger.log_llm_call(
                    request_id=request_id,
                    layer=layer,
                    model=resolved_model,
                    purpose=purpose or "json_classification",
                    prompt_tokens_approx=_approx_tokens(system + user),
                    response_tokens_approx=_approx_tokens(content),
                    duration_ms=duration_ms,
                    success=success,
                    error=error_msg,
                )

    @staticmethod
    def _strip_markdown_json(content: str) -> str:
        """Strip markdown code blocks from JSON content."""
        content = content.strip()
        # Handle ```json ... ``` or ``` ... ```
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json or ```)
            if lines:
                lines = lines[1:]
            # Remove last line if it's just ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        return content.strip()

    async def chat_with_history(
        self,
        system: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        timeout: float | None = None,
        temperature: float = 0.7,
        layer: str | None = None,
        purpose: str | None = None,
    ) -> str:
        """
        Send a chat request with conversation history.

        Args:
            system: System prompt.
            messages: List of message dicts with 'role' and 'content'.
            model: Model to use.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature.
            layer: Which pipeline layer is calling (for metrics).
            purpose: Purpose of the call (for metrics).

        Returns:
            The generated text response.
        """
        resolved_model = self._resolve_model(model)
        effective_timeout = timeout or MODELS.GENERATOR_TIMEOUT
        start_time = time.time()
        request_id = request_id_var.get()
        success = False
        error_msg = None
        content = ""

        client = await self._get_client()

        all_messages = [{"role": "system", "content": system}] + messages

        # Calculate prompt size for logging
        prompt_text = system + "".join(m.get("content", "") for m in messages)

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

            if response.status_code == 404:
                error_msg = f"Model not found: {resolved_model}"
                raise OllamaModelError(error_msg)

            if response.status_code != 200:
                error_text = response.text[:500]
                error_msg = f"Ollama returned status {response.status_code}: {error_text}"
                raise OllamaModelError(error_msg)

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON response: {e}"
                raise OllamaResponseError(error_msg) from e

            content = data.get("message", {}).get("content", "")

            if not content:
                error_msg = "Empty response from Ollama"
                raise OllamaResponseError(error_msg)

            success = True
            return content

        except httpx.ConnectError as e:
            error_msg = f"Failed to connect to Ollama: {e}"
            raise OllamaConnectionError(error_msg) from e
        except httpx.TimeoutException as e:
            error_msg = f"Ollama request timed out: {e}"
            raise OllamaTimeoutError(error_msg) from e
        except httpx.HTTPError as e:
            error_msg = f"HTTP error: {e}"
            raise OllamaConnectionError(error_msg) from e
        finally:
            duration_ms = (time.time() - start_time) * 1000

            # Record metrics
            prom_metrics = _get_metrics()
            if prom_metrics and layer and purpose:
                prom_metrics["ollama_calls"].labels(
                    model=resolved_model,
                    layer=layer,
                    purpose=purpose,
                ).observe(duration_ms / 1000)

            # Log LLM call
            if request_id and layer:
                audit_logger.log_llm_call(
                    request_id=request_id,
                    layer=layer,
                    model=resolved_model,
                    purpose=purpose or "chat_with_history",
                    prompt_tokens_approx=_approx_tokens(prompt_text),
                    response_tokens_approx=_approx_tokens(content),
                    duration_ms=duration_ms,
                    success=success,
                    error=error_msg,
                )

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((OllamaConnectionError, OllamaTimeoutError)),
        reraise=True,
    )
    async def embed(
        self,
        text: str,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> list[float]:
        """
        Generate embeddings for text.

        Args:
            text: Text to embed.
            model: Embedding model to use (defaults to nomic-embed-text).
            timeout: Request timeout in seconds.

        Returns:
            List of floats representing the embedding vector.

        Raises:
            OllamaConnectionError: Network connectivity issues.
            OllamaTimeoutError: Request timeout.
            OllamaModelError: Model loading/execution error.
            OllamaResponseError: Invalid response format.
        """
        # Default to a good embedding model
        embed_model = model or "nomic-embed-text"
        client = await self._get_client()

        payload = {
            "model": embed_model,
            "prompt": text,
        }

        try:
            response = await client.post(
                f"{self.url}/api/embeddings",
                json=payload,
                timeout=timeout,
            )

            if response.status_code == 404:
                raise OllamaModelError(f"Embedding model not found: {embed_model}")

            if response.status_code != 200:
                error_text = response.text[:500]
                raise OllamaModelError(
                    f"Ollama returned status {response.status_code}: {error_text}"
                )

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                raise OllamaResponseError(f"Invalid JSON response: {e}") from e

            embedding = data.get("embedding", [])
            if not embedding:
                raise OllamaResponseError("Empty embedding from Ollama")

            return embedding

        except httpx.ConnectError as e:
            raise OllamaConnectionError(f"Failed to connect to Ollama: {e}") from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(f"Ollama embedding request timed out: {e}") from e
        except httpx.HTTPError as e:
            raise OllamaConnectionError(f"HTTP error: {e}") from e

    async def embed_batch(
        self,
        texts: list[str],
        model: str | None = None,
        timeout: float = 60.0,
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.
            model: Embedding model to use.
            timeout: Request timeout per embedding.

        Returns:
            List of embedding vectors.
        """
        embeddings = []
        for text in texts:
            embedding = await self.embed(text, model=model, timeout=timeout)
            embeddings.append(embedding)
        return embeddings
