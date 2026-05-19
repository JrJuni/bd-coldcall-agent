"""Phase 13A - `answer_rfp_question` MCP tool (the vertical's terminus).

One Claude Desktop call drives:
  1. RAG retrieve (src.rag.retriever.retrieve)
  2. Sonnet cited-answer synthesis (src.llm.rfp_answer.synthesize_rfp_answer)
  3. Insert into rfp_answers (status='draft')
  4. Upsert to Notion Teamspace RFP Q&A page (with sync_map row)

If any step after step 1 fails, partial state survives - the
rfp_answers row exists with sync_status='failed' so a reviewer can see
what was attempted. The MCP tool surfaces the failure in its dict
return value.

A feature flag `MCP_TOOLS_ENABLED` (default 'true') is checked at call
time so tools can be temporarily disabled without restarting Claude
Desktop.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.api.config import get_api_settings
from src.api.models.notion_sync_map import NotionSyncMap
from src.api.models.rfp_answer import RfpAnswer
from src.api.orm import make_engine, make_session_factory
from src.notion import writer as _writer_mod
from src.notion.config import load_notion_config
from src.notion.databases.rfp_qa import (
    rfp_answer_to_children,
    rfp_answer_to_properties,
)
from src.rag import retriever as _retriever
from src.rag.namespace import DEFAULT_NAMESPACE
from src.llm import rfp_answer as _rfp_answer_mod


_LOGGER = logging.getLogger(__name__)


def _tools_enabled() -> bool:
    raw = os.getenv("MCP_TOOLS_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="answer_rfp_question",
        description=(
            "End-to-end RFP / security questionnaire answering. Retrieves "
            "from the project's RAG corpus, drafts a cited answer with "
            "Sonnet, persists the row in the local DB (status='draft'), "
            "and writes a page to the BDINT_Teamspace RFP Q&A database. "
            "Returns the answer text, citations, the rfp_answer_id for "
            "follow-up tool calls, and the Notion page URL for the "
            "human reviewer."
        ),
    )
    def answer_rfp_question(
        question: str,
        ws_slug: str = "default",
        namespace: str = DEFAULT_NAMESPACE,
        top_k: int = 8,
        lang: str = "en",
    ) -> dict[str, Any]:
        if not _tools_enabled():
            return {
                "status": "disabled",
                "message": "MCP_TOOLS_ENABLED=false; refusing to call LLM/Notion.",
            }
        if not question or not question.strip():
            return {"status": "error", "message": "question must be non-empty"}
        if lang not in ("en", "ko"):
            return {"status": "error", "message": "lang must be 'en' or 'ko'"}

        run_id = str(uuid.uuid4())

        # --- Step 1: retrieve ----------------------------------------------
        try:
            chunks = _retriever.retrieve(
                question, ws_slug=ws_slug, namespace=namespace, top_k=top_k
            )
        except Exception as exc:
            _LOGGER.exception("retrieve failed")
            return {
                "status": "error",
                "stage": "retrieve",
                "message": str(exc),
                "run_id": run_id,
            }

        # --- Step 2: LLM cited-answer synthesis ----------------------------
        try:
            draft, usage, model_id = _rfp_answer_mod.synthesize_rfp_answer(
                question, chunks, lang=lang  # type: ignore[arg-type]
            )
        except Exception as exc:
            _LOGGER.exception("synthesize failed")
            return {
                "status": "error",
                "stage": "synthesize",
                "message": str(exc),
                "run_id": run_id,
                "chunk_count": len(chunks),
            }

        # --- Step 3: persist (rfp_answers, status='draft') ----------------
        api_settings = get_api_settings()
        engine = make_engine(api_settings.database_url)
        SessionLocal = make_session_factory(engine)

        rfp_id: str | None = None
        notion_page_id: str | None = None
        notion_page_url: str | None = None
        sync_status = "skipped"
        sync_error: str | None = None

        with SessionLocal() as session:
            rfp = RfpAnswer(
                run_id=run_id,
                question=question,
                retrieved_chunks=[_chunk_to_dict(rc) for rc in chunks],
                generated_answer=draft.answer,
                citations=[c.model_dump() for c in draft.citations],
                evidence_quality=draft.evidence_quality,
                confidence=draft.confidence,
                model_version=model_id,
                prompt_version=_rfp_answer_mod.PROMPT_VERSION,
                status="draft",
            )
            session.add(rfp)
            session.flush()
            rfp_id = rfp.id

            # --- Step 4: Notion sync (Teamspace only in 13A) --------------
            cfg = load_notion_config()
            team = cfg.teamspace
            if not team.has_credentials or not team.rfp_qa_database_id:
                sync_status = "skipped"
                sync_error = (
                    "teamspace credentials or rfp_qa_database_id missing - "
                    "run scripts/bootstrap_notion.py first."
                )
            else:
                try:
                    writer = _writer_mod.NotionWriter(
                        token=team.token,  # type: ignore[arg-type]
                        workspace=team.name,
                    )
                    notion_page_id, _created = writer.upsert_via_sync_map(
                        session,
                        database_id=team.rfp_qa_database_id,
                        internal_table="rfp_answers",
                        internal_id=rfp.id,
                        properties=rfp_answer_to_properties(rfp),
                        children=rfp_answer_to_children(rfp),
                    )
                    notion_page_url = _page_url(notion_page_id)
                    sync_status = "success"
                except Exception as exc:
                    _LOGGER.exception("notion sync failed")
                    sync_status = "failed"
                    sync_error = str(exc)
                    # Record the failure in sync_map so the reviewer can
                    # see it from the Web UI later.
                    existing = (
                        session.query(NotionSyncMap)
                        .filter_by(
                            internal_table="rfp_answers",
                            internal_id=rfp.id,
                            notion_workspace=team.name,
                        )
                        .one_or_none()
                    )
                    if existing is not None:
                        existing.sync_status = "failed"
                        existing.error_message = str(exc)

            session.commit()

        return {
            "status": "ok",
            "run_id": run_id,
            "rfp_answer_id": rfp_id,
            "answer": draft.answer,
            "citations": [c.model_dump() for c in draft.citations],
            "evidence_quality": draft.evidence_quality,
            "confidence": draft.confidence,
            "model_version": model_id,
            "prompt_version": _rfp_answer_mod.PROMPT_VERSION,
            "chunk_count": len(chunks),
            "usage": usage,
            "sync_status": sync_status,
            "sync_error": sync_error,
            "notion_page_id": notion_page_id,
            "notion_page_url": notion_page_url,
        }


def _chunk_to_dict(rc) -> dict[str, Any]:
    """Mirrored from src.mcp.tools.query_rag for the rfp_answers JSON column."""
    c = rc.chunk
    return {
        "id": c.id,
        "doc_id": c.doc_id,
        "chunk_index": c.chunk_index,
        "title": c.title,
        "text": c.text,
        "source_type": c.source_type,
        "source_ref": c.source_ref,
        "similarity_score": rc.similarity_score,
    }


def _page_url(page_id: str) -> str:
    # Notion page URLs drop the dashes in the id.
    return f"https://www.notion.so/{page_id.replace('-', '')}"
