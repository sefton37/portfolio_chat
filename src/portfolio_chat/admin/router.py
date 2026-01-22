"""
Admin router for analytics dashboard.

Provides localhost-only API endpoints for viewing analytics data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from portfolio_chat.analytics.service import AnalyticsService
from portfolio_chat.analytics.storage import ConversationStorage
from portfolio_chat.config import ANALYTICS
from portfolio_chat.contact.storage import ContactStorage

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Shared instances (initialized on first use)
_storage: ConversationStorage | None = None
_service: AnalyticsService | None = None
_contact_storage: ContactStorage | None = None


def get_storage() -> ConversationStorage:
    """Get or create ConversationStorage instance."""
    global _storage
    if _storage is None:
        _storage = ConversationStorage()
    return _storage


def get_service() -> AnalyticsService:
    """Get or create AnalyticsService instance."""
    global _service
    if _service is None:
        _service = AnalyticsService(get_storage())
    return _service


def get_contact_storage() -> ContactStorage:
    """Get or create ContactStorage instance."""
    global _contact_storage
    if _contact_storage is None:
        _contact_storage = ContactStorage()
    return _contact_storage


async def localhost_only(request: Request) -> None:
    """
    Dependency that restricts access to localhost only.

    Raises HTTPException 403 if not from localhost.
    """
    if not ANALYTICS.ADMIN_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")

    client_ip = request.client.host if request.client else "unknown"
    allowed_ips = ("127.0.0.1", "::1", "localhost")

    if client_ip not in allowed_ips:
        logger.warning(f"Admin access denied from {client_ip}")
        raise HTTPException(status_code=403, detail="Admin access restricted to localhost")


@admin_router.get("", response_class=HTMLResponse, dependencies=[Depends(localhost_only)])
async def admin_dashboard() -> HTMLResponse:
    """
    Serve the admin dashboard HTML page.

    Returns the static HTML file for the analytics dashboard.
    """
    static_dir = Path(__file__).parent.parent / "static" / "admin"
    index_path = static_dir / "index.html"

    if not index_path.exists():
        raise HTTPException(status_code=500, detail="Dashboard not found")

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    return HTMLResponse(content=content)


@admin_router.get("/analytics/stats", dependencies=[Depends(localhost_only)])
async def get_stats(
    start_date: str | None = Query(None, description="Start date (ISO format)"),
    end_date: str | None = Query(None, description="End date (ISO format)"),
    service: AnalyticsService = Depends(get_service),
) -> dict[str, Any]:
    """
    Get aggregated analytics statistics.

    Returns total conversations, messages, averages, and domain breakdown.
    """
    start = _parse_date(start_date) if start_date else None
    end = _parse_date(end_date) if end_date else None

    stats = await service.get_stats(start_date=start, end_date=end)
    return stats.to_dict()


@admin_router.get("/analytics/timeseries", dependencies=[Depends(localhost_only)])
async def get_timeseries(
    start_date: str | None = Query(None, description="Start date (ISO format)"),
    end_date: str | None = Query(None, description="End date (ISO format)"),
    granularity: str = Query("day", description="Time bucket: hour, day, or week"),
    service: AnalyticsService = Depends(get_service),
) -> list[dict[str, Any]]:
    """
    Get time series data for charts.

    Returns conversation and message counts bucketed by time.
    """
    if granularity not in ("hour", "day", "week"):
        raise HTTPException(status_code=400, detail="Invalid granularity. Use: hour, day, or week")

    start = _parse_date(start_date) if start_date else None
    end = _parse_date(end_date) if end_date else None

    return await service.get_timeseries(
        start_date=start,
        end_date=end,
        granularity=granularity,
    )


@admin_router.get("/analytics/conversations", dependencies=[Depends(localhost_only)])
async def list_conversations(
    limit: int = Query(50, ge=1, le=200, description="Max conversations to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    start_date: str | None = Query(None, description="Start date filter (ISO format)"),
    end_date: str | None = Query(None, description="End date filter (ISO format)"),
    service: AnalyticsService = Depends(get_service),
) -> dict[str, Any]:
    """
    Get paginated list of conversations.

    Returns conversation summaries with pagination info.
    """
    start = _parse_date(start_date) if start_date else None
    end = _parse_date(end_date) if end_date else None

    return await service.get_conversation_list(
        limit=limit,
        offset=offset,
        start_date=start,
        end_date=end,
    )


@admin_router.get("/analytics/conversations/{conversation_id}", dependencies=[Depends(localhost_only)])
async def get_conversation(
    conversation_id: str,
    service: AnalyticsService = Depends(get_service),
) -> dict[str, Any]:
    """
    Get full conversation detail.

    Returns complete message history for a specific conversation.
    """
    detail = await service.get_conversation_detail(conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


def _parse_date(date_str: str) -> datetime | None:
    """Parse an ISO date string to datetime."""
    try:
        # Handle various ISO formats
        if "T" in date_str:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid date format: {date_str}")


# ===== Inbox Endpoints =====

@admin_router.get("/inbox", dependencies=[Depends(localhost_only)])
async def list_inbox_messages(
    limit: int = Query(50, ge=1, le=200, description="Max messages to return"),
    storage: ContactStorage = Depends(get_contact_storage),
) -> dict[str, Any]:
    """
    Get list of contact messages (inbox).

    Returns messages sent via the save_message_for_kellogg tool.
    """
    messages = await storage.list_recent(limit=limit)
    total = storage.count()

    return {
        "messages": [msg.to_dict() for msg in messages],
        "total": total,
    }


@admin_router.get("/inbox/{message_id}", dependencies=[Depends(localhost_only)])
async def get_inbox_message(
    message_id: str,
    storage: ContactStorage = Depends(get_contact_storage),
) -> dict[str, Any]:
    """
    Get a specific inbox message by ID.
    """
    message = await storage.get(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return message.to_dict()
