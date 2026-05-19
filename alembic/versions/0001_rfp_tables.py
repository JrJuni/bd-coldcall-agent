"""Phase 13A - rfp_answers + notion_sync_map.

Revision ID: 0001_rfp_tables
Revises:
Create Date: 2026-05-19

Two new tables that are ORM-native from day one. JSON columns use
SQLAlchemy's variant pattern so the same migration runs on SQLite
(stringified JSON) and Postgres (native JSONB).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0001_rfp_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "rfp_answers",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("retrieved_chunks", _JSON, nullable=False),
        sa.Column("generated_answer", sa.Text(), nullable=False),
        sa.Column("citations", _JSON, nullable=False),
        sa.Column("evidence_quality", sa.String(length=16), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rfp_answers_run_id", "rfp_answers", ["run_id"])
    op.create_index("ix_rfp_answers_status", "rfp_answers", ["status"])

    op.create_table(
        "notion_sync_map",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("internal_table", sa.String(length=64), nullable=False),
        sa.Column("internal_id", sa.String(length=64), nullable=False),
        sa.Column("notion_workspace", sa.String(length=32), nullable=False),
        sa.Column("notion_database_id", sa.String(length=64), nullable=False),
        sa.Column("notion_page_id", sa.String(length=64), nullable=False),
        sa.Column(
            "sync_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'success'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "internal_table",
            "internal_id",
            "notion_workspace",
            name="uq_notion_sync_map_entity_workspace",
        ),
    )
    op.create_index(
        "ix_notion_sync_map_internal_table",
        "notion_sync_map",
        ["internal_table"],
    )
    op.create_index(
        "ix_notion_sync_map_internal_id",
        "notion_sync_map",
        ["internal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notion_sync_map_internal_id", table_name="notion_sync_map")
    op.drop_index("ix_notion_sync_map_internal_table", table_name="notion_sync_map")
    op.drop_table("notion_sync_map")
    op.drop_index("ix_rfp_answers_status", table_name="rfp_answers")
    op.drop_index("ix_rfp_answers_run_id", table_name="rfp_answers")
    op.drop_table("rfp_answers")
