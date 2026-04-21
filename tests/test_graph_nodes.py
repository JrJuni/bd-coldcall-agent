"""Phase 5 Stream 1 — LangGraph node adapter coverage.

Each node's underlying Phase 1-4 function is monkeypatched at the
`src.graph.nodes` module level so these tests never touch the network, the
local GPU, the vector store, or Sonnet. The goal is to verify the adapters
translate state ↔ args correctly and that the `@_stage` decorator records
errors vs. marks stages completed as promised.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.graph import nodes
from src.graph.state import USAGE_KEYS, empty_usage, new_state
from src.llm.proposal_schemas import ProposalPoint
from src.rag.types import Chunk, RetrievedChunk
from src.search.base import Article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_state(tmp_path: Path, **overrides: Any) -> dict:
    s = new_state(
        company="NVIDIA",
        industry="semiconductor",
        lang="en",
        output_dir=tmp_path,
        run_id="20260421-NVIDIA",
        top_k=4,
    )
    s.update(overrides)
    return s


def _mk_article(url: str = "https://ex.com/a", *, body: str = "b", tags=None) -> Article:
    return Article(
        title="t",
        url=url,
        snippet="s",
        source="ex.com",
        lang="en",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        body=body,
        body_source="full" if body else "empty",
        translated_body=body,
        tags=tags or ["earnings"],
    )


def _mk_retrieved(doc_id: str = "local:doc:p", idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id=f"{doc_id}::{idx}",
            doc_id=doc_id,
            chunk_index=idx,
            text="capabilities blob",
            title="Product Overview",
            source_type="local",
            source_ref="data/company_docs/product_overview.md",
            last_modified=None,
            mime_type="text/markdown",
        ),
        similarity_score=0.88,
    )


# ---------------------------------------------------------------------------
# @_stage decorator
# ---------------------------------------------------------------------------


def test_stage_decorator_appends_to_stages_completed(tmp_path: Path):
    state = _seed_state(tmp_path, articles=[])

    @nodes._stage("dummy")
    def noop(_state):
        return {"articles": [_mk_article()]}

    patch = noop(state)
    assert "dummy" in patch["stages_completed"]
    assert len(patch["articles"]) == 1
    assert "failed_stage" not in patch


def test_stage_decorator_records_failed_stage_on_exception(tmp_path: Path):
    state = _seed_state(tmp_path)

    @nodes._stage("kaboom")
    def exploder(_state):
        raise RuntimeError("nope")

    patch = exploder(state)
    assert patch["failed_stage"] == "kaboom"
    errors = patch["errors"]
    assert len(errors) == 1
    assert errors[0]["stage"] == "kaboom"
    assert errors[0]["error_type"] == "RuntimeError"
    assert "nope" in errors[0]["message"]


def test_stage_decorator_preserves_previous_errors(tmp_path: Path):
    prior = {"stage": "earlier", "error_type": "X", "message": "y", "ts": "t"}
    state = _seed_state(tmp_path, errors=[prior])

    @nodes._stage("next")
    def fail(_state):
        raise ValueError("v")

    patch = fail(state)
    # Decorator must not drop the earlier error.
    assert len(patch["errors"]) == 2
    assert patch["errors"][0] == prior


# ---------------------------------------------------------------------------
# search_node
# ---------------------------------------------------------------------------


class _FakeBraveCtx:
    def __init__(self, articles):
        self._articles = articles
        self.search_calls: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def search(self, query, *, lang, days, kind="news", count=10):
        self.search_calls.append(
            dict(query=query, lang=lang, days=days, kind=kind, count=count)
        )
        return list(self._articles)


def test_search_node_en_lang_uses_monolingual_search(monkeypatch, tmp_path: Path):
    fake_client = _FakeBraveCtx([_mk_article("https://ex.com/1")])
    monkeypatch.setattr(nodes, "BraveSearch", lambda _key: fake_client)

    class _Secrets:
        brave_search_api_key = "stub"

    monkeypatch.setattr(nodes, "get_secrets", lambda: _Secrets())

    def _fail_bilingual(*a, **kw):
        raise AssertionError("bilingual should not be called for en lang")

    monkeypatch.setattr(nodes, "bilingual_news_search", _fail_bilingual)

    state = _seed_state(tmp_path, lang="en")
    patch = nodes.search_node(state)
    assert len(patch["articles"]) == 1
    assert nodes.STAGE_SEARCH in patch["stages_completed"]
    assert len(fake_client.search_calls) == 1
    assert fake_client.search_calls[0]["lang"] == "en"


def test_search_node_ko_lang_uses_bilingual(monkeypatch, tmp_path: Path):
    recorded: dict = {}

    def _mock_bilingual(client, query, *, primary_lang, **kw):
        recorded["query"] = query
        recorded["primary_lang"] = primary_lang
        return [_mk_article("https://ex.com/ko")], {"mode": "bilingual_ko"}

    monkeypatch.setattr(nodes, "bilingual_news_search", _mock_bilingual)
    monkeypatch.setattr(nodes, "BraveSearch", lambda _key: _FakeBraveCtx([]))

    class _Secrets:
        brave_search_api_key = "stub"

    monkeypatch.setattr(nodes, "get_secrets", lambda: _Secrets())

    state = _seed_state(tmp_path, lang="ko", company="엔비디아")
    patch = nodes.search_node(state)
    assert recorded["primary_lang"] == "ko"
    assert recorded["query"] == "엔비디아"
    assert len(patch["articles"]) == 1


def test_search_node_missing_api_key_records_failed_stage(monkeypatch, tmp_path: Path):
    class _Secrets:
        brave_search_api_key = ""

    monkeypatch.setattr(nodes, "get_secrets", lambda: _Secrets())
    state = _seed_state(tmp_path)
    patch = nodes.search_node(state)
    assert patch["failed_stage"] == nodes.STAGE_SEARCH
    assert patch["errors"][-1]["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# fetch / preprocess / retrieve
# ---------------------------------------------------------------------------


def test_fetch_node_delegates_to_fetch_bodies_parallel(monkeypatch, tmp_path: Path):
    seen: list[list[Article]] = []

    def _mock(articles):
        seen.append(list(articles))
        return articles

    monkeypatch.setattr(nodes, "fetch_bodies_parallel", _mock)

    state = _seed_state(tmp_path, articles=[_mk_article("https://ex.com/a")])
    patch = nodes.fetch_node(state)
    assert len(seen) == 1
    assert len(patch["articles"]) == 1
    assert nodes.STAGE_FETCH in patch["stages_completed"]


def test_fetch_node_passthrough_when_no_articles(monkeypatch, tmp_path: Path):
    called = []
    monkeypatch.setattr(
        nodes, "fetch_bodies_parallel", lambda a: called.append(a) or a
    )
    state = _seed_state(tmp_path, articles=[])
    patch = nodes.fetch_node(state)
    assert patch["articles"] == []
    assert called == []


def test_preprocess_node_delegates_and_propagates_kept(monkeypatch, tmp_path: Path):
    kept = [_mk_article("https://ex.com/kept")]

    def _mock(articles, *, target_lang=None):
        return list(kept), {
            "n_input": len(articles),
            "n_translated": 1,
            "n_tagged": 1,
            "n_output": len(kept),
        }

    monkeypatch.setattr(nodes, "preprocess_articles", _mock)

    state = _seed_state(
        tmp_path, articles=[_mk_article("https://ex.com/a"), _mk_article("https://ex.com/b")]
    )
    patch = nodes.preprocess_node(state)
    assert patch["articles"] == kept
    assert nodes.STAGE_PREPROCESS in patch["stages_completed"]


def test_retrieve_node_uses_state_top_k(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def _mock(query, *, top_k):
        captured["query"] = query
        captured["top_k"] = top_k
        return [_mk_retrieved()]

    monkeypatch.setattr(nodes, "retrieve", _mock)

    state = _seed_state(tmp_path, top_k=3)
    patch = nodes.retrieve_node(state)
    assert captured["query"] == "NVIDIA"
    assert captured["top_k"] == 3
    assert len(patch["tech_chunks"]) == 1


def test_retrieve_node_falls_back_to_settings_default(monkeypatch, tmp_path: Path):
    captured: dict = {}
    monkeypatch.setattr(
        nodes,
        "retrieve",
        lambda q, *, top_k: captured.update(top_k=top_k) or [_mk_retrieved()],
    )

    state = new_state(
        company="X",
        industry="y",
        lang="en",
        output_dir=tmp_path,
        run_id="r",
    )  # no top_k
    nodes.retrieve_node(state)
    from src.config.loader import get_settings

    assert captured["top_k"] == get_settings().llm.claude_rag_top_k


# ---------------------------------------------------------------------------
# synthesize / draft — usage merge
# ---------------------------------------------------------------------------


def test_synthesize_node_merges_usage_into_state(monkeypatch, tmp_path: Path):
    call_usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 10,
        "cache_creation_input_tokens": 20,
    }
    pp = [
        ProposalPoint(
            title="t",
            angle="growth_signal",
            rationale="r",
            evidence_article_urls=["https://ex.com/a"],
            tech_chunks_referenced=[],
        )
    ]
    monkeypatch.setattr(
        nodes,
        "synthesize_proposal_points",
        lambda *a, **kw: (pp, call_usage),
    )

    existing_usage = {k: 1 for k in USAGE_KEYS}
    state = _seed_state(
        tmp_path,
        articles=[_mk_article()],
        tech_chunks=[_mk_retrieved()],
        usage=existing_usage,
    )
    patch = nodes.synthesize_node(state)
    assert patch["proposal_points"] == pp
    # merge_usage sums existing + addition, adds 1 to each key from existing
    assert patch["usage"]["input_tokens"] == 101
    assert patch["usage"]["output_tokens"] == 51
    assert patch["usage"]["cache_read_input_tokens"] == 11
    assert patch["usage"]["cache_creation_input_tokens"] == 21


def test_draft_node_writes_proposal_md_and_merges_usage(monkeypatch, tmp_path: Path):
    from src.llm.proposal_schemas import ProposalDraft

    call_usage = {k: 2 for k in USAGE_KEYS}
    draft = ProposalDraft(
        language="en",
        target_company="NVIDIA",
        generated_at=datetime.now(timezone.utc),
        points=[
            ProposalPoint(
                title="t",
                angle="growth_signal",
                rationale="r",
                evidence_article_urls=["https://ex.com/a"],
                tech_chunks_referenced=[],
            )
        ],
        markdown="## Overview\n\nbody\n\n[^1]: https://ex.com/a",
    )
    monkeypatch.setattr(nodes, "draft_proposal", lambda *a, **kw: (draft, call_usage))

    state = _seed_state(
        tmp_path,
        articles=[_mk_article()],
        proposal_points=draft.points,
        usage=empty_usage(),
    )
    patch = nodes.draft_node(state)
    assert patch["proposal_md"] == draft.markdown
    assert patch["usage"]["input_tokens"] == 2


# ---------------------------------------------------------------------------
# persist_node
# ---------------------------------------------------------------------------


def test_persist_node_writes_proposal_and_intermediates(tmp_path: Path):
    pp = [
        ProposalPoint(
            title="t",
            angle="growth_signal",
            rationale="r",
            evidence_article_urls=["https://ex.com/a"],
            tech_chunks_referenced=[],
        )
    ]
    state = _seed_state(
        tmp_path,
        articles=[_mk_article("https://ex.com/a")],
        tech_chunks=[_mk_retrieved()],
        proposal_points=pp,
        proposal_md="## Overview\n\nhi\n",
        usage={k: 5 for k in USAGE_KEYS},
        stages_completed=[nodes.STAGE_SEARCH, nodes.STAGE_DRAFT],
    )
    patch = nodes.persist_node(state)
    # Markdown brief
    md_path = tmp_path / "proposal.md"
    assert md_path.exists()
    assert "Overview" in md_path.read_text(encoding="utf-8")
    # Intermediates
    inter = tmp_path / "intermediate"
    assert (inter / "articles_after_preprocess.json").exists()
    assert (inter / "tech_chunks.json").exists()
    assert (inter / "points.json").exists()
    # Run summary
    summary = json.loads((inter / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["company"] == "NVIDIA"
    assert summary["usage"]["input_tokens"] == 5
    assert summary["failed_stage"] is None
    assert "proposal_md_path" in summary
    assert nodes.STAGE_PERSIST in patch["stages_completed"]


def test_persist_node_tolerates_partial_state_after_failure(tmp_path: Path):
    # Only articles present — no tech_chunks, no points, no markdown.
    state = _seed_state(
        tmp_path,
        articles=[_mk_article("https://ex.com/a")],
        failed_stage=nodes.STAGE_RETRIEVE,
        errors=[{"stage": "retrieve", "error_type": "RuntimeError", "message": "x", "ts": "t"}],
    )
    nodes.persist_node(state)
    inter = tmp_path / "intermediate"
    # articles still written
    assert (inter / "articles_after_preprocess.json").exists()
    # but no proposal.md — nothing to write
    assert not (tmp_path / "proposal.md").exists()
    # summary captures failure
    summary = json.loads((inter / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["failed_stage"] == nodes.STAGE_RETRIEVE
    assert len(summary["errors"]) == 1
    assert summary["proposal_md_path"] is None


def test_persist_node_tolerates_missing_output_dir(tmp_path: Path, caplog):
    # State with no output_dir at all — e.g. orchestrator bug, or state
    # reconstructed from a checkpoint that predates output_dir.
    state = {
        "company": "NVIDIA",
        "industry": "semiconductor",
        "lang": "en",
        "stages_completed": [nodes.STAGE_SEARCH],
    }
    import logging as _logging
    with caplog.at_level(_logging.ERROR, logger="src.graph.nodes"):
        patch = nodes.persist_node(state)
    # No exception raised, stage still marked done
    assert nodes.STAGE_PERSIST in patch["stages_completed"]
    assert nodes.STAGE_SEARCH in patch["stages_completed"]
    # Nothing written to tmp_path
    assert not (tmp_path / "proposal.md").exists()
    assert not (tmp_path / "intermediate").exists()
    assert any("output_dir missing" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# route_after_stage
# ---------------------------------------------------------------------------


def test_route_after_stage_returns_persist_on_failure(tmp_path: Path):
    state = _seed_state(tmp_path, failed_stage="search")
    assert nodes.route_after_stage(state) == "persist"


def test_route_after_stage_returns_continue_on_success(tmp_path: Path):
    state = _seed_state(tmp_path)
    assert nodes.route_after_stage(state) == "continue"


# ---------------------------------------------------------------------------
# _to_jsonable
# ---------------------------------------------------------------------------


def test_to_jsonable_handles_datetime_path_dataclass_and_pydantic(tmp_path: Path):
    dt = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    art = _mk_article()
    point = ProposalPoint(
        title="t",
        angle="intro",
        rationale="r",
        evidence_article_urls=[],
        tech_chunks_referenced=[],
    )
    out = nodes._to_jsonable(
        {
            "dt": dt,
            "path": tmp_path,
            "article": art,
            "point": point,
            "nested": [{"inner": dt}],
        }
    )
    # Fully JSON-roundtrippable
    blob = json.dumps(out, ensure_ascii=False)
    parsed = json.loads(blob)
    assert parsed["dt"].startswith("2026-04-21")
    assert parsed["path"] == str(tmp_path)
    assert parsed["article"]["url"] == art.url
    assert parsed["point"]["angle"] == "intro"
