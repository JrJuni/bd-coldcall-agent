"""Phase 13B M7a - ORM-level smoke tests for Workspace + RagSummary.

These tests exercise the ORM models and the new RagSummaryStore directly,
independent of the FastAPI surface. They confirm that:
  - Workspace UNIQUE constraints fire on both slug and abs_path.
  - RagSummary upsert is idempotent across calls (DELETE-then-INSERT).
  - RagSummary delete_namespace removes only the targeted (ws_slug, namespace) pair.

The TestClient-based workspace tests in `test_api_workspaces.py` already
cover the route surface end-to-end through the ORM-backed store.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from src.api.models.rag_summary import RagSummary
from src.api.models.workspace import Workspace
from src.api.orm import Base, make_engine, make_session_factory
from src.api.store import RagSummaryStore


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "m7a.db"
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def test_workspace_orm_roundtrip(session_factory):
    with session_factory() as s:
        ws = Workspace(
            slug="default",
            label="Project Docs",
            abs_path="C:/proj/data/company_docs",
            is_builtin=True,
            created_at=_ts(),
            updated_at=_ts(),
        )
        s.add(ws)
        s.commit()

    with session_factory() as s:
        row = s.scalar(sa.select(Workspace).where(Workspace.slug == "default"))
        assert row is not None
        assert row.label == "Project Docs"
        assert row.is_builtin is True


def test_workspace_unique_constraints_fire(session_factory):
    ts = _ts()
    with session_factory() as s:
        s.add(
            Workspace(
                slug="alpha",
                label="Alpha",
                abs_path="C:/a",
                is_builtin=False,
                created_at=ts,
                updated_at=ts,
            )
        )
        s.commit()

    # Duplicate slug
    with session_factory() as s:
        s.add(
            Workspace(
                slug="alpha",
                label="Another",
                abs_path="C:/b",
                is_builtin=False,
                created_at=ts,
                updated_at=ts,
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()

    # Duplicate abs_path
    with session_factory() as s:
        s.add(
            Workspace(
                slug="beta",
                label="Beta",
                abs_path="C:/a",
                is_builtin=False,
                created_at=ts,
                updated_at=ts,
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_rag_summary_store_upsert_is_idempotent(session_factory):
    store = RagSummaryStore(session_factory)
    store.upsert(
        ws_slug="default",
        namespace="ns1",
        path="",
        summary="v1",
        lang="en",
        model="claude-sonnet-4-6",
        usage={"input_tokens": 10},
        chunk_count=3,
        chunks_in_namespace=10,
        indexed_at_at_generation="2026-05-01T00:00:00+00:00",
        generated_at="2026-05-19T00:00:00+00:00",
    )
    # Overwrite: should still be a single row, with v2 values.
    store.upsert(
        ws_slug="default",
        namespace="ns1",
        path="",
        summary="v2",
        lang="en",
        model="claude-sonnet-4-6",
        usage={"input_tokens": 20},
        chunk_count=5,
        chunks_in_namespace=12,
        indexed_at_at_generation="2026-05-10T00:00:00+00:00",
        generated_at="2026-05-19T01:00:00+00:00",
    )

    row, indexed_at_at_gen = store.get("default", "ns1", "")
    assert row is not None
    assert row["summary"] == "v2"
    assert row["chunk_count"] == 5
    assert row["usage"]["input_tokens"] == 20
    assert indexed_at_at_gen == "2026-05-10T00:00:00+00:00"

    with session_factory() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(RagSummary)) == 1


def test_rag_summary_store_delete_namespace_is_scoped(session_factory):
    store = RagSummaryStore(session_factory)
    # Seed two namespaces in the same workspace + one in another workspace.
    for ns in ("keep_me", "drop_me"):
        store.upsert(
            ws_slug="default",
            namespace=ns,
            path="",
            summary=f"summary for {ns}",
            lang="en",
            model=None,
            usage=None,
            chunk_count=1,
            chunks_in_namespace=1,
            indexed_at_at_generation=None,
            generated_at=_ts(),
        )
    store.upsert(
        ws_slug="other",
        namespace="drop_me",  # same namespace name, different workspace
        path="",
        summary="other workspace",
        lang="en",
        model=None,
        usage=None,
        chunk_count=1,
        chunks_in_namespace=1,
        indexed_at_at_generation=None,
        generated_at=_ts(),
    )

    store.delete_namespace("default", "drop_me")

    keep_row, _ = store.get("default", "keep_me", "")
    drop_row, _ = store.get("default", "drop_me", "")
    other_row, _ = store.get("other", "drop_me", "")
    assert keep_row is not None and keep_row["summary"] == "summary for keep_me"
    assert drop_row is None  # dropped
    assert other_row is not None  # untouched in the other workspace
