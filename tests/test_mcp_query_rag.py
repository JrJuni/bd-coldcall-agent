"""Phase 13A - smoke tests for the query_rag MCP tool.

We assert two things:
  1. The server builds and `query_rag` is registered alongside `version`.
  2. The serialization layer faithfully converts RetrievedChunk -> dict.

Real retrieval against the live ChromaDB is covered by the existing RAG
test suite; here we monkeypatch `src.rag.retriever.retrieve` so the test
never touches embeddings or the vector store.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.mcp.server import build_server
from src.mcp.tools.query_rag import _chunk_to_dict
from src.rag.types import Chunk, RetrievedChunk


def test_server_registers_query_rag() -> None:
    mcp = build_server()
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "version" in names
    assert "query_rag" in names


def test_chunk_to_dict_shape() -> None:
    chunk = Chunk(
        id="c-1",
        doc_id="d-1",
        chunk_index=0,
        text="hello",
        title="Doc",
        source_type="local",
        source_ref="/tmp/d.md",
        last_modified=datetime(2026, 5, 1, tzinfo=timezone.utc),
        mime_type="text/markdown",
        extra_metadata={"k": "v"},
    )
    rc = RetrievedChunk(chunk=chunk, similarity_score=0.81)

    out = _chunk_to_dict(rc)
    assert out["id"] == "c-1"
    assert out["text"] == "hello"
    assert out["similarity_score"] == pytest.approx(0.81)
    assert out["extra_metadata"] == {"k": "v"}
    assert out["last_modified"].startswith("2026-05-01")


def test_chunk_to_dict_handles_missing_last_modified() -> None:
    chunk = Chunk(
        id="c-2",
        doc_id="d-2",
        chunk_index=1,
        text="t",
        title="T",
        source_type="notion",
        source_ref="abcd",
        last_modified=None,
        mime_type="text/plain",
    )
    rc = RetrievedChunk(chunk=chunk, similarity_score=0.5)
    assert _chunk_to_dict(rc)["last_modified"] is None
