"""Phase 13A - `query_rag` MCP tool.

Thin wrapper around `src.rag.retriever.retrieve`. The retriever already
caches per-(ws_slug, namespace) VectorStore singletons, so repeated tool
calls in the same process are warm after the first.

The retrieval surface is intentionally exposed before the larger
`answer_rfp_question` tool - it lets Claude inspect the corpus directly,
preview chunks before answering, or refine retrieval params, without the
LLM-side cost of running the cited-answer prompt.
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

# Import the retriever module (not the symbol) so monkeypatching in
# tests can target `src.rag.retriever.retrieve` - matches the
# project-wide convention in CLAUDE.md.
from src.rag import retriever as _retriever
from src.rag.namespace import DEFAULT_NAMESPACE
from src.rag.types import RetrievedChunk


def _chunk_to_dict(rc: RetrievedChunk) -> dict[str, Any]:
    c = rc.chunk
    return {
        "id": c.id,
        "doc_id": c.doc_id,
        "chunk_index": c.chunk_index,
        "text": c.text,
        "title": c.title,
        "source_type": c.source_type,
        "source_ref": c.source_ref,
        "last_modified": c.last_modified.isoformat() if c.last_modified else None,
        "mime_type": c.mime_type,
        "extra_metadata": c.extra_metadata,
        "similarity_score": rc.similarity_score,
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="query_rag",
        description=(
            "Retrieve top-k chunks from the project's RAG corpus (ChromaDB "
            "+ bge-m3) for a given query. Returns chunks with similarity "
            "scores sorted descending. Use this to preview what the corpus "
            "contains for a topic before drafting an answer."
        ),
    )
    def query_rag(
        query: str,
        ws_slug: str = "default",
        namespace: str = DEFAULT_NAMESPACE,
        top_k: int = 5,
    ) -> dict[str, Any]:
        if not query.strip():
            return {
                "query": query,
                "chunks": [],
                "warning": "empty query",
            }
        chunks = _retriever.retrieve(
            query,
            ws_slug=ws_slug,
            namespace=namespace,
            top_k=top_k,
        )
        return {
            "query": query,
            "ws_slug": ws_slug,
            "namespace": namespace,
            "top_k": top_k,
            "chunk_count": len(chunks),
            "chunks": [_chunk_to_dict(rc) for rc in chunks],
        }
