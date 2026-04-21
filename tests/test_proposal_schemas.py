"""Coverage for Phase 4 proposal schemas + defensive JSON extraction."""
from __future__ import annotations

import pytest

from src.llm.proposal_schemas import (
    ProposalDraft,
    ProposalPoint,
    _extract_json,
    parse_proposal_points,
)


# ---- ProposalPoint validation -----------------------------------------


def test_proposal_point_happy_path():
    p = ProposalPoint(
        title="GPU supply crunch opens B2B opportunity",
        angle="growth_signal",
        rationale="NVIDIA's latest earnings show 120% YoY data-center revenue.",
        evidence_article_urls=["https://example.com/nvidia-q4"],
        tech_chunks_referenced=["notion:page:x::0"],
    )
    assert p.angle == "growth_signal"
    assert len(p.evidence_article_urls) == 1


def test_proposal_point_rejects_invalid_angle():
    with pytest.raises(Exception):
        ProposalPoint(
            title="bad",
            angle="not_an_angle",
            rationale="x",
            evidence_article_urls=["https://ex.com/a"],
        )


def test_proposal_point_rejects_empty_title():
    with pytest.raises(Exception):
        ProposalPoint(
            title="   ",
            angle="pain_point",
            rationale="x",
            evidence_article_urls=["https://ex.com/a"],
        )


def test_proposal_point_requires_evidence_unless_intro():
    # non-intro → needs evidence
    with pytest.raises(Exception):
        ProposalPoint(
            title="no-evidence pain",
            angle="pain_point",
            rationale="x",
            evidence_article_urls=[],
        )
    # intro → can omit evidence
    intro = ProposalPoint(
        title="Intro",
        angle="intro",
        rationale="Generic opener",
        evidence_article_urls=[],
    )
    assert intro.angle == "intro"


def test_proposal_point_strips_whitespace():
    p = ProposalPoint(
        title="  spaced  ",
        angle="tech_fit",
        rationale="  padded rationale  ",
        evidence_article_urls=["https://ex.com/a"],
    )
    assert p.title == "spaced"
    assert p.rationale == "padded rationale"


# ---- ProposalDraft validation -----------------------------------------


def test_proposal_draft_rejects_empty_markdown():
    from datetime import datetime, timezone

    p = ProposalPoint(
        title="t",
        angle="intro",
        rationale="r",
        evidence_article_urls=[],
    )
    with pytest.raises(Exception):
        ProposalDraft(
            language="en",
            target_company="NVIDIA",
            generated_at=datetime.now(timezone.utc),
            points=[p],
            markdown="   \n  ",
        )


# ---- _extract_json --------------------------------------------------


def test_extract_json_plain_array():
    assert _extract_json('[{"a": 1}]') == [{"a": 1}]


def test_extract_json_plain_object():
    assert _extract_json('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_extract_json_code_fence():
    raw = 'Here is the result:\n```json\n[{"x": 1}]\n```\nHope this helps.'
    assert _extract_json(raw) == [{"x": 1}]


def test_extract_json_unlabeled_fence():
    raw = 'Output:\n```\n{"y": 2}\n```'
    assert _extract_json(raw) == {"y": 2}


def test_extract_json_prose_before_and_after():
    raw = 'Sure! Here you go: [{"z": 3}] — that should cover it.'
    assert _extract_json(raw) == [{"z": 3}]


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("no json at all, just prose.") is None
    assert _extract_json("") is None
    assert _extract_json("   ") is None


def test_extract_json_handles_nested_structure():
    raw = '{"points": [{"title": "t", "nested": {"deep": true}}]}'
    assert _extract_json(raw) == {
        "points": [{"title": "t", "nested": {"deep": True}}]
    }


# ---- parse_proposal_points -----------------------------------------


def test_parse_proposal_points_direct_array():
    raw = (
        '[{"title": "x", "angle": "intro", "rationale": "r", '
        '"evidence_article_urls": [], "tech_chunks_referenced": []}]'
    )
    points = parse_proposal_points(raw)
    assert len(points) == 1
    assert points[0].title == "x"


def test_parse_proposal_points_wrapped_in_object():
    # Sonnet sometimes wraps the array in {"points": [...]}
    raw = (
        '{"points": [{"title": "x", "angle": "intro", '
        '"rationale": "r", "evidence_article_urls": []}]}'
    )
    points = parse_proposal_points(raw)
    assert len(points) == 1


def test_parse_proposal_points_raises_on_missing_json():
    with pytest.raises(ValueError):
        parse_proposal_points("just prose, no json")


def test_parse_proposal_points_raises_on_schema_violation():
    # missing required 'angle'
    raw = '[{"title": "x", "rationale": "r"}]'
    with pytest.raises(Exception):
        parse_proposal_points(raw)
