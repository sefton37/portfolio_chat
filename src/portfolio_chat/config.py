"""
Configuration module with frozen dataclasses and hard security minimums.

Pattern from talking_rock: Immutable config with semantic grouping
and environment variable overrides that enforce security floors.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


def _env_str(name: str, default: str) -> str:
    """Load string from environment variable."""
    return os.getenv(name, default)


def _env_int(name: str, default: int, min_val: int | None = None) -> int:
    """
    Load int from env with optional hard minimum for security-critical settings.

    The min_val parameter enforces a floor that cannot be bypassed via environment
    variables, protecting against misconfiguration attacks.
    """
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default

    if min_val is not None:
        return max(value, min_val)
    return value


def _env_float(name: str, default: float, min_val: float | None = None) -> float:
    """Load float from env with optional hard minimum."""
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default

    if min_val is not None:
        return max(value, min_val)
    return value


@dataclass(frozen=True)
class SecurityLimits:
    """Security-critical limits with hard minimums that cannot be bypassed."""

    # Input constraints
    MAX_INPUT_LENGTH: int = _env_int("MAX_INPUT_LENGTH", 2000, min_val=100)
    MAX_REQUEST_SIZE: int = _env_int("MAX_REQUEST_SIZE", 8192, min_val=1024)

    # Timeout constraints
    REQUEST_TIMEOUT: int = _env_int("REQUEST_TIMEOUT", 30, min_val=5)

    # Context constraints - increased for systems with more resources
    MAX_CONTEXT_LENGTH: int = _env_int("MAX_CONTEXT_LENGTH", 32000, min_val=1000)


@dataclass(frozen=True)
class RateLimits:
    """Rate limiting configuration with sensible defaults."""

    PER_IP_PER_MINUTE: int = _env_int("RATE_LIMIT_PER_IP_PER_MINUTE", 10, min_val=1)
    PER_IP_PER_HOUR: int = _env_int("RATE_LIMIT_PER_IP_PER_HOUR", 100, min_val=10)
    GLOBAL_PER_MINUTE: int = _env_int("RATE_LIMIT_GLOBAL_PER_MINUTE", 1000, min_val=100)


@dataclass(frozen=True)
class ModelConfig:
    """Model selection configuration."""

    # Tier 1: Fast classifiers (0.5B-1.5B)
    CLASSIFIER_MODEL: str = _env_str("CLASSIFIER_MODEL", "qwen2.5:0.5b")
    ROUTER_MODEL: str = _env_str("ROUTER_MODEL", "llama3.2:1b")

    # Tier 2: Generation model (7B-8B)
    GENERATOR_MODEL: str = _env_str("GENERATOR_MODEL", "mistral:7b")

    # Tier 3: Verifier model for L7/L8 (should be different from generator to avoid self-reinforcing bias)
    # Defaults to classifier model (smaller, different perspective)
    VERIFIER_MODEL: str = _env_str("VERIFIER_MODEL", _env_str("CLASSIFIER_MODEL", "qwen2.5:0.5b"))

    # Embedding model for semantic verification
    EMBEDDING_MODEL: str = _env_str("EMBEDDING_MODEL", "nomic-embed-text")

    # Ollama settings
    OLLAMA_URL: str = _env_str("OLLAMA_URL", "http://localhost:11434")

    # Timeouts per model tier (seconds)
    CLASSIFIER_TIMEOUT: float = _env_float("CLASSIFIER_TIMEOUT", 10.0, min_val=5.0)
    GENERATOR_TIMEOUT: float = _env_float("GENERATOR_TIMEOUT", 60.0, min_val=10.0)


@dataclass(frozen=True)
class ConversationLimits:
    """Conversation management limits."""

    MAX_TURNS: int = _env_int("CONVERSATION_MAX_TURNS", 10, min_val=2)
    TTL_SECONDS: int = _env_int("CONVERSATION_TTL_SECONDS", 1800, min_val=60)  # 30 minutes
    MAX_HISTORY_TOKENS: int = _env_int("MAX_HISTORY_TOKENS", 4000, min_val=500)


@dataclass(frozen=True)
class PipelineConfig:
    """Pipeline optimization settings."""

    # Use combined L2+L3 classifier (single LLM call instead of two)
    USE_COMBINED_CLASSIFIER: bool = _env_str("USE_COMBINED_CLASSIFIER", "true").lower() == "true"

    # Skip L7 revision layer (saves ~3-4s latency)
    SKIP_REVISION: bool = _env_str("SKIP_REVISION", "true").lower() == "true"

    # Use pattern matching for L8 instead of LLM (saves ~2-3s latency)
    USE_FAST_SAFETY_CHECK: bool = _env_str("USE_FAST_SAFETY_CHECK", "true").lower() == "true"

    # Enable streaming responses (progressive output)
    ENABLE_STREAMING: bool = _env_str("ENABLE_STREAMING", "true").lower() == "true"


@dataclass(frozen=True)
class ServerConfig:
    """Server configuration."""

    HOST: str = _env_str("HOST", "127.0.0.1")  # Default to localhost for safety
    PORT: int = _env_int("PORT", 8000)
    LOG_LEVEL: str = _env_str("LOG_LEVEL", "INFO")
    DEBUG: bool = _env_str("DEBUG", "false").lower() == "true"

    # CORS configuration - comma-separated list of allowed origins
    # Default restricts to production domain; override for development
    CORS_ORIGINS: tuple[str, ...] = tuple(
        origin.strip()
        for origin in _env_str(
            "CORS_ORIGINS",
            "https://kellogg.brengel.com,https://www.kellogg.brengel.com"
        ).split(",")
        if origin.strip()
    )

    # Trusted proxy IPs that are allowed to set X-Forwarded-For headers
    # Empty means don't trust any proxy (use direct client IP)
    # Set to Cloudflare IPs or your reverse proxy IP(s)
    TRUSTED_PROXIES: frozenset[str] = frozenset(
        ip.strip()
        for ip in _env_str("TRUSTED_PROXIES", "").split(",")
        if ip.strip()
    )

    # Whether to require authentication for /metrics endpoint
    METRICS_ENABLED: bool = _env_str("METRICS_ENABLED", "false").lower() == "true"


@dataclass(frozen=True)
class PathConfig:
    """Path configuration for context and prompts."""

    BASE_DIR: Path = Path(__file__).parent.parent.parent
    CONTEXT_DIR: Path = BASE_DIR / "context"
    PROMPTS_DIR: Path = BASE_DIR / "prompts"


@dataclass(frozen=True)
class AnalyticsConfig:
    """Analytics and admin dashboard configuration."""

    # Enable conversation logging
    ENABLED: bool = _env_str("ANALYTICS_ENABLED", "true").lower() == "true"

    # Admin dashboard enabled (requires localhost access)
    ADMIN_ENABLED: bool = _env_str("ADMIN_ENABLED", "true").lower() == "true"


# Module-level singletons (immutable)
SECURITY = SecurityLimits()
RATE_LIMITS = RateLimits()
MODELS = ModelConfig()
CONVERSATION = ConversationLimits()
PIPELINE = PipelineConfig()
SERVER = ServerConfig()
PATHS = PathConfig()
ANALYTICS = AnalyticsConfig()


@lru_cache(maxsize=1)
def get_all_config() -> dict[str, object]:
    """Return all configuration as a dictionary for debugging."""
    return {
        "security": SECURITY,
        "rate_limits": RATE_LIMITS,
        "models": MODELS,
        "conversation": CONVERSATION,
        "pipeline": PIPELINE,
        "server": SERVER,
        "paths": {
            "base_dir": str(PATHS.BASE_DIR),
            "context_dir": str(PATHS.CONTEXT_DIR),
            "prompts_dir": str(PATHS.PROMPTS_DIR),
        },
        "analytics": ANALYTICS,
    }
