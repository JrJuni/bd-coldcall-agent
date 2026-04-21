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

## Commands

```bash
# All unit tests (excludes live network smoke by default when key missing)
~/miniconda3/envs/bd-coldcall/python.exe -m pytest

# Single test
~/miniconda3/envs/bd-coldcall/python.exe -m pytest tests/test_brave.py::test_freshness_mapping -v

# Brave search probe (Phase 1 sanity check, hits real API)
~/miniconda3/envs/bd-coldcall/python.exe -m src.search.brave --query "AI 산업" --lang ko --days 30 --count 20 --fetch-bodies --save

# Phase 2 preprocess on a saved brave search JSON (loads Exaone 4bit + bge-m3)
~/miniconda3/envs/bd-coldcall/python.exe -m src.llm.preprocess --input outputs/search/<timestamp>_<...>.json --lang en --save

# Phase 3 RAG indexing (data/company_docs/*.md,txt,pdf + optional Notion)
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer                 # incremental (hash-compare)
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --force         # reindex all
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --dry-run       # report-only, no mutation
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --verify        # manifest ↔ store drift check
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --notion        # include Notion pages + DBs

# Phase 4 end-to-end smoke (retrieve → synthesize → draft; 2 Sonnet calls, ~$0.10-0.50)
~/miniconda3/envs/bd-coldcall/python.exe -m scripts.smoke_phase4 \
    --preprocess-json outputs/preprocess/<timestamp>_en.json \
    --company NVIDIA --industry semiconductor --lang en
# Writes outputs/{company}_{YYYYMMDD}.md + outputs/intermediate/{company}_{YYYYMMDD}_points.json

# Phase 5 full pipeline smoke (search → fetch → preprocess → retrieve → synthesize → draft → persist)
# ~180s end-to-end (Brave + Exaone 4bit + bge-m3 + 2 Sonnet calls), ~$0.30-0.60
~/miniconda3/envs/bd-coldcall/python.exe -m scripts.smoke_phase5 \
    --company NVIDIA --industry semiconductor --lang en --verbose
# Writes outputs/{company}_{YYYYMMDD}/proposal.md + intermediate/{articles_after_preprocess,tech_chunks,points,run_summary}.json

# Phase 6 top-level CLI — unified entry point (wraps orchestrator + indexer)
~/miniconda3/envs/bd-coldcall/python.exe main.py --help
~/miniconda3/envs/bd-coldcall/python.exe main.py run --company NVIDIA --industry semiconductor --lang en --verbose
~/miniconda3/envs/bd-coldcall/python.exe main.py ingest --notion --dry-run
~/miniconda3/envs/bd-coldcall/python.exe main.py ingest --verify
```

`--save` writes JSON (+ Markdown for brave) to `outputs/search/` and `outputs/preprocess/` — prefer this over stdout-only when debugging retrieval quality.

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

- **테스트에서 monkeypatch 해야 하는 의존성**(부수효과 있는 외부 호출·네트워크·LLM·I/O 클라이언트 등)을 `from X import Y` 형태로 직접 바인딩하지 마라. import 시점에 참조가 고정되어 patch 가 안 먹을 수 있고, 테스트가 원본 구현을 조용히 호출해 false green 이 난다. 대신 모듈 자체를 import 한 뒤 (`from src import foo as _foo`) 런타임에 `_foo.Y` 로 접근하라. graph / pipeline / orchestrator 계층은 이 규칙을 기본값으로 삼는다. 단, 상수·타입·예외 클래스 등 patch 대상이 아닌 심볼은 적용 대상이 아니다. (출처: `docs/lesson-learned.md` 2026-04-21 LangGraph monkeypatch 섹션)

### Config is 3-tier — do not collapse

- **`.env`** → secrets only (API keys). Gitignored. `.env.example` is the committed template.
- **`config/settings.yaml`** → non-secret runtime defaults (model names, quantization mode, chunk sizes, default lang). Committed.
- **`config/targets.yaml`** → user data: target companies, industry keyword templates, Notion page/DB IDs. Gitignored; `targets.example.yaml` is the committed template.

CLI flags override `settings.yaml`, which overrides schema defaults. This split is enforced by `src/config/schemas.py` (`Secrets` via pydantic-settings, `Settings` / `Targets` via plain BaseModel) and loaded by `src/config/loader.py`. Do not put LLM/search/RAG settings back into `.env` — that mixes secret lifecycle with config lifecycle and was intentionally undone.

### Shared core, multiple entry points

`src/core/orchestrator.run(company, industry, lang, ...)` is the shared entry point. Both consumers call it:

- **CLI** (`main.py`, Typer — Phase 6 done) — `main.py run` wraps `orchestrator.run()`, `main.py ingest` forwards to `src.rag.indexer.main()`.
- **Web UI** (Phase 7 — `src/api/` FastAPI backend + `web/` Next.js frontend) — Exaone loaded once in the FastAPI `lifespan` event and reused; long pipelines stream progress via SSE using the `status` / `current_stage` fields on `AgentState`.

When adding a new pipeline stage, wire it in `src/graph/` so both entry points get it for free. Don't duplicate orchestration logic in the CLI or API routes.

### Language policy

English is the default. Korean is a first-class alternative, not an afterthought. Prompts live under `src/prompts/{en,ko}/`; pick by `--lang` flag. Summarization output language follows the flag, independent of source article language.

## Dependency structure

Split on purpose — see `docs/lesson-learned.md` for why:

- `requirements.txt` — Phase 1+ essentials. Always installable on Windows without CUDA.
- `requirements-ml.txt` — Phase 2+ heavy ML (`torch`, `transformers`, `bitsandbytes`, `accelerate`, `chromadb`, `sentence-transformers`). Requires a CUDA or CPU torch install first via PyTorch's index URL.

Do not merge these back into one file. A CI or user without CUDA should be able to run Phase 1 and tests without touching ML wheels.

## Windows-specific: stdout encoding

CLI entry points must reconfigure stdout/stderr to UTF-8 before printing non-ASCII **or before a framework (Rich/Typer) renders help text at import time**. Windows consoles default to cp949/cp1252 and silently mojibake Korean output; Rich fails loudly on em-dash.

- Command-body printing only: call `sys.stdout.reconfigure(encoding="utf-8")` inside the entrypoint function, like `src/search/brave.py`'s `__main__`.
- Typer CLIs that render `--help` before any command runs: reconfigure at **module load**, like `main.py` (top-level `for _stream in (sys.stdout, sys.stderr): _stream.reconfigure(encoding="utf-8")`). Inside-command reconfigure is too late for Rich's help renderer.

## Project docs convention

`docs/` has four standing files — keep them current, don't let them rot:

- **`status.md`** — single source of truth for phase progress and long-term backlog. README stays focused on project description; roadmap lives here.
- **`architecture.md`** — updated when the pipeline shape, node boundaries, or data flow change.
- **`lesson-learned.md`** — append-only. Record failed approaches + why, and non-obvious successes. The Windows setup gotchas, conda ToS issue, and requirements split rationale all live here.
- **`security-audit.md`** — checklist + audit history. Review before release milestones.

Before a significant commit, update whichever of these are affected. `README.md` should only describe what already works, not roadmap.

## Notion integration

The project has a dedicated Notion workspace with a root page, `프로젝트 개요`, and `패치노트` sub-pages (see `reference_notion.md` in memory for IDs). Patch notes follow the same convention as the Groupstages project: version toggle header, date, witticism line, callout overview, then sectioned changes with colored tags. Use the `/patchnotes` skill to append new entries — don't hand-edit.
