"""Chroma-ready indexing payload builder for Meeting Intelligence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MeetingIndexChunk:
    id: str
    document_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def build_meeting_index_payload(meeting: dict[str, Any]) -> list[MeetingIndexChunk]:
    """Build deterministic summary/event chunks without touching ChromaDB.

    The actual vector upsert is intentionally left to a later phase. This
    function gives MCP/API callers a stable payload contract to test first.
    """
    meeting_id = int(meeting["id"])
    doc_id = f"meeting:{meeting_id}"
    chunks: list[MeetingIndexChunk] = [
        MeetingIndexChunk(
            id=f"{doc_id}:summary",
            document_id=doc_id,
            text=str(meeting.get("summary") or ""),
            metadata={
                "source_type": "meeting_summary",
                "meeting_id": meeting_id,
                "company_name": meeting.get("company_name"),
                "lang": meeting.get("lang"),
                "created_at": meeting.get("created_at"),
            },
        )
    ]

    for event in meeting.get("semantic_events", []) or []:
        event_id = int(event["id"])
        text = "\n".join(
            part
            for part in (
                event.get("subject"),
                event.get("summary"),
                event.get("evidence_text"),
            )
            if part
        )
        chunks.append(
            MeetingIndexChunk(
                id=f"{doc_id}:event:{event_id}",
                document_id=doc_id,
                text=text,
                metadata={
                    "source_type": "meeting_semantic_event",
                    "meeting_id": meeting_id,
                    "event_id": event_id,
                    "company_name": meeting.get("company_name"),
                    "event_type": event.get("type"),
                    "category": event.get("category"),
                    "subject": event.get("subject"),
                    "confidence": event.get("confidence"),
                    "evidence_text": event.get("evidence_text"),
                },
            )
        )
    return chunks
