"""Persistence and semantic aggregations for Meeting Intelligence."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from src.llm.meeting_analysis import (
    MeetingAnalysisResult,
    SemanticEntityAnalysis,
)
from src.meeting_intelligence import models as m


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_entity_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


class MeetingRepository:
    """Repository over the module-local Meeting Intelligence schema."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    # --- row serializers -------------------------------------------------

    @staticmethod
    def _meeting_row(row: m.Meeting) -> dict[str, Any]:
        return {
            "id": row.id,
            "company_name": row.company_name,
            "title": row.title,
            "occurred_at": row.occurred_at,
            "lang": row.lang,
            "source_type": row.source_type,
            "summary": row.summary,
            "created_at": row.created_at,
        }

    @staticmethod
    def _participant_row(row: m.MeetingParticipant) -> dict[str, Any]:
        return {
            "id": row.id,
            "meeting_id": row.meeting_id,
            "name": row.name,
            "role": row.role,
            "company": row.company,
            "is_customer": bool(row.is_customer),
            "metadata_json": _json_loads(row.metadata_json),
            "created_at": row.created_at,
        }

    @staticmethod
    def _insight_row(row: m.MeetingInsight | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row.id,
            "meeting_id": row.meeting_id,
            "meeting_summary": row.meeting_summary,
            "suggested_stage": row.suggested_stage,
            "follow_up_draft": row.follow_up_draft,
            "metadata_json": _json_loads(row.metadata_json),
            "created_at": row.created_at,
        }

    @staticmethod
    def _action_row(row: m.MeetingActionItem) -> dict[str, Any]:
        return {
            "id": row.id,
            "meeting_id": row.meeting_id,
            "description": row.description,
            "owner": row.owner,
            "due_date": row.due_date,
            "status": row.status,
            "evidence_text": row.evidence_text,
            "confidence": float(row.confidence or 0.0),
            "metadata_json": _json_loads(row.metadata_json),
            "created_at": row.created_at,
        }

    @staticmethod
    def _event_row(row: m.MeetingSemanticEvent) -> dict[str, Any]:
        return {
            "id": row.id,
            "meeting_id": row.meeting_id,
            "type": row.type,
            "category": row.category,
            "subject": row.subject,
            "summary": row.summary,
            "evidence_text": row.evidence_text,
            "severity": row.severity,
            "confidence": float(row.confidence or 0.0),
            "metadata_json": _json_loads(row.metadata_json),
            "created_at": row.created_at,
        }

    @staticmethod
    def _entity_row(row: m.SemanticEntity) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "normalized_name": row.normalized_name,
            "entity_type": row.entity_type,
            "metadata_json": _json_loads(row.metadata_json),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _mention_row(row: m.SemanticEntityMention) -> dict[str, Any]:
        return {
            "id": row.id,
            "entity_id": row.entity_id,
            "meeting_id": row.meeting_id,
            "event_id": row.event_id,
            "evidence_text": row.evidence_text,
            "confidence": float(row.confidence or 0.0),
            "metadata_json": _json_loads(row.metadata_json),
            "created_at": row.created_at,
        }

    @staticmethod
    def _relationship_row(
        row: m.SemanticRelationship,
        *,
        source: m.SemanticEntity | None = None,
        target: m.SemanticEntity | None = None,
    ) -> dict[str, Any]:
        data = {
            "id": row.id,
            "source_entity_id": row.source_entity_id,
            "relation_type": row.relation_type,
            "target_entity_id": row.target_entity_id,
            "source_event_id": row.source_event_id,
            "meeting_id": row.meeting_id,
            "evidence_text": row.evidence_text,
            "confidence": float(row.confidence or 0.0),
            "metadata_json": _json_loads(row.metadata_json),
            "created_at": row.created_at,
        }
        if source is not None:
            data["source_entity"] = MeetingRepository._entity_row(source)
        if target is not None:
            data["target_entity"] = MeetingRepository._entity_row(target)
        return data

    # --- writes ----------------------------------------------------------

    def create_meeting(
        self,
        *,
        company_name: str,
        summary: str,
        lang: str = "en",
        title: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        with self._sf() as session:
            row = m.Meeting(
                company_name=company_name,
                title=title,
                occurred_at=occurred_at,
                lang=lang,
                source_type="summary",
                summary=summary,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._meeting_row(row)

    def persist_analysis(
        self,
        meeting_id: int,
        analysis: MeetingAnalysisResult,
        *,
        usage: dict[str, int] | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        with self._sf() as session:
            meeting = session.get(m.Meeting, meeting_id)
            if meeting is None:
                raise ValueError(f"meeting {meeting_id} not found")

            metadata = {
                "usage": usage or {},
                "model": model,
                "prompt_version": prompt_version,
            }
            session.add(
                m.MeetingInsight(
                    meeting_id=meeting_id,
                    meeting_summary=analysis.meeting_summary,
                    suggested_stage=analysis.suggested_stage,
                    follow_up_draft=analysis.follow_up_draft,
                    metadata_json=_json_dumps(metadata),
                )
            )

            for participant in analysis.participants:
                session.add(
                    m.MeetingParticipant(
                        meeting_id=meeting_id,
                        name=participant.name,
                        role=participant.role,
                        company=participant.company,
                        is_customer=participant.is_customer,
                        metadata_json=_json_dumps(participant.metadata_json),
                    )
                )

            for action in analysis.action_items:
                session.add(
                    m.MeetingActionItem(
                        meeting_id=meeting_id,
                        description=action.description,
                        owner=action.owner,
                        due_date=action.due_date,
                        status=action.status,
                        evidence_text=action.evidence_text,
                        confidence=action.confidence,
                        metadata_json=_json_dumps(action.metadata_json),
                    )
                )

            event_rows: list[m.MeetingSemanticEvent] = []
            for event in analysis.semantic_events:
                row = m.MeetingSemanticEvent(
                    meeting_id=meeting_id,
                    type=event.type,
                    category=event.category,
                    subject=event.subject,
                    summary=event.summary,
                    evidence_text=event.evidence_text,
                    severity=event.severity,
                    confidence=event.confidence,
                    metadata_json=_json_dumps(event.metadata_json),
                )
                session.add(row)
                event_rows.append(row)
            session.flush()

            entity_by_key: dict[tuple[str, str], m.SemanticEntity] = {}
            for entity in analysis.entities:
                row = self._upsert_entity(session, entity)
                entity_by_key[(row.normalized_name, row.entity_type)] = row

            for rel in analysis.relationships:
                source = self._upsert_entity(
                    session,
                    SemanticEntityAnalysis(
                        name=rel.source_entity_name,
                        entity_type=rel.source_entity_type,
                    ),
                )
                target = self._upsert_entity(
                    session,
                    SemanticEntityAnalysis(
                        name=rel.target_entity_name,
                        entity_type=rel.target_entity_type,
                    ),
                )
                source_event = event_rows[rel.source_event_index]
                session.add(
                    m.SemanticRelationship(
                        source_entity_id=source.id,
                        relation_type=rel.relation_type,
                        target_entity_id=target.id,
                        source_event_id=source_event.id,
                        meeting_id=meeting_id,
                        evidence_text=rel.evidence_text,
                        confidence=rel.confidence,
                        metadata_json=_json_dumps(rel.metadata_json),
                    )
                )
                self._ensure_mention(
                    session,
                    entity=source,
                    meeting_id=meeting_id,
                    event_id=source_event.id,
                    evidence_text=rel.evidence_text,
                    confidence=rel.confidence,
                )
                self._ensure_mention(
                    session,
                    entity=target,
                    meeting_id=meeting_id,
                    event_id=source_event.id,
                    evidence_text=rel.evidence_text,
                    confidence=rel.confidence,
                )

            self._mention_entities_from_events(
                session,
                meeting_id=meeting_id,
                entities=list(entity_by_key.values()),
                events=event_rows,
            )

            session.commit()
        detail = self.get_meeting(meeting_id)
        if detail is None:
            raise ValueError(f"meeting {meeting_id} disappeared after persist")
        return detail

    def _upsert_entity(
        self, session: Session, entity: SemanticEntityAnalysis
    ) -> m.SemanticEntity:
        normalized = entity.normalized_name or normalize_entity_name(entity.name)
        row = session.scalar(
            sa.select(m.SemanticEntity).where(
                m.SemanticEntity.normalized_name == normalized,
                m.SemanticEntity.entity_type == entity.entity_type,
            )
        )
        if row is not None:
            row.name = entity.name
            row.metadata_json = _json_dumps(entity.metadata_json)
            return row
        row = m.SemanticEntity(
            name=entity.name,
            normalized_name=normalized,
            entity_type=entity.entity_type,
            metadata_json=_json_dumps(entity.metadata_json),
        )
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def _ensure_mention(
        session: Session,
        *,
        entity: m.SemanticEntity,
        meeting_id: int,
        event_id: int | None,
        evidence_text: str | None,
        confidence: float,
    ) -> None:
        exists = session.scalar(
            sa.select(m.SemanticEntityMention.id).where(
                m.SemanticEntityMention.entity_id == entity.id,
                m.SemanticEntityMention.meeting_id == meeting_id,
                m.SemanticEntityMention.event_id == event_id,
            )
        )
        if exists is not None:
            return
        session.add(
            m.SemanticEntityMention(
                entity_id=entity.id,
                meeting_id=meeting_id,
                event_id=event_id,
                evidence_text=evidence_text,
                confidence=confidence,
            )
        )

    def _mention_entities_from_events(
        self,
        session: Session,
        *,
        meeting_id: int,
        entities: list[m.SemanticEntity],
        events: list[m.MeetingSemanticEvent],
    ) -> None:
        for entity in entities:
            needle = normalize_entity_name(entity.name)
            for event in events:
                haystack = normalize_entity_name(
                    " ".join([event.subject, event.summary, event.evidence_text])
                )
                if needle and needle in haystack:
                    self._ensure_mention(
                        session,
                        entity=entity,
                        meeting_id=meeting_id,
                        event_id=event.id,
                        evidence_text=event.evidence_text,
                        confidence=event.confidence,
                    )

    # --- reads -----------------------------------------------------------

    def get_meeting(self, meeting_id: int) -> dict[str, Any] | None:
        with self._sf() as session:
            meeting = session.get(m.Meeting, meeting_id)
            if meeting is None:
                return None
            insight = session.scalar(
                sa.select(m.MeetingInsight).where(m.MeetingInsight.meeting_id == meeting_id)
            )
            participants = session.scalars(
                sa.select(m.MeetingParticipant)
                .where(m.MeetingParticipant.meeting_id == meeting_id)
                .order_by(m.MeetingParticipant.id.asc())
            ).all()
            actions = session.scalars(
                sa.select(m.MeetingActionItem)
                .where(m.MeetingActionItem.meeting_id == meeting_id)
                .order_by(m.MeetingActionItem.id.asc())
            ).all()
            events = session.scalars(
                sa.select(m.MeetingSemanticEvent)
                .where(m.MeetingSemanticEvent.meeting_id == meeting_id)
                .order_by(m.MeetingSemanticEvent.id.asc())
            ).all()
            mentions = session.scalars(
                sa.select(m.SemanticEntityMention)
                .where(m.SemanticEntityMention.meeting_id == meeting_id)
                .order_by(m.SemanticEntityMention.id.asc())
            ).all()
            relationships = session.scalars(
                sa.select(m.SemanticRelationship)
                .where(m.SemanticRelationship.meeting_id == meeting_id)
                .order_by(m.SemanticRelationship.id.asc())
            ).all()
            entities = session.scalars(
                sa.select(m.SemanticEntity)
                .join(m.SemanticEntityMention, m.SemanticEntity.id == m.SemanticEntityMention.entity_id)
                .where(m.SemanticEntityMention.meeting_id == meeting_id)
                .order_by(m.SemanticEntity.id.asc())
                .distinct()
            ).all()

            detail = self._meeting_row(meeting)
            detail.update(
                {
                    "insight": self._insight_row(insight),
                    "participants": [self._participant_row(p) for p in participants],
                    "action_items": [self._action_row(a) for a in actions],
                    "semantic_events": [self._event_row(e) for e in events],
                    "entities": [self._entity_row(e) for e in entities],
                    "entity_mentions": [self._mention_row(x) for x in mentions],
                    "relationships": [self._relationship_row(r) for r in relationships],
                }
            )
            return detail

    def recent_meetings(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._sf() as session:
            rows = session.scalars(
                sa.select(m.Meeting).order_by(m.Meeting.created_at.desc()).limit(limit)
            ).all()
            out: list[dict[str, Any]] = []
            for row in rows:
                event_count = session.scalar(
                    sa.select(sa.func.count(m.MeetingSemanticEvent.id)).where(
                        m.MeetingSemanticEvent.meeting_id == row.id
                    )
                )
                action_count = session.scalar(
                    sa.select(sa.func.count(m.MeetingActionItem.id)).where(
                        m.MeetingActionItem.meeting_id == row.id
                    )
                )
                item = self._meeting_row(row)
                item["semantic_event_count"] = int(event_count or 0)
                item["action_item_count"] = int(action_count or 0)
                out.append(item)
            return out

    def objections_by_category(self) -> list[dict[str, Any]]:
        return self._events_grouped_by_category(types=("technical_objection",))

    def product_feedback_candidates(self) -> list[dict[str, Any]]:
        types = ("product_feedback", "feature_request", "product_gap")
        with self._sf() as session:
            rows = session.execute(
                sa.select(m.MeetingSemanticEvent, m.Meeting)
                .join(m.Meeting, m.Meeting.id == m.MeetingSemanticEvent.meeting_id)
                .where(m.MeetingSemanticEvent.type.in_(types))
                .order_by(m.MeetingSemanticEvent.confidence.desc())
            ).all()
            return [
                {
                    **self._event_row(event),
                    "company_name": meeting.company_name,
                    "meeting_created_at": meeting.created_at,
                }
                for event, meeting in rows
            ]

    def open_action_items(self) -> list[dict[str, Any]]:
        with self._sf() as session:
            rows = session.execute(
                sa.select(m.MeetingActionItem, m.Meeting)
                .join(m.Meeting, m.Meeting.id == m.MeetingActionItem.meeting_id)
                .where(m.MeetingActionItem.status == "open")
                .order_by(m.MeetingActionItem.created_at.desc())
            ).all()
            return [
                {
                    **self._action_row(action),
                    "company_name": meeting.company_name,
                    "meeting_created_at": meeting.created_at,
                }
                for action, meeting in rows
            ]

    def top_topics(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._sf() as session:
            rows = session.execute(
                sa.select(
                    m.MeetingSemanticEvent.subject,
                    m.MeetingSemanticEvent.type,
                    sa.func.count().label("count"),
                )
                .group_by(m.MeetingSemanticEvent.subject, m.MeetingSemanticEvent.type)
                .order_by(sa.desc("count"), m.MeetingSemanticEvent.subject.asc())
                .limit(limit)
            ).all()
            topics: list[dict[str, Any]] = []
            for subject, event_type, count in rows:
                companies = session.execute(
                    sa.select(sa.distinct(m.Meeting.company_name))
                    .join(
                        m.MeetingSemanticEvent,
                        m.MeetingSemanticEvent.meeting_id == m.Meeting.id,
                    )
                    .where(
                        m.MeetingSemanticEvent.subject == subject,
                        m.MeetingSemanticEvent.type == event_type,
                    )
                    .order_by(m.Meeting.company_name.asc())
                ).scalars().all()
                topics.append(
                    {
                        "topic": subject,
                        "event_type": event_type,
                        "count": int(count),
                        "companies": list(companies),
                    }
                )
            return topics

    def _events_grouped_by_category(self, *, types: tuple[str, ...]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        with self._sf() as session:
            rows = session.execute(
                sa.select(m.MeetingSemanticEvent, m.Meeting)
                .join(m.Meeting, m.Meeting.id == m.MeetingSemanticEvent.meeting_id)
                .where(m.MeetingSemanticEvent.type.in_(types))
                .order_by(m.MeetingSemanticEvent.created_at.desc())
            ).all()
        for event, meeting in rows:
            category = event.category or "uncategorized"
            grouped[category].append(
                {
                    **self._event_row(event),
                    "company_name": meeting.company_name,
                    "meeting_created_at": meeting.created_at,
                }
            )
        return [
            {"category": category, "count": len(events), "events": events}
            for category, events in sorted(
                grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])
            )
        ]
