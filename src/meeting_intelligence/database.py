"""Small database helpers for the standalone Meeting Intelligence module."""
from __future__ import annotations

import os
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


_FACTORY_CACHE: dict[str, sessionmaker[Session]] = {}


def default_database_url() -> str:
    raw = os.getenv("MEETING_INTELLIGENCE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if raw and raw.strip():
        return raw.strip()
    app_db = Path(os.getenv("API_APP_DB", "data/app.db"))
    return f"sqlite:///{app_db.as_posix()}"


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
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


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    url = database_url or default_database_url()
    factory = _FACTORY_CACHE.get(url)
    if factory is None:
        factory = make_session_factory(make_engine(url))
        _FACTORY_CACHE[url] = factory
    return factory


def reset_session_factories() -> None:
    for factory in list(_FACTORY_CACHE.values()):
        engine = factory.kw.get("bind") if hasattr(factory, "kw") else None
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
    _FACTORY_CACHE.clear()
