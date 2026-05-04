# Commands

Phase-by-phase command catalog. CLAUDE.md `## Common commands` keeps only the five most-used invocations — anything debugging-specific or smoke-test-flavored lives here.

Use the project Conda Python directly (`~/miniconda3/envs/bd-coldcall/python.exe`) — never `python` / `py` (they hit the Microsoft Store stub on a fresh Windows box).

## Tests

```bash
# All unit tests (excludes live network smoke by default when key missing)
~/miniconda3/envs/bd-coldcall/python.exe -m pytest

# Single test
~/miniconda3/envs/bd-coldcall/python.exe -m pytest tests/test_brave.py::test_freshness_mapping -v
```

## Phase 1 — Brave search probe

Hits the real Brave Search API. Sanity check that bilingual blend + body fetch work end-to-end.

```bash
~/miniconda3/envs/bd-coldcall/python.exe -m src.search.brave \
    --query "AI 산업" --lang ko --days 30 --count 20 --fetch-bodies --save
```

`--save` writes JSON + Markdown to `outputs/search/<timestamp>_<...>.json` — prefer over stdout-only when debugging retrieval quality.

## Phase 2 — preprocess

Loads Exaone 4-bit + bge-m3, runs translate → 9-tag classify → dedup on a saved Brave search JSON.

```bash
~/miniconda3/envs/bd-coldcall/python.exe -m src.llm.preprocess \
    --input outputs/search/<timestamp>_<...>.json --lang en --save
```

## Phase 3 — RAG indexing

`data/company_docs/*.{md,txt,pdf}` + optional Notion. Manifest at `data/vectorstore/<workspace>/<namespace>/manifest.json`.

```bash
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer                 # incremental (hash-compare)
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --force         # reindex all
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --dry-run       # report-only, no mutation
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --verify        # manifest ↔ store drift check
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --notion        # include Notion pages + DBs
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --workspace <slug>     # index one external workspace
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --all-workspaces       # iterate every registered workspace
```

## Phase 4 — synthesize/draft smoke

End-to-end (retrieve → synthesize → draft) on a preprocessed JSON. 2 Sonnet calls, ~$0.10–0.50.

```bash
~/miniconda3/envs/bd-coldcall/python.exe -m scripts.smoke_phase4 \
    --preprocess-json outputs/preprocess/<timestamp>_en.json \
    --company NVIDIA --industry semiconductor --lang en
# Writes outputs/{company}_{YYYYMMDD}.md + outputs/intermediate/{company}_{YYYYMMDD}_points.json
```

## Phase 5 — full pipeline smoke

Search → fetch → preprocess → retrieve → synthesize → draft → persist. ~180s end-to-end (Brave + Exaone 4-bit + bge-m3 + 2 Sonnet calls), ~$0.30–0.60.

```bash
~/miniconda3/envs/bd-coldcall/python.exe -m scripts.smoke_phase5 \
    --company NVIDIA --industry semiconductor --lang en --verbose
# Writes outputs/{company}_{YYYYMMDD}/proposal.md +
# intermediate/{articles_after_preprocess,tech_chunks,points,run_summary}.json
```

## Phase 6 — top-level CLI

Unified entry point (wraps `src/core/orchestrator.run` + `src/rag/indexer.main`).

```bash
~/miniconda3/envs/bd-coldcall/python.exe main.py --help
~/miniconda3/envs/bd-coldcall/python.exe main.py run --company NVIDIA --industry semiconductor --lang en --verbose
~/miniconda3/envs/bd-coldcall/python.exe main.py ingest --notion --dry-run
~/miniconda3/envs/bd-coldcall/python.exe main.py ingest --verify
```

## Phase 7 — Web API + UI (dev)

```bash
# FastAPI backend (uvicorn autoreload). API_SKIP_WARMUP=1 skips the 30s Exaone warm-load
# so frontend dev is fast; drop the flag when you want the real pipeline.
API_SKIP_WARMUP=1 ~/miniconda3/envs/bd-coldcall/python.exe -m uvicorn src.api.app:app --reload

# Next.js 15 frontend (runs outside the conda env)
cd web && npm install && npm run dev    # http://localhost:3000
```

## Phase 9 — RAG-only target discovery

Sonnet 1-shot, 5 industries × 5 companies = 25, ~$0.04. No Brave / no Exaone — pure RAG + Sonnet.

```bash
~/miniconda3/envs/bd-coldcall/python.exe main.py discover --lang en \
    --seed-summary "One-paragraph product summary."
# Writes outputs/discovery_{YYYYMMDD}/{candidates.yaml, report.md}
```

## Notes

- `--save` flags persist JSON / Markdown under `outputs/` for retrieval-quality debugging — prefer over stdout-only.
- For environment setup (Miniconda install + ToS acceptance + env create) see `docs/lesson-learned.md`.
- For phase-by-phase progress and known smoke results, see `docs/status.md`.
