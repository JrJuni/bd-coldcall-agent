"""Shared fixtures for Meeting Intelligence tests."""
from __future__ import annotations

from src.llm import meeting_analysis as ma


def sample_summary() -> str:
    return (
        "Acme said SOC 2 is required before production. "
        "They are blocked by Salesforce integration work. "
        "Dana will send a POC scope by Friday. "
        "They mentioned OldCRM as the incumbent solution."
    )


def sample_analysis() -> ma.MeetingAnalysisResult:
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
