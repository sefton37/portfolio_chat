"""
Simulation engine that runs multi-turn conversations against a live portfolio_chat server.

Sends HTTP requests to the actual API endpoints, uses real Ollama models,
and tracks everything in SQLite.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx

from .db import SimulationDB
from .profiles import Profile, Turn, build_profiles

logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    """Configuration for the simulation engine."""
    base_url: str = "http://127.0.0.1:8000"
    request_timeout: float = 120.0  # Per-request timeout (LLM calls can be slow)
    delay_between_turns: float = 1.0  # Seconds between turns (respect rate limits)
    delay_between_profiles: float = 3.0  # Seconds between profile conversations
    db_path: str = ""  # Set dynamically
    max_retries: int = 2  # Retries on connection error (not on API errors)


class SimulationEngine:
    """Runs simulated conversations against live portfolio_chat."""

    def __init__(self, config: EngineConfig | None = None):
        self.config = config or EngineConfig()
        self.db: SimulationDB | None = None
        self.client: httpx.AsyncClient | None = None

    async def run(self, profiles: list[Profile] | None = None, notes: str = "") -> int:
        """
        Run a full simulation with all profiles.

        Returns the run_id for querying results.
        """
        profiles = profiles or build_profiles()

        self.db = SimulationDB(self.config.db_path)
        self.client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.request_timeout,
        )

        run_id = self.db.create_run(profile_count=len(profiles), notes=notes)
        total_turns = 0
        total_errors = 0

        logger.info(f"Starting simulation run #{run_id} with {len(profiles)} profiles")

        try:
            # Verify server is reachable
            if not await self._check_server():
                logger.error("Portfolio chat server not reachable. Aborting.")
                self.db.finish_run(run_id, 0, 1)
                return run_id

            for i, profile in enumerate(profiles, 1):
                logger.info(f"[{i}/{len(profiles)}] Running profile: {profile.name} ({profile.id})")

                turns_count, error_count = await self._run_profile(run_id, profile)
                total_turns += turns_count
                total_errors += error_count

                if i < len(profiles):
                    logger.info(f"  Waiting {self.config.delay_between_profiles}s before next profile...")
                    await asyncio.sleep(self.config.delay_between_profiles)

            self.db.finish_run(run_id, total_turns, total_errors)
            logger.info(
                f"Simulation run #{run_id} complete: {total_turns} turns, {total_errors} errors "
                f"across {len(profiles)} profiles"
            )
        finally:
            await self.client.aclose()
            # Don't close DB — caller may want to analyze

        return run_id

    async def _check_server(self) -> bool:
        """Verify the portfolio chat server is reachable."""
        try:
            resp = await self.client.get("/")  # type: ignore
            # Any response (even 401) means server is up
            return resp.status_code < 500
        except httpx.ConnectError:
            return False

    async def _run_profile(self, run_id: int, profile: Profile) -> tuple[int, int]:
        """Run a single profile's conversation. Returns (turn_count, error_count)."""
        conv_pk = self.db.create_conversation(  # type: ignore
            run_id=run_id,
            profile_id=profile.id,
            profile_name=profile.name,
            profile_category=profile.category.value,
        )

        turns = profile.get_conversation()
        conversation_id: str | None = None  # Will be set from first response
        successful = 0
        blocked = 0
        errors = 0
        total_time_ms = 0.0

        for turn_num, turn in enumerate(turns, 1):
            logger.info(f"  Turn {turn_num}/{len(turns)}: [{turn.intent}] {turn.message[:60]}...")

            result = await self._send_turn(turn, conversation_id, profile.id)

            # Track conversation_id for multi-turn
            if result.conversation_id and not conversation_id:
                conversation_id = result.conversation_id
            elif result.conversation_id:
                conversation_id = result.conversation_id

            # Record in DB
            turn_id = self.db.record_turn(  # type: ignore
                conversation_pk=conv_pk,
                turn_number=turn_num,
                user_message=turn.message,
                intent_label=turn.intent,
                expected_domain=turn.expected_domain,
                success=result.success,
                response_content=result.content,
                response_domain=result.domain,
                error_code=result.error_code,
                error_message=result.error_message,
                response_time_ms=result.response_time_ms,
                conversation_id_returned=result.conversation_id,
                layer_timings_json=json.dumps(result.layer_timings) if result.layer_timings else None,
                request_id=result.request_id,
            )

            if result.success:
                successful += 1
            elif result.error_code in ("BLOCKED_INPUT", "OUT_OF_SCOPE"):
                blocked += 1
            else:
                errors += 1

            total_time_ms += result.response_time_ms or 0

            # Log result summary
            if result.success:
                preview = (result.content or "")[:80].replace("\n", " ")
                logger.info(f"    -> [{result.domain}] {preview}...")
            else:
                logger.info(f"    -> ERROR: [{result.error_code}] {result.error_message}")

            # Delay between turns
            if turn_num < len(turns):
                await asyncio.sleep(self.config.delay_between_turns)

        self.db.finish_conversation(  # type: ignore
            conv_pk=conv_pk,
            conversation_id=conversation_id,
            total_turns=len(turns),
            successful=successful,
            blocked=blocked,
            errors=errors,
            total_time_ms=total_time_ms,
        )

        return len(turns), errors

    async def _send_turn(self, turn: Turn, conversation_id: str | None, profile_id: str = "") -> TurnResult:
        """Send a single turn to the chat API."""
        payload: dict = {"message": turn.message}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        # Use a unique simulated IP per profile so rate limits are per-profile,
        # not shared across all profiles (which would be unrealistic — real users
        # have different IPs). The server trusts CF-Connecting-IP from 127.0.0.1.
        simulated_ip = f"10.0.0.{hash(profile_id) % 254 + 1}"
        headers = {
            "Content-Type": "application/json",
            "CF-Connecting-IP": simulated_ip,
        }

        start_time = time.time()

        for attempt in range(self.config.max_retries + 1):
            try:
                resp = await self.client.post(  # type: ignore
                    "/chat",
                    json=payload,
                    headers=headers,
                )
                elapsed_ms = (time.time() - start_time) * 1000

                if resp.status_code == 422:
                    # Validation error
                    return TurnResult(
                        success=False,
                        error_code="VALIDATION_ERROR",
                        error_message=resp.text[:500],
                        response_time_ms=elapsed_ms,
                    )

                if resp.status_code == 429:
                    return TurnResult(
                        success=False,
                        error_code="RATE_LIMITED",
                        error_message="Rate limited by server",
                        response_time_ms=elapsed_ms,
                    )

                data = resp.json()
                return TurnResult(
                    success=data.get("success", False),
                    content=data.get("response", {}).get("content") if data.get("response") else None,
                    domain=data.get("response", {}).get("domain") if data.get("response") else None,
                    error_code=data.get("error", {}).get("code") if data.get("error") else None,
                    error_message=data.get("error", {}).get("message") if data.get("error") else None,
                    response_time_ms=data.get("metadata", {}).get("response_time_ms", elapsed_ms),
                    conversation_id=data.get("metadata", {}).get("conversation_id"),
                    layer_timings=data.get("metadata", {}).get("layer_timings_ms"),
                    request_id=data.get("metadata", {}).get("request_id"),
                )

            except httpx.ConnectError as e:
                if attempt < self.config.max_retries:
                    logger.warning(f"    Connection error (attempt {attempt + 1}), retrying...")
                    await asyncio.sleep(2)
                    continue
                return TurnResult(
                    success=False,
                    error_code="CONNECTION_ERROR",
                    error_message=str(e),
                    response_time_ms=(time.time() - start_time) * 1000,
                )
            except httpx.TimeoutException:
                return TurnResult(
                    success=False,
                    error_code="TIMEOUT",
                    error_message=f"Request timed out after {self.config.request_timeout}s",
                    response_time_ms=(time.time() - start_time) * 1000,
                )
            except Exception as e:
                return TurnResult(
                    success=False,
                    error_code="UNKNOWN_ERROR",
                    error_message=str(e)[:500],
                    response_time_ms=(time.time() - start_time) * 1000,
                )

        # Should not reach here
        return TurnResult(
            success=False,
            error_code="MAX_RETRIES",
            error_message="Exhausted all retries",
            response_time_ms=(time.time() - start_time) * 1000,
        )


@dataclass
class TurnResult:
    """Result from a single API call."""
    success: bool = False
    content: str | None = None
    domain: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    response_time_ms: float | None = None
    conversation_id: str | None = None
    layer_timings: dict | None = None
    request_id: str | None = None
