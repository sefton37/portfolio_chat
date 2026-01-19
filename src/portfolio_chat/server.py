"""
FastAPI Server

Main entry point for the portfolio chat API.
Provides /chat, /health, and /metrics endpoints.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from portfolio_chat.config import SERVER
from portfolio_chat.pipeline.orchestrator import PipelineOrchestrator
from portfolio_chat.utils.logging import generate_request_id, request_id_var, setup_logging

logger = logging.getLogger(__name__)


# Prometheus metrics - use helper to avoid duplicate registration on reload
def _get_or_create_counter(name: str, description: str, labels: list[str]) -> Counter:
    """Get existing counter or create new one."""
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]  # type: ignore
    return Counter(name, description, labels)


def _get_or_create_histogram(
    name: str, description: str, labels: list[str] | None = None, buckets: list[float] | None = None
) -> Histogram:
    """Get existing histogram or create new one."""
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]  # type: ignore
    kwargs: dict[str, Any] = {}
    if labels:
        kwargs["labelnames"] = labels
    if buckets:
        kwargs["buckets"] = buckets
    return Histogram(name, description, **kwargs)


CHAT_REQUESTS = _get_or_create_counter(
    "chat_requests_total",
    "Total chat requests",
    ["status", "domain"],
)

CHAT_DURATION = _get_or_create_histogram(
    "chat_request_duration_seconds",
    "Chat request duration in seconds",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

LAYER_BLOCKED = _get_or_create_counter(
    "chat_layer_blocked_total",
    "Requests blocked by layer",
    ["layer", "reason"],
)

OLLAMA_CALLS = _get_or_create_histogram(
    "ollama_call_duration_seconds",
    "Ollama API call duration",
    labels=["model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)


# Request/Response models
class ChatRequest(BaseModel):
    """Chat request body."""

    message: str = Field(..., min_length=1, max_length=5000)
    conversation_id: str | None = Field(None, max_length=100)


class ChatResponseContent(BaseModel):
    """Successful response content."""

    content: str
    domain: str


class ChatErrorContent(BaseModel):
    """Error response content."""

    code: str
    message: str


class ChatResponseMetadata(BaseModel):
    """Response metadata."""

    request_id: str
    response_time_ms: float
    conversation_id: str


class ChatResponseModel(BaseModel):
    """Chat API response."""

    success: bool
    response: ChatResponseContent | None = None
    error: ChatErrorContent | None = None
    metadata: ChatResponseMetadata


# Global orchestrator instance
orchestrator: PipelineOrchestrator | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    global orchestrator

    # Startup
    setup_logging(level=SERVER.LOG_LEVEL)
    logger.info("Starting Portfolio Chat server...")

    orchestrator = PipelineOrchestrator()

    # Check Ollama connection
    health = await orchestrator.health_check()
    if health.get("ollama"):
        logger.info("Ollama connection verified")
    else:
        logger.warning(f"Ollama not available: {health.get('ollama_error', 'unknown')}")

    logger.info(f"Server ready on {SERVER.HOST}:{SERVER.PORT}")

    yield

    # Shutdown
    logger.info("Shutting down Portfolio Chat server...")
    if orchestrator:
        await orchestrator.close()


# Create FastAPI app
app = FastAPI(
    title="Portfolio Chat API",
    description="Zero-trust LLM inference pipeline for Kellogg Brengel's portfolio",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next: Any) -> Any:
    """Add request ID and timing to all requests."""
    request_id = generate_request_id()
    request_id_var.set(request_id)

    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{duration:.3f}s"

    return response


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies."""
    # Check for forwarded headers (Cloudflare, nginx, etc.)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP in the chain
        return forwarded.split(",")[0].strip()

    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        return cf_connecting_ip

    # Fall back to direct client
    return request.client.host if request.client else "unknown"


@app.post("/chat", response_model=ChatResponseModel)
async def chat(request: Request, body: ChatRequest) -> ChatResponseModel:
    """
    Main chat endpoint.

    Processes a message through the 9-layer inference pipeline.
    """
    global orchestrator

    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    start_time = time.time()
    client_ip = get_client_ip(request)
    content_type = request.headers.get("content-type")
    content_length = request.headers.get("content-length")

    try:
        content_length_int = int(content_length) if content_length else None
    except ValueError:
        content_length_int = None

    # Process through pipeline
    result = await orchestrator.process_message(
        message=body.message,
        conversation_id=body.conversation_id,
        client_ip=client_ip,
        content_type=content_type,
        content_length=content_length_int,
    )

    # Update metrics
    duration = time.time() - start_time
    CHAT_DURATION.observe(duration)

    status = "success" if result.success else "error"
    domain = result.domain or "none"
    CHAT_REQUESTS.labels(status=status, domain=domain).inc()

    # Convert to response model
    response_dict = result.to_dict()

    return ChatResponseModel(
        success=response_dict["success"],
        response=ChatResponseContent(**response_dict["response"])
        if response_dict.get("response")
        else None,
        error=ChatErrorContent(**response_dict["error"])
        if response_dict.get("error")
        else None,
        metadata=ChatResponseMetadata(**response_dict["metadata"])
        if response_dict.get("metadata")
        else ChatResponseMetadata(
            request_id=request_id_var.get(),
            response_time_ms=duration * 1000,
            conversation_id="",
        ),
    )


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """
    Health check endpoint.

    Returns status of all pipeline components.
    """
    global orchestrator

    if orchestrator is None:
        return {
            "status": "unhealthy",
            "reason": "Service not initialized",
        }

    health = await orchestrator.health_check()

    return {
        "status": "healthy" if health.get("healthy") else "unhealthy",
        "components": health,
    }


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format.
    """
    return PlainTextResponse(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with API info."""
    return {
        "name": "Portfolio Chat API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


def main() -> None:
    """Run the server using uvicorn."""
    import uvicorn

    uvicorn.run(
        "portfolio_chat.server:app",
        host=SERVER.HOST,
        port=SERVER.PORT,
        reload=SERVER.DEBUG,
        log_level=SERVER.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
