# Meeting Intelligence Module

Status: standalone backend module, not yet wired into the production FastAPI app
or shared database migration chain.

## Implemented

- Summary-first LLM analysis contract in `src.llm.meeting_analysis`.
- Standalone SQLAlchemy schema under `src.meeting_intelligence.models`.
- Repository persistence for:
  - meetings
  - meeting_participants
  - meeting_insights
  - meeting_action_items
  - meeting_semantic_events
  - semantic_entities
  - semantic_entity_mentions
  - semantic_relationships
- Service entry point:
  - `analyze_meeting_summary(company_name, summary, repository, lang)`
- Mountable FastAPI router:
  - `POST /meetings/analyze`
  - `GET /meetings/{id}`
  - `GET /semantic/meetings/{id}/brief`
  - `GET /semantic/meetings/recent`
  - `GET /semantic/objections/by_category`
  - `GET /semantic/action-items/open`
  - `GET /semantic/product-feedback/candidates`
  - `GET /semantic/topics/top`
- Chroma-ready payload builder without performing vector upsert.

## Guardrails

- Input is `summary` only.
- Raw transcript, diarization, audio upload, Notion write, and account matching
  are out of scope.
- `evidence_text` is validated against the source summary.
- Semantic event types are enum-validated.
- Relationships persist `source_event_id` provenance.

## Deferred Integration

- Add shared Alembic/PostgreSQL migration after the current DB refactor settles.
- Register the router in `src/api/app.py` after API route ownership is stable.
- Decide whether the final model classes should move into `src/api/models` or
  stay module-local with explicit migration imports.
- Add MCP function wrappers over the service functions.
