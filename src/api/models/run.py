"""Phase 13C M9 - Run metadata snapshot model.

One row per run that has reached a *terminal* state (completed | failed).
In-flight runs stay in the process-local `RunStore` dict — only when
the status flips to completed/failed does the runner ask the store to
persist a snapshot of the public fields.

What we deliberately do NOT persist:
  - The per-record event log. SSE consumers only care about it during
    the run's lifetime; after completion the proposal_md and the cost
    snapshot are what matter.
  - The threading.Lock from RunRecord (obviously process-local).

Why a snapshot and not full event history:
  - Keeps the table cheap (one INSERT per run instead of one per event).
  - The Notion workspace already serves as the durable narrative log;
    this table is just for the Web UI run-history page to survive a
    process restart.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    company: Mapped[str] = mapped_column(sa.Text, nullable=False)
    industry: Mapped[str] = mapped_column(sa.Text, nullable=False)
    lang: Mapped[str] = mapped_column(sa.String(8), nullable=False)

    status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, index=True
    )
    current_stage: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    created_at: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=_now_iso)
    started_at: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    ended_at: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    errors_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    usage_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    article_counts_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    proposal_points_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    proposal_md: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    claude_model: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<Run run_id={self.run_id!r} status={self.status!r}>"
