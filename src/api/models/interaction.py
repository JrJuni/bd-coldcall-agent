"""Phase 13B M7b - Interaction model (ports the `interactions` table).

CRUD-only BD touchpoint log (call / meeting / email / note). `target_id`
is NULLABLE so free-text "I called Acme today" notes can be captured
before the company is registered as a Target.

Same FK-on-ORM rationale as `Target`: legacy SQLite has a real FK
constraint to targets(id), fresh Postgres tables created by Alembic
don't — to keep migration order flexible. Application code never
depends on the FK.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    target_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True, index=True)
    company_name: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    occurred_at: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    outcome: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    contact_role: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=_now_iso)

    def __repr__(self) -> str:
        return f"<Interaction id={self.id!r} kind={self.kind!r}>"
