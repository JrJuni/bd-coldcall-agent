"""Phase 13A - ORM smoke tests for the new rfp_answers + notion_sync_map.

Uses in-memory SQLite with Base.metadata.create_all() instead of running
the Alembic migration - migrations are validated separately via
`alembic upgrade head` against data/app.db. The point here is to lock
in the ORM <-> DB round-trip (JSON columns, defaults, UNIQUE constraint).
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from src.api.models.notion_sync_map import NotionSyncMap
from src.api.models.rfp_answer import RfpAnswer
from src.api.orm import Base, make_engine, make_session_factory


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = make_session_factory(engine)
    with SessionLocal() as s:
        yield s


def test_rfp_answer_roundtrip(session) -> None:
    rfp = RfpAnswer(
        run_id="run-1",
        question="Does the product support SOC 2?",
        retrieved_chunks=[{"id": "c1", "text": "SOC 2 Type II compliant."}],
        generated_answer="Yes, SOC 2 Type II.",
        citations=[{"chunk_id": "c1", "span": [0, 25]}],
        evidence_quality="high",
        confidence=0.9,
        model_version="claude-sonnet-4-6",
        prompt_version="rfp_answer.v1",
    )
    session.add(rfp)
    session.commit()

    row = session.query(RfpAnswer).filter_by(run_id="run-1").one()
    # UUID auto-assigned
    assert len(row.id) == 36
    # Default status
    assert row.status == "draft"
    # JSON columns survive the round-trip as Python collections
    assert row.retrieved_chunks == [{"id": "c1", "text": "SOC 2 Type II compliant."}]
    assert row.citations == [{"chunk_id": "c1", "span": [0, 25]}]
    # Timestamps populated
    assert row.created_at is not None
    assert row.updated_at is not None


def test_notion_sync_map_unique_constraint(session) -> None:
    a = NotionSyncMap(
        internal_table="rfp_answers",
        internal_id="abc",
        notion_workspace="teamspace",
        notion_database_id="db-1",
        notion_page_id="page-1",
    )
    session.add(a)
    session.commit()

    # Same (internal_table, internal_id, notion_workspace) -> rejected
    b = NotionSyncMap(
        internal_table="rfp_answers",
        internal_id="abc",
        notion_workspace="teamspace",
        notion_database_id="db-1",
        notion_page_id="page-2",
    )
    session.add(b)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # Different workspace -> allowed (the demo's publicspace pairing)
    c = NotionSyncMap(
        internal_table="rfp_answers",
        internal_id="abc",
        notion_workspace="publicspace",
        notion_database_id="db-2",
        notion_page_id="page-3",
    )
    session.add(c)
    session.commit()
    assert session.query(NotionSyncMap).filter_by(internal_id="abc").count() == 2


def test_rfp_answer_status_transitions(session) -> None:
    rfp = RfpAnswer(
        run_id="r",
        question="q",
        retrieved_chunks=[],
        generated_answer="a",
        citations=[],
    )
    session.add(rfp)
    session.commit()

    rfp.status = "reviewed"
    rfp.reviewer_notes = "looks good"
    session.commit()

    refreshed = session.query(RfpAnswer).filter_by(id=rfp.id).one()
    assert refreshed.status == "reviewed"
    assert refreshed.reviewer_notes == "looks good"
