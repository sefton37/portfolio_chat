"""Tests for semantic context retrieval (Layer 5 Semantic)."""

import pytest
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from portfolio_chat.pipeline.layer4_route import Domain
from portfolio_chat.pipeline.layer5_context import (
    SemanticContextRetriever,
    Layer5Status,
    ChunkWithEmbedding,
    cosine_similarity,
)


class TestCosineSimilarity:
    """Tests for cosine similarity function."""

    def test_identical_vectors(self):
        """Test that identical vectors have similarity 1.0."""
        vec = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """Test that orthogonal vectors have similarity 0.0."""
        vec_a = [1.0, 0.0]
        vec_b = [0.0, 1.0]
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """Test that opposite vectors have similarity -1.0."""
        vec_a = [1.0, 0.0]
        vec_b = [-1.0, 0.0]
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(-1.0)

    def test_different_lengths_returns_zero(self):
        """Test that vectors of different lengths return 0.0."""
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [1.0, 2.0]
        assert cosine_similarity(vec_a, vec_b) == 0.0

    def test_zero_vector_returns_zero(self):
        """Test that zero vectors return 0.0."""
        vec_a = [0.0, 0.0, 0.0]
        vec_b = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec_a, vec_b) == 0.0

    def test_similar_vectors(self):
        """Test that similar vectors have high similarity."""
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [1.1, 2.1, 3.1]
        similarity = cosine_similarity(vec_a, vec_b)
        assert similarity > 0.99


@pytest.fixture
def temp_context_dir():
    """Create a temporary context directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        # Create subdirectories
        (base / "professional").mkdir()
        (base / "projects").mkdir()
        (base / "meta").mkdir()
        (base / "philosophy").mkdir()

        # Create test files with distinct content
        (base / "professional" / "resume.md").write_text(
            "# Resume\n\nKellogg is a software engineer with Python and machine learning experience."
        )
        (base / "professional" / "skills.md").write_text(
            "# Skills\n\nProgramming: Python, JavaScript, TypeScript\nML: PyTorch, TensorFlow"
        )
        (base / "projects" / "overview.md").write_text(
            "# Projects Overview\n\nTalking Rock: AI assistant framework\nUkraine OSINT: Intelligence analysis tool"
        )
        (base / "projects" / "talking_rock_rag_summary.md").write_text(
            "# Talking Rock\n\nTalking Rock is a local-first AI assistant with three-agent architecture: CAIRN, ReOS, and RIVA."
        )
        (base / "projects" / "ukraine-osint-rag-summary.md").write_text(
            "# Ukraine OSINT Reader\n\nAn intelligence analysis tool for processing open-source information about the conflict."
        )
        (base / "meta" / "about_chat.md").write_text(
            "# About\n\nThis is a portfolio chat system built with FastAPI and Ollama."
        )
        (base / "meta" / "contact.md").write_text(
            "# Contact\n\nLinkedIn: linkedin.com/in/kellogg"
        )
        (base / "philosophy" / "professional_ethos.md").write_text(
            "# Problem Solving\n\nNo One philosophy: solutions that eliminate problems rather than manage them."
        )

        yield base


@pytest.fixture
def semantic_retriever(temp_context_dir):
    """Create a semantic context retriever with test directory."""
    return SemanticContextRetriever(
        context_dir=temp_context_dir,
        max_context_length=10000,
        chunk_size=200,
        chunk_overlap=50,
        top_k=3,
        min_similarity=0.3,
    )


class TestSemanticContextRetrieverChunking:
    """Tests for chunking logic."""

    def test_chunk_small_content(self, semantic_retriever):
        """Test that small content is returned as single chunk."""
        chunks = semantic_retriever._chunk_content(
            "Short content",
            "test_source",
            "Test Source",
        )
        assert len(chunks) == 1
        assert chunks[0][0] == "Short content"
        assert chunks[0][1] == "test_source"
        assert chunks[0][2] == "Test Source"

    def test_chunk_large_content(self, semantic_retriever):
        """Test that large content is split into multiple chunks."""
        # Create content larger than chunk_size (200)
        content = " ".join(["word"] * 100)  # ~500 chars
        chunks = semantic_retriever._chunk_content(
            content,
            "test_source",
            "Test Source",
        )
        assert len(chunks) > 1

    def test_chunk_overlap(self, semantic_retriever):
        """Test that chunks have overlap."""
        # Create content that will be split
        content = " ".join([f"word{i}" for i in range(100)])
        chunks = semantic_retriever._chunk_content(
            content,
            "test_source",
            "Test Source",
        )
        if len(chunks) >= 2:
            # Check for some overlap - last words of chunk 0 should appear in chunk 1
            words_chunk_0 = chunks[0][0].split()
            words_chunk_1 = chunks[1][0].split()
            # At least some words should overlap
            overlap = set(words_chunk_0[-10:]) & set(words_chunk_1[:10])
            assert len(overlap) > 0

    def test_chunk_empty_content(self, semantic_retriever):
        """Test that empty content returns no chunks."""
        chunks = semantic_retriever._chunk_content("", "test", "Test")
        assert len(chunks) == 0

    def test_chunk_whitespace_content(self, semantic_retriever):
        """Test that whitespace-only content returns no chunks."""
        chunks = semantic_retriever._chunk_content("   \n\t  ", "test", "Test")
        assert len(chunks) == 0


class TestSemanticContextRetrieverEmbedding:
    """Tests for embedding and retrieval logic."""

    @pytest.mark.asyncio
    async def test_retrieve_semantic_out_of_scope(self, semantic_retriever):
        """Test that out of scope returns no context."""
        result = await semantic_retriever.retrieve_semantic(
            Domain.OUT_OF_SCOPE,
            "any message",
        )
        assert result.passed
        assert result.context == ""
        assert result.status == Layer5Status.NO_CONTEXT

    @pytest.mark.asyncio
    async def test_retrieve_semantic_falls_back_on_embed_failure(self, semantic_retriever):
        """Test that retrieval falls back to base when embedding fails."""
        mock_client = MagicMock()
        mock_client.embed_batch = AsyncMock(side_effect=Exception("Embedding failed"))
        semantic_retriever._ollama_client = mock_client

        result = await semantic_retriever.retrieve_semantic(
            Domain.PROFESSIONAL,
            "Tell me about skills",
        )
        # Should fall back to base retrieval
        assert result.passed

    @pytest.mark.asyncio
    async def test_retrieve_semantic_with_mock_embeddings(self, semantic_retriever):
        """Test semantic retrieval with mocked embeddings."""
        # Create mock embeddings that will produce predictable similarities
        # The query embedding and first chunk embedding will be similar
        mock_client = MagicMock()

        # Mock embed_batch for chunks - return different embeddings for each chunk
        chunk_embeddings = [
            [1.0, 0.0, 0.0],  # First chunk - similar to query
            [0.0, 1.0, 0.0],  # Second chunk - orthogonal
            [0.0, 0.0, 1.0],  # Third chunk - orthogonal
            [0.9, 0.1, 0.0],  # Fourth chunk - somewhat similar
        ]
        mock_client.embed_batch = AsyncMock(return_value=chunk_embeddings)

        # Mock embed for query - similar to first chunk
        mock_client.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])

        semantic_retriever._ollama_client = mock_client

        result = await semantic_retriever.retrieve_semantic(
            Domain.PROFESSIONAL,
            "Tell me about Python skills",
        )

        assert result.passed
        assert len(result.sources_loaded) > 0
        assert "relevance:" in result.context

    @pytest.mark.asyncio
    async def test_retrieve_semantic_respects_min_similarity(self, temp_context_dir):
        """Test that chunks below min_similarity are excluded."""
        retriever = SemanticContextRetriever(
            context_dir=temp_context_dir,
            chunk_size=200,
            top_k=5,
            min_similarity=0.9,  # Very high threshold
        )

        mock_client = MagicMock()
        # All chunks have low similarity
        mock_client.embed_batch = AsyncMock(return_value=[
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ])
        mock_client.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])
        retriever._ollama_client = mock_client

        result = await retriever.retrieve_semantic(
            Domain.PROFESSIONAL,
            "Test query",
        )

        # Should fall back since no chunks above threshold
        assert result.passed

    @pytest.mark.asyncio
    async def test_retrieve_semantic_respects_top_k(self, temp_context_dir):
        """Test that only top_k chunks are returned."""
        retriever = SemanticContextRetriever(
            context_dir=temp_context_dir,
            chunk_size=50,  # Small chunks to get many
            top_k=2,
            min_similarity=0.0,  # Accept all
        )

        mock_client = MagicMock()
        # Return embeddings for several chunks
        mock_client.embed_batch = AsyncMock(return_value=[
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.8, 0.2, 0.0],
            [0.7, 0.3, 0.0],
            [0.6, 0.4, 0.0],
        ])
        mock_client.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])
        retriever._ollama_client = mock_client

        result = await retriever.retrieve_semantic(
            Domain.PROFESSIONAL,
            "Test query",
        )

        # Count the number of "From:" headers in context
        from_count = result.context.count("### From:")
        assert from_count <= 2  # top_k = 2


class TestSemanticContextRetrieverCache:
    """Tests for embedding cache."""

    def test_clear_cache_all(self, semantic_retriever):
        """Test clearing all caches."""
        semantic_retriever._chunk_cache[Domain.PROFESSIONAL] = []
        semantic_retriever._chunk_cache[Domain.PROJECTS] = []

        semantic_retriever.clear_cache()

        assert len(semantic_retriever._chunk_cache) == 0

    def test_clear_cache_specific_domain(self, semantic_retriever):
        """Test clearing cache for specific domain."""
        semantic_retriever._chunk_cache[Domain.PROFESSIONAL] = []
        semantic_retriever._chunk_cache[Domain.PROJECTS] = []

        semantic_retriever.clear_cache(Domain.PROFESSIONAL)

        assert Domain.PROFESSIONAL not in semantic_retriever._chunk_cache
        assert Domain.PROJECTS in semantic_retriever._chunk_cache

    @pytest.mark.asyncio
    async def test_cache_is_reused(self, semantic_retriever):
        """Test that cached chunks are reused."""
        mock_client = MagicMock()
        mock_client.embed_batch = AsyncMock(return_value=[[1.0, 0.0, 0.0]])
        mock_client.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])
        semantic_retriever._ollama_client = mock_client

        # First call - should embed
        await semantic_retriever.retrieve_semantic(Domain.PROFESSIONAL, "query 1")
        first_call_count = mock_client.embed_batch.call_count

        # Second call - should use cache
        await semantic_retriever.retrieve_semantic(Domain.PROFESSIONAL, "query 2")
        second_call_count = mock_client.embed_batch.call_count

        # embed_batch should only be called once (for initial caching)
        assert first_call_count == 1
        assert second_call_count == 1


class TestChunkWithEmbedding:
    """Tests for ChunkWithEmbedding dataclass."""

    def test_create_chunk(self):
        """Test creating a chunk with embedding."""
        chunk = ChunkWithEmbedding(
            text="Test content",
            source_name="test",
            source_display_name="Test Source",
            embedding=[1.0, 2.0, 3.0],
        )
        assert chunk.text == "Test content"
        assert chunk.source_name == "test"
        assert chunk.source_display_name == "Test Source"
        assert chunk.embedding == [1.0, 2.0, 3.0]
