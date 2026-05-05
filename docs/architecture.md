# Architecture

## 6-stage LangGraph Pipeline

```
[Input: company, industry, lang]
        │
        ▼
  ┌──────────────┐
  │  search      │  Brave Search API (news + web, en/ko, bilingual blend)
  └──────────────┘
        │  list[Article]  (snippet only)
        ▼
  ┌──────────────┐
  │  fetch       │  trafilatura + ThreadPool (Phase 1.5)
  └──────────────┘
        │  list[Article]  (body filled; snippet-fallback on paywall/403)
        ▼
  ┌──────────────────────┐
  │  preprocess (local)  │  Exaone 3.5 7.8B (4-bit) + bge-m3
  │   translate → tag    │    • translate body when lang != target
  │       → dedup        │    • 9-tag ENUM classify
  └──────────────────────┘    • cosine ≥ 0.90 union-find dedup (floor protected)
        │  list[Article]  (translated_body, tags, dedup_group_id)
        ▼
  ┌──────────────┐
  │  retrieve    │  ChromaDB + bge-m3  (our tech docs)
  └──────────────┘
        │  list[TechChunk]
        ▼
  ┌──────────────┐
  │  synthesize  │  Claude Sonnet 4.6 (prompt cache on tech chunks)
  └──────────────┘      tag-tier: high-value 7 tags → full translated_body
        │                        low-value 2 tags → snippet only
        │  list[ProposalPoint]
        ▼
  ┌──────────────┐
  │  draft       │  Claude Sonnet 4.6 → Markdown + source footnotes
  └──────────────┘
        │
        ▼
  outputs/{company}_{YYYYMMDD}.md
```

---

## Component Details

### 1. Search (`src/search/`)
- `SearchProvider` ABC — pluggable for free scrapers in the long term
- `BraveSearch` — implements `/v1/news/search` + `/v1/web/search`
- `bilingual.py` — for Korean queries, also runs an English query via translation lookup, guaranteeing foreign ≥ 50%
- Output: `Article(title, url, snippet, source, lang, published_at, metadata)` — body is empty

### 2. Fetch (`src/search/fetcher.py` — Phase 1.5)
- Parallel `httpx` + `trafilatura.extract(favor_precision=True)` calls via `ThreadPoolExecutor(max_workers=5)`
- Custom UA, per-url 10s timeout. On failure, copy snippet into body and mark `body_source="snippet"`
- Batch stats (`body_stats`) log full/snippet/empty ratios

### 3. Preprocess (`src/llm/preprocess.py` — Phase 2)
`src/llm/local_exaone.py` keeps Exaone 3.5 7.8B Instruct (4-bit nf4, double quant) resident on the GPU as a singleton, then runs three steps in sequence:

**3-1. Translate** (`src/llm/translate.py`)
- If `article.lang == target_lang`, passthrough (zero LLM calls)
- Else translate source → target via `src/prompts/{en,ko}/translate.txt`. Preserves proper nouns, numbers, quotes, titles
- On failure, copy original body into `translated_body` (so the pipeline doesn't break)

**3-2. Tag** (`src/llm/tag.py`)
- Fixed 9-tag ENUM (earnings / product_launch / partnership / leadership / regulatory / funding / m_and_a / tech_launch / other)
- JSON output enforced. `parse_tags()` extracts via regex even when output includes code fences/prose, ENUM-whitelist filters, falls back to `["other"]` on failure

**3-3. Dedup** (`src/rag/embeddings.py`)
- `BAAI/bge-m3` singleton embeds `translated_body` (L2 normalized)
- Upper-triangular cosine matrix → pairs above threshold sorted by similarity descending
- Union-find: representative selection key is `-len(body) → -published_at → index`
- **Floor-aware**: stops merging when group count drops to `min_articles_after_dedup` — reports `stopped_by_floor=True`
- Each article records `dedup_group_id` (≥0 = group member, -1 = solo)

### 4. RAG (`src/rag/`)

**Schema (`types.py`):** `Document` / `Chunk` / `RetrievedChunk`. Common fields (title, source_type, source_ref, last_modified, mime_type) are explicitly promoted; free-form fields land in `extra_metadata` and are JSON-serialized into a single `extra_json` Chroma metadata key.

**Normalization · chunking:**
- `normalize.py` — line-wise rstrip → collapse runs of ≥3 newlines to 2 → overall strip. Preserves internal whitespace/indent. Shared util for hash stability
- `chunker.py` — paragraph (`\n\n`) + sentence-based greedy packing. Overlap also at sentence-tail granularity. When a single sentence exceeds `chunk_size`, fall back to char-level hard-split + char-level overlap

**Connectors (`connectors/`):**
- `SourceConnector` ABC (`source_type` ClassVar + abstract `iter_documents()`)
- `LocalFileConnector` — recursive rglob, whitelisting `.md/.txt/.pdf`. PDF extracts page-by-page via pypdf with `[Page N]` separator. Skips scanned PDFs (all pages empty), warns + skips empty/stat-failed files
- `NotionConnector` — token or injected client. Pages via `pages.retrieve` + `databases.query` paginated. DFS over block tree to extract `rich_text.plain_text`; `child_page` becomes a separate Document (avoids duplication). Title rules: page = title property → heading fallback → `Untitled`, DB row = title property only

**Vector store (`store.py`):**
- `VectorStore(persist_path, collection_name)` — `chromadb.PersistentClient` + `get_or_create_collection(metadata={"hnsw:space":"cosine"})`
- Flattened metadata: `doc_id/chunk_index/title/source_type/source_ref/last_modified_iso/mime_type/extra_json`
- `similarity_score = 1 - distance/2` converts cosine distance to a 0–1 similarity (higher = more similar) — raw distance is not exposed externally

**Incremental indexer (`indexer.py`):**
- `run_indexer(connectors, store, manifest_path, ...)` — normalize → sha256 → manifest compare → chunk → embed → delete → upsert → manifest update
- **Atomicity:** embed must succeed before touching store/manifest. Mid-failure → state unchanged, next run recovers as `updated`
- **Incremental manifest:** `data/vectorstore/manifest.json` (v1). `{doc_id: {content_hash, last_modified, indexed_at, chunk_count, source_type}}`. Atomic swap via tmp → `os.replace`
- **Connector-isolated deletion:** only entries in the active `source_type` set are deletion candidates. `--notion` alone won't evict local entries
- CLI: `--local-dir` / `--no-local` / `--notion` / `--force` / `--dry-run` / `--verify`

**Retriever (`retriever.py`):**
- Module-singleton `VectorStore` reuse, `embed_texts([query])` → `store.query(emb, top_k)` → `list[RetrievedChunk]` (sorted by similarity_score descending). Empty-query guard. Designed so the Phase 4 synthesis node can build prompts without extra lookups

**Embedder:** `BAAI/bge-m3` (model is shared with preprocess dedup — `embeddings.get_embedder()` singleton)

### 5. Claude Agent (`src/llm/{claude_client,synthesize,draft}.py`)

**Client (`claude_client.py`):**
- `get_claude()` — Anthropic SDK singleton (lazy load, `ANTHROPIC_API_KEY` validation)
- `chat_cached(system, cached_context, volatile_context, task, max_tokens, temperature, model, client)` — splits user content into 3 blocks; **only the first block (tech_docs) carries `cache_control: ephemeral`**. Return dict includes `usage.cache_read_input_tokens` / `cache_creation_input_tokens`
- `chat_once(system, user, max_tokens, temperature, model, client)` — uncached single call (used by draft, where prompts are unique per target so caching has no benefit)

**Synthesis (`synthesize.py`):**
- `synthesize_proposal_points(articles, tech_chunks, *, target_company, industry, lang, client=None) -> list[ProposalPoint]`
- Prompt: `<tech_docs>` (cached) + `<articles>` (tag-tier applied body/snippet) + `<target>` + task
- **Tag tier (~35% input-token savings)**: high-value 7 (earnings, m_and_a, partnership, funding, regulatory, product_launch, tech_launch) → full `translated_body`; low-value 2 (leadership, other) → snippet only. `src/llm/tag_tier.py::select_body_or_snippet` / `has_high_value_tag`
- Article id is the `art_i` attribute, URL is also surfaced as an element attribute → model puts the URL straight into `evidence_article_urls`
- On JSON parse failure, retry once with `temperature +0.1` (cap 1.0); a second failure raises `ValueError`
- pydantic `ProposalPoint` validation: angle Literal of 5 (pain_point/growth_signal/tech_fit/risk_flag/intro), all but `intro` require ≥1 evidence URL

**Draft (`draft.py`):**
- `draft_proposal(points, articles, *, target_company, lang, client=None) -> ProposalDraft`
- 4-section Markdown (Overview / Key Points / Why Our Product / Next Steps)
- **Footnote pipeline**: code pre-assigns `[^1]..[^N]` to citation URLs in first-encounter order → passes `citation_map` to Sonnet → forgivingly renumbers `[^N]` in response (map hit first, miss → unused_pool fallback, drop when pool empty) → strips any `[^N]: URL` definition blocks Sonnet wrote → system regenerates accurate footnote definitions
- If `>1200 words`, log warn and return as-is (handled at Phase 5 retry edge)

**Schemas (`proposal_schemas.py`):** `ProposalPoint` + `ProposalDraft` + `_extract_json` (4-tier fallback: raw → code-fence → array regex → object regex) + `parse_proposal_points` (also accepts `{"points": [...]}` wrapper)

### 6. LangGraph (`src/graph/` — Phase 5 done)

**State (`state.py`):** `AgentState` TypedDict (`total=False`)
- inputs: `company, industry, lang, top_k`
- artifacts: `searched_articles` (search_node), `fetched_articles` (fetch_node), `processed_articles` (preprocess_node), `tech_chunks`, `proposal_points`, `proposal_md` — separating article lists per stage means we know which stage's output remains on the failure path
- meta: `errors` (list[dict]), `usage` (Anthropic 4-token accumulation), `stages_completed` (append-only), `failed_stage` (None | str), `status` (`"running" | "failed" | "completed"`), `current_stage` (None | str), `run_id`, `output_dir`, `started_at`, `ended_at`
- `new_state()` seed factory + `merge_usage()` pure reducer. `USAGE_KEYS` single source is `src/llm/claude_client.py`

**Errors (`errors.py`):** `TransientError` / `FatalError` exceptions + `StageError` dataclass (`{stage, error_type, message, ts}`) — `from_exception(stage, exc)` produces a serializable record

**Nodes (`nodes.py`):** 7 thin adapters. The actual logic reuses Phase 1–4 functions (`bilingual_news_search`, `fetch_bodies_parallel`, `preprocess_articles`, `retrieve`, `synthesize_proposal_points`, `draft_proposal`) as-is
- `@_stage(name)` decorator — catches exceptions and writes to `failed_stage` + `errors`, sets `current_stage = name` on both success and failure paths, appends to `stages_completed` on success. Doesn't differentiate TransientError (Phase 5 omits RetryPolicy)
- `search_node` — ko defaults to bilingual blend, en stays monolingual. `BraveSearch` is used as a context manager (close on session end)
- `fetch_node` / `preprocess_node` — no-op passthrough on empty articles
- `retrieve_node` — `top_k = state.top_k or settings.llm.claude_rag_top_k`
- `synthesize_node` / `draft_node` — each Sonnet call's usage accumulates into state via `merge_usage(state.usage, call_usage)`
- `persist_node` — always runs (even on failure path). Writes `intermediate/*.json` + `run_summary.json` from partial state. `articles_after_preprocess.json` records the latest-stage articles per `processed > fetched > searched` priority (helper `latest_articles()`); on failure path, `articles_searched.json` / `articles_fetched.json` are also dumped for stage-by-stage snapshots. Finalizes `status` (`failed` / `completed`), `ended_at`, `current_stage` (None on success, raising stage on failure). Uses `_to_jsonable` recursive serialization (dataclass/pydantic/datetime/Path)
- `route_after_stage` router — if `failed_stage` set, route to `"persist"` (skip all downstream stages); else `"continue"`

**Pipeline (`pipeline.py::build_graph()`):** `StateGraph(AgentState)` compiled
```
START → search ─┬─[continue]→ fetch ─┬─[continue]→ preprocess ─┬─[continue]→ retrieve ─┬─[continue]→ synthesize ─┬─[continue]→ draft → persist → END
                │                     │                         │                       │                         │                          ↑
                └───────[persist]─────┴───────[persist]──────────┴─────[persist]─────────┴────[persist]────────────┴────[persist]─────────────┘
```
- Stages 1–5 each use `add_conditional_edges(stage, route_after_stage, {"continue": next, "persist": persist})`. draft → persist is unconditional
- `MemorySaver` checkpointer (swapped to `SqliteSaver` in Phase 7 to support resumable execution)
- **RetryPolicy omitted** (Phase 5 decision): synthesize/draft already retry once with temperature +0.1 internally. Network-transient failures are rare, currently absorbed by cost. Revisit at Phase 7 long-running SSE

**Orchestrator (`src/core/orchestrator.py::run()`):** shared entry point for CLI (Phase 6) / FastAPI (Phase 7)
- `run(company, industry, lang, *, output_root=None, top_k=None, run_id=None) -> AgentState`
- `run_id` auto-generated (`{YYYYMMDD-HHMMSS}-{company}`), `output_dir = {root}/{company}_{YYYYMMDD}`
- `graph.invoke(state, config={"configurable": {"thread_id": run_id}})` — checkpointer snapshots state per step

**Outputs:** `outputs/{company}_{YYYYMMDD}/`
- `proposal.md` — final draft (omitted on failure)
- `intermediate/articles_after_preprocess.json` — latest-stage articles (typically post translate/tag/dedup; on failure path, prior-stage snapshot)
- `intermediate/articles_{searched,fetched}.json` — only on failure path. For per-stage diff analysis
- `intermediate/tech_chunks.json` — retrieve top-k
- `intermediate/points.json` — validated ProposalPoint list
- `intermediate/run_summary.json` — `{run_id, company, industry, lang, status, duration_s, started_at, ended_at, usage, errors, failed_stage, current_stage, stages_completed, proposal_md_path, generated_at}`

### 7. Web API (`src/api/` — Phase 7)

A thin layer where the FastAPI process keeps Exaone + bge-m3 singletons warm-stay, runs the **same `orchestrator`** as the CLI in the background, and streams progress over SSE.

**Lifespan (`app.py::lifespan`):**
- `anyio.to_thread.run_sync(local_exaone.load)` + `embeddings.get_embedder()` to eliminate first-request latency (~30s → 0). Skip with `API_SKIP_WARMUP=1` for tests/dev
- `build_sqlite_checkpointer(API_CHECKPOINT_DB)` opens connection with `sqlite3.connect(..., check_same_thread=False)`, wraps in `SqliteSaver`, stores in `app.state.checkpointer` — BackgroundTasks (worker thread) and SSE (event loop) share one connection, and `run_id` resumes are valid even after process restart
- CORS allowed origin via `API_CORS_ORIGINS` (default `http://localhost:3000`)

**Orchestrator dual entry:**
- `run(...)` — existing `graph.invoke()` (CLI). Returns final `AgentState`
- `run_streaming(...)` — `graph.stream(state, config, stream_mode="values")` yields each super-step state. FastAPI's `execute_run` consumes this to update `RunRecord` + append events

**RunStore / IngestStore (in-memory, `src/api/store.py`):**
- `RunRecord` — status (`queued|running|completed|failed`) + `current_stage` + `stages_completed` + `article_counts{searched,fetched,processed}` + `usage` + `proposal_md` + append-only `events: list[RunEvent{seq,kind,ts,payload}]`. Shared-state guarded with `threading.Lock`
- SSE endpoint uses `since_seq` polling (150ms) — no queue / coroutine-threadsafe plumbing; yields incrementally and closes the stream upon terminal-state detection

**Routes (`src/api/routes/`):**
```
GET  /healthz
POST /runs                     → 202 {run_id, status=queued, created_at}
GET  /runs                     → most-recent first
GET  /runs/{run_id}            → full summary + proposal_md
GET  /runs/{run_id}/events     → EventSourceResponse (SSE)
GET  /ingest/status            → manifest.json aggregation
POST /ingest                   → 202 {task_id}
GET  /ingest/tasks/{task_id}   → status
```

**DO NOT rule in practice:** `src/api/routes/runs.py` uses `from src.api import runner as _runner` + `_runner.execute_run(...)` to access via module — this lets tests do `monkeypatch.setattr("src.api.runner.execute_run", fake)` and avoid real Exaone/Sonnet calls. An earlier `from src.api.runner import execute_run` binding had caused a false-green (real LLM was called) and was reverted. `ingest.py`'s `get_settings` was changed to `from src.config import loader as _config_loader` for the same reason.

**Outputs:**
- API only keeps `RunRecord` in-memory (lost on process restart). Only LangGraph checkpoint persists in `API_CHECKPOINT_DB` — a dedicated execution-history table is on the long-term backlog
- Per-protocol layout — backend writes `outputs/{company}_{YYYYMMDD}/` directly, exposed via the `output_dir` field in `/runs/{run_id}` response

**Phase 10 extension (in progress) — `data/app.db` separation:**
- `src/api/db.py` persists 8-tab UI state in a SQLite file **separate** from langgraph `SqliteSaver` (which is checkpoint-only). Reason: SqliteSaver assumes sole ownership of its schema, so mixing app tables in could conflict on upgrades
- 5 tables: `discovery_runs` / `discovery_candidates` (FK CASCADE) / `targets` (FK SET NULL) / `interactions` (FK SET NULL) / `news_runs`
- `init_db()` is idempotent via `CREATE TABLE IF NOT EXISTS` + `executescript` — safe to call from lifespan on each boot
- `connect()` context manager: `row_factory=Row`, `PRAGMA foreign_keys=ON`, commit on normal exit / rollback on exception / always close
- env: `API_APP_DB` (default `data/app.db`)

### 8. Web UI (`web/` — Phase 7, Next.js 15 App Router)

- `/` form → `POST /runs` → redirect to `/runs/[id]`
- `/runs/[id]` — `EventSource(/runs/{id}/events)` SSE. On each event, refetch `GET /runs/{id}` for authoritative state. `StageProgress` component shows 7-stage badges; `react-markdown + remark-gfm` renders `proposal_md`
- `/rag` — calls `GET /ingest/status` and triggers `POST /ingest` (notion/force/dry_run toggles). Upload/delete UI is on the long-term backlog

The frontend reads only `NEXT_PUBLIC_API_BASE_URL` and holds no state of its own — easy to replace/extend.

**Phase 10 in progress — 8-tab expansion (P10-0 merged):**
- `web/src/components/Nav.tsx` — 8-tab nav with `usePathname()`-based active state. Mounted in `layout.tsx` header
- 8 tabs: Home (`/`) / Daily News (`/news`) / Discovery (`/discover`) / Targets (`/targets`) / Proposals (`/proposals`) / RAG Docs (`/rag`) / 사업 기록 / Business Records (`/interactions`) / Settings (`/settings`)
- At P10-0, skeleton complete with 6 stub pages + shared `StubPage.tsx` (title + ship-PR label + responsibility blurb). Real features fill in across P10-1 through P10-8
- Existing `/` (Run form) + `/runs/[id]` + `/rag` keep working — Phase 10 is additive, not breaking (Run form will move to `/proposals/new` in P10-4)

---

### 9. Target Discovery (`src/core/discover.py` — Phase 9 + 9.1, RAG-only sibling flow)

A separate entry point that reverse-infers "who would buy our product" using RAG only, without a known target company. Skips the 6-stage pipeline (search/fetch/preprocess/...) — uses retrieve only → 1 Sonnet call → outputs flat yaml + grouped md pair.

**Phase 9.1 core change**: narrowed the LLM's role from "tier judgment" to "0–10 scoring across 6 dimensions"; `final_score` and `tier` are now decided deterministically by code via `config/weights.yaml` + `config/tier_rules.yaml`. To counter mega-cap bias, added `config/sector_leaders.yaml` seed + region flag.

```
[Input: lang, n_industries=5, n_per_industry=5, seed_summary?,
        product="databricks", region="any", include_sector_leaders=True]
        │
        ▼
  ┌──────────────────────────┐
  │  retrieve(seed_query, top_k=20)   │  ChromaDB + bge-m3 (reused)
  │  manifest_path_for / load_manifest │  seed_doc_count / seed_chunk_count
  └──────────────────────────┘
        │
        ▼
  cached_context = <knowledge_base>     (Sonnet ephemeral cache)
  volatile_context =
    <product_summary>...                (optional, seed_summary)
    <region_constraint>{region}          (when region != "any")
    <sector_leader_seeds region="...">   (when include_sector_leaders)
        │
        ▼
  ┌──────────────────────────┐
  │  chat_cached (Sonnet 4.6)         │  output: scores{6 dim 0-10}+rationale
  │   + 1 retry (temp +0.1)           │  parse_discovery silently drops LLM's tier output
  └──────────────────────────┘
        │
        ▼
  ┌──────────────────────────┐
  │  scoring (code, $0)               │  weights = load_weights(product) + auto-normalize
  │  for c in candidates:             │  rules = load_tier_rules() (S/A/B/C threshold)
  │    c.final_score = weighted sum   │  c.tier = decide_tier(...) (epsilon 1e-6)
  │    c.tier = first-match           │
  └──────────────────────────┘
        │  DiscoveryResult (scores + final_score + tier all populated)
        ▼
  outputs/discovery_{YYYYMMDD}/
    ├ candidates.yaml   (flat: name/industry/scores{6}/final_score/tier/rationale)
    └ report.md         (S/A/B by industry + ⚠️ Strategic Edge [C] separate section)
```

**Schema (`discover_types.py`):**
- `Candidate` (pydantic) — `name`/`industry`/`scores: dict[str,int]` (6 dim 0–10)/`rationale`/`final_score: float`/`tier: Tier`. LLM emits only the first 4; the latter 2 are populated by code
- `parse_discovery` silently drops the LLM's `tier` / `final_score` outputs (preserves code-side authority)
- `_extract_json_object` (raw → fenced → object only) — dict-caller priority

**Scoring (`scoring.py` — added in Phase 9.1):**
- `WEIGHT_DIMENSIONS` 6 (pain_severity / data_complexity / governance_need / ai_maturity / buying_trigger / displacement_ease)
- `load_weights(product=None)` — load yaml → merge default + product override → validate completeness → auto-normalize + warn when sum ≠ 1.0
- `load_tier_rules()` — descending sort + 4 tiers (S/A/B/C) enforced
- `calc_final_score(scores, weights)` — weighted sum
- `decide_tier(final_score, rules)` — first-match descending. epsilon 1e-6 absorbs normalize float drift (e.g. `7×normalized ≈ 6.9999...` still hits A)
- Value of code-side decision: **recomputing the same LLM response under different weights = $0 extra cost**. Other products (Snowflake/Salesforce etc.) reuse via `products.<name>` override in weights.yaml

**Sector leaders seed (`config/sector_leaders.yaml` — added in Phase 9.1):**
- Flat list: `name` / `industry_hint` / `region` (ko/us/eu/global) / `notes?`
- Injected into LLM as inspiration via `<sector_leader_seeds region="...">` in `_render_volatile` → softens mega-cap bias (mid-market/local entries like Stripe/Adyen/Toss/KB Financial/Naver/Kakao)
- `region` flag (any/ko/us/eu/global) — "any" → all seeds; explicit region → that region + global only
- Gitignored ops yaml (same pattern as `competitors.yaml` / `intent_tiers.yaml`). `scripts/draft_sector_leaders.py` produces a Sonnet 1-shot draft

**Core function (`discover.py`):**
- `discover_targets(*, lang, n_industries=5, n_per_industry=5, seed_summary=None, seed_query=..., product="databricks", region="any", include_sector_leaders=True, output_root=None, top_k=20, client=None, write_artifacts=True) -> DiscoveryResult`
- max_tokens is `claude_max_tokens_discover=6000` (Phase 9.1 raised 4000 → 6000; scores 6 dim + sector_leaders push output tokens up)
- Prompt enforces "rationale = 1 sentence ~25 words" — scores carry per-dim judgment, so rationale is just the headline

**Thin adapters:**
- `main.py discover` — `--lang/--n-industries/--n-per-industry/--seed-summary/--seed-query/--product/--region/--sector-leaders|--no-sector-leaders/--top-k/--output-root/--verbose`
- `scripts/discover_targets.py` is identical (argparse)

**Output pair:**
- `candidates.yaml` — `{generated_at, seed{...}, industry_meta, candidates: [{name, industry, scores{6}, final_score, tier, rationale}], usage}`. Input format for backlog item 17 (web editor UI)
- `report.md` — seed-meta header + by-industry (S/A/B only) + ⚠️ Strategic Edge (C tier) separate section + Tokens summary

**Cost:** 1 Sonnet call, ~$0.045–0.08 / ~40–50s. Same RAG re-run drops to half via cache_read hit. Recomputing the same LLM response (different weights) = $0.

**MVP limits (intentional):** no factual verification — accepts company-name hallucination risk. Human review is the assumed downstream step. Phase 9.1 first run had 0 C-tier candidates — root cause is that sector_leaders.yaml lacked hyperscaler/lock-in cases; intentional additions to be considered in follow-up. Full reverse matching (Brave verification + per-industry active issues) is backlog item 8.

---

## Configuration flow
- Load `.env` → produce a type-validated `Settings` object via `pydantic-settings`
- `Settings` is shared across all modules (dependency injection)
- Existing environment variables override `.env` values

## Data persistence
- Vector store: `data/vectorstore/<namespace>/` (ChromaDB persistent, namespace-scoped since P10-2a — `default` is the default). From Phase 11 on, external workspaces add another prefix: `data/vectorstore/<ws_slug>/<namespace>/`
- Source documents: default ws → `data/company_docs/<namespace>/`; external ws → user-registered `abs_path` itself (`D:\my-docs\` etc.). Notion is separate (page IDs)
- Manifest: `data/vectorstore/<ws>/<namespace>/manifest.json` (`<ws>` segment omitted for default ws — legacy compat)
- Migration: on first boot / `indexer.main()`, if a flat layout (`data/vectorstore/{chroma.sqlite3, manifest.json}` + `data/company_docs/*.pdf`) is detected, `migrate_flat_layout` automatically moves it under `<root>/default/` (idempotent)
- Outputs: `outputs/{company}_{YYYYMMDD}.md`
- Intermediates: `outputs/{company}_{date}/intermediate/` (raw articles, summary JSONs, search results)
- Logs: `logs/` (one file per day)

---

## Phase 11 — Multi-workspace RAG (2026-05-02)

Breaks the single-root assumption of `data/company_docs/` and lets users add arbitrary abs paths (`D:\my-docs\` etc.) into the RAG tree.

### Workspace registry (`src/api/db.py::workspaces` table + `src/api/store.py::WorkspaceStore`)
- Columns: `id PK / slug UNIQUE / label / abs_path UNIQUE / is_builtin / created_at / updated_at`
- `init_db`'s `_seed_default_workspace` idempotently seeds `slug='default', label='Project Docs', abs_path=PROJECT_ROOT/data/company_docs, is_builtin=1`
- `WorkspaceStore.create` — auto-generates slug (`_slugify(label)` + `-2/-3` collision avoidance), `_validate_abs_path` (must be absolute, exist, be a dir, must reject paths inside `PROJECT_ROOT/data`); abs_path UNIQUE collision → `ValueError`
- `WorkspaceStore.delete(id, *, wipe_index=False)` — by default deletes only the DB row; `wipe_index=True` rmtree's `data/vectorstore/<slug>/` + deletes `rag_summaries` rows for the ws_slug. Never touches the user-registered source folder. Rejects `is_builtin=1` rows with ValueError

### Path resolution layer (`src/rag/workspaces.py`)
- `workspace_paths(ws_slug) -> (vs_root, cd_root)` — per-slug vectorstore + source directory mapping
- **Asymmetric default-ws** (intentional transitional handling, see `playbook.md` #18):
  - `default` → `(settings.rag.vectorstore_path, data/company_docs)` directly — preserves the legacy layout where existing namespaces live in `data/vectorstore/<ns>/`
  - external ws → `(settings.rag.vectorstore_path/<slug>, row.abs_path)` — per-slug prefix
- DO NOT rule: call `get_settings` via module-route (`from src.config import loader as _config_loader`) so the test monkeypatch flow stays intact

### Retriever / Indexer / Discover integration
- `src/rag/retriever.py::_STORES` cache key extended to `tuple[str, str]` `(ws_slug, namespace)`. `retrieve(query, *, ws_slug='default', namespace='default', top_k=None)`
- `src/rag/indexer.py` — `--workspace <slug>` (default `'default'`) + `--all-workspaces` flag. Body iterates workspaces via `_run_one_workspace(slug)`. `migrate_flat_layout` only runs for default
- `src/core/discover.py::discover_targets(*, ws_slug='default', namespace=DEFAULT_NAMESPACE, ...)` — both `_read_seed_meta` and `_retriever.retrieve` propagate ws_slug
- `main.py ingest` typer forwards `--workspace` / `--all-workspaces`

### API routes (`src/api/routes/workspaces.py` + ws-prefix on every `/rag/*`)
- 5 new endpoints: `GET/POST /workspaces`, `GET /workspaces/{id}`, `PATCH /workspaces/{id}`, `DELETE /workspaces/{id}?wipe_index=true|false`
- All 17 existing RAG endpoints prefixed to `/rag/workspaces/{ws_slug}/...`. Handlers take `ws_slug` path param and forward it to `_vectorstore_root(ws_slug)` / `_company_docs_root(ws_slug)` / `_get_cached_summary(ws_slug, ns, path)` / `_upsert_summary(ws_slug, ...)` / `_delete_namespace_summaries(ws_slug, ns)` / `_retriever._store(ws_slug, ns)`. Old paths removed (single-user dev tool, compat layer not worth carrying)
- `rag_summaries` table got `ws_slug TEXT NOT NULL DEFAULT 'default'` ALTER ADD. PK stays `(namespace, path)` due to SQLite ALTER limits — code uses `DELETE → INSERT` so INSERT/UPDATE/DELETE SQL doesn't depend on PK shape

### Frontend (`web/src/app/rag/page.tsx` + new components)
- URL `?path=` is a 3-segment `<ws_slug>/<ns>/<sub>`. `splitFullPath(fullPath) -> { ws, ns, sub }`
- 3 view-level decomposition:
  - **wsLevel** (`ws=""`) — workspace list view. Toolbar shows only `[+ Add Workspace]` (primary) + `[− Remove (N)]` (danger) + refresh (other file-ops buttons hidden)
  - **nsLevel** (`ws!="" && ns=""`) — namespace + root file list. Toolbar handles namespace creation/upload/delete/explorer
  - **inside** (`ws!="" && ns!=""`) — normal folder/file view
- `Breadcrumb` first segment maps slug → `workspace.label` (user-friendly display)
- `FolderTree` root node `Workspaces`, children are registered ws's (📦 + label), grandchildren are namespaces, great-grandchildren and below come from `listRagTree(ws, ns, sub)`
- `AddWorkspaceModal` — label + abs_path input + inline 422 server errors + immediate navigate to new ws on success
- `RemoveWorkspaceModal` — list of target labels + abs_paths + "Registered folders are never deleted" notice + "Also delete index" checkbox (default unchecked) → `deleteWorkspace(id, { wipe_index: true })` option
- `RagDocumentDropzone` takes `wsSlug` prop, `uploadAtRoot=nsLevel`

### Open gaps (split into backlog item 22)
- ~~Re-index UI hardcoded to default ws~~ (resolved 2026-05-04: `IngestTriggerRequest` forwards workspace/namespace; Re-index/Dry-run buttons disabled when ns not selected)
- Discovery/News tab namespace dropdown shows default ws only
- Dashboard `rag` aggregate counts default ws only
- Need 5 more backend tests for external-ws scenarios

---

## Phase 11+ — Cost Explorer (`/cost` tab) (2026-05-04)

A standalone viewer tab that exposes accumulated tokens as USD, daily trend, cache savings, budget, and pricing metrics. Active model (Sonnet/Haiku) is also swappable from the same page in one click.

### Pricing / Budget config (`config/pricing.yaml`, `config/cost_budget.yaml`)
- `Pricing.llm: dict[str, ModelRates]` — model id → 4 rates (input/output/cache_read/cache_write per Mtok). `Pricing.search: dict[str, SearchRates]` — external-search rates (Brave etc.)
- `CostBudget.monthly_usd / warn_pct` — monthly USD budget + warn threshold (0–1)
- Both registered under Settings PUT (`PUT /settings/{kind}`) — keys `pricing` / `cost_budget`. Reuses 2-pass YAML+Pydantic validation, atomic write, and lru_cache invalidation. **Not surfaced in Settings UI** — single entry point is the Cost page's `PricingBudgetEditor` form

### Calculator (`src/cost/calculator.py`)
A pure-function set with zero LLM/IO dependencies:
- `usd_for_run(usage, model, pricing)` — 4 tokens × 4 rates → input/output/cache_read/cache_write/total/cache_savings USD. Unregistered models try prefix-match → fall back to zero-rate. **`cache_savings_usd = cache_read_tokens × (input_rate − cache_read_rate) / 1M`** (converts Anthropic prompt-caching's 90% discount into "cash value")
- `kpi_block` — this_month / last_month / cumulative + cache savings + savings % (vs counterfactual)
- `aggregate_daily(records, *, days, today)` — trailing N-day zero-fill series (gap-free line chart)
- `aggregate_by(records, *, dim)` — group by `dim="model"` or `"run_type"`
- `per_unit(records)` — proposal = `completed` only (mean) / discovery = sum of `candidate_count` (fallback 25 if missing) → USD per candidate
- `budget_state(records, budget, today)` — this-month used USD + breach (≥warn_pct) + over_budget (≥1.0)
- `recent_runs_with_usd(records, *, limit=20)` — most recent first + 4 raw token types + USD

### Aggregator route (`src/api/routes/cost.py`)
- `_gather_records()` — normalizes 3 sources:
  - **Proposal**: `RunStore.list()` (in-memory). `RunRecord.claude_model` first, settings fallback otherwise
  - **Discovery**: `DiscoveryStore.list_runs()` (SQLite `discovery_runs.usage_json` + `claude_model` column)
  - **RAG summary**: direct SELECT from `rag_summaries` (`ws_slug`, `namespace`, `path`, `model`, `usage_json`, `generated_at`). run_type = `rag_summary`, run_id = `rag:<ws>:<ns>:<path>`
- `GET /cost/summary?days=30` — calls the 7 functions above, assembles `CostSummaryResponse`
- `GET /cost/active-model` — `{ active, available[] }`. `available` = pricing.yaml `llm` dict's model ids + 4 rates each
- **`POST /cost/active-model {"model": "..."}`** — validates against pricing.yaml-registered enum → replaces the single `claude_model:` line in settings.yaml via `r"^(\s*claude_model:\s*).*$"` regex (preserves comments/indent/other keys) → re-validates Settings pydantic post-swap → atomic write + `get_settings.cache_clear()`. Falls back to yaml round-trip on regex miss only (acknowledges loss of comments)

### Model tracking — RunRecord/DiscoveryStore.claude_model
To preserve cost accuracy of past runs after a model swap, we **snapshot the active model at run start**:
- `RunRecord.claude_model: str | None` field + `RunStore.create(claude_model=...)` parameter. `POST /runs` handler reads `settings.claude_model` immediately and pins it on the record
- `discovery_runs.claude_model TEXT` column + `_DISCOVERY_RUNS_NEW_COLUMNS` migration. `POST /discovery/runs` snapshots the same way
- Cost calculator prefers the record's `claude_model` → after an active-model change, new runs use new rates while past runs are still valued at their original rates

### Frontend (`web/src/app/cost/page.tsx` + `web/src/components/cost/*`)
8 components:
- `KpiCards` — 4 cards (this month / last month / cumulative / cache savings)
- `CostTrendChart` — 30/60/90-day toggle + recharts LineChart
- `CostBreakdownBars` — by model ↔ by run_type toggle + horizontal stacked bars
- `PerUnitCard` — $/proposal, $/discovery target
- `BudgetBar` — month-to-date progress bar; amber at warn, rose when over
- `RecentRunsTable` — pagination (10/page) + 4-color token-ratio mini-bar. **proposal=blue / discovery=violet / rag_summary=amber**
- `PricingBudgetEditor` — first implementation of the form-with-YAML-escape pattern. Per-model 4 inputs + monthly budget + warn% / "Edit YAML" toggle for raw textarea fallback / saves via `putSettings("pricing"/"cost_budget", yaml)`
- `ActiveModelSelector` — dropdown in the header right. Surfaces pricing.yaml model list + 4 rates each, shows active marker, closes on outside click. Change → immediate PUT → toast → `getCostSummary` auto-refresh

`recharts ^2.13.3` is a new dependency in `web/package.json`. Home's `CostBox` was also slimmed to the new USD-centric `DashboardCostSummary` schema + `/cost` link + amber/rose budget-threshold badges.

### Dashboard box slimming
`src/api/routes/dashboard.py::_cost_summary()` swapped from 8 raw-token fields (4 token types) to 9 USD fields (this_month_usd / last_month_usd / cumulative_usd / cache_savings_usd / cache_savings_pct / monthly_budget_usd / used_pct / breached / over_budget) returned by `cost.calculator.kpi_block + budget_state`. Falls back to zero-state on failure.

### Data flow summary
```
Anthropic SDK response.usage (4 token types)
  → claude_client.chat_cached/chat_once dict-ifies it
  → caller (synthesize/draft/discover/rag_summary) accumulates
  → stored in RunStore / discovery_runs / rag_summaries (each record carries claude_model)
  → /cost/summary SELECTs from all 3 sources × pricing.yaml multiplication → USD
  → frontend KpiCards/Trend/Breakdown/PerUnit/Budget/RecentRuns surface
```
