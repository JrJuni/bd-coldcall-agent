"""Phase 10 — SQLite app DB (separate from langgraph checkpoints).

Holds 8-tab UI state that needs to outlive process restarts:
  - discovery_runs / discovery_candidates  (Discovery 탭)
  - targets                                (Targets 탭)
  - interactions                           (사업 기록 탭)
  - news_runs                              (Daily News 캐시)

Why a separate DB instead of reusing `data/checkpoints.db`?
  langgraph's SqliteSaver expects exclusive ownership of its schema and
  rewrites tables on upgrade. Mixing app-level tables there is fragile —
  see `docs/lesson-learned.md` for the parallel "don't mix config and
  secrets" principle.

`connect()` returns a context-managed sqlite3 connection with
`row_factory=sqlite3.Row` and `PRAGMA foreign_keys=ON`. It commits on
clean exit and rolls back on exception.

`init_db()` is idempotent — `CREATE TABLE IF NOT EXISTS` for every
table, safe to call from `app.py::lifespan` on every boot.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator



_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS discovery_runs (
    run_id TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    seed_doc_count INTEGER NOT NULL DEFAULT 0,
    seed_chunk_count INTEGER NOT NULL DEFAULT 0,
    seed_summary TEXT,
    product TEXT,
    region TEXT,
    lang TEXT,
    namespace TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'queued',
    started_at TEXT,
    ended_at TEXT,
    failed_stage TEXT,
    error_message TEXT,
    source_yaml_path TEXT,
    usage_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    scores_json TEXT NOT NULL,
    final_score REAL NOT NULL DEFAULT 0,
    tier TEXT NOT NULL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES discovery_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    aliases_json TEXT,
    notes TEXT,
    stage TEXT NOT NULL DEFAULT 'planned',
    created_from TEXT NOT NULL DEFAULT 'manual',
    discovery_candidate_id INTEGER,
    last_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (discovery_candidate_id) REFERENCES discovery_candidates(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER,
    company_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    outcome TEXT,
    raw_text TEXT,
    contact_role TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (target_id) REFERENCES targets(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS news_runs (
    task_id TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    seed_summary TEXT,
    articles_json TEXT NOT NULL DEFAULT '[]',
    sonnet_summary TEXT,
    usage_json TEXT,
    ttl_hours INTEGER NOT NULL DEFAULT 12,
    namespace TEXT NOT NULL DEFAULT 'default',
    seed_query TEXT,
    lang TEXT NOT NULL DEFAULT 'en',
    days INTEGER NOT NULL DEFAULT 30,
    status TEXT NOT NULL DEFAULT 'queued',
    article_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    ended_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_news_runs_namespace_generated
    ON news_runs(namespace, generated_at DESC);

CREATE TABLE IF NOT EXISTS rag_summaries (
    namespace TEXT NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    lang TEXT NOT NULL,
    model TEXT,
    usage_json TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    chunks_in_namespace INTEGER NOT NULL DEFAULT 0,
    -- Folder's last_indexed_at AT THE MOMENT this summary was generated;
    -- compared against the current value to detect stale summaries.
    indexed_at_at_generation TEXT,
    generated_at TEXT NOT NULL,
    PRIMARY KEY (namespace, path)
);

CREATE INDEX IF NOT EXISTS idx_discovery_candidates_run_id
    ON discovery_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_status
    ON discovery_candidates(status);
CREATE INDEX IF NOT EXISTS idx_targets_stage ON targets(stage);
CREATE INDEX IF NOT EXISTS idx_interactions_target_id
    ON interactions(target_id);
CREATE INDEX IF NOT EXISTS idx_interactions_company_name
    ON interactions(company_name);
"""


SCHEMA_TABLES = (
    "discovery_runs",
    "discovery_candidates",
    "targets",
    "interactions",
    "news_runs",
    "rag_summaries",
)


@contextmanager
def connect(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open a connection with Row factory + FK enforcement, auto-commit on exit."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_DISCOVERY_RUNS_NEW_COLUMNS = (
    # Phase 10 P10-2b — added after P10-0 shipped, so existing app.db files
    # need ALTER TABLE backfill. Each tuple = (column, sql_decl_for_alter).
    ("namespace", "TEXT NOT NULL DEFAULT 'default'"),
    ("status", "TEXT NOT NULL DEFAULT 'queued'"),
    ("started_at", "TEXT"),
    ("ended_at", "TEXT"),
    ("failed_stage", "TEXT"),
    ("error_message", "TEXT"),
)


def _migrate_discovery_runs(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(discovery_runs)").fetchall()
    }
    for col, decl in _DISCOVERY_RUNS_NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE discovery_runs ADD COLUMN {col} {decl}")


_NEWS_RUNS_NEW_COLUMNS = (
    # Phase 10 P10-5 — added after P10-0 shipped. Same pattern as
    # discovery_runs: ALTER TABLE backfill for app.db files predating P10-5.
    ("namespace", "TEXT NOT NULL DEFAULT 'default'"),
    ("seed_query", "TEXT"),
    ("lang", "TEXT NOT NULL DEFAULT 'en'"),
    ("days", "INTEGER NOT NULL DEFAULT 30"),
    ("status", "TEXT NOT NULL DEFAULT 'queued'"),
    ("article_count", "INTEGER NOT NULL DEFAULT 0"),
    ("started_at", "TEXT"),
    ("ended_at", "TEXT"),
    ("error_message", "TEXT"),
    ("created_at", "TEXT"),
)


def _migrate_news_runs(conn: sqlite3.Connection) -> None:
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(news_runs)").fetchall()
    }
    for col, decl in _NEWS_RUNS_NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE news_runs ADD COLUMN {col} {decl}")
    # Index addition is idempotent via CREATE INDEX IF NOT EXISTS.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_news_runs_namespace_generated "
        "ON news_runs(namespace, generated_at DESC)"
    )


def init_db(db_path: Path | str) -> None:
    """Create tables idempotently. Safe to call on every boot.

    Also backfills new columns added after P10-0 shipped — `discovery_runs`
    gained namespace/status/started_at/ended_at/failed_stage/error_message
    in P10-2b. CREATE TABLE IF NOT EXISTS doesn't update existing schemas,
    so we ALTER TABLE for any missing column.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        _migrate_discovery_runs(conn)
        _migrate_news_runs(conn)
