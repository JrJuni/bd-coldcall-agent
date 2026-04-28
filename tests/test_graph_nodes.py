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
    state = _seed_state(tmp_path, searched_articles=[])

    @nodes._stage("dummy")
    def noop(_state):
        return {"searched_articles": [_mk_article()]}

    patch = noop(state)
    assert "dummy" in patch["stages_completed"]
    assert len(patch["searched_articles"]) == 1
    assert "failed_stage" not in patch
    # current_stage advances on success so checkpoint observers can track progress
    assert patch["current_stage"] == "dummy"


def test_stage_decorator_sets_current_stage_on_failure(tmp_path: Path):
    state = _seed_state(tmp_path)

    @nodes._stage("boom_stage")
    def exploder(_state):
        raise ValueError("v")

    patch = exploder(state)
    assert patch["failed_stage"] == "boom_stage"
    assert patch["current_stage"] == "boom_stage"


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


def test_search_node_invokes_run_all_channels_with_lang(monkeypatch, tmp_path: Path):
    """Phase 8 — search_node delegates to channels.run_all_channels and
    propagates company/lang. Verifies target lang flows through, en case."""
    captured: dict = {}

    def _fake_run_all_channels(*, company, primary_lang, settings, brave_api_key, max_workers=3):
        captured["company"] = company
        captured["primary_lang"] = primary_lang
        captured["brave_api_key"] = brave_api_key
        return [_mk_article("https://ex.com/1")], {
            "by_channel": {
                "target": {"returned": 1},
                "related": {"returned": 0},
                "competitor": {"returned": 0},
            },
            "channel_errors": {},
            "total_after_xchannel_dedup": 1,
        }

    class _Secrets:
        brave_search_api_key = "stub-key"

    monkeypatch.setattr(nodes, "get_secrets", lambda: _Secrets())
    monkeypatch.setattr(nodes._channels, "run_all_channels", _fake_run_all_channels)

    state = _seed_state(tmp_path, lang="en", company="NVIDIA")
    patch = nodes.search_node(state)

    assert captured["company"] == "NVIDIA"
    assert captured["primary_lang"] == "en"
    assert captured["brave_api_key"] == "stub-key"
    assert len(patch["searched_articles"]) == 1
    assert patch["search_meta"]["total_after_xchannel_dedup"] == 1
    assert nodes.STAGE_SEARCH in patch["stages_completed"]


def test_search_node_propagates_ko_lang(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def _fake_run_all_channels(*, company, primary_lang, settings, brave_api_key, max_workers=3):
        captured["primary_lang"] = primary_lang
        captured["company"] = company
        return [_mk_article("https://ex.com/ko")], {
            "by_channel": {"target": {"returned": 1}},
            "channel_errors": {},
            "total_after_xchannel_dedup": 1,
        }

    class _Secrets:
        brave_search_api_key = "stub"

    monkeypatch.setattr(nodes, "get_secrets", lambda: _Secrets())
    monkeypatch.setattr(nodes._channels, "run_all_channels", _fake_run_all_channels)

    state = _seed_state(tmp_path, lang="ko", company="엔비디아")
    patch = nodes.search_node(state)

    assert captured["primary_lang"] == "ko"
    assert captured["company"] == "엔비디아"
    assert len(patch["searched_articles"]) == 1


def test_search_node_records_partial_channel_errors(monkeypatch, tmp_path: Path):
    """One channel raised but the others returned — node still succeeds
    and partial errors land on search_meta."""
    def _fake_run_all_channels(*, company, primary_lang, settings, brave_api_key, max_workers=3):
        return (
            [_mk_article("https://ex.com/t")],
            {
                "by_channel": {
                    "target": {"returned": 1},
                    "related": {"returned": 0, "error": "boom"},
                    "competitor": {"returned": 0},
                },
                "channel_errors": {"related": "boom"},
                "total_after_xchannel_dedup": 1,
            },
        )

    class _Secrets:
        brave_search_api_key = "stub"

    monkeypatch.setattr(nodes, "get_secrets", lambda: _Secrets())
    monkeypatch.setattr(nodes._channels, "run_all_channels", _fake_run_all_channels)

    state = _seed_state(tmp_path, lang="en")
    patch = nodes.search_node(state)
    # Node succeeds — partial-failure does NOT trip @_stage error capture.
    assert patch.get("failed_stage") is None
    assert patch["search_meta"]["channel_errors"] == {"related": "boom"}


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

    def _mock(articles, **kw):
        seen.append(list(articles))
        return articles

    monkeypatch.setattr(nodes, "fetch_bodies_parallel", _mock)

    state = _seed_state(tmp_path, searched_articles=[_mk_article("https://ex.com/a")])
    patch = nodes.fetch_node(state)
    assert len(seen) == 1
    assert len(patch["fetched_articles"]) == 1
    assert nodes.STAGE_FETCH in patch["stages_completed"]


def test_fetch_node_passthrough_when_no_articles(monkeypatch, tmp_path: Path):
    called = []
    monkeypatch.setattr(
        nodes, "fetch_bodies_parallel", lambda a, **kw: called.append(a) or a
    )
    state = _seed_state(tmp_path, searched_articles=[])
    patch = nodes.fetch_node(state)
    assert patch["fetched_articles"] == []
    assert called == []


def test_fetch_node_competitor_takes_snippet_fast_path(monkeypatch, tmp_path: Path):
    """Phase 8 — competitor channel articles skip the HTTP fetch and get
    snippet promoted to body."""
    fetched_urls: list[str] = []

    def _mock(articles, **kw):
        # Verify only non-competitor articles are passed to the real fetch.
        for a in articles:
            fetched_urls.append(a.url)
            assert a.channel != "competitor"
        return articles

    monkeypatch.setattr(nodes, "fetch_bodies_parallel", _mock)

    target_art = _mk_article("https://ex.com/target")
    competitor_art = _mk_article("https://ex.com/competitor")
    competitor_art.channel = "competitor"
    competitor_art.snippet = "competitor snippet"

    state = _seed_state(
        tmp_path, searched_articles=[target_art, competitor_art]
    )
    patch = nodes.fetch_node(state)
    assert fetched_urls == ["https://ex.com/target"]
    fetched = patch["fetched_articles"]
    assert len(fetched) == 2
    by_url = {a.url: a for a in fetched}
    assert by_url["https://ex.com/competitor"].body == "competitor snippet"
    assert by_url["https://ex.com/competitor"].body_source == "snippet"


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
        tmp_path,
        fetched_articles=[_mk_article("https://ex.com/a"), _mk_article("https://ex.com/b")],
    )
    patch = nodes.preprocess_node(state)
    assert patch["processed_articles"] == kept
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
        processed_articles=[_mk_article()],
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
        processed_articles=[_mk_article()],
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
        processed_articles=[_mk_article("https://ex.com/a")],
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
    assert summary["status"] == "completed"
    assert summary["current_stage"] is None
    assert summary["ended_at"] is not None
    assert "proposal_md_path" in summary
    assert nodes.STAGE_PERSIST in patch["stages_completed"]
    # Returned patch also exposes the finalized fields for checkpoint observers
    assert patch["status"] == "completed"
    assert patch["current_stage"] is None
    assert patch["ended_at"] is not None


def test_persist_node_tolerates_partial_state_after_failure(tmp_path: Path):
    # Retrieve failed → preprocess succeeded → processed_articles populated,
    # but no tech_chunks / points / markdown.
    state = _seed_state(
        tmp_path,
        processed_articles=[_mk_article("https://ex.com/a")],
        failed_stage=nodes.STAGE_RETRIEVE,
        errors=[{"stage": "retrieve", "error_type": "RuntimeError", "message": "x", "ts": "t"}],
    )
    nodes.persist_node(state)
    inter = tmp_path / "intermediate"
    # articles still written — processed_articles is the latest stage's output
    assert (inter / "articles_after_preprocess.json").exists()
    # No per-stage dumps because only processed_articles was present
    assert not (inter / "articles_searched.json").exists()
    assert not (inter / "articles_fetched.json").exists()
    # but no proposal.md — nothing to write
    assert not (tmp_path / "proposal.md").exists()
    # summary captures failure
    summary = json.loads((inter / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["failed_stage"] == nodes.STAGE_RETRIEVE
    assert len(summary["errors"]) == 1
    assert summary["proposal_md_path"] is None
    assert summary["status"] == "failed"
    # On failure, current_stage pins to the stage that raised
    assert summary["current_stage"] == nodes.STAGE_RETRIEVE


def test_persist_node_dumps_earlier_stage_when_fetch_failed(tmp_path: Path):
    # Fetch failed → only searched_articles survived. persist should write
    # the searched list as the canonical articles file AND a per-stage dump.
    searched = [_mk_article("https://ex.com/searched")]
    state = _seed_state(
        tmp_path,
        searched_articles=searched,
        failed_stage=nodes.STAGE_FETCH,
        errors=[{"stage": "fetch", "error_type": "Timeout", "message": "t", "ts": "t"}],
    )
    nodes.persist_node(state)
    inter = tmp_path / "intermediate"
    # Canonical file has the searched list (no later stage produced articles)
    canonical = json.loads((inter / "articles_after_preprocess.json").read_text(encoding="utf-8"))
    assert len(canonical) == 1
    assert canonical[0]["url"] == "https://ex.com/searched"
    # Per-stage dump is written for post-mortem
    assert (inter / "articles_searched.json").exists()
    # No fetched_articles in state, so no fetched dump
    assert not (inter / "articles_fetched.json").exists()


def test_persist_node_dumps_fetched_when_preprocess_failed(tmp_path: Path):
    # Preprocess failed → fetched_articles is the latest. searched_articles
    # (strict superset of earlier stage) may also be populated — still
    # dumped separately for diff analysis.
    fetched = [_mk_article("https://ex.com/fetched")]
    state = _seed_state(
        tmp_path,
        searched_articles=[_mk_article("https://ex.com/searched1"), _mk_article("https://ex.com/searched2")],
        fetched_articles=fetched,
        failed_stage=nodes.STAGE_PREPROCESS,
        errors=[{"stage": "preprocess", "error_type": "CudaOOM", "message": "oom", "ts": "t"}],
    )
    nodes.persist_node(state)
    inter = tmp_path / "intermediate"
    canonical = json.loads((inter / "articles_after_preprocess.json").read_text(encoding="utf-8"))
    assert len(canonical) == 1
    assert canonical[0]["url"] == "https://ex.com/fetched"
    # Both earlier stages dumped
    assert (inter / "articles_searched.json").exists()
    assert (inter / "articles_fetched.json").exists()


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
