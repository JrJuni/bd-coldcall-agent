"""Meeting Intelligence database models.

Kept under a module-local SQLAlchemy base so this phase can be developed
without touching the shared `src/api/db.py` or the ongoing app-wide ORM
registration until the module is stable.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MeetingBase(DeclarativeBase):
    pass


class Meeting(MeetingBase):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    occurred_at: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    lang: Mapped[str] = mapped_column(sa.String(8), nullable=False, default="en")
    source_type: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="summary"
    )
    summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )


class MeetingParticipant(MeetingBase):
    __tablename__ = "meeting_participants"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    company: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_customer: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    metadata_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )


class MeetingInsight(MeetingBase):
    __tablename__ = "meeting_insights"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    meeting_summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    suggested_stage: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    follow_up_draft: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )


class MeetingActionItem(MeetingBase):
    __tablename__ = "meeting_action_items"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    due_date: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="open", index=True
    )
    evidence_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    metadata_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )


class MeetingSemanticEvent(MeetingBase):
    __tablename__ = "meeting_semantic_events"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)
    subject: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    evidence_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    metadata_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )


class SemanticEntity(MeetingBase):
    __tablename__ = "semantic_entities"
    __table_args__ = (
        sa.UniqueConstraint(
            "normalized_name", "entity_type", name="uq_semantic_entities_name_type"
        ),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    metadata_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )
    updated_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )


class SemanticEntityMention(MeetingBase):
    __tablename__ = "semantic_entity_mentions"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("semantic_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    meeting_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        sa.ForeignKey("meeting_semantic_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    evidence_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    metadata_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )


class SemanticRelationship(MeetingBase):
    __tablename__ = "semantic_relationships"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    source_entity_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("semantic_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(sa.String(80), nullable=False, index=True)
    target_entity_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("semantic_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_event_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("meeting_semantic_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    meeting_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    metadata_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=_now_iso
    )


MEETING_TABLES = (
    "meetings",
    "meeting_participants",
    "meeting_insights",
    "meeting_action_items",
    "meeting_semantic_events",
    "semantic_entities",
    "semantic_entity_mentions",
    "semantic_relationships",
)


def create_meeting_schema(engine: Engine) -> None:
    """Create only the Meeting Intelligence tables on the given engine."""
    MeetingBase.metadata.create_all(engine)
