"""Core RAG schema — Document, Chunk, RetrievedChunk.

Locked before connector / chunker / store implementation so every downstream
module has stable field names. Common metadata (title, source_type,
source_ref, last_modified, mime_type) is promoted to explicit fields;
anything free-form lives in `extra_metadata` and is JSON-serialized into a
single Chroma metadata key (`extra_json`) by the store layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


SourceType = Literal["local", "notion"]


@dataclass
class Document:
    id: str
    source_type: SourceType
    source_ref: str
    title: str
    content: str
    last_modified: datetime | None
    mime_type: str
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    id: str
    doc_id: str
    chunk_index: int
    text: str
    title: str
    source_type: str
    source_ref: str
    last_modified: datetime | None
    mime_type: str
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    chunk: Chunk
    similarity_score: float
