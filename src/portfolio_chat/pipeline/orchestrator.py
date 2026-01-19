"""
Pipeline Orchestrator

Coordinates all 9 layers of the zero-trust inference pipeline.
Handles layer-by-layer execution with early exits and error handling.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from portfolio_chat.conversation.manager import ConversationManager, MessageRole
from portfolio_chat.models.ollama_client import AsyncOllamaClient
from portfolio_chat.pipeline.layer0_network import Layer0NetworkGateway, Layer0Status
from portfolio_chat.pipeline.layer1_sanitize import Layer1Sanitizer, Layer1Status
from portfolio_chat.pipeline.layer2_jailbreak import Layer2JailbreakDetector
from portfolio_chat.pipeline.layer3_intent import Layer3IntentParser
from portfolio_chat.pipeline.layer4_route import Domain, Layer4Router
from portfolio_chat.pipeline.layer5_context import Layer5ContextRetriever
from portfolio_chat.pipeline.layer6_generate import Layer6Generator
from portfolio_chat.pipeline.layer7_revise import Layer7Reviser
from portfolio_chat.pipeline.layer8_safety import Layer8SafetyChecker
from portfolio_chat.pipeline.layer9_deliver import ChatResponse, Layer9Deliverer
from portfolio_chat.utils.logging import audit_logger, generate_request_id, hash_ip, request_id_var
from portfolio_chat.utils.rate_limit import InMemoryRateLimiter

logger = logging.getLogger(__name__)


def _get_metrics() -> dict | None:
    """Lazy import metrics to avoid circular imports."""
    try:
        from portfolio_chat.server import METRICS
        return METRICS
    except ImportError:
        return None


@dataclass
class PipelineMetrics:
    """Metrics collected during pipeline execution."""

    layer_timings: dict[str, float] = field(default_factory=dict)
    blocked_at_layer: str | None = None
    domain_matched: str | None = None
    conversation_turn: int = 0


class PipelineOrchestrator:
    """
    Orchestrates the 9-layer inference pipeline.

    Executes layers in sequence with early exits for blocked requests.
    Handles errors gracefully with safe fallback responses.
    """

    def __init__(
        self,
        rate_limiter: InMemoryRateLimiter | None = None,
        conversation_manager: ConversationManager | None = None,
        ollama_client: AsyncOllamaClient | None = None,
    ) -> None:
        """
        Initialize orchestrator with all layer components.

        Args:
            rate_limiter: Shared rate limiter instance.
            conversation_manager: Shared conversation manager.
            ollama_client: Shared Ollama client.
        """
        # Shared components
        self.rate_limiter = rate_limiter or InMemoryRateLimiter()
        self.conversation_manager = conversation_manager or ConversationManager()
        self.ollama_client = ollama_client or AsyncOllamaClient()

        # Initialize all layers
        self.layer0 = Layer0NetworkGateway(rate_limiter=self.rate_limiter)
        self.layer1 = Layer1Sanitizer()
        self.layer2 = Layer2JailbreakDetector(client=self.ollama_client)
        self.layer3 = Layer3IntentParser(client=self.ollama_client)
        self.layer4 = Layer4Router()
        self.layer5 = Layer5ContextRetriever()
        self.layer6 = Layer6Generator(client=self.ollama_client)
        self.layer7 = Layer7Reviser(client=self.ollama_client)
        self.layer8 = Layer8SafetyChecker(client=self.ollama_client)
        self.layer9 = Layer9Deliverer()

    async def process_message(
        self,
        message: str,
        conversation_id: str | None,
        client_ip: str,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> ChatResponse:
        """
        Process a message through all pipeline layers.

        Args:
            message: The user's message.
            conversation_id: Optional conversation ID for multi-turn.
            client_ip: Client IP address.
            content_type: Request Content-Type header.
            content_length: Request Content-Length in bytes.

        Returns:
            ChatResponse with result or error.
        """
        start_time = time.time()
        request_id = generate_request_id()
        request_id_var.set(request_id)
        ip_hash = hash_ip(client_ip)
        metrics = PipelineMetrics()

        # Get or create conversation
        conversation, is_new = await self.conversation_manager.get_or_create(conversation_id)
        conv_id = conversation.id
        metrics.conversation_turn = conversation.turn_count

        logger.info(
            f"Processing request {request_id}: conv={conv_id}, turn={metrics.conversation_turn}"
        )

        try:
            # ===== LAYER 0: Network Gateway =====
            l0_start = time.time()
            l0_result = await self.layer0.validate_request(
                client_ip=client_ip,
                request_id=request_id,
                content_type=content_type,
                content_length=content_length,
                has_message=bool(message),
            )
            metrics.layer_timings["L0"] = time.time() - l0_start

            if l0_result.blocked:
                metrics.blocked_at_layer = "L0"
                error_type = {
                    Layer0Status.RATE_LIMITED: "rate_limited",
                    Layer0Status.REQUEST_TOO_LARGE: "input_too_long",
                    Layer0Status.INVALID_CONTENT_TYPE: "internal_error",
                    Layer0Status.MISSING_MESSAGE: "internal_error",
                }.get(l0_result.status, "internal_error")

                return self.layer9.deliver_error(
                    error_type=error_type,
                    request_id=request_id,
                    conversation_id=conv_id,
                    start_time=start_time,
                    ip_hash=ip_hash,
                    blocked_at_layer="L0",
                    custom_message=l0_result.error_message,
                )

            # ===== LAYER 1: Input Sanitization =====
            l1_start = time.time()
            l1_result = self.layer1.sanitize(message, ip_hash=ip_hash)
            metrics.layer_timings["L1"] = time.time() - l1_start

            if l1_result.blocked:
                metrics.blocked_at_layer = "L1"
                error_type = {
                    Layer1Status.INPUT_TOO_LONG: "input_too_long",
                    Layer1Status.BLOCKED_PATTERN: "blocked_input",
                    Layer1Status.EMPTY_INPUT: "internal_error",
                }.get(l1_result.status, "internal_error")

                return self.layer9.deliver_error(
                    error_type=error_type,
                    request_id=request_id,
                    conversation_id=conv_id,
                    start_time=start_time,
                    ip_hash=ip_hash,
                    blocked_at_layer="L1",
                    custom_message=l1_result.error_message,
                )

            sanitized_message = l1_result.sanitized_input or message

            # Log user message with full content
            audit_logger.log_user_message(
                request_id=request_id,
                conversation_id=conv_id,
                turn=metrics.conversation_turn,
                raw_message=message,
                sanitized_message=sanitized_message,
                ip_hash=ip_hash,
            )

            # ===== LAYER 2: Jailbreak Detection =====
            l2_start = time.time()
            conversation_history = conversation.get_history()
            l2_result = await self.layer2.detect(
                message=sanitized_message,
                conversation_history=conversation_history,
                ip_hash=ip_hash,
            )
            metrics.layer_timings["L2"] = time.time() - l2_start

            # Log L2 safety check result
            audit_logger.log_safety_check(
                request_id=request_id,
                layer="L2",
                passed=not l2_result.blocked,
                classification=l2_result.status.value if l2_result.status else "UNKNOWN",
                confidence=l2_result.confidence,
                reason=l2_result.reason.value if l2_result.reason else None,
            )

            if l2_result.blocked:
                metrics.blocked_at_layer = "L2"
                return self.layer9.deliver_error(
                    error_type="blocked_input",
                    request_id=request_id,
                    conversation_id=conv_id,
                    start_time=start_time,
                    ip_hash=ip_hash,
                    blocked_at_layer="L2",
                    custom_message=l2_result.error_message,
                )

            # ===== LAYER 3: Intent Parsing =====
            l3_start = time.time()
            l3_result = await self.layer3.parse(sanitized_message)
            metrics.layer_timings["L3"] = time.time() - l3_start

            # Ensure we have an intent (Layer 3 should always provide one)
            from portfolio_chat.pipeline.layer3_intent import Intent, QuestionType

            intent = l3_result.intent
            if intent is None:
                # Shouldn't happen, but handle gracefully
                logger.warning("Intent parsing returned no intent, using default")
                intent = Intent(
                    topic="general",
                    question_type=QuestionType.AMBIGUOUS,
                    confidence=0.0,
                )

            # Log intent parsing result
            audit_logger.log_intent_parsed(
                request_id=request_id,
                topic=intent.topic,
                question_type=intent.question_type.value,
                entities=intent.entities,
                emotional_tone=intent.emotional_tone.value if hasattr(intent.emotional_tone, 'value') else str(intent.emotional_tone),
                confidence=intent.confidence,
            )

            # ===== LAYER 4: Domain Routing =====
            l4_start = time.time()
            l4_result = self.layer4.route(
                intent=intent,
                original_message=sanitized_message,
            )
            metrics.layer_timings["L4"] = time.time() - l4_start
            metrics.domain_matched = l4_result.domain.value

            # Log domain routing result
            audit_logger.log_domain_routed(
                request_id=request_id,
                domain=l4_result.domain.value,
                confidence=l4_result.confidence,
                fallback_used=l4_result.domain == Domain.OUT_OF_SCOPE,
            )

            # ===== LAYER 5: Context Retrieval =====
            l5_start = time.time()
            l5_result = self.layer5.retrieve(
                domain=l4_result.domain,
                _intent=intent,
            )
            metrics.layer_timings["L5"] = time.time() - l5_start

            # Log context retrieval result
            audit_logger.log_context_retrieved(
                request_id=request_id,
                domain=l4_result.domain.value,
                sources_used=l5_result.sources_loaded,
                context_length=len(l5_result.context) if l5_result.context else 0,
            )

            # ===== LAYER 6: Response Generation =====
            l6_start = time.time()
            l6_result = await self.layer6.generate(
                message=sanitized_message,
                domain=l4_result.domain,
                context=l5_result.context,
                conversation_history=conversation_history,
            )
            metrics.layer_timings["L6"] = time.time() - l6_start

            if not l6_result.passed or not l6_result.response:
                # Generation failed - use fallback
                logger.warning(f"Generation failed: {l6_result.error_message}")
                fallback = await self.layer6.generate_fallback_response(l4_result.domain)
                l6_result.response = fallback

            # ===== LAYER 7: Response Revision =====
            l7_start = time.time()
            l7_result = await self.layer7.revise(
                response=l6_result.response,
                context=l5_result.context,
                original_question=sanitized_message,
            )
            metrics.layer_timings["L7"] = time.time() - l7_start

            final_response = l7_result.response

            # ===== LAYER 8: Output Safety Check =====
            l8_start = time.time()
            l8_result = await self.layer8.check(
                response=final_response,
                context=l5_result.context,
                ip_hash=ip_hash,
            )
            metrics.layer_timings["L8"] = time.time() - l8_start

            # Log L8 safety check result
            audit_logger.log_safety_check(
                request_id=request_id,
                layer="L8",
                passed=l8_result.passed,
                classification=l8_result.status,
                confidence=1.0,  # L8 doesn't provide confidence scores
                reason=", ".join(i.value for i in l8_result.issues) if l8_result.issues else None,
            )

            revised = l7_result.was_revised if hasattr(l7_result, 'was_revised') else False

            if not l8_result.passed:
                metrics.blocked_at_layer = "L8"
                # Use safe fallback instead of error
                final_response = Layer8SafetyChecker.get_safe_fallback_response()

            # Log the final bot response
            audit_logger.log_bot_response(
                request_id=request_id,
                conversation_id=conv_id,
                turn=metrics.conversation_turn,
                response=final_response,
                domain=l4_result.domain.value,
                revised=revised,
            )

            # ===== Update Conversation History =====
            await self.conversation_manager.add_message(
                conv_id, MessageRole.USER, sanitized_message
            )
            await self.conversation_manager.add_message(
                conv_id, MessageRole.ASSISTANT, final_response
            )

            # ===== LAYER 9: Response Delivery =====
            total_time_ms = (time.time() - start_time) * 1000

            # Log layer timings
            audit_logger.log_layer_timing(
                request_id=request_id,
                layer_timings=metrics.layer_timings,
                total_time_ms=total_time_ms,
            )

            # Record Prometheus metrics
            prom_metrics = _get_metrics()
            if prom_metrics:
                # Record per-layer durations
                for layer, duration in metrics.layer_timings.items():
                    prom_metrics["layer_duration"].labels(layer=layer).observe(duration)

                # Record intent confidence
                prom_metrics["intent_confidence"].observe(intent.confidence)

                # Record domain request
                prom_metrics["domain_requests"].labels(domain=l4_result.domain.value).inc()

                # Record conversation turn
                prom_metrics["conversation_turns"].observe(metrics.conversation_turn + 1)

                # Record response length
                prom_metrics["response_length"].observe(len(final_response))

            return self.layer9.deliver_success(
                response=final_response,
                domain=l4_result.domain,
                request_id=request_id,
                conversation_id=conv_id,
                start_time=start_time,
                ip_hash=ip_hash,
                layer_timings=metrics.layer_timings,
            )

        except Exception as e:
            logger.error(f"Unexpected error in pipeline: {e}", exc_info=True)
            return self.layer9.deliver_error(
                error_type="internal_error",
                request_id=request_id,
                conversation_id=conv_id,
                start_time=start_time,
                ip_hash=ip_hash,
                blocked_at_layer=metrics.blocked_at_layer,
            )

    async def health_check(self) -> dict[str, bool | str]:
        """
        Check health of all pipeline components.

        Returns:
            Dictionary with component health status.
        """
        health: dict[str, bool | str] = {}

        # Check Ollama
        try:
            health["ollama"] = await self.ollama_client.health_check()
        except Exception as e:
            health["ollama"] = False
            health["ollama_error"] = str(e)

        # Check rate limiter
        health["rate_limiter"] = True  # In-memory, always "up"

        # Check conversation manager
        health["conversation_manager"] = True

        # Overall health
        health["healthy"] = all(
            v for k, v in health.items()
            if k in ["ollama", "rate_limiter", "conversation_manager"]
        )

        return health

    async def close(self) -> None:
        """Clean up resources."""
        await self.ollama_client.close()
