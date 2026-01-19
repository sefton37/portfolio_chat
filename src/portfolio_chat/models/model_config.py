"""Model configuration and tier definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ModelTier(Enum):
    """Model tiers based on size and purpose."""

    CLASSIFIER = "classifier"  # 0.5B-1.5B, fast classification
    ROUTER = "router"  # 1B-3B, intent parsing and routing
    GENERATOR = "generator"  # 7B-8B, response generation


@dataclass(frozen=True)
class ModelSpec:
    """Specification for a model."""

    name: str
    tier: ModelTier
    default_timeout: float
    default_temperature: float


# Model specifications
MODEL_SPECS: dict[str, ModelSpec] = {
    "qwen2.5:0.5b": ModelSpec(
        name="qwen2.5:0.5b",
        tier=ModelTier.CLASSIFIER,
        default_timeout=10.0,
        default_temperature=0.0,
    ),
    "llama3.2:1b": ModelSpec(
        name="llama3.2:1b",
        tier=ModelTier.ROUTER,
        default_timeout=15.0,
        default_temperature=0.0,
    ),
    "qwen2.5:1.5b": ModelSpec(
        name="qwen2.5:1.5b",
        tier=ModelTier.ROUTER,
        default_timeout=15.0,
        default_temperature=0.0,
    ),
    "mistral:7b": ModelSpec(
        name="mistral:7b",
        tier=ModelTier.GENERATOR,
        default_timeout=60.0,
        default_temperature=0.7,
    ),
    "llama3.1:8b": ModelSpec(
        name="llama3.1:8b",
        tier=ModelTier.GENERATOR,
        default_timeout=60.0,
        default_temperature=0.7,
    ),
}


def get_model_spec(model_name: str) -> ModelSpec | None:
    """Get the specification for a model by name."""
    return MODEL_SPECS.get(model_name)
