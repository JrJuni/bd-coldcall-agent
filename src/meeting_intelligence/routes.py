"""Mountable FastAPI routes for Meeting Intelligence.

The main app does not include this router yet; keeping it mountable lets the
module be tested and later exposed either through FastAPI or MCP once the
larger production refactor settles.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.meeting_intelligence import service as _service
from src.meeting_intelligence import database as _database
from src.meeting_intelligence.models import create_meeting_schema
from src.meeting_intelligence.repository import MeetingRepository


class MeetingAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=100_000)
    lang: Literal["en", "ko"] = "en"
    title: str | None = Field(default=None, max_length=300)
    occurred_at: str | None = Field(default=None, max_length=64)


class MeetingAnalyzeResponse(BaseModel):
    meeting_id: int
    status: Literal["completed"]
    meeting: dict[str, Any]


class MeetingDetailResponse(BaseModel):
    meeting: dict[str, Any]


class RecentMeetingsResponse(BaseModel):
    meetings: list[dict[str, Any]]


class SemanticGroupedResponse(BaseModel):
    items: list[dict[str, Any]]


class SemanticItemsResponse(BaseModel):
    items: list[dict[str, Any]]


router = APIRouter()


def get_meeting_repository() -> MeetingRepository:
    factory = _database.get_session_factory()
    engine = factory.kw.get("bind") if hasattr(factory, "kw") else None
    if engine is not None:
        create_meeting_schema(engine)
    return MeetingRepository(factory)


@router.post("/meetings/analyze", response_model=MeetingAnalyzeResponse)
async def analyze_meeting(payload: MeetingAnalyzeRequest) -> MeetingAnalyzeResponse:
    repo = get_meeting_repository()
    try:
        meeting = _service.analyze_meeting_summary(
            company_name=payload.company_name,
            summary=payload.summary,
            repository=repo,
            lang=payload.lang,
            title=payload.title,
            occurred_at=payload.occurred_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return MeetingAnalyzeResponse(
        meeting_id=int(meeting["id"]), status="completed", meeting=meeting
    )


@router.get("/meetings/{meeting_id}", response_model=MeetingDetailResponse)
async def get_meeting(meeting_id: int) -> MeetingDetailResponse:
    meeting = _service.meeting_brief(get_meeting_repository(), meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail=f"meeting {meeting_id} not found")
    return MeetingDetailResponse(meeting=meeting)


@router.get(
    "/semantic/meetings/{meeting_id}/brief", response_model=MeetingDetailResponse
)
async def get_meeting_brief(meeting_id: int) -> MeetingDetailResponse:
    return await get_meeting(meeting_id)


@router.get("/semantic/meetings/recent", response_model=RecentMeetingsResponse)
async def recent_meetings(limit: int = 20) -> RecentMeetingsResponse:
    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be in [1, 200]")
    return RecentMeetingsResponse(
        meetings=_service.recent_meetings(get_meeting_repository(), limit=limit)
    )


@router.get(
    "/semantic/objections/by_category", response_model=SemanticGroupedResponse
)
async def objections_by_category() -> SemanticGroupedResponse:
    return SemanticGroupedResponse(
        items=_service.objections_by_category(get_meeting_repository())
    )


@router.get("/semantic/action-items/open", response_model=SemanticItemsResponse)
async def open_action_items() -> SemanticItemsResponse:
    return SemanticItemsResponse(
        items=_service.open_action_items(get_meeting_repository())
    )


@router.get(
    "/semantic/product-feedback/candidates", response_model=SemanticItemsResponse
)
async def product_feedback_candidates() -> SemanticItemsResponse:
    return SemanticItemsResponse(
        items=_service.product_feedback_candidates(get_meeting_repository())
    )


@router.get("/semantic/topics/top", response_model=SemanticItemsResponse)
async def top_topics(limit: int = 20) -> SemanticItemsResponse:
    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be in [1, 200]")
    return SemanticItemsResponse(
        items=_service.top_topics(get_meeting_repository(), limit=limit)
    )
