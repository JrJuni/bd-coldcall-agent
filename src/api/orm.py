"""Phase 13A — SQLAlchemy 2.x ORM seam.

This module is the *dual-engine* boundary between application code and the
database. New Phase 13+ tables (`rfp_answers`, `notion_sync_map`, …) are
ORM-native from day one; existing 7 tables in `src/api/db.py` will be
ported store-by-store in Phase 13B.

Engine selection is URL-driven:

    DATABASE_URL=sqlite:///data/app.db                  → SQLite (default)
    DATABASE_URL=postgresql+psycopg://...               → Postgres (Neon)

JSON columns use the SQLite-friendly pattern

    sa.JSON().with_variant(JSONB, "postgresql")

so the same migration runs on both engines without a `postgresql_only`
guard. SQLite gets stringified JSON, Postgres gets native JSONB; ORM
attribute access returns Python `dict` / `list` in either case.

For tests, call `make_engine("sqlite:///:memory:")` to get a fresh
in-memory database, then `Base.metadata.create_all(engine)` to skip
Alembic entirely.
"""
from __future__ import annotations

import logging
from typing import Generator

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


_LOGGER = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for every Phase 13+ ORM model.

    Alembic's `env.py` reads `Base.metadata` for autogenerate, so any new
    model needs to be imported at least once before `alembic revision
    --autogenerate` is invoked. The `src/api/orm.py` module imports each
    model file at the bottom for exactly this reason.
    """


def json_column(*, nullable: bool = True, default=None) -> sa.Column:
    """JSON column that uses JSONB on Postgres, plain JSON on SQLite.

    Use for any structured payload (retrieved_chunks, citations, usage,
    weights snapshot, …) that needs to round-trip through both engines.
    """
    col_type = sa.JSON().with_variant(JSONB(), "postgresql")
    return sa.Column(col_type, nullable=nullable, default=default)


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Build a SQLAlchemy engine for the given URL.

    SQLite gets `check_same_thread=False` so FastAPI worker threads can
    share a session factory the way they already do with raw sqlite3 in
    `src/api/db.py::connect`. SQLite also gets a `PRAGMA foreign_keys=ON`
    listener so the legacy `ON DELETE CASCADE` constraints (created by
    `init_db()` long before Phase 13B) keep firing — without it, deleting
    a `discovery_runs` row leaves orphaned `discovery_candidates` rows.

    Postgres uses the default pool; FKs are enforced server-side.
    """
    if database_url.startswith("sqlite"):
        engine = sa.create_engine(
            database_url,
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False},
        )

        @sa.event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _conn_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
            finally:
                cursor.close()

        return engine
    return sa.create_engine(database_url, echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


# --- Process-wide session factory cache (Phase 13B) --------------------------
#
# Stores (WorkspaceStore, …) and the RAG route helpers need a session
# factory without going through `app.state` — they may be called from
# Typer CLIs, MCP tools, or background threads. We cache one factory per
# database URL so repeated calls reuse the same engine + pool. The
# FastAPI lifespan ALSO builds its own factory on `app.state` for the
# `get_session` Depends() consumers; for SQLite these point at the same
# file (independent engines is fine), for Postgres they share the
# server-side DB.
_factory_cache: dict[str, sessionmaker[Session]] = {}


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Return a cached session factory for the given URL (or default)."""
    if database_url is None:
        from src.api.config import get_api_settings

        database_url = get_api_settings().database_url
    factory = _factory_cache.get(database_url)
    if factory is None:
        factory = make_session_factory(make_engine(database_url))
        _factory_cache[database_url] = factory
    return factory


def reset_session_factories() -> None:
    """Test hook — drop cached factories so env-driven URL changes apply.

    Pair with `reset_api_settings_cache()` and `store.reset_stores()` in
    test fixtures that re-point `API_APP_DB` or `DATABASE_URL` per test.
    """
    for factory in list(_factory_cache.values()):
        engine = factory.kw.get("bind") if hasattr(factory, "kw") else None
        if engine is not None:
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
    _factory_cache.clear()


# --- FastAPI dependency ------------------------------------------------------
#
# The session factory is stored on `app.state.db_session_factory` by the
# lifespan handler. Routes that want an ORM session declare:
#
#     from fastapi import Depends
#     from src.api.orm import get_session
#
#     @router.get(...)
#     def handler(session: Session = Depends(get_session)) -> ...:
#         ...
#
# We avoid a module-level singleton because tests need to swap the engine
# per test, and FastAPI dependency overrides only work if we go through
# `request.app.state`.
def get_session(request) -> Generator[Session, None, None]:  # type: ignore[no-untyped-def]
    """FastAPI dependency: yields a Session bound to app.state engine."""
    from fastapi import HTTPException

    factory = getattr(request.app.state, "db_session_factory", None)
    if factory is None:
        raise HTTPException(
            status_code=503,
            detail="ORM session factory not initialized (lifespan not ready).",
        )
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --- Model imports -----------------------------------------------------------
#
# Models live under `src/api/models/` and register against `Base.metadata`
# by being imported. M2 adds `rfp_answer` + `notion_sync_map`; Phase 13B
# will add the rest. Keep this section as the canonical "what tables
# exist in the ORM" list — Alembic env.py imports `src.api.orm` once and
# relies on these side-effect imports.
from src.api import models as _models  # noqa: E402,F401
