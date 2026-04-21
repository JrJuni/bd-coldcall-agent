"""Sentence-first chunker with sentence-level overlap.

The default unit of splitting is a sentence (or a paragraph break). Chunks
are filled greedily up to `chunk_size` characters; overlap between adjacent
chunks is expressed in whole sentences whose joined length fits within
`chunk_overlap` characters. Sentences longer than `chunk_size` fall back to
character-level hard-splitting with character-level overlap.

The intent: bge-m3 is happier when chunk boundaries respect sentences, and
retrieval results are easier to read back to the synthesis prompt without
mid-sentence clipping.
"""
from __future__ import annotations

import re

from src.rag.normalize import normalize_content
from src.rag.types import Chunk, Document


# Sentence boundary: sentence-ending punctuation followed by whitespace,
# OR a blank-line paragraph separator. Korean is handled implicitly via
# paragraph breaks and `.` / `。` when present.
_BOUNDARY_RE = re.compile(r"(?:(?<=[.!?。！？])\s+)|(?:\n\s*\n)")


def _split_units(text: str) -> list[str]:
    parts = _BOUNDARY_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _tail_for_overlap(units: list[str], max_chars: int) -> list[str]:
    if max_chars <= 0 or not units:
        return []
    tail: list[str] = []
    for u in reversed(units):
        candidate = [u] + tail
        joined_len = sum(len(x) for x in candidate) + (len(candidate) - 1)
        if joined_len > max_chars:
            break
        tail = candidate
    return tail


def _hard_split(text: str, size: int, overlap: int) -> list[str]:
    step = max(1, size - overlap)
    out: list[str] = []
    i = 0
    while i < len(text):
        piece = text[i : i + size]
        if piece:
            out.append(piece)
        if i + size >= len(text):
            break
        i += step
    return out


def chunk_document(
    doc: Document,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Return chunks for a Document. Empty content → []."""
    normalized = normalize_content(doc.content)
    if not normalized:
        return []

    units = _split_units(normalized)
    if not units:
        return []

    texts: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            texts.append(" ".join(current))
            current = []
            current_len = 0

    for unit in units:
        if len(unit) > chunk_size:
            flush()
            texts.extend(_hard_split(unit, chunk_size, chunk_overlap))
            continue

        sep_len = 1 if current else 0
        projected = current_len + sep_len + len(unit)
        if projected <= chunk_size:
            current.append(unit)
            current_len = projected
        else:
            texts.append(" ".join(current))
            tail = _tail_for_overlap(current, chunk_overlap)
            current = list(tail) + [unit]
            current_len = sum(len(u) for u in current) + max(0, len(current) - 1)

    flush()

    out: list[Chunk] = []
    for idx, text in enumerate(texts):
        text = text.strip()
        if not text:
            continue
        out.append(
            Chunk(
                id=f"{doc.id}::{idx}",
                doc_id=doc.id,
                chunk_index=idx,
                text=text,
                title=doc.title,
                source_type=doc.source_type,
                source_ref=doc.source_ref,
                last_modified=doc.last_modified,
                mime_type=doc.mime_type,
                extra_metadata=dict(doc.extra_metadata),
            )
        )
    return out
