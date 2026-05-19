"""Phase 13A - Notion sync map.

One row per (internal entity, notion workspace) pairing. Lets the writer
do idempotent upserts:

    find_by_external_id(database_id, internal_id) -> page_id or None

`internal_id` is a string so it can hold UUIDs (rfp_answers), legacy
auto-increment ints stringified (targets, interactions, ...), or any
future natural key. The UNIQUE constraint enforces "one Notion page per
entity per workspace" and lets us retry sync without creating dupes.

`notion_workspace` is a free-form string for now (typical values:
'teamspace', 'publicspace') because the demo workspace structure may
grow and we don't want a destructive Enum migration to add a new one.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotionSyncMap(Base):
    __tablename__ = "notion_sync_map"
    __table_args__ = (
        sa.UniqueConstraint(
            "internal_table",
            "internal_id",
            "notion_workspace",
            name="uq_notion_sync_map_entity_workspace",
        ),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)

    internal_table: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    internal_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)

    notion_workspace: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    notion_database_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    notion_page_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    sync_status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default="success"
    )
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    synced_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<NotionSyncMap {self.internal_table}:{self.internal_id} "
            f"-> {self.notion_workspace}:{self.notion_page_id}>"
        )
