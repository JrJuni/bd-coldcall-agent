"""Alembic coverage for Meeting Intelligence tables.

Uses a throwaway SQLite file under data/ instead of pytest's tmp_path
because this Windows sandbox has restricted default TEMP permissions.
The migration itself is written with Postgres-compatible SQLAlchemy types
and server defaults.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from src.meeting_intelligence.models import MEETING_TABLES
from src.meeting_intelligence.repository import MeetingRepository
from src.meeting_intelligence.database import make_engine, make_session_factory
from tests.meeting_intelligence_samples import sample_analysis, sample_summary


def _db_url_and_path() -> tuple[str, Path]:
    path = Path("data") / f"test_meeting_migration_{uuid4().hex}.db"
    return f"sqlite:///{path.as_posix()}", path


def _alembic_config() -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    return cfg


def _cleanup_sqlite(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        except PermissionError:
            pass


def test_meeting_intelligence_alembic_upgrade_and_downgrade(monkeypatch):
    url, db_path = _db_url_and_path()
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic_config()
    engine = None
    try:
        command.upgrade(cfg, "head")
        engine = make_engine(url)
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
        assert set(MEETING_TABLES).issubset(tables)

        columns = {c["name"]: c for c in inspector.get_columns("meetings")}
        assert {"id", "company_name", "summary", "source_type", "created_at"} <= set(columns)
        assert columns["summary"]["nullable"] is False

        fks = inspector.get_foreign_keys("semantic_relationships")
        constrained = {tuple(fk["constrained_columns"]) for fk in fks}
        assert ("source_event_id",) in constrained
        assert ("meeting_id",) in constrained

        command.downgrade(cfg, "0005_runs")
        tables_after = set(sa.inspect(engine).get_table_names())
        assert not (set(MEETING_TABLES) & tables_after)
        assert "runs" in tables_after
    finally:
        if engine is not None:
            engine.dispose()
        _cleanup_sqlite(db_path)


def test_repository_roundtrip_on_migrated_schema(monkeypatch):
    url, db_path = _db_url_and_path()
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _alembic_config()
    engine = None
    try:
        command.upgrade(cfg, "head")
        engine = make_engine(url)
        repo = MeetingRepository(make_session_factory(engine))
        meeting = repo.create_meeting(
            company_name="Acme",
            summary=sample_summary(),
            lang="en",
        )
        detail = repo.persist_analysis(
            meeting["id"],
            sample_analysis(),
            usage={"input_tokens": 1},
            model="test-model",
            prompt_version="meeting_analysis.v1",
        )
        assert detail["summary"] == sample_summary()
        assert detail["relationships"][0]["source_event_id"]
        assert repo.objections_by_category()[0]["category"] == "integration"
    finally:
        if engine is not None:
            engine.dispose()
        _cleanup_sqlite(db_path)
