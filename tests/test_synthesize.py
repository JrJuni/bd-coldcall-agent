"""Phase 4 Stream 1 — synthesize_proposal_points coverage.

Uses a hand-rolled fake Anthropic client (no network) so the Sonnet call is
deterministic. Asserts:
  - JSON / fenced / prose extraction
  - retry behavior on schema violation
  - tag-tier: low-value article emits snippet, high-value emits full body
  - cache_control: ephemeral attaches to the tech_docs block only
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from src.llm.synthesize import synthesize_proposal_points
from src.rag.types import Chunk, RetrievedChunk
from src.search.base import Article


# ---- Fakes ----------------------------------------------------------------


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 100
        self.output_tokens = 50
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 100


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


def _article(
    *,
    url: str = "https://example.com/a1",
    tags: list[str] | None = None,
    translated_body: str = "translated full body text",
    snippet: str = "short snippet",
) -> Article:
    return Article(
        title="Example Article",
        url=url,
        snippet=snippet,
        source="example.com",
        lang="en",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tags=tags or [],
        translated_body=translated_body,
        body="",
    )


def _retrieved(doc_id: str = "local:doc:overview", idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id=f"{doc_id}::{idx}",
            doc_id=doc_id,
            chunk_index=idx,
            text="Our product does X, Y, Z capabilities for semiconductor BD.",
            title="Product Overview",
            source_type="local",
            source_ref="data/company_docs/product_overview.md",
            last_modified=None,
            mime_type="text/markdown",
        ),
        similarity_score=0.87,
    )


_VALID_POINTS_JSON = (
    "["
    '{"title": "Recent earnings surge", "angle": "growth_signal",'
    ' "rationale": "NVIDIA reported strong data-center demand.",'
    ' "evidence_article_urls": ["https://example.com/a1"],'
    ' "tech_chunks_referenced": ["local:doc:overview::0"]},'
    '{"title": "Ice-breaker", "angle": "intro",'
    ' "rationale": "Opening line for the cold call.",'
    ' "evidence_article_urls": [],'
    ' "tech_chunks_referenced": []}'
    "]"
)


# ---- Happy path ----------------------------------------------------------


def test_returns_parsed_points_on_clean_json():
    fake = _FakeClient([_VALID_POINTS_JSON])
    arts = [_article(tags=["earnings"])]
    points = synthesize_proposal_points(
        arts,
        [_retrieved()],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="en",
        client=fake,
    )
    assert len(points) == 2
    assert points[0].angle == "growth_signal"
    assert points[1].angle == "intro"
    # exactly one Sonnet call on clean json
    assert len(fake.messages.calls) == 1


def test_handles_json_inside_code_fence():
    fenced = f"Here is the output:\n```json\n{_VALID_POINTS_JSON}\n```\nDone."
    fake = _FakeClient([fenced])
    points = synthesize_proposal_points(
        [_article(tags=["partnership"])],
        [_retrieved()],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="en",
        client=fake,
    )
    assert len(points) == 2


def test_handles_prose_wrapped_json():
    prose = f"Sure! Here are the points: {_VALID_POINTS_JSON} — enjoy."
    fake = _FakeClient([prose])
    points = synthesize_proposal_points(
        [_article(tags=["funding"])],
        [_retrieved()],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="en",
        client=fake,
    )
    assert len(points) == 2


# ---- Retry + failure -----------------------------------------------------


def test_retries_once_on_schema_violation_then_succeeds():
    # 1st response: invalid angle → validation error
    # 2nd response: valid JSON → success
    bad = (
        '[{"title": "t", "angle": "not_an_angle", "rationale": "r",'
        ' "evidence_article_urls": ["https://x.com"]}]'
    )
    fake = _FakeClient([bad, _VALID_POINTS_JSON])
    points = synthesize_proposal_points(
        [_article(tags=["other"])],
        [_retrieved()],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="en",
        client=fake,
    )
    assert len(points) == 2
    # Exactly two calls: initial + one retry
    assert len(fake.messages.calls) == 2
    # Second call must have a higher temperature than the first
    t1 = fake.messages.calls[0]["temperature"]
    t2 = fake.messages.calls[1]["temperature"]
    assert t2 > t1
    assert t2 == pytest.approx(t1 + 0.1, abs=1e-6)


def test_raises_valueerror_after_two_failures():
    fake = _FakeClient(["no json at all", "still not json"])
    with pytest.raises(ValueError):
        synthesize_proposal_points(
            [_article(tags=["other"])],
            [_retrieved()],
            target_company="NVIDIA",
            industry="semiconductor",
            lang="en",
            client=fake,
        )
    # No third attempt
    assert len(fake.messages.calls) == 2


# ---- Tag-tier body vs snippet in assembled prompt -----------------------


def test_high_value_article_uses_translated_body_in_prompt():
    fake = _FakeClient([_VALID_POINTS_JSON])
    art = _article(
        tags=["earnings"],
        translated_body="FULL_BODY_MARKER translated long text",
        snippet="SNIPPET_MARKER short",
    )
    synthesize_proposal_points(
        [art],
        [_retrieved()],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="en",
        client=fake,
    )
    # Capture the user content sent to Sonnet
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    assembled = "\n".join(block["text"] for block in user_content)
    assert "FULL_BODY_MARKER" in assembled
    assert "SNIPPET_MARKER" not in assembled
    # tier marker should read "high"
    assert 'tier="high"' in assembled


def test_low_value_article_uses_snippet_in_prompt():
    fake = _FakeClient([_VALID_POINTS_JSON])
    art = _article(
        tags=["leadership"],
        translated_body="FULL_BODY_MARKER translated long text",
        snippet="SNIPPET_MARKER short",
    )
    synthesize_proposal_points(
        [art],
        [_retrieved()],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="en",
        client=fake,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    assembled = "\n".join(block["text"] for block in user_content)
    assert "SNIPPET_MARKER" in assembled
    assert "FULL_BODY_MARKER" not in assembled
    assert 'tier="low"' in assembled


# ---- cache_control placement --------------------------------------------


def test_cache_control_attached_only_to_tech_docs_block():
    fake = _FakeClient([_VALID_POINTS_JSON])
    synthesize_proposal_points(
        [_article(tags=["earnings"])],
        [_retrieved()],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="en",
        client=fake,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    # First block = tech_docs (cached), remaining blocks = volatile + task (uncached)
    assert user_content[0].get("cache_control") == {"type": "ephemeral"}
    assert "<tech_docs>" in user_content[0]["text"]
    for block in user_content[1:]:
        assert "cache_control" not in block


def test_tech_chunks_referenced_ids_visible_in_prompt():
    fake = _FakeClient([_VALID_POINTS_JSON])
    rc = _retrieved(doc_id="local:doc:pricing", idx=2)
    synthesize_proposal_points(
        [_article(tags=["earnings"])],
        [rc],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="en",
        client=fake,
    )
    user_content = fake.messages.calls[0]["messages"][0]["content"]
    tech_block_text = user_content[0]["text"]
    assert 'id="local:doc:pricing::2"' in tech_block_text


# ---- Language routing ----------------------------------------------------


def test_ko_lang_loads_korean_prompt():
    fake = _FakeClient([_VALID_POINTS_JSON])
    synthesize_proposal_points(
        [_article(tags=["earnings"])],
        [_retrieved()],
        target_company="NVIDIA",
        industry="semiconductor",
        lang="ko",
        client=fake,
    )
    system_sent = fake.messages.calls[0]["system"]
    # Sanity: Korean prompt should contain at least one Korean character
    assert any("\uac00" <= ch <= "\ud7a3" for ch in system_sent)
