"""
Analytics service for computing aggregated statistics.

Provides methods to calculate conversation metrics and time series data.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from portfolio_chat.analytics.storage import ConversationLog, ConversationStorage

logger = logging.getLogger(__name__)


@dataclass
class AnalyticsStats:
    """Aggregated analytics statistics."""

    total_conversations: int
    total_messages: int
    avg_messages_per_conversation: float
    median_messages_per_conversation: float
    avg_response_time_ms: float
    total_blocked: int
    domains_breakdown: dict[str, int]
    period_start: str | None
    period_end: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_conversations": self.total_conversations,
            "total_messages": self.total_messages,
            "avg_messages_per_conversation": round(self.avg_messages_per_conversation, 2),
            "median_messages_per_conversation": self.median_messages_per_conversation,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "total_blocked": self.total_blocked,
            "domains_breakdown": self.domains_breakdown,
            "period_start": self.period_start,
            "period_end": self.period_end,
        }


@dataclass
class TimeSeriesPoint:
    """A single point in a time series."""

    timestamp: str
    conversations: int
    messages: int


class AnalyticsService:
    """
    Service for computing analytics from conversation logs.

    Provides aggregated statistics and time series data.
    """

    def __init__(self, storage: ConversationStorage | None = None) -> None:
        """
        Initialize analytics service.

        Args:
            storage: ConversationStorage instance. Creates new one if not provided.
        """
        self.storage = storage or ConversationStorage()

    async def get_stats(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> AnalyticsStats:
        """
        Get aggregated statistics for a time period.

        Args:
            start_date: Start of period (inclusive). Defaults to all time.
            end_date: End of period (inclusive). Defaults to now.

        Returns:
            AnalyticsStats with computed metrics.
        """
        conversations = await self.storage.list_recent(
            limit=10000,  # Get all within range
            start_date=start_date,
            end_date=end_date,
        )

        if not conversations:
            return AnalyticsStats(
                total_conversations=0,
                total_messages=0,
                avg_messages_per_conversation=0.0,
                median_messages_per_conversation=0.0,
                avg_response_time_ms=0.0,
                total_blocked=0,
                domains_breakdown={},
                period_start=start_date.isoformat() if start_date else None,
                period_end=end_date.isoformat() if end_date else None,
            )

        # Calculate metrics
        total_conversations = len(conversations)
        message_counts = [len(c.messages) for c in conversations]
        total_messages = sum(message_counts)

        avg_messages = total_messages / total_conversations if total_conversations > 0 else 0.0

        # Calculate median
        sorted_counts = sorted(message_counts)
        n = len(sorted_counts)
        if n % 2 == 0:
            median_messages = (sorted_counts[n // 2 - 1] + sorted_counts[n // 2]) / 2
        else:
            median_messages = float(sorted_counts[n // 2])

        # Average response time
        total_response_time = sum(c.total_response_time_ms for c in conversations)
        total_turns = sum(c.total_turns for c in conversations)
        avg_response_time = total_response_time / total_turns if total_turns > 0 else 0.0

        # Count blocked
        total_blocked = sum(1 for c in conversations if c.blocked_at_layer)

        # Domain breakdown
        domains: dict[str, int] = defaultdict(int)
        for conv in conversations:
            for domain in conv.domains_used:
                domains[domain] += 1

        return AnalyticsStats(
            total_conversations=total_conversations,
            total_messages=total_messages,
            avg_messages_per_conversation=avg_messages,
            median_messages_per_conversation=median_messages,
            avg_response_time_ms=avg_response_time,
            total_blocked=total_blocked,
            domains_breakdown=dict(domains),
            period_start=start_date.isoformat() if start_date else None,
            period_end=end_date.isoformat() if end_date else None,
        )

    async def get_timeseries(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        granularity: str = "day",
    ) -> list[dict[str, Any]]:
        """
        Get time series data for charting.

        Args:
            start_date: Start of period. Defaults to 30 days ago.
            end_date: End of period. Defaults to now.
            granularity: Time bucket size: "hour", "day", or "week".

        Returns:
            List of time series data points.
        """
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        conversations = await self.storage.list_recent(
            limit=10000,
            start_date=start_date,
            end_date=end_date,
        )

        # Group by time bucket
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"conversations": 0, "messages": 0})

        for conv in conversations:
            try:
                ts = datetime.fromisoformat(conv.started_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            # Determine bucket key based on granularity
            if granularity == "hour":
                bucket_key = ts.strftime("%Y-%m-%dT%H:00:00Z")
            elif granularity == "week":
                # Start of week (Monday)
                week_start = ts - timedelta(days=ts.weekday())
                bucket_key = week_start.strftime("%Y-%m-%dT00:00:00Z")
            else:  # day
                bucket_key = ts.strftime("%Y-%m-%dT00:00:00Z")

            buckets[bucket_key]["conversations"] += 1
            buckets[bucket_key]["messages"] += len(conv.messages)

        # Sort by timestamp and return
        sorted_keys = sorted(buckets.keys())
        return [
            {
                "timestamp": key,
                "conversations": buckets[key]["conversations"],
                "messages": buckets[key]["messages"],
            }
            for key in sorted_keys
        ]

    async def get_conversation_list(
        self,
        limit: int = 50,
        offset: int = 0,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Get paginated list of conversations with summary info.

        Args:
            limit: Maximum conversations to return.
            offset: Number to skip for pagination.
            start_date: Filter start date.
            end_date: Filter end date.

        Returns:
            Dictionary with conversations list and pagination info.
        """
        conversations = await self.storage.list_recent(
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
        )

        total = await self.storage.count(start_date=start_date, end_date=end_date)

        return {
            "conversations": [
                {
                    "id": c.id,
                    "started_at": c.started_at,
                    "last_activity": c.last_activity,
                    "total_turns": c.total_turns,
                    "message_count": len(c.messages),
                    "domains_used": c.domains_used,
                    "blocked_at_layer": c.blocked_at_layer,
                    "avg_response_time_ms": (
                        c.total_response_time_ms / c.total_turns
                        if c.total_turns > 0
                        else 0
                    ),
                }
                for c in conversations
            ],
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(conversations) < total,
            },
        }

    async def get_conversation_detail(self, conversation_id: str) -> dict[str, Any] | None:
        """
        Get full conversation detail.

        Args:
            conversation_id: The conversation ID.

        Returns:
            Full conversation data or None if not found.
        """
        conv = await self.storage.get(conversation_id)
        if conv is None:
            return None

        return conv.to_dict()
