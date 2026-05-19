"""Phase 13B M7a - port workspaces + rag_summaries to Alembic.

Revision ID: 0002_workspaces_rag
Revises: 0001_rfp_tables
Create Date: 2026-05-19

Idempotent: both tables are already created by `src/api/db.py::init_db()`
on legacy databases (`CREATE TABLE IF NOT EXISTS`). We only create them
here when missing so that:

  - fresh DBs (test fixtures, CI, brand-new dev boxes) get the tables via
    Alembic and don't need init_db() at all.
  - legacy DBs (already have the tables from Phase 10/11) skip creation
    and only register the migration in alembic_version.

This is the M7a foothold for the rest of Phase 13B — once every store is
ported, init_db() can drop its raw SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0002_workspaces_rag"
down_revision: Union[str, None] = "0001_rfp_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if "workspaces" not in existing:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("slug", sa.String(length=128), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("abs_path", sa.Text(), nullable=False),
            sa.Column(
                "is_builtin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.String(length=32), nullable=False),
            sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
            sa.UniqueConstraint("abs_path", name="uq_workspaces_abs_path"),
        )
        op.create_index("idx_workspaces_slug", "workspaces", ["slug"])

    if "rag_summaries" not in existing:
        op.create_table(
            "rag_summaries",
            sa.Column(
                "ws_slug",
                sa.String(length=128),
                nullable=False,
                server_default=sa.text("'default'"),
            ),
            sa.Column("namespace", sa.String(length=128), nullable=False),
            sa.Column(
                "path",
                sa.String(length=512),
                nullable=False,
                server_default=sa.text("''"),
            ),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("lang", sa.String(length=8), nullable=False),
            sa.Column("model", sa.String(length=64), nullable=True),
            sa.Column("usage_json", sa.Text(), nullable=True),
            sa.Column(
                "chunk_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "chunks_in_namespace",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("indexed_at_at_generation", sa.String(length=32), nullable=True),
            sa.Column("generated_at", sa.String(length=32), nullable=False),
            sa.PrimaryKeyConstraint(
                "ws_slug", "namespace", "path", name="pk_rag_summaries"
            ),
        )


def downgrade() -> None:
    existing = _existing_tables()
    if "rag_summaries" in existing:
        op.drop_table("rag_summaries")
    if "workspaces" in existing:
        op.drop_index("idx_workspaces_slug", table_name="workspaces")
        op.drop_table("workspaces")
