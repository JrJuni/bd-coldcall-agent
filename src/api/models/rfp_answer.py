"""Phase 13A — RFP answer model.

Each row is one evaluation log entry: the question, the chunks the RAG
layer surfaced, the LLM-drafted cited answer, and the metadata needed to
re-run / compare prompts and models. Rows always start at status='draft'
and progress through 'reviewed' to 'published' during the human review
loop (Phase 13.5 will add the promote workflow).

Important shape decisions:
  - `id` is a UUID string, not an autoinc int. The MCP tool returns it
    so the model can refer to it in follow-up turns ("rfp_answer_id":
    "..."), and a stable cross-engine ID avoids exposing the ints from
    legacy tables.
  - `retrieved_chunks` and `citations` are JSON columns via
    `json_column()` so they map to JSONB on Postgres and string-JSON on
    SQLite without diverging migrations.
  - `status` is a plain string (not an Enum) so promoting later in
    Phase 13.5 doesn't require a destructive migration.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base, json_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class RfpAnswer(Base):
    __tablename__ = "rfp_answers"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)

    question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    retrieved_chunks = json_column(nullable=False, default=list)
    generated_answer: Mapped[str] = mapped_column(sa.Text, nullable=False)
    citations = json_column(nullable=False, default=list)

    # Self-rated by the answer prompt; structured strings are easier to
    # filter/index than free-form floats.
    evidence_quality: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    model_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    reviewer_notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default="draft", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    def __repr__(self) -> str:
        return f"<RfpAnswer id={self.id!r} status={self.status!r}>"
