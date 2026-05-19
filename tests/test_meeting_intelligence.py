"""Phase M - Meeting Intelligence module-level tests.

Schema is delivered through `src.api.orm::Base.metadata.create_all` for
in-memory fixtures, or through Alembic for migration tests. The HTTP
route surface is exercised separately in `tests/test_meeting_routes.py`
via `TestClient(create_app())`.
"""
from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from src.api.orm import Base, make_engine, make_session_factory
from src.llm import meeting_analysis as ma
from src.meeting_intelligence import service
from src.meeting_intelligence.indexing import build_meeting_index_payload
from src.meeting_intelligence.models import MEETING_TABLES
from src.meeting_intelligence.repository import MeetingRepository


SUMMARY = (
    "Acme said SOC 2 is required before production. "
    "They are blocked by Salesforce integration work. "
    "Dana will send a POC scope by Friday. "
    "They mentioned OldCRM as the incumbent solution."
)


def _analysis() -> ma.MeetingAnalysisResult:
    return ma.MeetingAnalysisResult(
        **{
            "meeting_summary": "Acme needs security approval and integration work before a POC.",
            "suggested_stage": "poc_scoping",
            "follow_up_draft": "Thanks Dana - I will send the SOC 2 details and POC plan.",
            "participants": [
                {
                    "name": "Dana",
                    "role": "Director of Engineering",
                    "company": "Acme",
                    "is_customer": True,
                }
            ],
            "action_items": [
                {
                    "description": "Send POC scope",
                    "owner": "Dana",
                    "due_date": "Friday",
                    "status": "open",
                    "evidence_text": "Dana will send a POC scope by Friday.",
                    "confidence": 0.91,
                }
            ],
            "semantic_events": [
                {
                    "type": "security_requirement",
                    "category": "security",
                    "subject": "SOC 2",
                    "summary": "SOC 2 approval is a production gate.",
                    "evidence_text": "Acme said SOC 2 is required before production.",
                    "severity": "high",
                    "confidence": 0.94,
                },
                {
                    "type": "technical_objection",
                    "category": "integration",
                    "subject": "Salesforce integration",
                    "summary": "Integration work is blocking progress.",
                    "evidence_text": "They are blocked by Salesforce integration work.",
                    "severity": "medium",
                    "confidence": 0.88,
                },
                {
                    "type": "incumbent_solution",
                    "category": "crm",
                    "subject": "OldCRM",
                    "summary": "OldCRM is the incumbent solution.",
                    "evidence_text": "They mentioned OldCRM as the incumbent solution.",
                    "severity": "medium",
                    "confidence": 0.82,
                },
                {
                    "type": "product_feedback",
                    "category": "integration",
                    "subject": "Salesforce integration",
                    "summary": "Salesforce integration should be easier.",
                    "evidence_text": "They are blocked by Salesforce integration work.",
                    "severity": "medium",
                    "confidence": 0.8,
                },
            ],
            "entities": [
                {"name": "Acme", "entity_type": "company"},
                {"name": "SOC 2", "entity_type": "compliance_requirement"},
                {"name": "Salesforce", "entity_type": "integration"},
                {"name": "OldCRM", "entity_type": "competitor"},
            ],
            "relationships": [
                {
                    "source_entity_name": "Acme",
                    "source_entity_type": "company",
                    "relation_type": "requires",
                    "target_entity_name": "SOC 2",
                    "target_entity_type": "compliance_requirement",
                    "source_event_index": 0,
                    "evidence_text": "Acme said SOC 2 is required before production.",
                    "confidence": 0.94,
                },
                {
                    "source_entity_name": "Acme",
                    "source_entity_type": "company",
                    "relation_type": "blocked_by",
                    "target_entity_name": "Salesforce",
                    "target_entity_type": "integration",
                    "source_event_index": 1,
                    "evidence_text": "They are blocked by Salesforce integration work.",
                    "confidence": 0.88,
                },
            ],
        }
    )


@pytest.fixture
def repo() -> MeetingRepository:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return MeetingRepository(make_session_factory(engine))


def test_m1_schema_creates_all_tables():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = sa.inspect(engine)
    names = set(inspector.get_table_names())
    assert set(MEETING_TABLES).issubset(names)


def test_m2_parser_accepts_wrapped_json_and_validates_event_enum():
    raw = "model prose\n```json\n" + json.dumps(_analysis().model_dump()) + "\n```"
    parsed = ma.parse_meeting_analysis(raw)
    assert parsed.semantic_events[0].type == "security_requirement"
    bad = _analysis().model_dump()
    bad["semantic_events"][0]["type"] = "pricing_feedback"
    with pytest.raises(ValueError):
        ma.MeetingAnalysisResult(**bad)


def test_m2_evidence_must_come_from_summary():
    parsed = _analysis()
    ma.validate_evidence_from_summary(parsed, SUMMARY)
    bad = parsed.model_copy(deep=True)
    bad.semantic_events[0].evidence_text = "Acme privately hates audits."
    with pytest.raises(ValueError, match="source summary"):
        ma.validate_evidence_from_summary(bad, SUMMARY)


def test_m3_service_persists_meeting_graph(repo, monkeypatch):
    def fake_llm(company_name, summary, *, lang="en", client=None):
        return _analysis(), {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }, "claude-sonnet-test"

    monkeypatch.setattr(ma, "analyze_meeting_summary", fake_llm)
    detail = service.analyze_meeting_summary(
        company_name="Acme",
        summary=SUMMARY,
        repository=repo,
        lang="en",
    )

    assert detail["summary"] == SUMMARY
    assert detail["source_type"] == "summary"
    assert detail["insight"]["metadata_json"]["model"] == "claude-sonnet-test"
    assert len(detail["action_items"]) == 1
    assert detail["action_items"][0]["status"] == "open"
    assert {e["type"] for e in detail["semantic_events"]} >= {
        "technical_objection",
        "product_feedback",
    }
    assert detail["relationships"]
    assert all(r["source_event_id"] for r in detail["relationships"])


def test_m4_semantic_aggregations_are_visualization_ready(repo, monkeypatch):
    monkeypatch.setattr(
        ma,
        "analyze_meeting_summary",
        lambda *args, **kwargs: (_analysis(), {}, "test-model"),
    )
    service.analyze_meeting_summary(
        company_name="Acme", summary=SUMMARY, repository=repo, lang="en"
    )

    objections = service.objections_by_category(repo)
    assert objections[0]["category"] == "integration"
    assert objections[0]["count"] == 1
    assert objections[0]["events"][0]["company_name"] == "Acme"

    open_items = service.open_action_items(repo)
    assert open_items[0]["description"] == "Send POC scope"
    assert open_items[0]["company_name"] == "Acme"

    feedback = service.product_feedback_candidates(repo)
    assert feedback[0]["type"] == "product_feedback"

    topics = service.top_topics(repo)
    assert any(t["topic"] == "Salesforce integration" for t in topics)


def test_m5_builds_chroma_ready_index_payload(repo, monkeypatch):
    monkeypatch.setattr(
        ma,
        "analyze_meeting_summary",
        lambda *args, **kwargs: (_analysis(), {}, "test-model"),
    )
    meeting = service.analyze_meeting_summary(
        company_name="Acme", summary=SUMMARY, repository=repo, lang="en"
    )
    chunks = build_meeting_index_payload(meeting)
    assert chunks[0].id.endswith(":summary")
    assert chunks[0].text == SUMMARY
    event_chunks = [c for c in chunks if c.metadata["source_type"] == "meeting_semantic_event"]
    assert event_chunks
    assert event_chunks[0].metadata["meeting_id"] == meeting["id"]
    assert "evidence_text" in event_chunks[0].metadata
