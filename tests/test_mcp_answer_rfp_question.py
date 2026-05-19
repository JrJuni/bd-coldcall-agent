"""Phase 13A - end-to-end test for the answer_rfp_question MCP tool.

Mocks every external dependency:
  - src.rag.retriever.retrieve -> canned chunk list
  - src.llm.rfp_answer.synthesize_rfp_answer -> canned RfpAnswerDraft
  - src.notion.writer.NotionWriter -> stub with in-memory pages.create

Confirms that one tool call lands all four artifacts:
  - status ok in the return dict
  - rfp_answers row with status='draft'
  - notion_sync_map row pointing at the stub page
  - notion_page_url populated
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.api.models.notion_sync_map import NotionSyncMap
from src.api.models.rfp_answer import RfpAnswer
from src.api.orm import Base, make_engine, make_session_factory
from src.llm.rfp_schemas import RfpAnswerDraft, RfpCitation
from src.rag.types import Chunk, RetrievedChunk


def _fake_chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk=Chunk(
                id="c-1",
                doc_id="d-1",
                chunk_index=0,
                text="The product is SOC 2 Type II compliant since 2024.",
                title="Security Posture",
                source_type="local",
                source_ref="docs/security.md",
                last_modified=datetime(2026, 4, 1, tzinfo=timezone.utc),
                mime_type="text/markdown",
            ),
            similarity_score=0.92,
        ),
    ]


def _fake_draft() -> RfpAnswerDraft:
    return RfpAnswerDraft(
        answer="Yes - the product is SOC 2 Type II compliant since 2024.",
        citations=[
            RfpCitation(
                chunk_id="d-1::0",
                quote="SOC 2 Type II compliant since 2024",
                source_ref="docs/security.md",
            )
        ],
        evidence_quality="high",
        confidence=0.92,
    )


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point the tool at a temp SQLite + create the schema."""
    db_path = tmp_path / "app.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    # Reset the cached ApiSettings so DATABASE_URL takes effect.
    from src.api import config as api_config

    api_config.reset_api_settings_cache()

    engine = make_engine(url)
    Base.metadata.create_all(engine)
    return url


@pytest.fixture
def stub_notion(monkeypatch):
    """Stub NotionWriter with an in-memory pages.create."""

    class _Pages:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.updated: list[dict] = []

        def create(self, **kwargs):
            self.created.append(kwargs)
            return {"id": f"page-{len(self.created)}"}

        def update(self, page_id, properties):
            self.updated.append({"page_id": page_id, "properties": properties})
            return {"id": page_id}

    class _Blocks:
        def __init__(self) -> None:
            self.children = MagicMock()
            self.children.append = MagicMock(return_value={})

    class _StubClient:
        def __init__(self) -> None:
            self.pages = _Pages()
            self.blocks = _Blocks()

    pages_holder: dict[str, _Pages] = {}

    # Patch the NotionWriter class so `_client` is pre-populated with our stub.
    real_init = _real_init = None
    from src.notion import writer as writer_mod

    real_init = writer_mod.NotionWriter.__init__

    def fake_init(self, token, *, workspace):
        real_init(self, token, workspace=workspace)
        client = _StubClient()
        self._client = client
        pages_holder["pages"] = client.pages

    monkeypatch.setattr(writer_mod.NotionWriter, "__init__", fake_init)
    return pages_holder


@pytest.fixture
def patched_pipeline(monkeypatch):
    """Patch retrieve + synthesize + config loader."""
    from src.llm import rfp_answer as rfp_mod
    from src.mcp.tools import answer_rfp_question as tool_mod
    from src.notion import config as notion_config

    monkeypatch.setattr(
        tool_mod._retriever,
        "retrieve",
        lambda question, **kwargs: _fake_chunks(),
    )

    def fake_synth(question, chunks, *, lang="en", client=None):
        return _fake_draft(), {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }, "claude-sonnet-4-6"

    monkeypatch.setattr(rfp_mod, "synthesize_rfp_answer", fake_synth)

    # Notion config: feed a workspace with credentials so the sync path runs.
    fake_team = notion_config.WorkspaceConfig(
        name="teamspace",
        token="stub-token",
        root_page_id="root123",
        rfp_qa_database_id="db-rfp",
    )
    fake_pub = notion_config.WorkspaceConfig(
        name="publicspace",
        token=None,
        root_page_id="",
        rfp_qa_database_id="",
    )
    fake_cfg = notion_config.NotionConfig(teamspace=fake_team, publicspace=fake_pub)
    monkeypatch.setattr(tool_mod, "load_notion_config", lambda: fake_cfg)


def test_answer_rfp_question_end_to_end(isolated_db, stub_notion, patched_pipeline):
    from src.mcp.server import build_server

    mcp = build_server()
    # The tool is exposed via FastMCP's registry; call our underlying function
    # directly. FastMCP wraps it but the wrapper just forwards args.
    from src.mcp.tools.answer_rfp_question import register  # noqa: F401
    # Grab the callable via the tool list:
    import asyncio

    tools = asyncio.run(mcp.list_tools())
    assert "answer_rfp_question" in {t.name for t in tools}

    # Invoke via the tool manager directly (skips MCP's network frame).
    result_obj = asyncio.run(
        mcp.call_tool(
            "answer_rfp_question",
            {
                "question": "Is the product SOC 2 Type II compliant?",
                "ws_slug": "default",
                "namespace": "default",
                "top_k": 5,
                "lang": "en",
            },
        )
    )
    # FastMCP returns (content, structured) where structured is the dict.
    if isinstance(result_obj, tuple) and len(result_obj) == 2:
        _content, structured = result_obj
        result = structured
    else:
        result = result_obj

    assert result["status"] == "ok"
    assert result["answer"].startswith("Yes")
    assert result["sync_status"] == "success"
    assert result["rfp_answer_id"]
    assert result["notion_page_url"].startswith("https://www.notion.so/")

    # Verify DB rows landed.
    engine = make_engine(isolated_db)
    SessionLocal = make_session_factory(engine)
    with SessionLocal() as s:
        rfp_rows = s.query(RfpAnswer).all()
        assert len(rfp_rows) == 1
        row = rfp_rows[0]
        assert row.status == "draft"
        assert row.evidence_quality == "high"
        assert row.confidence == pytest.approx(0.92)
        assert row.model_version == "claude-sonnet-4-6"
        assert row.prompt_version == "rfp_answer.v1"

        sync_rows = s.query(NotionSyncMap).all()
        assert len(sync_rows) == 1
        assert sync_rows[0].notion_workspace == "teamspace"
        assert sync_rows[0].sync_status == "success"


def test_answer_rfp_question_skips_sync_without_credentials(
    isolated_db, stub_notion, monkeypatch
):
    """Without Notion creds the LLM/DB path still runs; sync is marked skipped."""
    from src.llm import rfp_answer as rfp_mod
    from src.mcp.tools import answer_rfp_question as tool_mod
    from src.notion import config as notion_config

    monkeypatch.setattr(
        tool_mod._retriever,
        "retrieve",
        lambda question, **kwargs: _fake_chunks(),
    )
    monkeypatch.setattr(
        rfp_mod,
        "synthesize_rfp_answer",
        lambda q, c, **kw: (_fake_draft(), {k: 0 for k in (
            "input_tokens", "output_tokens",
            "cache_read_input_tokens", "cache_creation_input_tokens",
        )}, "claude-sonnet-4-6"),
    )
    empty_team = notion_config.WorkspaceConfig(
        name="teamspace", token=None, root_page_id="", rfp_qa_database_id=""
    )
    empty_pub = notion_config.WorkspaceConfig(
        name="publicspace", token=None, root_page_id="", rfp_qa_database_id=""
    )
    monkeypatch.setattr(
        tool_mod,
        "load_notion_config",
        lambda: notion_config.NotionConfig(teamspace=empty_team, publicspace=empty_pub),
    )

    from src.mcp.server import build_server
    import asyncio

    mcp = build_server()
    raw = asyncio.run(
        mcp.call_tool(
            "answer_rfp_question",
            {"question": "q?", "ws_slug": "default", "namespace": "default"},
        )
    )
    result = raw[1] if isinstance(raw, tuple) and len(raw) == 2 else raw
    assert result["status"] == "ok"
    assert result["sync_status"] == "skipped"
    assert result["sync_error"]  # truthy explanation
    # The DB row is still created.
    engine = make_engine(isolated_db)
    SessionLocal = make_session_factory(engine)
    with SessionLocal() as s:
        assert s.query(RfpAnswer).count() == 1
        assert s.query(NotionSyncMap).count() == 0
