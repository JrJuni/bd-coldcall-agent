"""Phase 7 — SqliteSaver provisioning for the FastAPI backend.

Held on `app.state.checkpointer` so every `execute_run` call reuses the
same underlying SQLite connection. `check_same_thread=False` is required
because anyio dispatches BackgroundTasks onto a worker thread while
other requests read from the event loop thread — both may write
checkpoints.

CLI / tests keep the in-memory default (`MemorySaver`), so nothing about
the sqlite file touches them.
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


def close_checkpointer(checkpointer: Any) -> None:
    """Close the underlying SQLite connection if present. Best-effort."""
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        _LOGGER.exception("close_checkpointer: failed to close connection")
