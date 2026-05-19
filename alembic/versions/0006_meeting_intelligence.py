"""Phase M - Meeting Intelligence semantic BI tables.

Revision ID: 0006_meeting_intelligence
Revises: 0005_runs
Create Date: 2026-05-19

Creates the summary-first Meeting Intelligence persistence layer.

Dual-engine: every column type (sa.Text / sa.String(N) / sa.Integer /
sa.Float / sa.Boolean), every server_default (sa.text("'en'"),
sa.true(), sa.text("0")), the autoincrement integer PKs (SQLite
ROWID-aliased, Postgres SERIAL), the FK CASCADE, and the unique
constraint `uq_semantic_entities_name_type` all render identically on
SQLite and Postgres. The migration is idempotent via inspector
(`_existing_tables()`) so re-runs against a partly-migrated DB are
safe.

`metadata_json` columns are sa.Text — JSON is stored as a serialized
string for parity with 0005_runs.*_json. If a Postgres deployment
later wants JSONB semantics, that's a separate ALTER migration; the
data round-trips as-is during the SQLite -> Postgres cutover (see
scripts/migrate_sqlite_to_postgres.py).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0006_meeting_intelligence"
down_revision: Union[str, None] = "0005_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if index_name in existing:
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    existing = _existing_tables()

    if "meetings" not in existing:
        op.create_table(
            "meetings",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("company_name", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("occurred_at", sa.String(length=64), nullable=True),
            sa.Column(
                "lang",
                sa.String(length=8),
                nullable=False,
                server_default=sa.text("'en'"),
            ),
            sa.Column(
                "source_type",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'summary'"),
            ),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("created_at", sa.String(length=32), nullable=False),
        )
        op.create_index("idx_meetings_company_name", "meetings", ["company_name"])

    if "meeting_participants" not in existing:
        op.create_table(
            "meeting_participants",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("meeting_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=True),
            sa.Column("company", sa.Text(), nullable=True),
            sa.Column(
                "is_customer",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "idx_meeting_participants_meeting_id",
            "meeting_participants",
            ["meeting_id"],
        )

    if "meeting_insights" not in existing:
        op.create_table(
            "meeting_insights",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("meeting_id", sa.Integer(), nullable=False, unique=True),
            sa.Column("meeting_summary", sa.Text(), nullable=False),
            sa.Column("suggested_stage", sa.Text(), nullable=True),
            sa.Column("follow_up_draft", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "idx_meeting_insights_meeting_id",
            "meeting_insights",
            ["meeting_id"],
        )

    if "meeting_action_items" not in existing:
        op.create_table(
            "meeting_action_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("meeting_id", sa.Integer(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("owner", sa.Text(), nullable=True),
            sa.Column("due_date", sa.String(length=64), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'open'"),
            ),
            sa.Column("evidence_text", sa.Text(), nullable=True),
            sa.Column(
                "confidence",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "idx_meeting_action_items_meeting_id",
            "meeting_action_items",
            ["meeting_id"],
        )
        op.create_index(
            "idx_meeting_action_items_status",
            "meeting_action_items",
            ["status"],
        )

    if "meeting_semantic_events" not in existing:
        op.create_table(
            "meeting_semantic_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("meeting_id", sa.Integer(), nullable=False),
            sa.Column("type", sa.String(length=64), nullable=False),
            sa.Column("category", sa.Text(), nullable=True),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("evidence_text", sa.Text(), nullable=False),
            sa.Column("severity", sa.String(length=32), nullable=True),
            sa.Column(
                "confidence",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "idx_meeting_semantic_events_meeting_id",
            "meeting_semantic_events",
            ["meeting_id"],
        )
        op.create_index(
            "idx_meeting_semantic_events_type",
            "meeting_semantic_events",
            ["type"],
        )
        op.create_index(
            "idx_meeting_semantic_events_category",
            "meeting_semantic_events",
            ["category"],
        )

    if "semantic_entities" not in existing:
        op.create_table(
            "semantic_entities",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("normalized_name", sa.Text(), nullable=False),
            sa.Column("entity_type", sa.String(length=64), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.Column("updated_at", sa.String(length=32), nullable=False),
            sa.UniqueConstraint(
                "normalized_name",
                "entity_type",
                name="uq_semantic_entities_name_type",
            ),
        )
        op.create_index(
            "idx_semantic_entities_normalized_name",
            "semantic_entities",
            ["normalized_name"],
        )
        op.create_index(
            "idx_semantic_entities_type",
            "semantic_entities",
            ["entity_type"],
        )

    if "semantic_entity_mentions" not in existing:
        op.create_table(
            "semantic_entity_mentions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("meeting_id", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.Integer(), nullable=True),
            sa.Column("evidence_text", sa.Text(), nullable=True),
            sa.Column(
                "confidence",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(
                ["entity_id"], ["semantic_entities.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["event_id"], ["meeting_semantic_events.id"], ondelete="CASCADE"
            ),
        )
        op.create_index(
            "idx_semantic_mentions_meeting_id",
            "semantic_entity_mentions",
            ["meeting_id"],
        )
        op.create_index(
            "idx_semantic_mentions_event_id",
            "semantic_entity_mentions",
            ["event_id"],
        )

    if "semantic_relationships" not in existing:
        op.create_table(
            "semantic_relationships",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("source_entity_id", sa.Integer(), nullable=False),
            sa.Column("relation_type", sa.String(length=80), nullable=False),
            sa.Column("target_entity_id", sa.Integer(), nullable=False),
            sa.Column("source_event_id", sa.Integer(), nullable=False),
            sa.Column("meeting_id", sa.Integer(), nullable=False),
            sa.Column("evidence_text", sa.Text(), nullable=False),
            sa.Column(
                "confidence",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(
                ["source_entity_id"], ["semantic_entities.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["target_entity_id"], ["semantic_entities.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["source_event_id"], ["meeting_semantic_events.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "idx_semantic_relationships_source_entity_id",
            "semantic_relationships",
            ["source_entity_id"],
        )
        op.create_index(
            "idx_semantic_relationships_target_entity_id",
            "semantic_relationships",
            ["target_entity_id"],
        )
        op.create_index(
            "idx_semantic_relationships_event_id",
            "semantic_relationships",
            ["source_event_id"],
        )
        op.create_index(
            "idx_semantic_relationships_meeting_id",
            "semantic_relationships",
            ["meeting_id"],
        )


def downgrade() -> None:
    existing = _existing_tables()
    if "semantic_relationships" in existing:
        _drop_index_if_exists(
            "idx_semantic_relationships_meeting_id",
            "semantic_relationships",
        )
        _drop_index_if_exists(
            "idx_semantic_relationships_event_id",
            "semantic_relationships",
        )
        _drop_index_if_exists(
            "idx_semantic_relationships_target_entity_id",
            "semantic_relationships",
        )
        _drop_index_if_exists(
            "idx_semantic_relationships_source_entity_id",
            "semantic_relationships",
        )
        op.drop_table("semantic_relationships")
    if "semantic_entity_mentions" in existing:
        _drop_index_if_exists(
            "idx_semantic_mentions_event_id",
            "semantic_entity_mentions",
        )
        _drop_index_if_exists(
            "idx_semantic_mentions_meeting_id",
            "semantic_entity_mentions",
        )
        op.drop_table("semantic_entity_mentions")
    if "semantic_entities" in existing:
        _drop_index_if_exists(
            "idx_semantic_entities_type",
            "semantic_entities",
        )
        _drop_index_if_exists(
            "idx_semantic_entities_normalized_name",
            "semantic_entities",
        )
        op.drop_table("semantic_entities")
    if "meeting_semantic_events" in existing:
        _drop_index_if_exists(
            "idx_meeting_semantic_events_category",
            "meeting_semantic_events",
        )
        _drop_index_if_exists(
            "idx_meeting_semantic_events_type",
            "meeting_semantic_events",
        )
        _drop_index_if_exists(
            "idx_meeting_semantic_events_meeting_id",
            "meeting_semantic_events",
        )
        op.drop_table("meeting_semantic_events")
    if "meeting_action_items" in existing:
        _drop_index_if_exists(
            "idx_meeting_action_items_status",
            "meeting_action_items",
        )
        _drop_index_if_exists(
            "idx_meeting_action_items_meeting_id",
            "meeting_action_items",
        )
        op.drop_table("meeting_action_items")
    if "meeting_insights" in existing:
        _drop_index_if_exists(
            "idx_meeting_insights_meeting_id",
            "meeting_insights",
        )
        op.drop_table("meeting_insights")
    if "meeting_participants" in existing:
        _drop_index_if_exists(
            "idx_meeting_participants_meeting_id",
            "meeting_participants",
        )
        op.drop_table("meeting_participants")
    if "meetings" in existing:
        _drop_index_if_exists("idx_meetings_company_name", "meetings")
        op.drop_table("meetings")
