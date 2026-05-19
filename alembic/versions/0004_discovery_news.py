"""Phase 13B M7c - port discovery_runs / discovery_candidates / news_runs.

Revision ID: 0004_discovery_news
Revises: 0003_targets_interactions
Create Date: 2026-05-19

Idempotent — same pattern as 0002 / 0003. Legacy DBs created by
`init_db()` already hold these tables (Phase 10 P10-2 / P10-5) and we
skip creation on those. Fresh Postgres targets get the tables here.

Foreign key from `discovery_candidates.run_id` to `discovery_runs.run_id`
is not declared (legacy DBs keep theirs via earlier init_db SQL).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004_discovery_news"
down_revision: Union[str, None] = "0003_targets_interactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if "discovery_runs" not in existing:
        op.create_table(
            "discovery_runs",
            sa.Column("run_id", sa.String(length=128), primary_key=True),
            sa.Column("generated_at", sa.String(length=32), nullable=False),
            sa.Column(
                "seed_doc_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "seed_chunk_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("seed_summary", sa.Text(), nullable=True),
            sa.Column("profile", sa.Text(), nullable=True),
            sa.Column("region", sa.Text(), nullable=True),
            sa.Column("lang", sa.String(length=8), nullable=True),
            sa.Column(
                "namespace",
                sa.String(length=128),
                nullable=False,
                server_default=sa.text("'default'"),
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'queued'"),
            ),
            sa.Column("started_at", sa.String(length=32), nullable=True),
            sa.Column("ended_at", sa.String(length=32), nullable=True),
            sa.Column("failed_stage", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("source_yaml_path", sa.Text(), nullable=True),
            sa.Column("usage_json", sa.Text(), nullable=True),
            sa.Column("claude_model", sa.String(length=64), nullable=True),
            sa.Column("weights_snapshot_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
        )

    if "discovery_candidates" not in existing:
        op.create_table(
            "discovery_candidates",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("industry", sa.Text(), nullable=False),
            sa.Column("scores_json", sa.Text(), nullable=False),
            sa.Column(
                "final_score",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("tier", sa.String(length=8), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
            sa.Column("updated_at", sa.String(length=32), nullable=False),
        )
        op.create_index(
            "idx_discovery_candidates_run_id",
            "discovery_candidates",
            ["run_id"],
        )
        op.create_index(
            "idx_discovery_candidates_status",
            "discovery_candidates",
            ["status"],
        )

    if "news_runs" not in existing:
        op.create_table(
            "news_runs",
            sa.Column("task_id", sa.String(length=128), primary_key=True),
            sa.Column("generated_at", sa.String(length=32), nullable=False),
            sa.Column("seed_summary", sa.Text(), nullable=True),
            sa.Column(
                "articles_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column("sonnet_summary", sa.Text(), nullable=True),
            sa.Column("usage_json", sa.Text(), nullable=True),
            sa.Column(
                "ttl_hours",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("12"),
            ),
            sa.Column(
                "namespace",
                sa.String(length=128),
                nullable=False,
                server_default=sa.text("'default'"),
            ),
            sa.Column("seed_query", sa.Text(), nullable=True),
            sa.Column(
                "lang",
                sa.String(length=8),
                nullable=False,
                server_default=sa.text("'en'"),
            ),
            sa.Column(
                "days",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("30"),
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'queued'"),
            ),
            sa.Column(
                "article_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("started_at", sa.String(length=32), nullable=True),
            sa.Column("ended_at", sa.String(length=32), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=True),
        )
        op.create_index(
            "idx_news_runs_namespace_generated",
            "news_runs",
            ["namespace", sa.text("generated_at DESC")],
        )


def downgrade() -> None:
    existing = _existing_tables()
    if "news_runs" in existing:
        op.drop_index("idx_news_runs_namespace_generated", table_name="news_runs")
        op.drop_table("news_runs")
    if "discovery_candidates" in existing:
        op.drop_index(
            "idx_discovery_candidates_status",
            table_name="discovery_candidates",
        )
        op.drop_index(
            "idx_discovery_candidates_run_id",
            table_name="discovery_candidates",
        )
        op.drop_table("discovery_candidates")
    if "discovery_runs" in existing:
        op.drop_table("discovery_runs")
