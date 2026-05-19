"""Meeting Intelligence service functions.

The core entry point accepts a pasted summary, stores the raw meeting,
calls the structured LLM parser, validates summary-grounded evidence, and
persists semantic events/entities/relationships in one DB transaction.
"""
from __future__ import annotations

from typing import Literal

from src.llm import meeting_analysis as _meeting_analysis
from src.meeting_intelligence.repository import MeetingRepository


def analyze_meeting_summary(
    *,
    company_name: str,
    summary: str,
    repository: MeetingRepository,
    lang: Literal["en", "ko"] = "en",
    title: str | None = None,
    occurred_at: str | None = None,
) -> dict:
    """Analyze one meeting summary and persist all structured artifacts.

    No transcript or raw-audio inputs are accepted in this service layer.
    That scope guard is intentional for the Meeting Intelligence MVP.
    """
    clean_company = company_name.strip()
    clean_summary = summary.strip()
    if not clean_company:
        raise ValueError("company_name must be non-empty")
    if not clean_summary:
        raise ValueError("summary must be non-empty")

    raw_meeting = repository.create_meeting(
        company_name=clean_company,
        summary=clean_summary,
        lang=lang,
        title=title,
        occurred_at=occurred_at,
    )
    analysis, usage, model = _meeting_analysis.analyze_meeting_summary(
        clean_company,
        clean_summary,
        lang=lang,
    )
    _meeting_analysis.validate_evidence_from_summary(analysis, clean_summary)
    return repository.persist_analysis(
        raw_meeting["id"],
        analysis,
        usage=usage,
        model=model,
        prompt_version=_meeting_analysis.PROMPT_VERSION,
    )


def meeting_brief(repository: MeetingRepository, meeting_id: int) -> dict | None:
    """Return one meeting in the visualization-ready semantic shape."""
    return repository.get_meeting(meeting_id)


def recent_meetings(repository: MeetingRepository, *, limit: int = 20) -> list[dict]:
    return repository.recent_meetings(limit=limit)


def objections_by_category(repository: MeetingRepository) -> list[dict]:
    return repository.objections_by_category()


def open_action_items(repository: MeetingRepository) -> list[dict]:
    return repository.open_action_items()


def product_feedback_candidates(repository: MeetingRepository) -> list[dict]:
    return repository.product_feedback_candidates()


def top_topics(repository: MeetingRepository, *, limit: int = 20) -> list[dict]:
    return repository.top_topics(limit=limit)
