"""Phase 13B M7d - SQLite -> Postgres dump/load.

One-shot migration from the legacy `data/app.db` SQLite file to a
Postgres target (Neon free tier in the M7d plan). Reads every Phase 13
ORM-registered table via SQLAlchemy and INSERTs into the destination,
preserving primary keys.

Usage:
  ~/miniconda3/envs/bd-coldcall/python.exe scripts/migrate_sqlite_to_postgres.py \
      --source sqlite:///data/app.db \
      --target postgresql+psycopg://user:pass@host/db?sslmode=require

By default the script is a dry run that prints row counts per table.
Pass `--apply` to actually INSERT into the target.

Important:
  - The target DB must already have the schema (run `alembic upgrade head`
    against it first).
  - Auto-increment / SERIAL sequences on Postgres are bumped to MAX(id)
    after each table copy so subsequent natural inserts don't collide.
  - The migration aborts if a target table already has rows, unless you
    pass `--force-empty-target` (drops and re-inserts the table's rows).

Reversibility:
  Keep the SQLite file. If anything goes wrong on Postgres, point the
  app back at the SQLite URL and the original state is intact.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Iterable, Type

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Side-effect imports register every model on Base.metadata.
from src.api.models.discovery import DiscoveryCandidate, DiscoveryRun  # noqa: F401
from src.api.models.interaction import Interaction  # noqa: F401
from src.api.models.news_run import NewsRun  # noqa: F401
from src.api.models.notion_sync_map import NotionSyncMap  # noqa: F401
from src.api.models.rag_summary import RagSummary  # noqa: F401
from src.api.models.rfp_answer import RfpAnswer  # noqa: F401
from src.api.models.target import Target  # noqa: F401
from src.api.models.workspace import Workspace  # noqa: F401
from src.api.orm import Base, make_engine


_LOGGER = logging.getLogger("migrate_sqlite_to_postgres")


# Copy order matters when foreign keys are enforced server-side
# (Postgres, unlike our SQLite migrations, keeps real FK constraints
# only when the legacy db.py SQL is used; the Alembic-created Postgres
# tables don't carry FKs — see model docstrings). We still respect a
# topological order so a future re-introduction of FKs Just Works.
COPY_ORDER: list[Type[DeclarativeBase]] = [
    Workspace,
    RagSummary,
    DiscoveryRun,
    DiscoveryCandidate,
    Target,
    Interaction,
    NewsRun,
    RfpAnswer,
    NotionSyncMap,
]


def _row_to_kwargs(row: DeclarativeBase) -> dict:
    """Return a dict of column → value for cloning a row into a new Session."""
    state = sa.inspect(row)
    return {col.key: getattr(row, col.key) for col in state.mapper.column_attrs}


def _count(session: Session, model: Type[DeclarativeBase]) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(model)) or 0


def _bump_postgres_sequences(
    target_session: Session, model: Type[DeclarativeBase]
) -> None:
    """For tables with an `id` SERIAL, set the sequence to MAX(id).

    SQLAlchemy's `Identity()` / Postgres SERIAL keeps its own sequence
    counter; INSERTing rows with explicit IDs doesn't bump it. Without
    this, the first natural insert post-migration collides on the PK.
    """
    pk_cols = sa.inspect(model).primary_key
    if len(pk_cols) != 1:
        return
    pk = pk_cols[0]
    # Only integer auto-increment-ish columns need the sequence bump.
    py_type = getattr(pk.type, "python_type", None)
    if py_type is not int:
        return
    table_name = model.__tablename__
    col_name = pk.name
    bind = target_session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    seq_name = f"{table_name}_{col_name}_seq"
    # `pg_get_serial_sequence` resolves the actual sequence name for
    # tables created with SERIAL / IDENTITY without us guessing.
    target_session.execute(
        sa.text(
            f"SELECT setval("
            f"  pg_get_serial_sequence('{table_name}', '{col_name}'), "
            f"  COALESCE((SELECT MAX({col_name}) FROM {table_name}), 0) + 1, "
            f"  false"
            f")"
        )
    )
    _LOGGER.info("bumped sequence %s for %s.%s", seq_name, table_name, col_name)


def _copy_table(
    source_session: Session,
    target_session: Session,
    model: Type[DeclarativeBase],
    *,
    apply: bool,
    force_empty_target: bool,
) -> tuple[int, int]:
    """Copy all rows of `model` from source to target.

    Returns (rows_in_source, rows_inserted). When apply=False, only the
    source count is meaningful and `rows_inserted` is 0.
    """
    src_count = _count(source_session, model)
    tgt_count = _count(target_session, model)
    _LOGGER.info(
        "%s: source=%d, target=%d", model.__tablename__, src_count, tgt_count
    )
    if not apply:
        return src_count, 0
    if tgt_count and not force_empty_target:
        raise RuntimeError(
            f"target table {model.__tablename__} already has {tgt_count} rows; "
            f"pass --force-empty-target to drop them before copy"
        )
    if tgt_count and force_empty_target:
        _LOGGER.warning(
            "deleting %d rows from target %s (force-empty-target)",
            tgt_count,
            model.__tablename__,
        )
        target_session.execute(sa.delete(model))
        target_session.commit()

    rows: Iterable[DeclarativeBase] = source_session.scalars(sa.select(model))
    inserted = 0
    batch: list[DeclarativeBase] = []
    BATCH = 500
    for row in rows:
        target_session.add(model(**_row_to_kwargs(row)))
        inserted += 1
        if inserted % BATCH == 0:
            target_session.commit()
            _LOGGER.info(
                "%s: %d / %d copied", model.__tablename__, inserted, src_count
            )
    target_session.commit()
    _bump_postgres_sequences(target_session, model)
    return src_count, inserted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 13B M7d - copy SQLite app data to Postgres."
    )
    parser.add_argument(
        "--source", required=True, help="SQLAlchemy URL of the source DB"
    )
    parser.add_argument(
        "--target", required=True, help="SQLAlchemy URL of the destination DB"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually INSERT into target. Omit for a dry-run row-count.",
    )
    parser.add_argument(
        "--force-empty-target",
        action="store_true",
        help="Delete existing rows on the target before copying.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    src_engine = make_engine(args.source)
    tgt_engine = make_engine(args.target)
    # Ensure the destination has the schema.
    _LOGGER.info("source: %s", args.source)
    _LOGGER.info("target: %s", args.target)
    _LOGGER.info("apply mode: %s", args.apply)

    SrcSession = sessionmaker(bind=src_engine, future=True)
    TgtSession = sessionmaker(bind=tgt_engine, future=True)

    totals = {"source": 0, "inserted": 0}
    with SrcSession() as src, TgtSession() as tgt:
        # Sanity: target tables exist?
        tgt_tables = set(sa.inspect(tgt_engine).get_table_names())
        missing = [
            m.__tablename__
            for m in COPY_ORDER
            if m.__tablename__ not in tgt_tables
        ]
        if missing:
            _LOGGER.error(
                "target is missing tables (run `alembic upgrade head` first): %s",
                missing,
            )
            return 2

        for model in COPY_ORDER:
            try:
                src_n, ins_n = _copy_table(
                    src,
                    tgt,
                    model,
                    apply=args.apply,
                    force_empty_target=args.force_empty_target,
                )
            except Exception as exc:
                _LOGGER.exception(
                    "failed copying %s: %s", model.__tablename__, exc
                )
                return 3
            totals["source"] += src_n
            totals["inserted"] += ins_n

    _LOGGER.info(
        "done. source rows=%d, inserted=%d, mode=%s",
        totals["source"],
        totals["inserted"],
        "apply" if args.apply else "dry-run",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
