"""Phase 13B M7b - Target model (ports the `targets` table).

Mirrors the legacy schema in `src/api/db.py::_SCHEMA_SQL`. `aliases_json`
stays a TEXT column (manually JSON-encoded by `TargetStore`) instead of
going through `json_column()` because legacy databases hold strings
there and we want to avoid an in-place data normalization in this port.

Foreign key to `discovery_candidates(id)` is deliberately NOT declared
on the ORM side — the discovery_candidates table is ported in M7c, so
declaring the FK here would block Alembic on fresh Postgres targets
that run 0003 before 0004. Application code already enforces existence
manually.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    industry: Mapped[str] = mapped_column(sa.Text, nullable=False)
    aliases_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    stage: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        default="planned",
        server_default=sa.text("'planned'"),
    )
    created_from: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        default="manual",
        server_default=sa.text("'manual'"),
    )
    discovery_candidate_id: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, index=True
    )
    last_run_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=_now_iso)
    updated_at: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=_now_iso)

    def __repr__(self) -> str:
        return f"<Target id={self.id!r} name={self.name!r}>"
