"""Pydantic schemas for Phase 4 BD proposal artifacts.

Sonnet returns JSON; `_extract_json` is defensive about prose/fence wrapping
(same tolerance strategy as `src/llm/tag.py::parse_tags`). Validation is
strict — schema misses raise so the synthesize node can retry once with a
bumped temperature before giving up.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# The five BD angles a ProposalPoint can express. Fixed ENUM; anything off-list
# is rejected at validation time so the synthesis node can't quietly degrade.
PROPOSAL_ANGLES: tuple[str, ...] = (
    "pain_point",
    "growth_signal",
    "tech_fit",
    "risk_flag",
    "intro",
)


class ProposalPoint(BaseModel):
    title: str
    angle: Literal["pain_point", "growth_signal", "tech_fit", "risk_flag", "intro"]
    rationale: str
    evidence_article_urls: list[str] = Field(default_factory=list)
    tech_chunks_referenced: list[str] = Field(default_factory=list)

    @field_validator("title", "rationale")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field must be non-empty")
        return v.strip()

    @field_validator("evidence_article_urls")
    @classmethod
    def _at_least_one_evidence(cls, v: list[str], info) -> list[str]:
        # Allow intro angle to have 0 evidence URLs; everything else needs ≥1.
        angle = info.data.get("angle") if info.data else None
        if angle != "intro" and not v:
            raise ValueError(
                "non-intro ProposalPoint requires at least one evidence URL"
            )
        return v


class ProposalDraft(BaseModel):
    language: Literal["en", "ko"]
    target_company: str
    generated_at: datetime
    points: list[ProposalPoint]
    markdown: str

    @field_validator("markdown")
    @classmethod
    def _markdown_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("markdown body must be non-empty")
        return v


# ---- JSON extraction utilities ----------------------------------------


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> Any | None:
    """Pull the first valid JSON value out of arbitrary LLM output.

    Strategy (in order of attempts):
    1. Try to parse the whole string as JSON directly
    2. Look for a ```json ...``` or ``` ...``` fenced block and parse its body
    3. Look for the widest [...] array span and parse it
    4. Look for the widest {...} object span and parse it

    Returns the parsed Python object (list/dict/scalar) or None if nothing
    decodes. Never raises — callers decide how to handle None.
    """
    if not raw or not raw.strip():
        return None

    candidates: list[str] = [raw.strip()]
    fence_match = _FENCE_RE.search(raw)
    if fence_match:
        candidates.append(fence_match.group(1).strip())
    array_match = _ARRAY_RE.search(raw)
    if array_match:
        candidates.append(array_match.group(0))
    object_match = _OBJECT_RE.search(raw)
    if object_match:
        candidates.append(object_match.group(0))

    for c in candidates:
        if not c:
            continue
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


def parse_proposal_points(raw: str) -> list[ProposalPoint]:
    """Extract + validate a ProposalPoint list from Sonnet output.

    Raises ValueError on any validation failure so the caller can retry once.
    """
    parsed = _extract_json(raw)
    if parsed is None:
        raise ValueError("no JSON found in model output")
    if isinstance(parsed, dict) and "points" in parsed:
        parsed = parsed["points"]
    if not isinstance(parsed, list):
        raise ValueError(f"expected JSON array of ProposalPoint, got {type(parsed).__name__}")
    return [ProposalPoint(**item) for item in parsed]
