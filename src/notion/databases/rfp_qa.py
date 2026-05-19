"""Phase 13A - Notion RFP Q&A Evaluation database (Teamspace).

This database is the working / evaluation layer that accumulates every
RFP-style question the agent answers along with the model & prompt
metadata needed for reviewer triage. Phase 13.5 will add a promotion
flow that copies status='reviewed' rows to a sibling database in the
BDINT_Publicspace.

Schema layout (Notion property names <-> rfp_answers columns):

  Question         (title)           question
  Internal ID      (rich_text)       id          <- external lookup key
  Status           (select)          status
  Evidence quality (select)          evidence_quality
  Confidence       (number)          confidence
  Model version    (rich_text)       model_version
  Prompt version   (rich_text)       prompt_version
  Run ID           (rich_text)       run_id
  Reviewer notes   (rich_text)       reviewer_notes
  Created at       (date)            created_at

The full generated answer + citations live in the page body (children
blocks) - too long for property cells, and the page body is the
human-readable surface anyway.
"""
from __future__ import annotations

from typing import Any

from src.api.models.rfp_answer import RfpAnswer


# --- schema (used by bootstrap_notion.py to create the database) ----------

DATABASE_TITLE = "RFP Q&A Evaluation"

STATUS_OPTIONS = [
    {"name": "draft", "color": "gray"},
    {"name": "reviewed", "color": "yellow"},
    {"name": "published", "color": "green"},
]

EVIDENCE_QUALITY_OPTIONS = [
    {"name": "high", "color": "green"},
    {"name": "medium", "color": "yellow"},
    {"name": "low", "color": "red"},
]


def database_schema() -> dict[str, Any]:
    """The properties payload for databases.create."""
    return {
        "Question": {"title": {}},
        "Internal ID": {"rich_text": {}},
        "Status": {"select": {"options": STATUS_OPTIONS}},
        "Evidence quality": {"select": {"options": EVIDENCE_QUALITY_OPTIONS}},
        "Confidence": {"number": {"format": "number"}},
        "Model version": {"rich_text": {}},
        "Prompt version": {"rich_text": {}},
        "Run ID": {"rich_text": {}},
        "Reviewer notes": {"rich_text": {}},
        "Created at": {"date": {}},
    }


# --- helpers --------------------------------------------------------------


def _rich_text(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    # Notion limits rich_text content to 2000 chars per block. We chunk
    # at 1900 to stay well under that for safety; longer payloads should
    # use page body blocks instead.
    text = value[:1900]
    return [{"type": "text", "text": {"content": text}}]


def _title(value: str) -> list[dict[str, Any]]:
    return _rich_text(value or "(empty question)")


def _select(value: str | None) -> dict[str, Any] | None:
    return {"name": value} if value else None


# --- ORM -> Notion properties --------------------------------------------


def rfp_answer_to_properties(answer: RfpAnswer) -> dict[str, Any]:
    return {
        "Question": {"title": _title(answer.question)},
        "Internal ID": {"rich_text": _rich_text(answer.id)},
        "Status": {"select": _select(answer.status)},
        "Evidence quality": {"select": _select(answer.evidence_quality)},
        "Confidence": {"number": answer.confidence},
        "Model version": {"rich_text": _rich_text(answer.model_version)},
        "Prompt version": {"rich_text": _rich_text(answer.prompt_version)},
        "Run ID": {"rich_text": _rich_text(answer.run_id)},
        "Reviewer notes": {"rich_text": _rich_text(answer.reviewer_notes)},
        "Created at": {
            "date": {"start": answer.created_at.isoformat()}
            if answer.created_at
            else None
        },
    }


# --- ORM -> Notion page body (children blocks) ----------------------------


def _paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def _heading2(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": _rich_text(text)},
    }


def _bulleted(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _split_paragraphs(text: str, *, chunk: int = 1900) -> list[dict[str, Any]]:
    """Notion rich_text caps at 2000 chars per block. Split long answers."""
    if not text:
        return [_paragraph("(no answer)")]
    out = []
    for i in range(0, len(text), chunk):
        out.append(_paragraph(text[i : i + chunk]))
    return out


def rfp_answer_to_children(answer: RfpAnswer) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    blocks.append(_heading2("Answer"))
    blocks.extend(_split_paragraphs(answer.generated_answer or ""))

    citations = answer.citations or []
    if citations:
        blocks.append(_heading2("Citations"))
        for cite in citations:
            label = _format_citation(cite)
            blocks.append(_bulleted(label))

    chunks = answer.retrieved_chunks or []
    if chunks:
        blocks.append(_heading2("Retrieved chunks"))
        for chunk in chunks[:20]:  # cap to avoid huge bodies
            label = _format_chunk(chunk)
            blocks.append(_bulleted(label))

    return blocks


def _format_citation(cite: dict[str, Any]) -> str:
    chunk_id = cite.get("chunk_id") or cite.get("id") or "?"
    span = cite.get("span")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        return f"{chunk_id} [{span[0]}-{span[1]}]"
    return str(chunk_id)


def _format_chunk(chunk: dict[str, Any]) -> str:
    title = chunk.get("title") or "(untitled)"
    source = chunk.get("source_ref") or ""
    text = (chunk.get("text") or "")[:200]
    if source:
        return f"{title} - {source}: {text}"
    return f"{title}: {text}"
