"""
Semantic verification utility for hallucination detection.

Uses embeddings to verify that response content is semantically
similar to the provided context.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from portfolio_chat.models.ollama_client import AsyncOllamaClient, OllamaError

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of semantic verification."""

    verified: bool
    overall_similarity: float
    low_similarity_sentences: list[str]
    error: str | None = None


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Returns value between -1 and 1, where 1 means identical direction.
    """
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences.

    Simple sentence splitting - handles common cases.
    """
    # Replace common abbreviations to avoid false splits
    text = text.replace("Mr.", "Mr").replace("Mrs.", "Mrs").replace("Dr.", "Dr")
    text = text.replace("e.g.", "eg").replace("i.e.", "ie")

    sentences = []
    current = []

    for char in text:
        current.append(char)
        if char in ".!?":
            sentence = "".join(current).strip()
            if len(sentence) > 10:  # Skip very short fragments
                sentences.append(sentence)
            current = []

    # Add remaining text if any
    remaining = "".join(current).strip()
    if len(remaining) > 10:
        sentences.append(remaining)

    return sentences


class SemanticVerifier:
    """
    Verifies that response content is semantically grounded in context.

    Uses embeddings to compare response sentences against context.
    Flags sentences that have low semantic similarity to any part of the context.
    """

    # Similarity threshold - sentences below this are flagged
    SIMILARITY_THRESHOLD = 0.5

    # Minimum sentences with low similarity to fail verification
    MIN_LOW_SIMILARITY_TO_FAIL = 2

    def __init__(
        self,
        client: AsyncOllamaClient | None = None,
        embedding_model: str = "nomic-embed-text",
        similarity_threshold: float | None = None,
    ) -> None:
        """
        Initialize verifier.

        Args:
            client: Ollama client instance.
            embedding_model: Model to use for embeddings.
            similarity_threshold: Custom similarity threshold.
        """
        self.client = client or AsyncOllamaClient()
        self.embedding_model = embedding_model
        self.threshold = similarity_threshold or self.SIMILARITY_THRESHOLD

    async def verify(
        self,
        response: str,
        context: str,
    ) -> VerificationResult:
        """
        Verify that response content is grounded in context.

        Args:
            response: The generated response to verify.
            context: The context that was provided.

        Returns:
            VerificationResult with similarity analysis.
        """
        try:
            # Split response into sentences
            response_sentences = split_into_sentences(response)
            if not response_sentences:
                return VerificationResult(
                    verified=True,
                    overall_similarity=1.0,
                    low_similarity_sentences=[],
                )

            # Split context into chunks for comparison
            # Use larger chunks for context to capture more semantic meaning
            context_chunks = self._chunk_context(context)
            if not context_chunks:
                # No context - can't verify, pass through
                return VerificationResult(
                    verified=True,
                    overall_similarity=0.0,
                    low_similarity_sentences=[],
                    error="No context provided for verification",
                )

            # Get embeddings for context chunks
            context_embeddings = await self.client.embed_batch(
                context_chunks, model=self.embedding_model
            )

            # Check each response sentence
            low_similarity_sentences = []
            similarities = []

            for sentence in response_sentences:
                # Skip meta sentences (greetings, acknowledgments)
                if self._is_meta_sentence(sentence):
                    continue

                # Get embedding for sentence
                try:
                    sentence_embedding = await self.client.embed(
                        sentence, model=self.embedding_model
                    )
                except OllamaError:
                    # Skip sentences we can't embed
                    continue

                # Find max similarity to any context chunk
                max_similarity = 0.0
                for ctx_embedding in context_embeddings:
                    sim = cosine_similarity(sentence_embedding, ctx_embedding)
                    max_similarity = max(max_similarity, sim)

                similarities.append(max_similarity)

                if max_similarity < self.threshold:
                    low_similarity_sentences.append(sentence)
                    logger.debug(
                        f"Low similarity ({max_similarity:.2f}): {sentence[:100]}"
                    )

            # Calculate overall similarity
            overall = sum(similarities) / len(similarities) if similarities else 1.0

            # Determine if verification passes
            # Allow some low-similarity sentences (could be reasonable inferences)
            verified = len(low_similarity_sentences) < self.MIN_LOW_SIMILARITY_TO_FAIL

            if not verified:
                logger.warning(
                    f"Semantic verification failed: {len(low_similarity_sentences)} "
                    f"sentences with low similarity to context"
                )

            return VerificationResult(
                verified=verified,
                overall_similarity=overall,
                low_similarity_sentences=low_similarity_sentences,
            )

        except OllamaError as e:
            logger.warning(f"Embedding error during verification: {e}")
            # Fail open on embedding errors - don't block legitimate responses
            return VerificationResult(
                verified=True,
                overall_similarity=0.0,
                low_similarity_sentences=[],
                error=str(e),
            )

        except Exception as e:
            logger.error(f"Unexpected error in semantic verification: {e}")
            return VerificationResult(
                verified=True,
                overall_similarity=0.0,
                low_similarity_sentences=[],
                error=str(e),
            )

    def _chunk_context(self, context: str, chunk_size: int = 500) -> list[str]:
        """
        Split context into overlapping chunks for comparison.

        Args:
            context: The context text.
            chunk_size: Target size for each chunk.

        Returns:
            List of context chunks.
        """
        if len(context) <= chunk_size:
            return [context] if context.strip() else []

        chunks = []
        words = context.split()
        current_chunk: list[str] = []
        current_length = 0

        for word in words:
            current_chunk.append(word)
            current_length += len(word) + 1

            if current_length >= chunk_size:
                chunks.append(" ".join(current_chunk))
                # Overlap: keep last 1/4 of words
                overlap_start = len(current_chunk) * 3 // 4
                current_chunk = current_chunk[overlap_start:]
                current_length = sum(len(w) + 1 for w in current_chunk)

        # Add remaining
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    def _is_meta_sentence(self, sentence: str) -> bool:
        """
        Check if a sentence is meta-commentary rather than factual claim.

        Meta sentences (greetings, transitions) shouldn't be verified
        against context.
        """
        meta_patterns = [
            "i'd be happy to",
            "let me",
            "here's",
            "based on",
            "according to",
            "from the context",
            "the information shows",
            "i can help",
            "is there anything",
            "feel free to",
            "happy to help",
            "would you like",
        ]
        lower = sentence.lower()
        return any(pattern in lower for pattern in meta_patterns)
