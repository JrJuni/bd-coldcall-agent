"""Alembic env — Phase 13A.

URL resolution mirrors `src/api/config.py::_resolve_database_url`:
  1. `DATABASE_URL` if set
  2. fall back to `sqlite:///<API_APP_DB or data/app.db>`

This keeps `alembic upgrade head` working out of the box on a fresh dev
box (SQLite) and on a configured Neon Postgres without any config edits.
"""
from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import the ORM Base so autogenerate sees every model registered under
# `src/api/models/`. The side-effect import in `src/api/orm.py` is what
# wires the metadata together — don't reorder.
from src.api.orm import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """Same precedence as src/api/config.py::_resolve_database_url."""
    raw = os.getenv("DATABASE_URL")
    if raw and raw.strip():
        return raw.strip()
    app_db = Path(os.getenv("API_APP_DB", "data/app.db"))
    return f"sqlite:///{app_db.as_posix()}"


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # render_as_batch=True keeps ALTER TABLE on SQLite working —
        # required even when DATABASE_URL is currently Postgres, because
        # dev boxes flip between engines during Phase 13.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
