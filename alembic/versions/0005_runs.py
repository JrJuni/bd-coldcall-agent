"""Phase 13C M9 - runs snapshot table.

Revision ID: 0005_runs
Revises: 0004_discovery_news
Create Date: 2026-05-19

Minimal impl of the hybrid choice for the RunStore persistence question:
in-flight runs stay in `src/api/store.py:RunStore` (process-local dict +
event log), terminal runs (completed / failed) get a metadata snapshot
written here so the Web UI run-history page survives a process restart.

Idempotent (same convention as 0002 / 0003 / 0004) — only creates the
table if absent. No legacy `init_db()` path holds a `runs` table, so on
existing SQLite this is a clean create; on fresh Postgres after Neon
cutover the same.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0005_runs"
down_revision: Union[str, None] = "0004_discovery_news"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "runs" in _existing_tables():
        return
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(length=128), primary_key=True),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("industry", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("failed_stage", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.String(length=32), nullable=True),
        sa.Column("ended_at", sa.String(length=32), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("errors_json", sa.Text(), nullable=True),
        sa.Column("usage_json", sa.Text(), nullable=True),
        sa.Column("article_counts_json", sa.Text(), nullable=True),
        sa.Column(
            "proposal_points_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("proposal_md", sa.Text(), nullable=True),
        sa.Column("output_dir", sa.Text(), nullable=True),
        sa.Column("claude_model", sa.String(length=64), nullable=True),
    )
    op.create_index("idx_runs_status", "runs", ["status"])
    op.create_index("idx_runs_created_at", "runs", ["created_at"])


def downgrade() -> None:
    if "runs" not in _existing_tables():
        return
    op.drop_index("idx_runs_created_at", table_name="runs")
    op.drop_index("idx_runs_status", table_name="runs")
    op.drop_table("runs")
