"""Phase 13B M7d - smoke test for the SQLite -> Postgres migration script.

We can't reach Neon from CI, so the test exercises the script's row-copy
machinery against two SQLite databases. That covers everything except
the Postgres SERIAL sequence bump (guarded by a dialect check in the
script itself, so it's a no-op here).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from src.api.models.rfp_answer import RfpAnswer
from src.api.models.target import Target
from src.api.models.workspace import Workspace
from src.api.orm import Base, make_engine
from src.meeting_intelligence.models import (
    Meeting,
    MeetingParticipant,
    MeetingSemanticEvent,
    SemanticEntity,
    SemanticEntityMention,
)
from scripts.migrate_sqlite_to_postgres import COPY_ORDER, _copy_table


def test_copy_round_trip(tmp_path):
    src_url = f"sqlite:///{(tmp_path / 'src.db').as_posix()}"
    tgt_url = f"sqlite:///{(tmp_path / 'tgt.db').as_posix()}"

    src_engine = make_engine(src_url)
    tgt_engine = make_engine(tgt_url)
    Base.metadata.create_all(src_engine)
    Base.metadata.create_all(tgt_engine)

    SrcSession = sessionmaker(bind=src_engine, future=True)
    TgtSession = sessionmaker(bind=tgt_engine, future=True)

    # Seed source with one row per table that we care about.
    ts = "2026-05-19T00:00:00+00:00"
    with SrcSession() as s:
        s.add(
            Workspace(
                slug="default",
                label="Project Docs",
                abs_path="C:/proj/data/company_docs",
                is_builtin=True,
                created_at=ts,
                updated_at=ts,
            )
        )
        s.add(
            Target(
                name="Acme",
                industry="semiconductor",
                aliases_json='["ACME","Acme Corp"]',
                stage="planned",
                created_from="manual",
                created_at=ts,
                updated_at=ts,
            )
        )
        s.add(
            RfpAnswer(
                id="rfp-1",
                run_id="run-1",
                question="Is the product SOC 2 compliant?",
                retrieved_chunks=[{"id": "c1"}],
                generated_answer="Yes.",
                citations=[{"chunk_id": "c1"}],
                evidence_quality="high",
                confidence=0.91,
                model_version="claude-sonnet-4-6",
                prompt_version="rfp_answer.v1",
                status="draft",
            )
        )
        s.commit()

    # Seed Meeting Intelligence — exercise the FK chain so the copy order
    # is verified end-to-end (parent before children before joins).
    with SrcSession() as s:
        meeting = Meeting(
            company_name="Acme",
            summary="SOC 2 is required before production.",
            source_type="summary",
            lang="en",
            created_at=ts,
        )
        s.add(meeting)
        s.flush()
        meeting_id = meeting.id

        s.add(
            MeetingParticipant(
                meeting_id=meeting_id,
                name="Dana",
                role="Director",
                company="Acme",
                is_customer=True,
                created_at=ts,
            )
        )
        event = MeetingSemanticEvent(
            meeting_id=meeting_id,
            type="security_requirement",
            subject="SOC 2",
            summary="SOC 2 is a gate.",
            evidence_text="SOC 2 is required before production.",
            severity="high",
            confidence=0.94,
            created_at=ts,
        )
        s.add(event)
        entity = SemanticEntity(
            name="SOC 2",
            normalized_name="soc 2",
            entity_type="compliance_requirement",
            created_at=ts,
            updated_at=ts,
        )
        s.add(entity)
        s.flush()
        s.add(
            SemanticEntityMention(
                entity_id=entity.id,
                meeting_id=meeting_id,
                event_id=event.id,
                evidence_text="SOC 2 is required before production.",
                confidence=0.94,
                created_at=ts,
            )
        )
        s.commit()

    # Run the copy.
    totals_src = 0
    totals_ins = 0
    with SrcSession() as src, TgtSession() as tgt:
        for model in COPY_ORDER:
            src_n, ins_n = _copy_table(
                src, tgt, model, apply=True, force_empty_target=False
            )
            totals_src += src_n
            totals_ins += ins_n

    # 3 Phase-13 rows + 5 meeting rows.
    assert totals_src == 8
    assert totals_ins == 8

    with TgtSession() as t:
        ws = t.scalar(sa.select(Workspace).where(Workspace.slug == "default"))
        assert ws is not None
        assert ws.is_builtin is True

        tgt_targets = t.scalars(sa.select(Target)).all()
        assert len(tgt_targets) == 1
        assert tgt_targets[0].name == "Acme"
        assert tgt_targets[0].aliases_json == '["ACME","Acme Corp"]'

        tgt_rfp = t.scalars(sa.select(RfpAnswer)).all()
        assert len(tgt_rfp) == 1
        assert tgt_rfp[0].id == "rfp-1"
        assert tgt_rfp[0].retrieved_chunks == [{"id": "c1"}]
        assert tgt_rfp[0].evidence_quality == "high"

        # Meeting FK graph survived the copy: the join row still points at
        # the right meeting + event + entity (all PKs preserved by the
        # migration script via explicit id columns).
        mention = t.scalars(sa.select(SemanticEntityMention)).one()
        meeting = t.scalars(sa.select(Meeting)).one()
        event = t.scalars(sa.select(MeetingSemanticEvent)).one()
        entity = t.scalars(sa.select(SemanticEntity)).one()
        assert mention.meeting_id == meeting.id
        assert mention.event_id == event.id
        assert mention.entity_id == entity.id
        assert entity.normalized_name == "soc 2"


def test_dry_run_does_not_insert(tmp_path):
    src_url = f"sqlite:///{(tmp_path / 'src2.db').as_posix()}"
    tgt_url = f"sqlite:///{(tmp_path / 'tgt2.db').as_posix()}"

    src_engine = make_engine(src_url)
    tgt_engine = make_engine(tgt_url)
    Base.metadata.create_all(src_engine)
    Base.metadata.create_all(tgt_engine)

    SrcSession = sessionmaker(bind=src_engine, future=True)
    TgtSession = sessionmaker(bind=tgt_engine, future=True)

    ts = "2026-05-19T00:00:00+00:00"
    with SrcSession() as s:
        s.add(
            Workspace(
                slug="w1",
                label="w1",
                abs_path="C:/somewhere",
                is_builtin=False,
                created_at=ts,
                updated_at=ts,
            )
        )
        s.commit()

    with SrcSession() as src, TgtSession() as tgt:
        for model in COPY_ORDER:
            src_n, ins_n = _copy_table(
                src, tgt, model, apply=False, force_empty_target=False
            )
            # Even when the source has rows, dry-run reports 0 insertions.
            assert ins_n == 0

    # Target stays empty.
    with TgtSession() as t:
        assert t.scalar(sa.select(sa.func.count()).select_from(Workspace)) == 0
