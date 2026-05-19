"""Phase 13B M7b - port targets + interactions to Alembic.

Revision ID: 0003_targets_interactions
Revises: 0002_workspaces_rag
Create Date: 2026-05-19

Idempotent — these tables already exist on any database initialized by
`src/api/db.py::init_db()` (Phase 10 P10-1 / P10-6). We skip creation on
those legacy DBs and only create on fresh ORM-only Postgres targets.

Foreign keys present in the legacy SQLite schema are deliberately NOT
recreated here so that Phase 13B's store-by-store port doesn't have to
preserve a migration order that doesn't match the legacy creation order.
Existing legacy DBs retain their FKs (we skip creation), fresh Postgres
DBs don't — application code never depended on the constraints.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_targets_interactions"
down_revision: Union[str, None] = "0002_workspaces_rag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if "targets" not in existing:
        op.create_table(
            "targets",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("industry", sa.Text(), nullable=False),
            sa.Column("aliases_json", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "stage",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'planned'"),
            ),
            sa.Column(
                "created_from",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'manual'"),
            ),
            sa.Column("discovery_candidate_id", sa.Integer(), nullable=True),
            sa.Column("last_run_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.String(length=32), nullable=False),
        )
        op.create_index("idx_targets_stage", "targets", ["stage"])
        op.create_index(
            "idx_targets_discovery_candidate_id",
            "targets",
            ["discovery_candidate_id"],
        )

    if "interactions" not in existing:
        op.create_table(
            "interactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("company_name", sa.Text(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("occurred_at", sa.String(length=32), nullable=False),
            sa.Column("outcome", sa.Text(), nullable=True),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("contact_role", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
        )
        op.create_index(
            "idx_interactions_target_id", "interactions", ["target_id"]
        )
        op.create_index(
            "idx_interactions_company_name", "interactions", ["company_name"]
        )


def downgrade() -> None:
    existing = _existing_tables()
    if "interactions" in existing:
        op.drop_index("idx_interactions_company_name", table_name="interactions")
        op.drop_index("idx_interactions_target_id", table_name="interactions")
        op.drop_table("interactions")
    if "targets" in existing:
        op.drop_index("idx_targets_discovery_candidate_id", table_name="targets")
        op.drop_index("idx_targets_stage", table_name="targets")
        op.drop_table("targets")
