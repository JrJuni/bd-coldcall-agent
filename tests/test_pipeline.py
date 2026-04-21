"""Phase 5 Stream 2 — `build_graph()` end-to-end invocation coverage.

Monkeypatches every node's underlying Phase 1-4 function so the graph runs
fully in-memory. Verifies:
  - happy path — stages execute in order, all artifacts land in state
  - failure path — mid-pipeline exception routes directly to persist_node
  - persist runs on both paths and writes run_summary.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.graph import nodes
from src.graph.pipeline import STAGES, build_graph
from src.graph.state import new_state, empty_usage
from src.llm.proposal_schemas import ProposalDraft, ProposalPoint
from src.rag.types import Chunk, RetrievedChunk
from src.search.base import Article


def _article(url: str) -> Article:
    return Article(
        title="t", url=url, snippet="s", source="ex.com", lang="en",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        body="b", body_source="full", translated_body="b", tags=["earnings"],
    )


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id="local:doc:p::0", doc_id="local:doc:p", chunk_index=0,
            text="x", title="T", source_type="local",
            source_ref="r", last_modified=None, mime_type="text/markdown",
        ),
        similarity_score=0.9,
    )


def _pp() -> list[ProposalPoint]:
    return [
        ProposalPoint(
            title="t", angle="growth_signal", rationale="r",
            evidence_article_urls=["https://ex.com/a"],
            tech_chunks_referenced=[],
        )
    ]


def _draft() -> ProposalDraft:
    return ProposalDraft(
        language="en",
        target_company="NVIDIA",
        generated_at=datetime.now(timezone.utc),
        points=_pp(),
        markdown="## Overview\n\nbody\n\n[^1]: https://ex.com/a",
    )


def _install_happy_fakes(monkeypatch):
    """All real node dependencies stubbed with in-memory equivalents."""
    class _Secrets:
        brave_search_api_key = "stub"

    class _FakeBrave:
        def __init__(self, _key): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def search(self, q, **kw): return [_article("https://ex.com/a")]

    monkeypatch.setattr(nodes, "get_secrets", lambda: _Secrets())
    monkeypatch.setattr(nodes, "BraveSearch", _FakeBrave)
    monkeypatch.setattr(nodes, "fetch_bodies_parallel", lambda articles: list(articles))
    monkeypatch.setattr(
        nodes, "preprocess_articles",
        lambda articles, *, target_lang=None: (
            list(articles),
            {"n_input": len(articles), "n_translated": 0, "n_tagged": len(articles), "n_output": len(articles)},
        ),
    )
    monkeypatch.setattr(nodes, "retrieve", lambda q, *, top_k: [_chunk()])

    usage = {k: 10 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    monkeypatch.setattr(
        nodes, "synthesize_proposal_points", lambda *a, **kw: (_pp(), usage)
    )
    monkeypatch.setattr(
        nodes, "draft_proposal", lambda *a, **kw: (_draft(), usage)
    )


def test_build_graph_registers_all_stages():
    graph = build_graph()
    # All 7 stage names present as node keys in the compiled graph.
    node_names = set(graph.get_graph().nodes.keys())
    for stage in STAGES:
        assert stage in node_names


def test_happy_path_produces_full_output(monkeypatch, tmp_path: Path):
    _install_happy_fakes(monkeypatch)
    graph = build_graph()

    state = new_state(
        company="NVIDIA", industry="semiconductor", lang="en",
        output_dir=tmp_path, run_id="t-happy", top_k=2,
    )
    result = graph.invoke(
        state,
        config={"configurable": {"thread_id": "t-happy"}},
    )

    assert "failed_stage" not in result or result["failed_stage"] is None
    # Every successful stage recorded (including persist).
    done = set(result["stages_completed"])
    assert done == set(STAGES)
    assert len(result["articles"]) == 1
    assert len(result["tech_chunks"]) == 1
    assert len(result["proposal_points"]) == 1
    assert "## Overview" in result["proposal_md"]
    # Usage summed from synthesize + draft (10 + 10 for each key).
    assert result["usage"]["input_tokens"] == 20
    # Disk side-effects
    assert (tmp_path / "proposal.md").exists()
    summary = json.loads((tmp_path / "intermediate" / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["failed_stage"] is None
    assert "persist" in summary["stages_completed"]
    # Status transitions running → completed, current_stage cleared
    assert result["status"] == "completed"
    assert result["current_stage"] is None
    assert result.get("ended_at") is not None
    assert summary["status"] == "completed"


def test_mid_pipeline_failure_routes_to_persist(monkeypatch, tmp_path: Path):
    _install_happy_fakes(monkeypatch)

    # Make retrieve blow up. Preprocess should still have run; synthesize/
    # draft should be skipped; persist must still execute.
    def _retrieve_boom(q, *, top_k):
        raise RuntimeError("chromadb offline")

    monkeypatch.setattr(nodes, "retrieve", _retrieve_boom)

    def _should_not_run(*a, **kw):
        raise AssertionError("downstream node ran after failure")

    monkeypatch.setattr(nodes, "synthesize_proposal_points", _should_not_run)
    monkeypatch.setattr(nodes, "draft_proposal", _should_not_run)

    graph = build_graph()
    state = new_state(
        company="NVIDIA", industry="semiconductor", lang="en",
        output_dir=tmp_path, run_id="t-fail", top_k=2,
    )
    result = graph.invoke(
        state,
        config={"configurable": {"thread_id": "t-fail"}},
    )

    assert result["failed_stage"] == nodes.STAGE_RETRIEVE
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == nodes.STAGE_RETRIEVE
    # Upstream stages ran and recorded completion; downstream stages did not.
    done = set(result["stages_completed"])
    assert nodes.STAGE_SEARCH in done
    assert nodes.STAGE_FETCH in done
    assert nodes.STAGE_PREPROCESS in done
    assert nodes.STAGE_PERSIST in done
    assert nodes.STAGE_SYNTHESIZE not in done
    assert nodes.STAGE_DRAFT not in done
    # No proposal.md because nothing was drafted
    assert not (tmp_path / "proposal.md").exists()
    # But run_summary DOES capture the failure
    summary = json.loads((tmp_path / "intermediate" / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["failed_stage"] == nodes.STAGE_RETRIEVE
    assert summary["proposal_md_path"] is None
    # Failure state pins current_stage to the raising stage
    assert summary["status"] == "failed"
    assert summary["current_stage"] == nodes.STAGE_RETRIEVE
    assert result["status"] == "failed"


def test_search_failure_still_produces_run_summary(monkeypatch, tmp_path: Path):
    _install_happy_fakes(monkeypatch)

    class _Secrets:
        brave_search_api_key = ""  # triggers RuntimeError in search_node

    monkeypatch.setattr(nodes, "get_secrets", lambda: _Secrets())

    def _should_not_run(*a, **kw):
        raise AssertionError("downstream node ran after failure")

    monkeypatch.setattr(nodes, "fetch_bodies_parallel", _should_not_run)
    monkeypatch.setattr(nodes, "preprocess_articles", _should_not_run)

    graph = build_graph()
    state = new_state(
        company="X", industry="y", lang="en",
        output_dir=tmp_path, run_id="t-search-fail",
    )
    result = graph.invoke(
        state,
        config={"configurable": {"thread_id": "t-search-fail"}},
    )
    assert result["failed_stage"] == nodes.STAGE_SEARCH
    summary = json.loads((tmp_path / "intermediate" / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["failed_stage"] == nodes.STAGE_SEARCH
    # Only search (failed) and persist should appear in stages_completed
    assert nodes.STAGE_PERSIST in result["stages_completed"]
