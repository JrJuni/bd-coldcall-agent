"""Phase 4 Stream 2 — draft_proposal coverage.

Uses a hand-rolled fake Anthropic client (see test_synthesize.py for the
same pattern). Covers the section-layout contract, footnote renumbering,
auto-appended footnote block, length warn log, and Korean output ratio.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pytest

from src.llm.draft import (
    _LENGTH_WARN_THRESHOLD_WORDS,
    _build_footnote_block,
    _collect_cited_urls,
    _renumber_footnote_refs,
    draft_proposal,
)
from src.llm.proposal_schemas import ProposalPoint
from src.search.base import Article


# ---- Fakes ----------------------------------------------------------------


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 200
        self.output_tokens = 150
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]
        self.usage = _FakeUsage()
        self.stop_reason = "end_turn"
        self.model = "claude-sonnet-4-6"


class _FakeMessages:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if not self._outputs:
            raise AssertionError("Fake client out of scripted outputs")
        return _FakeResponse(self._outputs.pop(0))


class _FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.messages = _FakeMessages(outputs)


# ---- Fixtures -------------------------------------------------------------


def _point(
    *,
    title: str = "t",
    angle: str = "growth_signal",
    rationale: str = "r",
    urls: list[str] | None = None,
) -> ProposalPoint:
    if urls is None:
        urls = ["https://ex.com/a"]
    return ProposalPoint(
        title=title,
        angle=angle,  # type: ignore[arg-type]
        rationale=rationale,
        evidence_article_urls=urls,
        tech_chunks_referenced=[],
    )


def _article(url: str, title: str = "Example") -> Article:
    return Article(
        title=title,
        url=url,
        snippet="",
        source="ex.com",
        lang="en",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tags=[],
    )


_FULL_BRIEF_EN = """## Overview

NVIDIA is riding a massive data-center demand wave.

## Key Points

- **Growth signal:** Strong earnings [^1]
- **Intro:** Meaningful opener

## Why Our Product

Our platform pairs well with this demand.

## Next Steps

- Schedule a 30-min intro call.
"""

_FULL_BRIEF_KO = """## 개요

NVIDIA 는 데이터센터 수요 파도를 타고 있습니다.

## 핵심 포인트

- **성장 신호:** 강한 실적 [^1]
- **오프닝:** 의미 있는 도입부

## 우리 제품이 맞는 이유

우리 플랫폼은 이 수요와 잘 맞습니다.

## 다음 스텝

- 30분 미팅 일정 제안.
"""


# ---- Pure helper tests ---------------------------------------------------


def test_collect_cited_urls_dedupes_preserving_order():
    p1 = _point(urls=["https://a.com/1", "https://b.com/2"])
    p2 = _point(urls=["https://b.com/2", "https://c.com/3"])
    p3 = _point(angle="intro", rationale="i", urls=[])
    assert _collect_cited_urls([p1, p2, p3]) == [
        "https://a.com/1",
        "https://b.com/2",
        "https://c.com/3",
    ]


def test_renumber_footnote_refs_starts_from_one_on_skipped_numbers():
    # Sonnet used [^3] then [^5] — should become [^1], [^2]
    url_by_footnote = {
        1: "https://a.com/1",
        2: "https://b.com/2",
        3: "https://c.com/3",
        5: "https://e.com/5",
    }
    md = "See [^3] and later [^5] plus [^3] again."
    new_md, ordered = _renumber_footnote_refs(md, url_by_footnote)
    assert new_md == "See [^1] and later [^2] plus [^1] again."
    assert ordered == ["https://c.com/3", "https://e.com/5"]


def test_renumber_drops_unknown_footnote_numbers():
    url_by_footnote = {1: "https://a.com/1"}
    md = "Known [^1] vs unknown [^99] end."
    new_md, ordered = _renumber_footnote_refs(md, url_by_footnote)
    assert "[^99]" not in new_md
    assert "[^1]" in new_md
    assert ordered == ["https://a.com/1"]


def test_build_footnote_block_empty_returns_empty_string():
    assert _build_footnote_block([]) == ""


def test_build_footnote_block_has_separator_and_numbered_entries():
    block = _build_footnote_block(["https://a.com/1", "https://b.com/2"])
    assert "---" in block
    assert "[^1]: https://a.com/1" in block
    assert "[^2]: https://b.com/2" in block


# ---- draft_proposal end-to-end ------------------------------------------


def test_draft_proposal_produces_all_four_section_headers():
    fake = _FakeClient([_FULL_BRIEF_EN])
    points = [
        _point(urls=["https://ex.com/earnings"]),
        _point(title="opener", angle="intro", rationale="i", urls=[]),
    ]
    draft, usage = draft_proposal(
        points,
        [_article("https://ex.com/earnings", "Earnings")],
        target_company="NVIDIA",
        lang="en",
        client=fake,
    )
    md = draft.markdown
    assert "## Overview" in md
    assert "## Key Points" in md
    assert "## Why Our Product" in md
    assert "## Next Steps" in md
    # Automatically appended footnote block
    assert "[^1]: https://ex.com/earnings" in md
    assert draft.language == "en"
    assert draft.target_company == "NVIDIA"
    assert len(draft.points) == 2
    # Usage surfaced for the single Sonnet call
    assert usage["input_tokens"] == 200
    assert usage["output_tokens"] == 150


def test_draft_proposal_renumbers_off_by_one_footnotes():
    # Sonnet returned a brief that starts at [^3] instead of [^1] — the
    # finalizer should rewrite inline refs to start from 1 and build the
    # definition block to match.
    brief = (
        "## Overview\nContext.\n"
        "## Key Points\n- **Growth signal:** x [^3]\n"
        "## Why Our Product\nFit.\n"
        "## Next Steps\n- Follow up.\n"
    )
    fake = _FakeClient([brief])
    points = [_point(urls=["https://ex.com/only"])]
    draft, _usage = draft_proposal(
        points,
        [_article("https://ex.com/only")],
        target_company="X",
        lang="en",
        client=fake,
    )
    assert "[^3]" not in draft.markdown
    assert "[^1]" in draft.markdown
    assert "[^1]: https://ex.com/only" in draft.markdown


def test_draft_proposal_strips_sonnet_written_footnote_block():
    # If Sonnet ignores the "no footnote block" rule, we strip it and append
    # our own based on the citation map.
    brief = (
        "## Overview\nctx.\n## Key Points\n- **Growth signal:** x [^1]\n"
        "## Why Our Product\nfit.\n## Next Steps\n- step.\n\n"
        "[^1]: https://wrong-url.example/hallucinated\n"
    )
    fake = _FakeClient([brief])
    points = [_point(urls=["https://real.com/ok"])]
    draft, _usage = draft_proposal(
        points,
        [_article("https://real.com/ok")],
        target_company="X",
        lang="en",
        client=fake,
    )
    assert "https://wrong-url.example/hallucinated" not in draft.markdown
    assert "[^1]: https://real.com/ok" in draft.markdown


def test_draft_proposal_citation_map_sent_to_sonnet():
    fake = _FakeClient([_FULL_BRIEF_EN])
    points = [_point(urls=["https://ex.com/earnings"])]
    _draft, _usage = draft_proposal(
        points,
        [_article("https://ex.com/earnings", "Earnings Q4")],
        target_company="NVIDIA",
        lang="en",
        client=fake,
    )
    user_text = fake.messages.calls[0]["messages"][0]["content"]
    # Citation map with footnote number visible to the model
    assert "<citation_map>" in user_text
    assert 'footnote="[^1]"' in user_text
    assert 'url="https://ex.com/earnings"' in user_text
    # Proposal points block passes through angle + rationale
    assert '<point index="0" angle="growth_signal">' in user_text


def test_draft_proposal_warn_log_when_over_word_threshold(caplog):
    long_body = "word " * (_LENGTH_WARN_THRESHOLD_WORDS + 50)
    brief = (
        "## Overview\n" + long_body + "\n"
        "## Key Points\n- x [^1]\n"
        "## Why Our Product\nfit.\n"
        "## Next Steps\n- step.\n"
    )
    fake = _FakeClient([brief])
    points = [_point(urls=["https://ex.com/a"])]
    with caplog.at_level(logging.WARNING, logger="src.llm.draft"):
        draft, _usage = draft_proposal(
            points,
            [_article("https://ex.com/a")],
            target_company="X",
            lang="en",
            client=fake,
        )
    assert any(
        "markdown is" in rec.message and "words" in rec.message
        for rec in caplog.records
    )
    # Still returned; no exception
    assert "## Overview" in draft.markdown


def test_draft_proposal_korean_ratio_at_least_half():
    fake = _FakeClient([_FULL_BRIEF_KO])
    points = [_point(urls=["https://ex.com/a"])]
    draft, _usage = draft_proposal(
        points,
        [_article("https://ex.com/a")],
        target_company="엔비디아",
        lang="ko",
        client=fake,
    )
    md = draft.markdown
    # Count hangul vs non-hangul alpha characters. Footnote block and URLs
    # drag the ratio down, so strip obvious non-prose spans first.
    prose = md
    hangul = sum(1 for ch in prose if "\uac00" <= ch <= "\ud7a3")
    alpha = sum(1 for ch in prose if ch.isalpha())
    assert alpha > 0
    assert hangul / alpha >= 0.5


def test_draft_proposal_empty_points_raises():
    fake = _FakeClient([])
    with pytest.raises(ValueError):
        draft_proposal(
            [],
            [],
            target_company="X",
            lang="en",
            client=fake,
        )


def test_draft_proposal_empty_response_raises():
    fake = _FakeClient(["   "])
    points = [_point(urls=["https://ex.com/a"])]
    with pytest.raises(ValueError):
        draft_proposal(
            points,
            [_article("https://ex.com/a")],
            target_company="X",
            lang="en",
            client=fake,
        )


def test_draft_proposal_ko_loads_korean_system_prompt():
    fake = _FakeClient([_FULL_BRIEF_KO])
    points = [_point(urls=["https://ex.com/a"])]
    _draft, _usage = draft_proposal(
        points,
        [_article("https://ex.com/a")],
        target_company="X",
        lang="ko",
        client=fake,
    )
    system_sent = fake.messages.calls[0]["system"]
    assert any("\uac00" <= ch <= "\ud7a3" for ch in system_sent)
