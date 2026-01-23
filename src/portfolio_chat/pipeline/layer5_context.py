"""
Layer 5: Context Retrieval

Retrieves relevant context based on domain routing.
Uses registry pattern with static file lookup (no RAG).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from portfolio_chat.config import MODELS, PATHS, PIPELINE, SECURITY
from portfolio_chat.pipeline.layer3_intent import Intent
from portfolio_chat.pipeline.layer4_route import Domain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextSource:
    """Definition of a context source."""

    name: str  # Internal identifier
    display_name: str  # UI label
    file_pattern: str  # Relative path or glob pattern
    domain: Domain  # Which domain this belongs to
    required: bool = False  # Always include for this domain?
    priority: int = 0  # Higher priority loaded first


# Registry of all context sources
CONTEXT_SOURCES: tuple[ContextSource, ...] = (
    # Professional domain
    ContextSource(
        name="skills",
        display_name="Skills",
        file_pattern="professional/skills.md",
        domain=Domain.PROFESSIONAL,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="resume",
        display_name="Resume",
        file_pattern="professional/resume.md",
        domain=Domain.PROFESSIONAL,
        required=True,
        priority=8,
    ),
    ContextSource(
        name="achievements",
        display_name="Achievements",
        file_pattern="professional/achievements.md",
        domain=Domain.PROFESSIONAL,
        required=False,
        priority=3,
    ),
    # Projects domain
    ContextSource(
        name="projects_overview",
        display_name="Projects Overview",
        file_pattern="projects/overview.md",
        domain=Domain.PROJECTS,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="portfolio_site",
        display_name="Portfolio Site",
        file_pattern="projects/portfolio_rag_summary.md",
        domain=Domain.PROJECTS,
        required=False,
        priority=5,
    ),
    ContextSource(
        name="talking_rock",
        display_name="Talking Rock",
        file_pattern="projects/talking_rock_rag_summary.md",
        domain=Domain.PROJECTS,
        required=False,
        priority=5,
    ),
    ContextSource(
        name="ukraine_osint",
        display_name="Ukraine OSINT Reader",
        file_pattern="projects/ukraine-osint-rag-summary.md",
        domain=Domain.PROJECTS,
        required=False,
        priority=4,
    ),
    ContextSource(
        name="inflation_dashboard",
        display_name="Inflation Dashboard",
        file_pattern="projects/inflation-dashboard-rag-summary.md",
        domain=Domain.PROJECTS,
        required=False,
        priority=4,
    ),
    ContextSource(
        name="great_minds",
        display_name="Great Minds Roundtable",
        file_pattern="projects/great-minds-summary.md",
        domain=Domain.PROJECTS,
        required=False,
        priority=4,
    ),
    # Hobbies domain
    ContextSource(
        name="first_robotics",
        display_name="FIRST Robotics",
        file_pattern="hobbies/first_robotics.md",
        domain=Domain.HOBBIES,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="hobbies",
        display_name="Hobbies & Interests",
        file_pattern="hobbies/hobbies.md",
        domain=Domain.HOBBIES,
        required=False,
        priority=5,
    ),
    # Philosophy domain
    ContextSource(
        name="problem_solving",
        display_name="Problem Solving Ethos",
        file_pattern="philosophy/professional_ethos.md",
        domain=Domain.PHILOSOPHY,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="values",
        display_name="Professional Philosophy",
        file_pattern="philosophy/professional_philosophy.md",
        domain=Domain.PHILOSOPHY,
        required=False,
        priority=5,
    ),
    # LinkedIn domain
    ContextSource(
        name="contact",
        display_name="Contact Info",
        file_pattern="meta/contact.md",
        domain=Domain.LINKEDIN,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="resume_linkedin",
        display_name="Resume",
        file_pattern="professional/resume.md",
        domain=Domain.LINKEDIN,
        required=False,
        priority=5,
    ),
    # Meta domain
    ContextSource(
        name="about_chat",
        display_name="About Chat",
        file_pattern="meta/about_chat.md",
        domain=Domain.META,
        required=True,
        priority=10,
    ),
    ContextSource(
        name="portfolio_overview",
        display_name="Portfolio Overview",
        file_pattern="meta/portfolio_rag_summary.md",
        domain=Domain.META,
        required=False,
        priority=5,
    ),
)

# Set of valid source names for validation
VALID_SOURCE_NAMES = frozenset(s.name for s in CONTEXT_SOURCES)


class Layer5Status:
    """Status codes for Layer 5 context retrieval."""

    SUCCESS = "success"
    PARTIAL = "partial"  # Some files missing
    NO_CONTEXT = "no_context"
    INSUFFICIENT = "insufficient"  # Context exists but is placeholder/sparse
    ERROR = "error"


# Minimum useful context threshold (chars) - below this, content is likely placeholder
MIN_USEFUL_CONTEXT_LENGTH = 200

# Patterns that indicate placeholder content (should not be used for generation)
PLACEHOLDER_PATTERNS = [
    "placeholder",
    "todo:",
    "coming soon",
    "to be added",
    "[insert",
    "lorem ipsum",
    "example content",
]


@dataclass
class Layer5Result:
    """Result of Layer 5 context retrieval."""

    status: str
    passed: bool
    context: str
    sources_loaded: list[str]
    sources_missing: list[str]
    total_length: int
    is_placeholder: bool = False  # True if content appears to be placeholder
    context_quality: float = 1.0  # 0.0-1.0 score of context usefulness


class Layer5ContextRetriever:
    """
    Context retriever using registry pattern.

    Loads relevant context files based on domain routing.
    No RAG - uses static, pre-curated content only.
    """

    def __init__(
        self,
        context_dir: Path | None = None,
        max_context_length: int | None = None,
    ) -> None:
        """
        Initialize context retriever.

        Args:
            context_dir: Directory containing context files.
            max_context_length: Maximum total context length.
        """
        self.context_dir = context_dir or PATHS.CONTEXT_DIR
        self.max_context_length = max_context_length or SECURITY.MAX_CONTEXT_LENGTH

        # Build domain to sources mapping
        self._domain_sources: dict[Domain, list[ContextSource]] = {}
        for source in CONTEXT_SOURCES:
            if source.domain not in self._domain_sources:
                self._domain_sources[source.domain] = []
            self._domain_sources[source.domain].append(source)

        # Sort by priority (higher first)
        for domain in self._domain_sources:
            self._domain_sources[domain].sort(key=lambda s: -s.priority)

    def _get_sources_for_domain(self, domain: Domain) -> Iterator[ContextSource]:
        """Get context sources for a domain, required first."""
        sources = self._domain_sources.get(domain, [])

        # Yield required sources first
        for source in sources:
            if source.required:
                yield source

        # Then optional sources
        for source in sources:
            if not source.required:
                yield source

    def _load_file(self, source: ContextSource) -> str | None:
        """Load a single context file."""
        file_path = self.context_dir / source.file_pattern

        if not file_path.exists():
            logger.debug(f"Context file not found: {file_path}")
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
            return content.strip()
        except Exception as e:
            logger.error(f"Error reading context file {file_path}: {e}")
            return None

    def _is_placeholder_content(self, content: str) -> bool:
        """Check if content appears to be placeholder/stub content."""
        content_lower = content.lower()
        for pattern in PLACEHOLDER_PATTERNS:
            if pattern in content_lower:
                return True
        return False

    def _calculate_context_quality(
        self,
        context: str,
        sources_loaded: int,
        sources_missing: int,
        has_placeholder: bool,
    ) -> float:
        """
        Calculate a quality score for the retrieved context.

        Returns a score from 0.0 to 1.0:
        - 1.0: Full, substantial context with no issues
        - 0.5-0.9: Partial context or some missing sources
        - 0.1-0.4: Sparse or mostly placeholder
        - 0.0: No usable context
        """
        if not context or len(context) < MIN_USEFUL_CONTEXT_LENGTH:
            return 0.0

        if has_placeholder:
            return 0.2  # Placeholder content is low quality

        # Base score from content length (logarithmic scale)
        import math
        length_score = min(1.0, math.log10(len(context) + 1) / 4)  # ~1.0 at 10k chars

        # Penalty for missing sources
        total_sources = sources_loaded + sources_missing
        if total_sources > 0:
            completeness = sources_loaded / total_sources
        else:
            completeness = 0.0

        # Combined score
        return round(length_score * 0.6 + completeness * 0.4, 2)

    def retrieve(
        self,
        domain: Domain,
        _intent: Intent | None = None,
    ) -> Layer5Result:
        """
        Retrieve context for a domain.

        Args:
            domain: The target domain.
            intent: Optional intent for more specific retrieval.

        Returns:
            Layer5Result with concatenated context.
        """
        # Handle out of scope
        if domain == Domain.OUT_OF_SCOPE:
            return Layer5Result(
                status=Layer5Status.NO_CONTEXT,
                passed=True,
                context="",
                sources_loaded=[],
                sources_missing=[],
                total_length=0,
            )

        # Collect context from sources
        context_parts: list[str] = []
        sources_loaded: list[str] = []
        sources_missing: list[str] = []
        total_length = 0

        for source in self._get_sources_for_domain(domain):
            # Check if we have room for more context
            if total_length >= self.max_context_length:
                break

            content = self._load_file(source)

            if content is None:
                sources_missing.append(source.name)
                continue

            # Check if adding this would exceed limit
            remaining = self.max_context_length - total_length
            if len(content) > remaining:
                # Truncate if necessary
                content = content[:remaining] + "\n[Content truncated]"

            # Add section header for clarity
            context_parts.append(f"## {source.display_name}\n\n{content}")
            sources_loaded.append(source.name)
            total_length += len(content)

        # Build final context
        context = "\n\n---\n\n".join(context_parts)

        # Check for placeholder content
        has_placeholder = self._is_placeholder_content(context)

        # Calculate context quality
        context_quality = self._calculate_context_quality(
            context=context,
            sources_loaded=len(sources_loaded),
            sources_missing=len(sources_missing),
            has_placeholder=has_placeholder,
        )

        # Determine status
        if not sources_loaded:
            status = Layer5Status.NO_CONTEXT
        elif has_placeholder or len(context) < MIN_USEFUL_CONTEXT_LENGTH:
            status = Layer5Status.INSUFFICIENT
        elif sources_missing:
            status = Layer5Status.PARTIAL
        else:
            status = Layer5Status.SUCCESS

        return Layer5Result(
            status=status,
            passed=True,  # Always passes - handling done by orchestrator
            context=context,
            sources_loaded=sources_loaded,
            sources_missing=sources_missing,
            total_length=len(context),
            is_placeholder=has_placeholder,
            context_quality=context_quality,
        )

    def get_available_sources(self) -> dict[str, list[str]]:
        """Get available sources grouped by domain."""
        result: dict[str, list[str]] = {}
        for domain, sources in self._domain_sources.items():
            result[domain.value] = [s.name for s in sources]
        return result


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Returns value between -1 and 1, where 1 means identical direction.
    """
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


@dataclass
class ChunkWithEmbedding:
    """A chunk of context with its embedding and metadata."""

    text: str
    source_name: str
    source_display_name: str
    embedding: list[float]


class SemanticContextRetriever(Layer5ContextRetriever):
    """
    Context retriever with semantic ranking.

    Extends Layer5ContextRetriever to add semantic search via embeddings.
    Chunks context files and ranks them by similarity to the user query.

    Optimizations:
    - Disk persistence: Embeddings cached to JSON files
    - File change detection: Re-embeds only when source files change
    - Pre-warming: Can embed all domains at startup
    """

    CACHE_VERSION = "v1"  # Bump to invalidate all caches

    def __init__(
        self,
        context_dir: Path | None = None,
        max_context_length: int | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        top_k: int | None = None,
        min_similarity: float | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        """
        Initialize semantic context retriever.

        Args:
            context_dir: Directory containing context files.
            max_context_length: Maximum total context length.
            chunk_size: Target size for each chunk (chars).
            chunk_overlap: Overlap between chunks (chars).
            top_k: Number of top chunks to return.
            min_similarity: Minimum similarity threshold.
            cache_dir: Directory for embedding cache files.
        """
        super().__init__(context_dir, max_context_length)
        self.chunk_size = chunk_size or PIPELINE.SEMANTIC_CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or PIPELINE.SEMANTIC_CHUNK_OVERLAP
        self.top_k = top_k or PIPELINE.SEMANTIC_TOP_K_CHUNKS
        self.min_similarity = min_similarity or PIPELINE.SEMANTIC_MIN_SIMILARITY
        self.cache_dir = cache_dir or PATHS.CACHE_DIR

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache: domain -> list of ChunkWithEmbedding
        self._chunk_cache: dict[Domain, list[ChunkWithEmbedding]] = {}
        self._ollama_client: object | None = None  # Lazy-loaded

    def _get_ollama_client(self) -> object:
        """Get or create the Ollama client (lazy loading to avoid circular imports)."""
        if self._ollama_client is None:
            from portfolio_chat.models.ollama_client import AsyncOllamaClient
            self._ollama_client = AsyncOllamaClient()
        return self._ollama_client

    def _get_cache_path(self, domain: Domain) -> Path:
        """Get the cache file path for a domain."""
        return self.cache_dir / f"embeddings_{domain.value}_{self.CACHE_VERSION}.json"

    def _compute_sources_hash(self, domain: Domain) -> str:
        """
        Compute a hash of all source files for a domain.

        Used to detect when source files have changed and cache needs refresh.
        """
        hasher = hashlib.md5()
        for source in sorted(self._get_sources_for_domain(domain), key=lambda s: s.name):
            file_path = self.context_dir / source.file_pattern
            if file_path.exists():
                # Include file path, size, and mtime in hash
                stat = file_path.stat()
                hasher.update(f"{source.file_pattern}:{stat.st_size}:{stat.st_mtime}".encode())
        return hasher.hexdigest()

    def _load_cache_from_disk(self, domain: Domain) -> list[ChunkWithEmbedding] | None:
        """
        Load cached embeddings from disk if valid.

        Returns None if cache doesn't exist or is stale.
        """
        cache_path = self._get_cache_path(domain)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path) as f:
                data = json.load(f)

            # Verify cache is still valid
            if data.get("sources_hash") != self._compute_sources_hash(domain):
                logger.info(f"Cache stale for {domain.value}, source files changed")
                return None

            # Reconstruct ChunkWithEmbedding objects
            chunks = [
                ChunkWithEmbedding(
                    text=c["text"],
                    source_name=c["source_name"],
                    source_display_name=c["source_display_name"],
                    embedding=c["embedding"],
                )
                for c in data.get("chunks", [])
            ]
            logger.info(f"Loaded {len(chunks)} cached embeddings for {domain.value}")
            return chunks

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to load cache for {domain.value}: {e}")
            return None

    def _save_cache_to_disk(self, domain: Domain, chunks: list[ChunkWithEmbedding]) -> None:
        """Save embeddings to disk cache."""
        cache_path = self._get_cache_path(domain)
        try:
            data = {
                "sources_hash": self._compute_sources_hash(domain),
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "chunks": [
                    {
                        "text": c.text,
                        "source_name": c.source_name,
                        "source_display_name": c.source_display_name,
                        "embedding": c.embedding,
                    }
                    for c in chunks
                ],
            }
            with open(cache_path, "w") as f:
                json.dump(data, f)
            logger.info(f"Saved {len(chunks)} embeddings to cache for {domain.value}")
        except OSError as e:
            logger.warning(f"Failed to save cache for {domain.value}: {e}")

    def _chunk_content(
        self,
        content: str,
        source_name: str,
        source_display_name: str,
    ) -> list[tuple[str, str, str]]:
        """
        Split content into overlapping chunks with source attribution.

        Args:
            content: The content to chunk.
            source_name: Internal source identifier.
            source_display_name: Human-readable source name.

        Returns:
            List of (chunk_text, source_name, display_name) tuples.
        """
        if len(content) <= self.chunk_size:
            return [(content.strip(), source_name, source_display_name)] if content.strip() else []

        chunks = []
        words = content.split()
        current_chunk: list[str] = []
        current_length = 0

        for word in words:
            current_chunk.append(word)
            current_length += len(word) + 1

            if current_length >= self.chunk_size:
                chunk_text = " ".join(current_chunk)
                chunks.append((chunk_text, source_name, source_display_name))

                # Overlap: keep words that roughly equal overlap size
                overlap_chars = 0
                overlap_words: list[str] = []
                for w in reversed(current_chunk):
                    overlap_chars += len(w) + 1
                    overlap_words.insert(0, w)
                    if overlap_chars >= self.chunk_overlap:
                        break

                current_chunk = overlap_words
                current_length = sum(len(w) + 1 for w in current_chunk)

        # Add remaining
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            if chunk_text.strip():
                chunks.append((chunk_text, source_name, source_display_name))

        return chunks

    async def _ensure_chunks_embedded(self, domain: Domain) -> list[ChunkWithEmbedding]:
        """
        Embed and cache all chunks for a domain (lazy loading).

        Checks in order:
        1. In-memory cache
        2. Disk cache (if valid)
        3. Compute fresh embeddings

        Args:
            domain: The domain to load chunks for.

        Returns:
            List of chunks with embeddings.
        """
        # Check in-memory cache first
        if domain in self._chunk_cache:
            return self._chunk_cache[domain]

        # Try loading from disk cache
        cached = self._load_cache_from_disk(domain)
        if cached is not None:
            self._chunk_cache[domain] = cached
            return cached

        # Need to compute embeddings
        client = self._get_ollama_client()
        all_chunks: list[tuple[str, str, str]] = []

        # Load and chunk all sources for this domain
        for source in self._get_sources_for_domain(domain):
            content = self._load_file(source)
            if content is None:
                continue

            chunks = self._chunk_content(content, source.name, source.display_name)
            all_chunks.extend(chunks)

        if not all_chunks:
            self._chunk_cache[domain] = []
            return []

        # Embed all chunks
        logger.info(f"Computing embeddings for {len(all_chunks)} chunks in {domain.value}")
        texts = [c[0] for c in all_chunks]

        try:
            embeddings = await client.embed_batch(texts, model=MODELS.EMBEDDING_MODEL)
        except Exception as e:
            logger.error(f"Failed to embed chunks for {domain.value}: {e}")
            self._chunk_cache[domain] = []
            return []

        # Create chunk objects with embeddings
        embedded_chunks = [
            ChunkWithEmbedding(
                text=chunk[0],
                source_name=chunk[1],
                source_display_name=chunk[2],
                embedding=embedding,
            )
            for chunk, embedding in zip(all_chunks, embeddings)
        ]

        # Save to both caches
        self._chunk_cache[domain] = embedded_chunks
        self._save_cache_to_disk(domain, embedded_chunks)

        logger.info(f"Cached {len(embedded_chunks)} embeddings for {domain.value}")
        return embedded_chunks

    async def prewarm_all_domains(self) -> None:
        """
        Pre-warm embeddings for all domains.

        Call this at server startup to avoid cold-start latency on first query.
        Also warms up the embedding model with a dummy query.
        """
        for domain in Domain:
            if domain == Domain.OUT_OF_SCOPE:
                continue
            try:
                await self._ensure_chunks_embedded(domain)
            except Exception as e:
                logger.error(f"Failed to prewarm {domain.value}: {e}")

        # Warm up the embedding model with a dummy query
        # This keeps the model loaded in memory for faster first-query response
        try:
            client = self._get_ollama_client()
            await client.embed("warmup query", model=MODELS.EMBEDDING_MODEL)
            logger.debug("Embedding model warmed up")
        except Exception as e:
            logger.warning(f"Failed to warm up embedding model: {e}")

    async def retrieve_semantic(
        self,
        domain: Domain,
        message: str,
        intent: Intent | None = None,
    ) -> Layer5Result:
        """
        Retrieve context ranked by semantic similarity to message.

        Always includes required sources (overview files) first for grounding,
        then adds semantically relevant chunks for specific details.

        Args:
            domain: The target domain.
            message: The user's message to match against.
            intent: Optional intent (currently unused but kept for interface).

        Returns:
            Layer5Result with semantically ranked context.
        """
        # Handle out of scope
        if domain == Domain.OUT_OF_SCOPE:
            return Layer5Result(
                status=Layer5Status.NO_CONTEXT,
                passed=True,
                context="",
                sources_loaded=[],
                sources_missing=[],
                total_length=0,
            )

        # Get embedded chunks for domain
        chunks = await self._ensure_chunks_embedded(domain)

        if not chunks:
            # Fall back to base retrieval if embedding failed
            logger.warning(f"No chunks available for {domain.value}, falling back to base retrieval")
            return self.retrieve(domain, intent)

        # Embed the user message
        client = self._get_ollama_client()
        try:
            query_embedding = await client.embed(message, model=MODELS.EMBEDDING_MODEL)
        except Exception as e:
            logger.error(f"Failed to embed query: {e}")
            return self.retrieve(domain, intent)

        # Identify required sources for this domain (overview files that should always be included)
        required_source_names = {
            s.name for s in self._get_sources_for_domain(domain) if s.required
        }

        # Compute similarity for all chunks
        scored_chunks: list[tuple[ChunkWithEmbedding, float]] = []
        for chunk in chunks:
            similarity = cosine_similarity(query_embedding, chunk.embedding)
            if similarity >= self.min_similarity:
                scored_chunks.append((chunk, similarity))

        # Sort by similarity descending
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # Build context in two phases:
        # Phase 1: Include first chunks from required sources (overview/grounding)
        # Phase 2: Add top semantic matches (specific details)
        context_parts: list[str] = []
        sources_loaded: set[str] = set()
        included_chunk_texts: set[str] = set()  # Track to avoid duplicates
        total_length = 0

        # Phase 1: Required source chunks (first 2 chunks from each required source)
        REQUIRED_CHUNKS_PER_SOURCE = 2
        for source_name in required_source_names:
            source_chunks = [c for c in chunks if c.source_name == source_name]
            # Take first N chunks (they contain the intro/summary)
            for chunk in source_chunks[:REQUIRED_CHUNKS_PER_SOURCE]:
                if total_length >= self.max_context_length:
                    break

                chunk_content = f"### From: {chunk.source_display_name} (overview)\n{chunk.text}"
                remaining = self.max_context_length - total_length
                if len(chunk_content) > remaining:
                    chunk_content = chunk_content[:remaining] + "\n[Truncated]"

                context_parts.append(chunk_content)
                sources_loaded.add(chunk.source_name)
                included_chunk_texts.add(chunk.text)
                total_length += len(chunk_content)

        # Phase 2: Add top semantic matches (excluding already included chunks)
        semantic_added = 0
        for chunk, similarity in scored_chunks:
            if semantic_added >= self.top_k:
                break
            if total_length >= self.max_context_length:
                break
            if chunk.text in included_chunk_texts:
                continue  # Skip duplicates

            chunk_header = f"### From: {chunk.source_display_name} (relevance: {similarity:.2f})"
            chunk_content = f"{chunk_header}\n{chunk.text}"

            remaining = self.max_context_length - total_length
            if len(chunk_content) > remaining:
                chunk_content = chunk_content[:remaining] + "\n[Truncated]"

            context_parts.append(chunk_content)
            sources_loaded.add(chunk.source_name)
            included_chunk_texts.add(chunk.text)
            total_length += len(chunk_content)
            semantic_added += 1

        if not context_parts:
            # No context at all - use base retrieval
            logger.debug(f"No context built for query")
            return self.retrieve(domain, intent)

        # Build final context
        context = "## Context\n\n" + "\n\n".join(context_parts)

        # Determine missing sources (sources in domain but not in results)
        all_source_names = {s.name for s in self._get_sources_for_domain(domain)}
        sources_missing = list(all_source_names - sources_loaded)

        # Calculate context quality based on similarity scores
        if scored_chunks:
            avg_similarity = sum(sim for _, sim in scored_chunks[:self.top_k]) / min(len(scored_chunks), self.top_k)
            top_similarity = scored_chunks[0][1]
            # Quality is weighted average of top and average similarity
            context_quality = round(0.6 * top_similarity + 0.4 * avg_similarity, 2)
        else:
            context_quality = 0.8  # Default quality when we have required sources but no semantic matches

        # Check for placeholder content
        has_placeholder = self._is_placeholder_content(context)
        if has_placeholder:
            context_quality = min(context_quality, 0.2)

        # Determine status
        if not context_parts:
            status = Layer5Status.NO_CONTEXT
        elif has_placeholder or context_quality < 0.4:
            status = Layer5Status.INSUFFICIENT
        elif len(sources_loaded) < len(all_source_names) // 2:
            status = Layer5Status.PARTIAL
        else:
            status = Layer5Status.SUCCESS

        return Layer5Result(
            status=status,
            passed=True,
            context=context,
            sources_loaded=list(sources_loaded),
            sources_missing=sources_missing,
            total_length=len(context),
            is_placeholder=has_placeholder,
            context_quality=context_quality,
        )

    def clear_cache(self, domain: Domain | None = None) -> None:
        """
        Clear the embedding cache.

        Args:
            domain: If provided, only clear cache for this domain.
                   If None, clear all caches.
        """
        if domain is not None:
            self._chunk_cache.pop(domain, None)
        else:
            self._chunk_cache.clear()


# Module-level retriever instance
context_retriever = Layer5ContextRetriever()
