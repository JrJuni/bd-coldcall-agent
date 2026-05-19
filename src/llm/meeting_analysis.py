"""Summary-first Meeting Intelligence analysis contract.

This module owns the LLM-facing JSON schema and parser. It deliberately
does not handle raw transcripts; callers pass one already-produced meeting
summary, and the model turns it into structured BD/SE signals.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.config.loader import PROJECT_ROOT, get_settings
from src.llm.claude_client import USAGE_KEYS, chat_once
from src.llm.proposal_schemas import _extract_json


PROMPT_VERSION = "meeting_analysis.v1"
_SYSTEM_TASK_SEPARATOR = "---TASK---"

MEETING_EVENT_TYPES: tuple[str, ...] = (
    "pain_point",
    "business_goal",
    "success_metric",
    "technical_requirement",
    "integration_requirement",
    "security_requirement",
    "compliance_requirement",
    "deployment_constraint",
    "technical_objection",
    "buying_trigger",
    "budget_signal",
    "timeline_signal",
    "decision_criteria",
    "decision_process",
    "champion_signal",
    "blocker_signal",
    "competitor_mention",
    "incumbent_solution",
    "use_case",
    "solution_fit",
    "product_gap",
    "feature_request",
    "poc_scope_candidate",
    "action_item",
    "open_question",
    "risk_flag",
    "product_feedback",
)

MeetingEventType = Literal[
    "pain_point",
    "business_goal",
    "success_metric",
    "technical_requirement",
    "integration_requirement",
    "security_requirement",
    "compliance_requirement",
    "deployment_constraint",
    "technical_objection",
    "buying_trigger",
    "budget_signal",
    "timeline_signal",
    "decision_criteria",
    "decision_process",
    "champion_signal",
    "blocker_signal",
    "competitor_mention",
    "incumbent_solution",
    "use_case",
    "solution_fit",
    "product_gap",
    "feature_request",
    "poc_scope_candidate",
    "action_item",
    "open_question",
    "risk_flag",
    "product_feedback",
]

MeetingActionStatus = Literal["open", "in_progress", "done", "cancelled"]
MeetingSeverity = Literal["low", "medium", "high", "critical"]


def _coerce_metadata(data: Any) -> Any:
    if isinstance(data, dict) and "metadata" in data and "metadata_json" not in data:
        data["metadata_json"] = data.pop("metadata")
    return data


def _normalize_entity_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


class MeetingParticipantAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    is_customer: bool = True
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _metadata_alias(cls, data: Any) -> Any:
        return _coerce_metadata(data)


class MeetingActionItemAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    description: str = Field(..., min_length=1)
    owner: str | None = Field(default=None, max_length=200)
    due_date: str | None = Field(default=None, max_length=64)
    status: MeetingActionStatus = "open"
    evidence_text: str | None = Field(default=None, max_length=2000)
    confidence: float = 0.0
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _metadata_alias(cls, data: Any) -> Any:
        return _coerce_metadata(data)

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= float(v) <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return float(v)


class MeetingSemanticEventAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: MeetingEventType
    category: str | None = Field(default=None, max_length=120)
    subject: str = Field(..., min_length=1, max_length=240)
    summary: str = Field(..., min_length=1)
    evidence_text: str = Field(..., min_length=1, max_length=3000)
    severity: MeetingSeverity | None = None
    confidence: float = 0.0
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _metadata_alias(cls, data: Any) -> Any:
        return _coerce_metadata(data)

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= float(v) <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return float(v)


class SemanticEntityAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=240)
    entity_type: str = Field(default="other", min_length=1, max_length=80)
    normalized_name: str | None = Field(default=None, max_length=240)
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _metadata_alias(cls, data: Any) -> Any:
        return _coerce_metadata(data)

    @model_validator(mode="after")
    def _fill_normalized_name(self) -> "SemanticEntityAnalysis":
        if not self.normalized_name:
            self.normalized_name = _normalize_entity_name(self.name)
        return self


class SemanticRelationshipAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_entity_name: str = Field(..., min_length=1, max_length=240)
    source_entity_type: str = Field(default="other", min_length=1, max_length=80)
    relation_type: str = Field(..., min_length=1, max_length=80)
    target_entity_name: str = Field(..., min_length=1, max_length=240)
    target_entity_type: str = Field(default="other", min_length=1, max_length=80)
    source_event_index: int = Field(..., ge=0)
    evidence_text: str = Field(..., min_length=1, max_length=3000)
    confidence: float = 0.0
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = _coerce_metadata(data)
        if "source_entity" in data and "source_entity_name" not in data:
            data["source_entity_name"] = data.pop("source_entity")
        if "target_entity" in data and "target_entity_name" not in data:
            data["target_entity_name"] = data.pop("target_entity")
        return data

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= float(v) <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return float(v)


class MeetingAnalysisResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    meeting_summary: str = Field(..., min_length=1)
    suggested_stage: str | None = Field(default=None, max_length=120)
    follow_up_draft: str | None = None
    participants: list[MeetingParticipantAnalysis] = Field(default_factory=list)
    action_items: list[MeetingActionItemAnalysis] = Field(default_factory=list)
    semantic_events: list[MeetingSemanticEventAnalysis] = Field(default_factory=list)
    entities: list[SemanticEntityAnalysis] = Field(default_factory=list)
    relationships: list[SemanticRelationshipAnalysis] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "events" in data and "semantic_events" not in data:
            data["semantic_events"] = data.pop("events")
        if "actions" in data and "action_items" not in data:
            data["action_items"] = data.pop("actions")
        if "follow_up_email_draft" in data and "follow_up_draft" not in data:
            data["follow_up_draft"] = data.pop("follow_up_email_draft")
        return data

    @model_validator(mode="after")
    def _relationship_event_indices(self) -> "MeetingAnalysisResult":
        n = len(self.semantic_events)
        for rel in self.relationships:
            if rel.source_event_index >= n:
                raise ValueError(
                    "relationship.source_event_index points outside "
                    f"semantic_events (index={rel.source_event_index}, count={n})"
                )
        return self


def _load_prompt(lang: Literal["en", "ko"]) -> tuple[str, str]:
    path = PROJECT_ROOT / "src" / "prompts" / lang / "meeting_analysis.txt"
    content = path.read_text(encoding="utf-8")
    parts = content.split(_SYSTEM_TASK_SEPARATOR, 1)
    if len(parts) != 2:
        raise ValueError(
            f"meeting_analysis.txt ({lang}) must contain "
            f"{_SYSTEM_TASK_SEPARATOR!r}"
        )
    return parts[0].strip(), parts[1].strip()


def parse_meeting_analysis(raw: str) -> MeetingAnalysisResult:
    parsed: Any = _extract_json(raw)
    if parsed is None:
        raise ValueError("no JSON found in model output")
    if not isinstance(parsed, dict):
        raise ValueError(
            f"expected JSON object for MeetingAnalysisResult, got {type(parsed).__name__}"
        )
    return MeetingAnalysisResult(**parsed)


def _norm_for_evidence(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def validate_evidence_from_summary(
    analysis: MeetingAnalysisResult, source_summary: str
) -> None:
    """Ensure every evidence_text is grounded in the pasted summary.

    The check is whitespace/case tolerant but still requires the model to
    copy evidence from the summary instead of inventing provenance.
    """
    haystack = _norm_for_evidence(source_summary)
    if not haystack:
        raise ValueError("source summary must be non-empty")

    evidence_items: list[tuple[str, str]] = []
    for idx, event in enumerate(analysis.semantic_events):
        evidence_items.append((f"semantic_events[{idx}].evidence_text", event.evidence_text))
    for idx, action in enumerate(analysis.action_items):
        if action.evidence_text:
            evidence_items.append((f"action_items[{idx}].evidence_text", action.evidence_text))
    for idx, rel in enumerate(analysis.relationships):
        evidence_items.append((f"relationships[{idx}].evidence_text", rel.evidence_text))

    for field, evidence in evidence_items:
        if _norm_for_evidence(evidence) not in haystack:
            raise ValueError(f"{field} must be copied from the source summary")


def analyze_meeting_summary(
    company_name: str,
    summary: str,
    *,
    lang: Literal["en", "ko"] = "en",
    client: Any | None = None,
) -> tuple[MeetingAnalysisResult, dict[str, int], str]:
    """Analyze one pasted meeting summary with Sonnet.

    Returns `(analysis, usage, model_id)`. The parser is JSON-structural
    rather than prose-sensitive; callers can mock this function in service
    tests to avoid live LLM work.
    """
    if not company_name or not company_name.strip():
        raise ValueError("company_name must be non-empty")
    if not summary or not summary.strip():
        raise ValueError("summary must be non-empty")

    settings = get_settings()
    system, task_template = _load_prompt(lang)
    task = task_template.format(
        company_name=company_name.strip(),
        summary=summary.strip(),
        event_types=", ".join(MEETING_EVENT_TYPES),
    )
    max_tokens = settings.llm.claude_max_tokens_draft
    base_temp = settings.llm.claude_temperature
    temperatures = [base_temp, min(base_temp + 0.1, 1.0)]

    total_usage: dict[str, int] = {k: 0 for k in USAGE_KEYS}
    last_model = settings.llm.claude_model
    last_error: Exception | None = None

    for temp in temperatures:
        resp = chat_once(
            system=system,
            user=task,
            max_tokens=max_tokens,
            temperature=temp,
            client=client,
        )
        resp_usage = resp.get("usage", {}) or {}
        for k in USAGE_KEYS:
            total_usage[k] += int(resp_usage.get(k, 0) or 0)
        last_model = resp.get("model") or last_model
        try:
            analysis = parse_meeting_analysis(resp["text"])
            validate_evidence_from_summary(analysis, summary)
            return analysis, total_usage, last_model
        except Exception as e:
            last_error = e
            continue

    raise ValueError(
        f"analyze_meeting_summary failed after {len(temperatures)} attempts: {last_error}"
    ) from last_error
