"""Phase 7 → 13C — LangGraph checkpointer provisioning.

Held on `app.state.checkpointer` so every `execute_run` call reuses the
same underlying connection. The shape of that connection now depends on
`DATABASE_URL`:

- `sqlite://`  → SqliteSaver against `settings.checkpoint_db` (a
  separate file, because langgraph's SqliteSaver expects exclusive
  ownership of its schema).
- `postgresql+psycopg://` → PostgresSaver against the same Postgres
  database the app uses for everything else. `setup()` is called once
  on boot so the `checkpoints` / `checkpoint_writes` tables exist.

`check_same_thread=False` (SQLite) is required because anyio dispatches
BackgroundTasks onto a worker thread while other requests read from the
event loop thread.

CLI / tests keep the in-memory default (`MemorySaver`); nothing here
touches them.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any


_LOGGER = logging.getLogger(__name__)


def build_sqlite_checkpointer(db_path: Path) -> Any:
    """Return a `SqliteSaver` bound to `db_path` (parent dir auto-created)."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)


def build_postgres_checkpointer(database_url: str) -> Any:
    """Return a `PostgresSaver` bound to `database_url`.

    The SQLAlchemy `postgresql+psycopg://` prefix isn't a valid libpq URL —
    PostgresSaver passes the string through to psycopg, which wants a
    bare `postgresql://`. We strip the SQLAlchemy dialect tag if present.

    `setup()` is invoked once so the langgraph schema (`checkpoints`,
    `checkpoint_writes`, `checkpoint_blobs`) is created if absent. The
    saver keeps an internal psycopg connection — `close_checkpointer`
    handles cleanup.
    """
    from langgraph.checkpoint.postgres import PostgresSaver

    libpq_url = database_url
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if libpq_url.startswith(prefix):
            libpq_url = "postgresql://" + libpq_url[len(prefix):]
            break

    # PostgresSaver.from_conn_string returns a context manager that
    # yields a saver bound to a fresh connection. We need to enter it
    # manually here because the saver has to outlive the call (the
    # FastAPI lifespan owns it for the lifetime of the process).
    cm = PostgresSaver.from_conn_string(libpq_url)
    saver = cm.__enter__()
    # Keep a handle to the context manager on the saver so
    # `close_checkpointer` can call __exit__ later.
    saver._lifespan_cm = cm  # type: ignore[attr-defined]
    saver.setup()
    return saver


def build_checkpointer(settings: Any) -> Any:
    """Pick the right saver based on `settings.database_url` scheme.

    Postgres URLs share the app database (langgraph creates its own
    tables there). SQLite still gets a dedicated checkpoint file because
    SqliteSaver wants exclusive ownership of the schema — see the
    docstring at the top of `src/api/db.py` for the parallel reasoning.
    """
    url = (settings.database_url or "").lower()
    if url.startswith("postgresql") or url.startswith("postgres://"):
        _LOGGER.info("checkpoint: PostgresSaver (URL scheme dispatch)")
        return build_postgres_checkpointer(settings.database_url)
    _LOGGER.info("checkpoint: SqliteSaver at %s", settings.checkpoint_db)
    return build_sqlite_checkpointer(settings.checkpoint_db)


def close_checkpointer(checkpointer: Any) -> None:
    """Close the underlying connection if present. Best-effort.

    Works for both SqliteSaver (carries `conn`) and PostgresSaver (we
    stashed the context manager on `_lifespan_cm` in
    `build_postgres_checkpointer`).
    """
    cm = getattr(checkpointer, "_lifespan_cm", None)
    if cm is not None:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            _LOGGER.exception("close_checkpointer: PostgresSaver exit failed")
        return
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        _LOGGER.exception("close_checkpointer: failed to close connection")
