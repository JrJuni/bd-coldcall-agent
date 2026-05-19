# bd-coldcall-agent

> Agent-first BD intelligence platform — driven from Claude Desktop (MCP) and Codex, with a Notion workspace as the durable knowledge layer. The Web UI is observability for the same backend.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-1C3C3C)
![MCP](https://img.shields.io/badge/MCP-stdio-7C3AED)
![DB](https://img.shields.io/badge/DB-SQLite_%E2%87%84_Postgres-336791)
![Models](https://img.shields.io/badge/Models-Exaone_7.8B_|_Sonnet_4.6-FF6B6B)
![Status](https://img.shields.io/badge/status-Phase_13_complete-success)

## Overview

bd-coldcall-agent is an AI agent for B2B Business Development research and RFP / security-questionnaire answering. There are three surfaces over the same orchestration core:

- **MCP (primary)** — Claude Desktop / Codex call tools like `answer_rfp_question`, `query_rag`, and (Phase 14+) the rest of the BD entity surface. Tools write to the app DB and sync to Notion.
- **Notion workspace (durable layer)** — Two workspaces:
  - `BDINT_Teamspace` — working / evaluation layer. RFP draft answers, retrieved chunks, citations, evidence quality, reviewer notes, model/prompt versions accumulate here.
  - `BDINT_Publicspace` — curated knowledge layer. Reviewed Q&A get promoted here (Phase 13.5).
- **Web UI (observability)** — Next.js console for runs, RAG documents, cost, dashboard. The CRM-shaped `/targets` and `/interactions` pages are labeled "legacy" because Notion is now the system of record for those entities.

The same agent also still drives the original cold-call research pipeline: given a target company + industry, it produces a cited proposal in Markdown.

## Agent-first surface (Phase 13)

### MCP tools

| Tool | Description |
|---|---|
| `version` | App version + Python / platform / git sha — smoke test for Claude Desktop wiring. |
| `query_rag` | Retrieve top-k chunks from the project's ChromaDB corpus for a given workspace + namespace. |
| `answer_rfp_question` | End-to-end: retrieve → Claude Sonnet draft with citations → log to `rfp_answers` (SQLite/Postgres) → upsert page in BDINT_Teamspace RFP Q&A DB. |

Add the server to Claude Desktop's `claude_desktop_config.json` (see `docs/phase13.md` for the snippet) and the tools appear under `bd-coldcall-agent`. Stdio transport, no separate server process; HTTP/SSE is a Phase 14 follow-up.

### Dual-engine ORM (SQLite ↔ Postgres)

Phase 13B ported every store (`workspaces`, `rag_summaries`, `targets`, `interactions`, `discovery_runs`, `discovery_candidates`, `news_runs`, `rfp_answers`, `notion_sync_map`, `runs`) onto SQLAlchemy 2.x. The schema runs unmodified on either engine because JSON columns use `sa.JSON().with_variant(JSONB, "postgresql")`. Cutover script: `scripts/migrate_sqlite_to_postgres.py`.

LangGraph checkpoints follow the same URL dispatch (`SqliteSaver` ↔ `PostgresSaver`).

### RunStore persistence (Phase 13C)

In-flight pipeline runs stay in the process-local `RunStore` dict (with the SSE event log). When a run reaches `completed` / `failed`, a metadata snapshot writes to the `runs` table so the Web UI history page survives a process restart. Full rationale in `docs/phase13.md`.

## Pipeline (still here, still the engine)

Underneath the agent surface, the cold-call research run is the same six-stage LangGraph pipeline:

```
[target company + industry + lang]
  → [1]   Brave Search (news + web, en/ko, bilingual blend)
  → [1.5] Fetch — trafilatura + ThreadPool (fills Article.body)
  → [2]   Local Exaone 7.8B (4-bit) — deterministic only:
            translate → 9-tag classify → bge-m3 dedup
  → [3]   ChromaDB + bge-m3 retrieval — our tech docs
  → [4]   Claude Sonnet 4.6 — proposal points (reads full translated body)
  → [5]   Claude Sonnet 4.6 — drafted Markdown proposal
  → outputs/{company}_{YYYYMMDD}.md
```

The dual-model split (deterministic prep on a 7.8B model, all BD reasoning on Sonnet with `cache_control: ephemeral` on tech chunks) is intentional — see `CLAUDE.md` for the rationale.

## Tech stack

| Layer | Tool |
|-------|------|
| Agent transport | MCP stdio (Claude Desktop, Codex) |
| Orchestration | LangGraph + FastAPI |
| Local LLM | Exaone 7.8B (Transformers + bitsandbytes 4-bit) |
| Cloud LLM | Claude Sonnet 4.6 (Anthropic SDK, prompt caching) |
| Embeddings | `BAAI/bge-m3` (ko / en) |
| Vector store | ChromaDB (persistent) |
| App DB | SQLite (dev) ⇄ Postgres / Neon (production) via SQLAlchemy 2.x + Alembic |
| Checkpoints | `SqliteSaver` ⇄ `PostgresSaver` (URL-scheme dispatch) |
| Search | Brave Search API |
| Doc connectors | Local PDF / MD / TXT, Notion API (read), Notion writer (Phase 13) |
| Web frontend | Next.js 15 + Tailwind CSS + TypeScript |
| Language | Python 3.11+ |

## Requirements

- Python 3.11+
- GPU with 6–12 GB VRAM for 4-bit Exaone loading (fp16 mode needs ~16 GB)
- API keys: **Anthropic**, **Brave Search**, **Notion** (Notion is required for the Phase 13 RFP tool — separate integration tokens per Notion workspace; see `docs/phase13.md`).

## Getting started

```bash
# 1. Clone + install Phase 1 essentials
git clone https://github.com/<username>/bd-coldcall-agent.git
cd bd-coldcall-agent
pip install -r requirements.txt

# 2. Install Phase 2+ ML stack (pick a torch index URL first)
pip install torch --index-url https://download.pytorch.org/whl/cu121   # or .../whl/cpu
pip install -r requirements-ml.txt

# 3. Configure secrets and DB
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, BRAVE_SEARCH_API_KEY,
# NOTION_TEAMSPACE_TOKEN / NOTION_PUBLICSPACE_TOKEN (for RFP tool),
# and DATABASE_URL (sqlite:///data/app.db by default, or a Neon URL).
python -m alembic upgrade head

# 4. (Optional) Wire up Notion — see docs/phase13.md
cp config/notion.example.yaml config/notion.yaml
# Fill in the BDINT root page ids, then:
python scripts/bootstrap_notion.py

# 5. Drop company tech docs into data/company_docs/ and index
python main.py ingest

# 6a. Drive from the CLI
python main.py run --company "NVIDIA" --industry "semiconductor" --lang en

# 6b. ...or expose to Claude Desktop via MCP (stdio)
# Add the snippet from docs/phase13.md to claude_desktop_config.json,
# restart Claude Desktop, and call answer_rfp_question(...) directly.

# 6c. ...or run the FastAPI + Next.js stack
API_SKIP_WARMUP=1 python -m uvicorn src.api.app:app --reload
cd web && npm install && npm run dev    # http://localhost:3000
```

## Documentation

- `docs/phase13.md` — Phase 13 working doc: MCP setup, Notion integration, Neon cutover, RunStore decision.
- `docs/architecture.md` — pipeline shape, node boundaries, data flow.
- `docs/status.md` — progress snapshot.
- `docs/backlog.md` — long-term plan / out-of-scope ideas.
- `docs/playbook.md` — patterns that survived a hard problem.
- `docs/lesson-learned.md` — failures and the diagnosis.
- `docs/commands.md` — per-phase command catalog.
- `CLAUDE.md` — guidance for Claude Code when working on the repo.

## License

MIT
