"""Phase 13B M7a - RagSummary model (ports the `rag_summaries` table).

One row per (ws_slug, namespace, path) AI-generated namespace summary.
Mirrors the post-P11-2 schema in `src/api/db.py::_SCHEMA_SQL`.

`usage_json` stays a string column (JSON-encoded) rather than the
`json_column()` variant used by Phase 13A tables because legacy
databases on disk already hold TEXT here; switching to JSONB on
Postgres would require a real data migration. The route layer JSON-
decodes on read.

`indexed_at_at_generation` is the folder's last_indexed_at AT THE MOMENT
this summary was generated. Stale detection compares it against the
current folder timestamp.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base


class RagSummary(Base):
    __tablename__ = "rag_summaries"

    ws_slug: Mapped[str] = mapped_column(
        sa.String(128), primary_key=True, nullable=False, server_default=sa.text("'default'")
    )
    namespace: Mapped[str] = mapped_column(sa.String(128), primary_key=True, nullable=False)
    path: Mapped[str] = mapped_column(
        sa.String(512), primary_key=True, nullable=False, server_default=sa.text("''")
    )

    summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    lang: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    model: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    usage_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    chunk_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    chunks_in_namespace: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )

    indexed_at_at_generation: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    generated_at: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<RagSummary {self.ws_slug}:{self.namespace}:{self.path!r}>"
        )
