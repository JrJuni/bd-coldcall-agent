"""Phase 13B M7c - NewsRun model.

Ports the Phase 10 P10-5 `news_runs` schema. `articles_json` and
`usage_json` stay TEXT columns (manual JSON in the store layer) —
articles can be large (10–50 hits per row) and the legacy SQLite DBs
already hold strings here. JSONB on Postgres would be nice but isn't
worth a data migration in M7c.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NewsRun(Base):
    __tablename__ = "news_runs"

    task_id: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    generated_at: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    seed_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    articles_json: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'[]'")
    )
    sonnet_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    usage_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    ttl_hours: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=12, server_default=sa.text("12")
    )
    namespace: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
        default="default",
        server_default=sa.text("'default'"),
    )
    seed_query: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    lang: Mapped[str] = mapped_column(
        sa.String(8),
        nullable=False,
        default="en",
        server_default=sa.text("'en'"),
    )
    days: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=30, server_default=sa.text("30")
    )
    status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        default="queued",
        server_default=sa.text("'queued'"),
    )
    article_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    started_at: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    ended_at: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, default=_now_iso)

    def __repr__(self) -> str:
        return f"<NewsRun task_id={self.task_id!r} status={self.status!r}>"
