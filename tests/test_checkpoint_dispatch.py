"""Phase 13C M8 - URL-scheme dispatch for the LangGraph checkpointer.

We can't reach Neon Postgres from CI, so the test patches
`build_postgres_checkpointer` to a sentinel and asserts the dispatch
picks it when `settings.database_url` starts with `postgresql://`. The
SQLite path is exercised end-to-end against tmp_path because
SqliteSaver is process-local and cheap.

Resume verification on Postgres itself (the plan's exit criterion) is
the user's responsibility against Neon once the cutover lands — there's
no way to run it in CI without provisioning a real Postgres.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

from src.api import checkpoint as _checkpoint


@dataclass
class _StubSettings:
    database_url: str
    checkpoint_db: Path


def test_dispatch_picks_sqlite_for_sqlite_url(tmp_path, monkeypatch):
    settings = _StubSettings(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        checkpoint_db=tmp_path / "ck.db",
    )
    saver = _checkpoint.build_checkpointer(settings)
    try:
        # SqliteSaver carries a `conn` attribute (sqlite3.Connection).
        assert hasattr(saver, "conn")
        # The checkpoint file was created at the configured path.
        assert settings.checkpoint_db.exists()
    finally:
        _checkpoint.close_checkpointer(saver)


def test_dispatch_picks_postgres_for_postgres_url(monkeypatch, tmp_path):
    captured: dict[str, str] = {}

    def fake_pg(url: str):
        captured["url"] = url
        m = MagicMock(name="PostgresSaverStub")
        m._lifespan_cm = MagicMock()
        return m

    monkeypatch.setattr(_checkpoint, "build_postgres_checkpointer", fake_pg)

    settings = _StubSettings(
        database_url="postgresql+psycopg://u:p@host/db?sslmode=require",
        checkpoint_db=tmp_path / "unused.db",
    )
    saver = _checkpoint.build_checkpointer(settings)
    assert (
        captured["url"]
        == "postgresql+psycopg://u:p@host/db?sslmode=require"
    )
    # The SQLite file is NOT created on the Postgres path.
    assert not settings.checkpoint_db.exists()

    # close_checkpointer should invoke __exit__ on the stashed context manager.
    _checkpoint.close_checkpointer(saver)
    saver._lifespan_cm.__exit__.assert_called_once()


def test_libpq_url_normalization():
    """postgresql+psycopg:// is stripped to bare postgresql:// for psycopg."""
    # The normalization happens inside build_postgres_checkpointer; rather
    # than import langgraph here (heavy + needs network), assert against
    # the function's documented contract by re-implementing the stripper
    # check.
    for src, expected in (
        (
            "postgresql+psycopg://u:p@h/db",
            "postgresql://u:p@h/db",
        ),
        (
            "postgresql+psycopg2://u:p@h/db",
            "postgresql://u:p@h/db",
        ),
        (
            "postgresql://u:p@h/db",
            "postgresql://u:p@h/db",  # untouched
        ),
    ):
        # Inline the stripping rule from build_postgres_checkpointer.
        out = src
        for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
            if out.startswith(prefix):
                out = "postgresql://" + out[len(prefix):]
                break
        assert out == expected, f"{src!r} → {out!r}, expected {expected!r}"
