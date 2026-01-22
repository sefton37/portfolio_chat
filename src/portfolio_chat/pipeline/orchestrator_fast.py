"""
Fast Pipeline Orchestrator

Optimized version with:
- Combined L2+L3 (single LLM call)
- Optional L7 skip
- Fast pattern-based L8
- Streaming support
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from collections.abc import AsyncIterator

from portfolio_chat.analytics.storage import ConversationStorage as AnalyticsStorage
from portfolio_chat.config import ANALYTICS, PIPELINE, MODELS
from portfolio_chat.contact.storage import ContactStorage
from portfolio_chat.conversation.manager import ConversationManager, MessageRole
from portfolio_chat.models.ollama_client import AsyncOllamaClient
from portfolio_chat.pipeline.layer0_network import Layer0NetworkGateway, Layer0Status
from portfolio_chat.pipeline.layer1_sanitize import Layer1Sanitizer, Layer1Status
from portfolio_chat.pipeline.layer2_combined import Layer2CombinedClassifier, CombinedStatus
from portfolio_chat.pipeline.layer4_route import Domain, Layer4Router
from portfolio_chat.pipeline.layer5_context import Layer5ContextRetriever, Layer5Status
from portfolio_chat.pipeline.layer6_generate import Layer6Generator, Layer6Status
from portfolio_chat.pipeline.layer8_fast import Layer8FastChecker
from portfolio_chat.pipeline.layer9_deliver import ChatResponse, Layer9Deliverer
from portfolio_chat.tools.executor import ToolExecutor
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


class FastPipelineOrchestrator:
    """
    Optimized pipeline orchestrator.

    Key optimizations:
    - Combined L2+L3 saves one LLM call (~3-4s)
    - Skip L7 revision saves one LLM call (~3-4s)
    - Fast L8 pattern matching saves one LLM call (~2-3s)
    - Total savings: ~8-11s per request
    """

    MAX_TOOL_ITERATIONS = 3

    def __init__(
        self,
        rate_limiter: InMemoryRateLimiter | None = None,
        conversation_manager: ConversationManager | None = None,
        ollama_client: AsyncOllamaClient | None = None,
        contact_storage: ContactStorage | None = None,
        analytics_storage: AnalyticsStorage | None = None,
    ) -> None:
        # Shared components
        self.rate_limiter = rate_limiter or InMemoryRateLimiter()
        self.conversation_manager = conversation_manager or ConversationManager()
        self.ollama_client = ollama_client or AsyncOllamaClient()
        self.contact_storage = contact_storage or ContactStorage()
        self.analytics_storage = analytics_storage or (AnalyticsStorage() if ANALYTICS.ENABLED else None)

        # Initialize optimized layers
        self.layer0 = Layer0NetworkGateway(rate_limiter=self.rate_limiter)
        self.layer1 = Layer1Sanitizer()
        self.layer2_combined = Layer2CombinedClassifier(client=self.ollama_client)
        self.layer4 = Layer4Router()
        self.layer5 = Layer5ContextRetriever()
        self.layer6 = Layer6Generator(client=self.ollama_client, enable_tools=True)
        self.layer8_fast = Layer8FastChecker()
        self.layer9 = Layer9Deliverer()

    async def process_message(
        self,
        message: str,
        conversation_id: str | None,
        client_ip: str,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> ChatResponse:
        """Process a message through the optimized pipeline."""
        start_time = time.time()
        request_id = generate_request_id()
        request_id_var.set(request_id)
        ip_hash = hash_ip(client_ip)
        metrics = PipelineMetrics()

        # Get or create conversation
        conversation, is_new = await self.conversation_manager.get_or_create(conversation_id)
        conv_id = conversation.id
        metrics.conversation_turn = conversation.turn_count

        logger.info(f"[FAST] Processing request {request_id}: conv={conv_id}")

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
                return self.layer9.deliver_error(
                    error_type="blocked_input",
                    request_id=request_id,
                    conversation_id=conv_id,
                    start_time=start_time,
                    ip_hash=ip_hash,
                    blocked_at_layer="L1",
                    custom_message=l1_result.error_message,
                )

            sanitized_message = l1_result.sanitized_input or message

            # Log user message
            audit_logger.log_user_message(
                request_id=request_id,
                conversation_id=conv_id,
                turn=metrics.conversation_turn,
                raw_message=message,
                sanitized_message=sanitized_message,
                ip_hash=ip_hash,
            )

            if self.analytics_storage:
                await self.analytics_storage.log_message(
                    conversation_id=conv_id,
                    role="user",
                    content=sanitized_message,
                    ip_hash=ip_hash,
                )

            # ===== LAYER 2+3 COMBINED: Security + Intent =====
            l23_start = time.time()
            conversation_history = conversation.get_history()
            combined_result = await self.layer2_combined.classify(
                message=sanitized_message,
                conversation_history=conversation_history,
                ip_hash=ip_hash,
            )
            metrics.layer_timings["L2+L3"] = time.time() - l23_start

            if combined_result.status == CombinedStatus.BLOCKED:
                metrics.blocked_at_layer = "L2"
                if self.analytics_storage:
                    await self.analytics_storage.log_message(
                        conversation_id=conv_id,
                        role="assistant",
                        content="[BLOCKED]",
                        ip_hash=ip_hash,
                        response_time_ms=(time.time() - start_time) * 1000,
                        blocked_at_layer="L2",
                    )
                return self.layer9.deliver_error(
                    error_type="blocked_input",
                    request_id=request_id,
                    conversation_id=conv_id,
                    start_time=start_time,
                    ip_hash=ip_hash,
                    blocked_at_layer="L2",
                    custom_message=combined_result.error_message,
                )

            intent = combined_result.intent
            if intent is None:
                from portfolio_chat.pipeline.layer3_intent import Intent, QuestionType
                intent = Intent(topic="general", question_type=QuestionType.AMBIGUOUS, confidence=0.5)

            # ===== LAYER 4: Domain Routing =====
            l4_start = time.time()
            l4_result = self.layer4.route(intent=intent, original_message=sanitized_message)
            metrics.layer_timings["L4"] = time.time() - l4_start
            metrics.domain_matched = l4_result.domain.value

            # ===== LAYER 5: Context Retrieval =====
            l5_start = time.time()
            l5_result = self.layer5.retrieve(domain=l4_result.domain, _intent=intent)
            metrics.layer_timings["L5"] = time.time() - l5_start

            # Check for insufficient context
            MIN_CONTEXT_QUALITY = 0.4
            context_insufficient = (
                l5_result.status == Layer5Status.INSUFFICIENT
                or l5_result.is_placeholder
                or l5_result.context_quality < MIN_CONTEXT_QUALITY
            )

            if context_insufficient:
                no_info_response = (
                    f"I don't have detailed information about that topic. "
                    f"Is there something else about Kellogg's work I can help with?"
                )
                return self.layer9.deliver_success(
                    response=no_info_response,
                    domain=l4_result.domain,
                    request_id=request_id,
                    conversation_id=conv_id,
                    start_time=start_time,
                    ip_hash=ip_hash,
                    layer_timings=metrics.layer_timings,
                )

            # ===== LAYER 6: Response Generation =====
            l6_start = time.time()

            tool_executor = ToolExecutor(
                contact_storage=self.contact_storage,
                conversation_id=conv_id,
                client_ip_hash=ip_hash,
            )
            self.layer6.set_tool_executor(tool_executor)

            l6_result = await self.layer6.generate(
                message=sanitized_message,
                domain=l4_result.domain,
                context=l5_result.context,
                conversation_history=conversation_history,
                sources=l5_result.sources_loaded,
            )

            # Handle tool calls
            tool_iteration = 0
            while (
                l6_result.status == Layer6Status.TOOL_CALL
                and l6_result.tool_calls
                and tool_iteration < self.MAX_TOOL_ITERATIONS
            ):
                tool_iteration += 1
                tool_results = await tool_executor.execute_all(l6_result.tool_calls)

                l6_result = await self.layer6.generate(
                    message=sanitized_message,
                    domain=l4_result.domain,
                    context=l5_result.context,
                    conversation_history=conversation_history,
                    sources=l5_result.sources_loaded,
                    tool_results=tool_results,
                )

            metrics.layer_timings["L6"] = time.time() - l6_start

            if not l6_result.passed or not l6_result.response:
                fallback = await self.layer6.generate_fallback_response(l4_result.domain)
                l6_result.response = fallback

            final_response = l6_result.response

            # ===== SKIP L7 (Revision) - configured off =====
            # L7 adds ~3-4s latency for marginal improvement
            metrics.layer_timings["L7"] = 0.0  # Skipped

            # ===== LAYER 8: Fast Safety Check =====
            l8_start = time.time()
            l8_result = self.layer8_fast.check(final_response, l5_result.context)
            metrics.layer_timings["L8"] = time.time() - l8_start

            if not l8_result.passed:
                metrics.blocked_at_layer = "L8"
                final_response = Layer8FastChecker.get_safe_fallback_response()

            # Log response
            audit_logger.log_bot_response(
                request_id=request_id,
                conversation_id=conv_id,
                turn=metrics.conversation_turn,
                response=final_response,
                domain=l4_result.domain.value,
                revised=False,
            )

            response_time_ms = (time.time() - start_time) * 1000

            if self.analytics_storage:
                await self.analytics_storage.log_message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=final_response,
                    ip_hash=ip_hash,
                    domain=l4_result.domain.value,
                    response_time_ms=response_time_ms,
                    blocked_at_layer=metrics.blocked_at_layer,
                )

            # Update conversation history
            await self.conversation_manager.add_message(conv_id, MessageRole.USER, sanitized_message)
            await self.conversation_manager.add_message(conv_id, MessageRole.ASSISTANT, final_response)

            # Log timing
            total_time_ms = (time.time() - start_time) * 1000
            audit_logger.log_layer_timing(
                request_id=request_id,
                layer_timings=metrics.layer_timings,
                total_time_ms=total_time_ms,
            )

            logger.info(f"[FAST] Request {request_id} completed in {total_time_ms:.0f}ms")

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
            logger.error(f"Unexpected error in fast pipeline: {e}", exc_info=True)
            return self.layer9.deliver_error(
                error_type="internal_error",
                request_id=request_id,
                conversation_id=conv_id,
                start_time=start_time,
                ip_hash=ip_hash,
                blocked_at_layer=metrics.blocked_at_layer,
            )

    async def process_message_stream(
        self,
        message: str,
        conversation_id: str | None,
        client_ip: str,
    ) -> AsyncIterator[str]:
        """
        Process message with streaming response.

        Yields response chunks as they're generated.
        """
        start_time = time.time()
        request_id = generate_request_id()
        request_id_var.set(request_id)
        ip_hash = hash_ip(client_ip)

        conversation, _ = await self.conversation_manager.get_or_create(conversation_id)
        conv_id = conversation.id

        try:
            # Quick validation layers (L0, L1)
            l0_result = await self.layer0.validate_request(
                client_ip=client_ip,
                request_id=request_id,
                has_message=bool(message),
            )
            if l0_result.blocked:
                yield l0_result.error_message or "Rate limited. Please try again."
                return

            l1_result = self.layer1.sanitize(message, ip_hash=ip_hash)
            if l1_result.blocked:
                yield l1_result.error_message or "Invalid input."
                return

            sanitized_message = l1_result.sanitized_input or message

            # Combined security + intent (L2+L3)
            conversation_history = conversation.get_history()
            combined_result = await self.layer2_combined.classify(
                message=sanitized_message,
                conversation_history=conversation_history,
                ip_hash=ip_hash,
            )

            if combined_result.status == CombinedStatus.BLOCKED:
                yield combined_result.error_message or "I can only answer questions about Kellogg's work."
                return

            intent = combined_result.intent
            if intent is None:
                from portfolio_chat.pipeline.layer3_intent import Intent, QuestionType
                intent = Intent(topic="general", question_type=QuestionType.AMBIGUOUS, confidence=0.5)

            # Routing (L4) and Context (L5)
            l4_result = self.layer4.route(intent=intent, original_message=sanitized_message)
            l5_result = self.layer5.retrieve(domain=l4_result.domain, _intent=intent)

            if l5_result.context_quality < 0.4:
                yield "I don't have detailed information about that topic."
                return

            # Stream generation (L6)
            system_prompt = self.layer6._get_system_prompt(l4_result.domain)
            user_message = self.layer6._format_user_message(
                sanitized_message,
                l5_result.context,
                conversation_history,
                l5_result.sources_loaded,
            )

            full_response = ""
            async for chunk in self.ollama_client.chat_stream(
                system=system_prompt,
                user=user_message,
                model=MODELS.GENERATOR_MODEL,
            ):
                full_response += chunk
                yield chunk

            # Post-generation safety check
            l8_result = self.layer8_fast.check(full_response)
            if not l8_result.passed:
                # Can't unsend, but log the issue
                logger.warning(f"Streamed response failed safety check: {l8_result.issue_details}")

            # Update conversation
            await self.conversation_manager.add_message(conv_id, MessageRole.USER, sanitized_message)
            await self.conversation_manager.add_message(conv_id, MessageRole.ASSISTANT, full_response)

        except Exception as e:
            logger.error(f"Error in streaming pipeline: {e}", exc_info=True)
            yield "I'm having technical difficulties. Please try again."

    async def health_check(self) -> dict[str, bool | str]:
        """Check health of all pipeline components."""
        health: dict[str, bool | str] = {}

        try:
            health["ollama"] = await self.ollama_client.health_check()
        except Exception as e:
            health["ollama"] = False
            health["ollama_error"] = str(e)

        health["rate_limiter"] = True
        health["conversation_manager"] = True
        health["healthy"] = all(
            v for k, v in health.items()
            if k in ["ollama", "rate_limiter", "conversation_manager"]
        )

        return health

    async def close(self) -> None:
        """Clean up resources."""
        await self.ollama_client.close()
