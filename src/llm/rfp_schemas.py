"""Phase 13A - schemas for the cited RFP answer artifact.

`answer_rfp_question` returns one `RfpAnswerDraft`. Parsing is strict so
the MCP tool can retry on malformed output the same way `synthesize.py`
does for ProposalPoints.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.llm.proposal_schemas import _extract_json


class RfpCitation(BaseModel):
    chunk_id: str
    quote: str | None = None  # short verbatim snippet supporting the answer
    source_ref: str | None = None  # mirrored from the chunk for human review

    @field_validator("chunk_id")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("chunk_id must be non-empty")
        return v.strip()


class RfpAnswerDraft(BaseModel):
    answer: str
    citations: list[RfpCitation] = Field(default_factory=list)
    evidence_quality: Literal["high", "medium", "low"]
    confidence: float

    @field_validator("answer")
    @classmethod
    def _answer_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("answer must be non-empty")
        return v.strip()

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return v


def parse_rfp_answer(raw: str) -> RfpAnswerDraft:
    """Extract + validate one RfpAnswerDraft from a Sonnet response.

    Tolerant of fenced blocks / prose wrapping (same `_extract_json`
    helper used elsewhere in the project). Raises ValueError on any
    schema failure so the caller can retry once.
    """
    parsed: Any = _extract_json(raw)
    if parsed is None:
        raise ValueError("no JSON found in model output")
    if not isinstance(parsed, dict):
        raise ValueError(
            f"expected JSON object for RfpAnswerDraft, got {type(parsed).__name__}"
        )
    return RfpAnswerDraft(**parsed)
