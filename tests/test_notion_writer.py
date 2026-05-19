"""Phase 13A - Notion writer + sync_map upsert tests.

Mocks notion-client at the boundary so the tests never touch the
network. Confirms two invariants:

  1. First upsert -> client.pages.create called once, sync_map row
     persisted, `(page_id, created=True)` returned.
  2. Repeat upsert with the same internal_id -> client.pages.create NOT
     called again, client.pages.update called once, sync_map row
     unchanged in count, `(page_id, created=False)` returned.

Plus tests for the RFP Q&A mapper to ensure ORM -> Notion property
serialization is stable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.api.models.notion_sync_map import NotionSyncMap
from src.api.models.rfp_answer import RfpAnswer
from src.api.orm import Base, make_engine, make_session_factory
from src.notion.databases.rfp_qa import (
    rfp_answer_to_children,
    rfp_answer_to_properties,
)
from src.notion.writer import NotionWriter


# --- Notion client stub -----------------------------------------------------


class _StubPages:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return {"id": f"page-{len(self.create_calls)}"}

    def update(self, page_id, properties):
        self.update_calls.append({"page_id": page_id, "properties": properties})
        return {"id": page_id}


class _StubBlocksChildren:
    def __init__(self) -> None:
        self.append_calls: list[dict] = []

    def append(self, block_id, children):
        self.append_calls.append({"block_id": block_id, "children": children})
        return {}


class _StubBlocks:
    def __init__(self) -> None:
        self.children = _StubBlocksChildren()


class _StubClient:
    def __init__(self) -> None:
        self.pages = _StubPages()
        self.blocks = _StubBlocks()


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = make_session_factory(engine)
    with SessionLocal() as s:
        yield s


@pytest.fixture
def writer():
    w = NotionWriter(token="stub-token", workspace="teamspace")
    w._client = _StubClient()
    return w


# --- upsert behavior --------------------------------------------------------


def test_upsert_creates_then_updates(session, writer) -> None:
    page_id_first, created_first = writer.upsert_via_sync_map(
        session,
        database_id="db-rfp",
        internal_table="rfp_answers",
        internal_id="abc",
        properties={"Question": {"title": []}},
    )
    session.commit()

    assert created_first is True
    assert page_id_first == "page-1"
    assert len(writer.client.pages.create_calls) == 1
    assert len(writer.client.pages.update_calls) == 0
    assert session.query(NotionSyncMap).count() == 1

    page_id_second, created_second = writer.upsert_via_sync_map(
        session,
        database_id="db-rfp",
        internal_table="rfp_answers",
        internal_id="abc",
        properties={"Question": {"title": [{"text": {"content": "updated"}}]}},
    )
    session.commit()

    assert created_second is False
    assert page_id_second == "page-1"  # same page reused
    assert len(writer.client.pages.create_calls) == 1  # not called again
    assert len(writer.client.pages.update_calls) == 1
    assert session.query(NotionSyncMap).count() == 1  # no duplicates


def test_upsert_different_workspaces_create_separate_rows(session) -> None:
    team = NotionWriter(token="t", workspace="teamspace")
    team._client = _StubClient()
    pub = NotionWriter(token="p", workspace="publicspace")
    pub._client = _StubClient()

    team.upsert_via_sync_map(
        session,
        database_id="db-team",
        internal_table="rfp_answers",
        internal_id="abc",
        properties={},
    )
    pub.upsert_via_sync_map(
        session,
        database_id="db-pub",
        internal_table="rfp_answers",
        internal_id="abc",
        properties={},
    )
    session.commit()

    rows = session.query(NotionSyncMap).filter_by(internal_id="abc").all()
    assert {r.notion_workspace for r in rows} == {"teamspace", "publicspace"}


# --- mapper -----------------------------------------------------------------


def test_rfp_answer_to_properties_shape() -> None:
    rfp = RfpAnswer(
        id="11111111-2222-3333-4444-555555555555",
        run_id="r-1",
        question="Does the product support SOC 2?",
        retrieved_chunks=[],
        generated_answer="Yes.",
        citations=[],
        evidence_quality="high",
        confidence=0.9,
        model_version="claude-sonnet-4-6",
        prompt_version="rfp_answer.v1",
        status="draft",
        created_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )

    props = rfp_answer_to_properties(rfp)
    assert props["Status"]["select"] == {"name": "draft"}
    assert props["Evidence quality"]["select"] == {"name": "high"}
    assert props["Confidence"]["number"] == pytest.approx(0.9)
    assert props["Internal ID"]["rich_text"][0]["text"]["content"] == rfp.id
    assert props["Question"]["title"][0]["text"]["content"].startswith(
        "Does the product"
    )
    # Created at populated when datetime present
    assert props["Created at"]["date"]["start"].startswith("2026-05-19")


def test_rfp_answer_to_children_includes_answer_and_citations() -> None:
    rfp = RfpAnswer(
        id="x",
        run_id="r",
        question="q",
        retrieved_chunks=[{"id": "c1", "title": "Doc", "source_ref": "/p.md", "text": "hi"}],
        generated_answer="The answer body.",
        citations=[{"chunk_id": "c1", "span": [0, 5]}],
        evidence_quality="medium",
        confidence=0.5,
        status="draft",
    )

    blocks = rfp_answer_to_children(rfp)
    types = [b["type"] for b in blocks]
    # Headings present
    headings = [b for b in blocks if b["type"] == "heading_2"]
    heading_texts = [
        h["heading_2"]["rich_text"][0]["text"]["content"] for h in headings
    ]
    assert "Answer" in heading_texts
    assert "Citations" in heading_texts
    assert "Retrieved chunks" in heading_texts
    # At least one paragraph carries the answer body
    paragraphs = [b for b in blocks if b["type"] == "paragraph"]
    paragraph_text = "".join(
        p["paragraph"]["rich_text"][0]["text"]["content"] for p in paragraphs
    )
    assert "The answer body." in paragraph_text


def test_rfp_answer_to_properties_handles_long_question() -> None:
    """Notion rich_text caps at 2000 chars; our helper truncates at 1900."""
    long_q = "Q? " * 2000
    rfp = RfpAnswer(
        run_id="r",
        question=long_q,
        retrieved_chunks=[],
        generated_answer="a",
        citations=[],
        status="draft",
    )
    props = rfp_answer_to_properties(rfp)
    content = props["Question"]["title"][0]["text"]["content"]
    assert len(content) <= 1900
