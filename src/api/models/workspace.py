"""Phase 13B M7a - Workspace model (ports the `workspaces` table).

Mirrors the schema in `src/api/db.py::_SCHEMA_SQL` so legacy databases
(seeded by `init_db()` long before Phase 13B) keep working — only the
declarative class is new, the on-disk shape is unchanged.

Why timestamps are stored as strings (not `DateTime`):
  The wire surface (`WorkspaceSummary.created_at: str`) returns ISO-8601
  strings. Keeping the column as TEXT preserves round-trip compatibility
  with the legacy `WorkspaceStore` and avoids forcing every route /
  consumer to format datetimes. Phase 13B+ can normalize once every
  table is ORM-native.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(sa.String(128), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    abs_path: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    is_builtin: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.text("0")
    )
    created_at: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=_now_iso)
    updated_at: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=_now_iso)

    def __repr__(self) -> str:
        return f"<Workspace id={self.id!r} slug={self.slug!r}>"
