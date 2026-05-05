# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dev environment

Conda-based on Windows. The env is named `bd-coldcall` and lives at `~/miniconda3/envs/bd-coldcall/`. Use its Python directly — never `python` / `py`, which hit the Microsoft Store stub on a fresh Windows box.

```bash
# Run anything in the env
~/miniconda3/envs/bd-coldcall/python.exe -m <module> [args]

# Install Phase 1 (always-installable) deps
~/miniconda3/envs/bd-coldcall/python.exe -m pip install -r requirements.txt

# Install Phase 2+ ML deps — pick CUDA or CPU torch index FIRST
~/miniconda3/envs/bd-coldcall/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu121
~/miniconda3/envs/bd-coldcall/python.exe -m pip install -r requirements-ml.txt
```

If the env doesn't exist yet, see the setup steps in `docs/lesson-learned.md` (Miniconda install → ToS acceptance → env create). That file also captures Windows-specific gotchas worth re-reading before debugging obscure failures.

## Common commands

Use the project Conda Python directly (`~/miniconda3/envs/bd-coldcall/python.exe`) — never `python` / `py`.

```bash
# Tests
~/miniconda3/envs/bd-coldcall/python.exe -m pytest

# Top-level CLI
~/miniconda3/envs/bd-coldcall/python.exe main.py --help
~/miniconda3/envs/bd-coldcall/python.exe main.py run --company NVIDIA --industry semiconductor --lang en --verbose
~/miniconda3/envs/bd-coldcall/python.exe main.py ingest [--notion] [--force] [--dry-run] [--verify]
~/miniconda3/envs/bd-coldcall/python.exe main.py discover --lang en --seed-summary "..."

# Web API + UI (dev)
API_SKIP_WARMUP=1 ~/miniconda3/envs/bd-coldcall/python.exe -m uvicorn src.api.app:app --reload
cd web && npm install && npm run dev    # http://localhost:3000
```

Phase-by-phase smoke commands and saved-output flags: `docs/commands.md`.

## Notion RAG setup

To enable `--notion` on the indexer:

1. <https://www.notion.so/my-integrations> → **New integration** → Internal → copy the secret
2. Put `NOTION_TOKEN=secret_...` in `.env`
3. In Notion, open each page/DB to index → `...` → **Add connections** → pick this integration
4. List the page/DB UUIDs in `config/targets.yaml` under `rag.notion_page_ids` / `rag.notion_database_ids`

## Architecture — the big picture

Six-stage LangGraph pipeline, designed around a **dual-model role split** (not a summarize-then-synthesize hand-off):

```
[target company + industry + lang]
  → [1]   Brave Search API (news + web, en/ko, bilingual blend)
  → [1.5] Fetch — trafilatura + ThreadPool (fills Article.body)
  → [2]   Local Exaone 7.8B (4-bit) — DETERMINISTIC PREPROCESSING ONLY:
            translate (if lang != target) → 9-tag ENUM classify → bge-m3 dedup
  → [3]   ChromaDB + bge-m3 retrieval — our own tech docs
  → [4]   Claude Sonnet 4.6 — synthesize proposal points (reads full translated_body)
  → [5]   Claude Sonnet 4.6 — draft the final Markdown proposal
  → outputs/{company}_{YYYYMMDD}.md
```

Why this split: 7.8B-class models hallucinate on BD reasoning tasks, and funneling their summary JSON into Sonnet double-compresses context. So the local model sticks to deterministic work (translate, classify, dedup) where it's stable, and Sonnet receives the **full translated bodies** and does all reasoning in one place. The cost offset comes from (a) dedup (union-find over bge-m3 cosine ≥ 0.90 with a `min_articles_after_dedup` floor so we don't over-prune), (b) tag-tier selection at the Sonnet call (high-value 7 tags → full body, low-value 2 tags → snippet), and (c) `cache_control: ephemeral` on tech chunks so running many targets against the same company knowledge base stays near-free.

**Things that break this design** — push back when asked:
- Letting the local model produce BD summaries / proposal points — reintroduces hallucination + context loss.
- Sending all articles at full length to Sonnet regardless of tag — defeats the tier-based token savings.
- Changing the prompt-cache key on the tech-docs context — defeats the per-target amortization.

## DO NOT

- For monkeypatchable deps (LLM clients, I/O, network), import the module — `from src.api import runner as _runner` + `_runner.execute_run(...)` — not the symbol. Direct `from X import Y` binds at import time and silently slips false-greens. Applies to graph/pipeline/orchestrator/route layers. See `docs/lesson-learned.md` (2026-04-21) and `docs/playbook.md#2`.
- Tests that mutate `config/*.yaml` via `PUT /settings/{kind}` MUST use an isolated `CONFIG_DIR` fixture (`monkeypatch.setattr(_loader, "CONFIG_DIR", tmp)`) — pattern in `tests/test_api_settings.py::isolated_config`. Without it, prod yaml gets clobbered and may ship wrong values to all users. See `docs/lesson-learned.md` (2026-05-04).

### Config is 3-tier — do not collapse

- **`.env`** → secrets only (API keys). Gitignored. `.env.example` is the committed template.
- **`config/settings.yaml`** → non-secret runtime defaults (model names, quantization mode, chunk sizes, default lang). Committed.
- **`config/targets.yaml`** → user data: target companies, industry keyword templates, Notion page/DB IDs. Gitignored; `targets.example.yaml` is the committed template.

CLI flags override `settings.yaml`, which overrides schema defaults. This split is enforced by `src/config/schemas.py` (`Secrets` via pydantic-settings, `Settings` / `Targets` via plain BaseModel) and loaded by `src/config/loader.py`. Do not put LLM/search/RAG settings back into `.env` — that mixes secret lifecycle with config lifecycle and was intentionally undone.

### Shared core, multiple entry points

`src/core/orchestrator.run(company, industry, lang, ...)` is the shared entry point. Both consumers call it:

- **CLI** (`main.py`, Typer — Phase 6 done) — `main.py run` wraps `orchestrator.run()`, `main.py ingest` forwards to `src.rag.indexer.main()`.
- **Web UI** (Phase 7 done — `src/api/` FastAPI backend + `web/` Next.js 15 frontend) — Exaone + bge-m3 loaded once in the FastAPI `lifespan` event, `SqliteSaver` checkpointer persists runs across restarts, and the API exposes `orchestrator.run_streaming()` to drive SSE progress via the `status` / `current_stage` fields on `AgentState`. Frontend binds `EventSource` to `/runs/{id}/events` and refetches `/runs/{id}` on each tick for authoritative state.

When adding a new pipeline stage, wire it in `src/graph/` so both entry points get it for free. Don't duplicate orchestration logic in the CLI or API routes.

### Language policy

English is the default. Korean is a first-class alternative, not an afterthought. Prompts live under `src/prompts/{en,ko}/`; pick by `--lang` flag. Summarization output language follows the flag, independent of source article language.

## Dependency structure

Split on purpose — see `docs/lesson-learned.md` for why:

- `requirements.txt` — Phase 1+ essentials. Always installable on Windows without CUDA.
- `requirements-ml.txt` — Phase 2+ heavy ML (`torch`, `transformers`, `bitsandbytes`, `accelerate`, `chromadb`, `sentence-transformers`). Requires a CUDA or CPU torch install first via PyTorch's index URL.

Do not merge these back into one file. A CI or user without CUDA should be able to run Phase 1 and tests without touching ML wheels.

## Windows stdout encoding

New CLI entry points must reconfigure stdout/stderr to UTF-8 — Typer / Rich CLIs at **module load** (top of `main.py`), command-body printers inside the function. See `docs/playbook.md#9` for the framework-help timing rationale.

## Project docs convention

`docs/` has seven standing files — keep them current, don't let them rot:

- **`status.md`** — progress snapshot of what's **in flight or recently done**. Long-term plans live in `backlog.md`, not here.
- **`backlog.md`** — long-term plan / big-picture / out-of-scope ideas. `/projectrecord` promotes items to status on start, drops them on completion.
- **`architecture.md`** — pipeline shape, node boundaries, data flow. Updated when structure changes.
- **`lesson-learned.md`** — append-only, **failures only**. "Tried X, broke Y, here's why" entries so we don't repeat the same mistake.
- **`playbook.md`** — append-only, **successes only**. Patterns that survived a hard problem and are reusable elsewhere. Each entry has a Problem / Solution / Why-it-works / Reusable-in structure. **Check first when you hit an error or are stuck** — grep the keyword index at the top.
- **`commands.md`** — phase-by-phase command catalog (smoke scripts, RAG indexer flags, etc.). CLAUDE.md keeps only the five most-used invocations.
- **`security-audit.md`** — checklist + audit history. Review before release milestones.

Before a significant commit, update whichever of these are affected. `README.md` should only describe what already works, not roadmap.

## Notion integration

The project has a dedicated Notion workspace with a root page, `프로젝트 개요` (Project Overview), and `패치노트` (Patch Notes) sub-pages (see `reference_notion.md` in memory for IDs). Patch notes follow the same convention as the Groupstages project: version toggle header, date, witticism line, callout overview, then sectioned changes with colored tags. Use the `/patchnotes` skill to append new entries — don't hand-edit.
