"""Phase 10 P10-2a — /rag/namespaces endpoints.

Discovery (P10-2b) and other tabs need the list of available RAG
namespaces (workspaces) to populate their dropdowns. P10-3 will extend
this module with folder tree / file management; for now it only enumerates
namespaces and reads each namespace's manifest for top-level counts.

Module-level access only — `from src.config import loader as _config_loader`
follows the DO NOT rule.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter

from src.api.schemas import RagNamespaceListResponse, RagNamespaceSummary
from src.config import loader as _config_loader
from src.rag.namespace import (
    DEFAULT_NAMESPACE,
    MANIFEST_FILENAME,
    list_namespaces,
    vectorstore_root_for,
)


_LOGGER = logging.getLogger(__name__)


router = APIRouter()


def _summarize(vs_root: Path, namespace: str) -> RagNamespaceSummary:
    manifest = vectorstore_root_for(vs_root, namespace) / MANIFEST_FILENAME
    summary = RagNamespaceSummary(
        name=namespace,
        is_default=(namespace == DEFAULT_NAMESPACE),
    )
    if not manifest.exists():
        return summary
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("rag namespaces: failed to read %s: %s", manifest, exc)
        return summary

    documents = raw.get("documents") or {}
    by_type: dict[str, int] = {}
    chunk_total = 0
    for entry in documents.values():
        st = entry.get("source_type") or "unknown"
        by_type[st] = by_type.get(st, 0) + 1
        chunk_total += int(entry.get("chunk_count") or 0)

    summary.document_count = len(documents)
    summary.chunk_count = chunk_total
    summary.updated_at = raw.get("updated_at")
    summary.by_source_type = by_type
    return summary


@router.get("/rag/namespaces", response_model=RagNamespaceListResponse)
async def get_rag_namespaces() -> RagNamespaceListResponse:
    settings = _config_loader.get_settings()
    vs_root = Path(settings.rag.vectorstore_path)
    names = list_namespaces(vs_root)
    # Always surface DEFAULT_NAMESPACE so the dropdown is never empty
    # even before the first index pass.
    if DEFAULT_NAMESPACE not in names:
        names.insert(0, DEFAULT_NAMESPACE)
    summaries = [_summarize(vs_root, n) for n in names]
    return RagNamespaceListResponse(
        namespaces=summaries, default=DEFAULT_NAMESPACE
    )
