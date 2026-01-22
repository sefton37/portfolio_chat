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

from portfolio_chat.config import SECURITY, SERVER
from portfolio_chat.contact.storage import ContactStorage
from portfolio_chat.pipeline.orchestrator import PipelineOrchestrator
from portfolio_chat.utils.logging import generate_request_id, hash_ip, request_id_var, setup_logging

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
    labels=["model", "layer", "purpose"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

LAYER_DURATION = _get_or_create_histogram(
    "chat_layer_duration_seconds",
    "Duration of each pipeline layer",
    labels=["layer"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
)

INTENT_CONFIDENCE = _get_or_create_histogram(
    "chat_intent_confidence",
    "Intent parser confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

DOMAIN_REQUESTS = _get_or_create_counter(
    "chat_domain_requests_total",
    "Requests by domain",
    ["domain"],
)

CONVERSATION_TURNS = _get_or_create_histogram(
    "chat_conversation_turns",
    "Number of turns in conversations",
    buckets=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
)

RESPONSE_LENGTH = _get_or_create_histogram(
    "chat_response_length_chars",
    "Length of bot responses in characters",
    buckets=[50, 100, 200, 500, 1000, 2000, 5000],
)

# Export metrics for use by other modules
METRICS = {
    "ollama_calls": OLLAMA_CALLS,
    "layer_duration": LAYER_DURATION,
    "intent_confidence": INTENT_CONFIDENCE,
    "domain_requests": DOMAIN_REQUESTS,
    "conversation_turns": CONVERSATION_TURNS,
    "response_length": RESPONSE_LENGTH,
    "layer_blocked": LAYER_BLOCKED,
}


# Request/Response models
class ChatRequest(BaseModel):
    """Chat request body."""

    message: str = Field(..., min_length=1, max_length=SECURITY.MAX_INPUT_LENGTH)
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
    layer_timings_ms: dict[str, float] = {}


class ChatResponseModel(BaseModel):
    """Chat API response."""

    success: bool
    response: ChatResponseContent | None = None
    error: ChatErrorContent | None = None
    metadata: ChatResponseMetadata


# Contact endpoint models
class ContactRequest(BaseModel):
    """Contact form request body."""

    message: str = Field(..., min_length=1, max_length=SECURITY.MAX_INPUT_LENGTH)
    sender_name: str | None = Field(None, max_length=100)
    sender_email: str | None = Field(None, max_length=254)
    context: str | None = Field(None, max_length=SECURITY.MAX_INPUT_LENGTH)  # Conversation summary
    conversation_id: str | None = Field(None, max_length=100)


class ContactResponseModel(BaseModel):
    """Contact API response."""

    success: bool
    message_id: str | None = None
    error: str | None = None


# Global instances
orchestrator: PipelineOrchestrator | None = None
contact_storage: ContactStorage | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    global orchestrator, contact_storage

    # Startup
    setup_logging(level=SERVER.LOG_LEVEL)
    logger.info("Starting Portfolio Chat server...")

    orchestrator = PipelineOrchestrator()
    contact_storage = ContactStorage()

    # Check Ollama connection
    health = await orchestrator.health_check()
    if health.get("ollama"):
        logger.info("Ollama connection verified")
    else:
        logger.warning(f"Ollama not available: {health.get('ollama_error', 'unknown')}")

    logger.info(f"Contact storage: {contact_storage.storage_dir}")
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

# CORS middleware - origins configured via CORS_ORIGINS environment variable
# Production default: https://kellogg.brengel.com
# Development: set CORS_ORIGINS=http://localhost:3000,http://localhost:4321
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(SERVER.CORS_ORIGINS),
    allow_credentials=False,  # Not using cookies/sessions
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
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
    """
    Extract client IP from request with proxy validation.

    Only trusts X-Forwarded-For/CF-Connecting-IP headers if the immediate
    peer IP is in the TRUSTED_PROXIES list. This prevents IP spoofing
    attacks where attackers bypass rate limits by forging headers.
    """
    direct_ip = request.client.host if request.client else "unknown"

    # If no trusted proxies configured, always use direct IP
    if not SERVER.TRUSTED_PROXIES:
        return direct_ip

    # Only trust forwarded headers if request comes from a trusted proxy
    if direct_ip not in SERVER.TRUSTED_PROXIES:
        # Request not from trusted proxy - use direct IP to prevent spoofing
        return direct_ip

    # Request is from trusted proxy - safe to use forwarded headers
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        return cf_connecting_ip.strip()

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first (client) IP in the chain
        return forwarded.split(",")[0].strip()

    # Fall back to direct client if no forwarding headers present
    return direct_ip


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


@app.post("/contact", response_model=ContactResponseModel)
async def contact(request: Request, body: ContactRequest) -> ContactResponseModel:
    """
    Contact form endpoint.

    Stores a message from a visitor for later review.
    Can include optional sender info and conversation context.
    """
    global contact_storage

    if contact_storage is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    client_ip = get_client_ip(request)
    ip_hash = hash_ip(client_ip)

    # Basic email validation if provided
    if body.sender_email and "@" not in body.sender_email:
        return ContactResponseModel(
            success=False,
            error="Invalid email format",
        )

    try:
        stored = await contact_storage.store(
            message=body.message,
            sender_name=body.sender_name,
            sender_email=body.sender_email,
            context=body.context,
            ip_hash=ip_hash,
            conversation_id=body.conversation_id,
        )

        logger.info(f"Contact message stored: {stored.id}")

        return ContactResponseModel(
            success=True,
            message_id=stored.id,
        )

    except Exception as e:
        logger.error(f"Failed to store contact message: {e}")
        return ContactResponseModel(
            success=False,
            error="Failed to store message. Please try again.",
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
async def metrics(request: Request) -> PlainTextResponse:
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format.
    Only enabled if METRICS_ENABLED=true to prevent information disclosure.
    """
    if not SERVER.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")

    # Only allow metrics from trusted proxies or localhost
    client_ip = request.client.host if request.client else "unknown"
    allowed = (
        client_ip in ("127.0.0.1", "::1", "localhost")
        or client_ip in SERVER.TRUSTED_PROXIES
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

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
