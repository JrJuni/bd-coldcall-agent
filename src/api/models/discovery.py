"""Phase 13B M7c - DiscoveryRun + DiscoveryCandidate models.

Ports the Phase 10 P10-2b raw-sqlite schemas. JSON-shaped payloads
(`scores_json`, `usage_json`, `weights_snapshot_json`) stay as TEXT
columns because the legacy SQLite databases hold strings there and we
JSON-encode/decode in the store layer — same pattern as Phase 13B M7b
(`targets.aliases_json`).

`region` is a delimiter-joined list of ISO 3166-1 alpha-2 codes (or
the canonical "any" / "global" tokens). Decoding lives in `DiscoveryStore`.

Foreign key from `discovery_candidates.run_id` to `discovery_runs.run_id`
is NOT declared on the ORM side, matching the Phase 13B convention: the
legacy SQLite table has it, fresh Postgres tables don't. Application
code already enforces existence manually before insert.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.api.orm import Base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    run_id: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    generated_at: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    seed_doc_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    seed_chunk_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    seed_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    profile: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    region: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    lang: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    namespace: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
        default="default",
        server_default=sa.text("'default'"),
    )
    status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        default="queued",
        server_default=sa.text("'queued'"),
    )
    started_at: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    ended_at: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source_yaml_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    usage_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    claude_model: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    weights_snapshot_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=_now_iso)

    def __repr__(self) -> str:
        return f"<DiscoveryRun run_id={self.run_id!r} status={self.status!r}>"


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    industry: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scores_json: Mapped[str] = mapped_column(sa.Text, nullable=False)
    final_score: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.0, server_default=sa.text("0")
    )
    tier: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        default="active",
        server_default=sa.text("'active'"),
        index=True,
    )
    updated_at: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    def __repr__(self) -> str:
        return f"<DiscoveryCandidate id={self.id!r} tier={self.tier!r}>"
