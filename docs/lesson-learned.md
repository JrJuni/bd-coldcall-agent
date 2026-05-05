# Lessons Learned

Append-only log of approaches tried, failure causes, and validated know-how, accumulated by date.

## Entry format

```
## [YYYY-MM-DD] One-line topic
**Tried**: which approach was taken
**Result**: success / failure + observed behavior
**Lesson**: what to do next time
```

---

## [2026-04-20] Windows `python` command resolves to the Microsoft Store stub
**Tried**: `python --version` to check the environment.
**Result**: With no real Python installed, `C:\Users\<user>\AppData\Local\Microsoft\WindowsApps\python.exe` stub was picked up and only printed "Python was not found". `py` launcher also missing.
**Lesson**: Assume Windows machines have no Python by default. Install explicitly via `winget install Anaconda.Miniconda3 --silent --scope user` or `winget install Python.Python.3.11`. Miniconda path: `~/miniconda3/Scripts/conda.exe`.

## [2026-04-20] Fresh Miniconda install rejects channel ToS
**Tried**: `conda create -n bd-coldcall python=3.11 -y` for new env.
**Result**: `CondaToSNonInteractiveError` — any env creation fails until ToS for `pkgs/main`, `pkgs/r`, `pkgs/msys2` channels is accepted.
**Lesson**: Miniconda `py313_26.1.1` (shipped after 2025-11) requires explicit ToS acceptance. Run these 3 lines right after install:
```
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/msys2
```

## [2026-04-20] Korean garbled in Windows Python stdout (cp949)
**Tried**: `python -m src.search.brave --query "AI 산업" --lang ko` and printed Brave response to console.
**Result**: Response JSON had valid UTF-8 Korean, but the console decoded as cp949 → mojibake. Same issue with file redirection.
**Lesson**: Force `sys.stdout.reconfigure(encoding="utf-8")` at CLI entry. `PYTHONIOENCODING=utf-8` env var works too, but pinning it in the entrypoint is more reproducible. Apply across all CLIs (`main.py`, `src/cli/*`).

## [2026-05-02] Tailwind class order drives CSS specificity — primary button rendered white-on-white
**Tried**: `ToolbarButton` had `bg-white` in its base className, with primary tone appending `bg-slate-900 hover:bg-slate-800` as toneCls. Naively assumed the trailing `${toneCls}` would win.
**Result**: Primary button rendered white outside hover (white-on-white = invisible). User reported "Re-index and Add Workspace are missing". Cause is not className token order but the **order in the generated Tailwind CSS file**: when `.bg-white` and `.bg-slate-900` have equal specificity, the one declared later in the CSS wins. Tailwind sorts by alpha/numeric, so `bg-slate-900` comes first and `bg-white` overrides it.
**Lesson**: For components that toggle `bg-*` per tone, never bake a `bg-*` into the base className — push every bg into toneCls. Default tone gets explicit `bg-white`; primary/danger bring their own. Same trap applies to `text-*` and `border-*`: when base and modifier both set utilities in the same category, the result is decided by generated CSS order, not className string order.

## [2026-05-02] Existing `app.db` failed lifespan init after schema change — inline `CREATE INDEX` in `_SCHEMA_SQL` ran before `ALTER`
**Tried**: P10-5 added `namespace` column to `news_runs`, updated `_SCHEMA_SQL` with `CREATE TABLE IF NOT EXISTS news_runs (..., namespace TEXT ...)` and added `CREATE INDEX IF NOT EXISTS idx_news_runs_namespace_generated ON news_runs(namespace, ...)` in the same SQL script. `_migrate_news_runs` was also written to (idempotently) create the same index.
**Result**: Fresh DBs after P10-5 worked. But user environments with `data/app.db` from P10-0 onward died with `OperationalError: no such column: namespace` on `init_db`. Reason: `CREATE TABLE IF NOT EXISTS` is a no-op when the table already exists — it does not add columns. Then the next line, `CREATE INDEX ... ON news_runs(namespace, ...)`, references the missing column on the existing table and fails. `_migrate_news_runs` runs `ALTER TABLE ADD COLUMN` later (after `executescript`).
**Lesson**: `_SCHEMA_SQL` should hold **only statements that are valid the moment a fresh DB is created**. Indexes that depend on added columns belong inside `_migrate_*`, after `ALTER TABLE ADD COLUMN`. `CREATE INDEX IF NOT EXISTS` is idempotent, so re-running it on a fresh DB is harmless. More generally: any statement dependent on a schema change is a migration helper's responsibility; `_SCHEMA_SQL` stays as the "v1 fresh schema" baseline.

## [2026-04-20] Snippets alone aren't enough for BD summarization — full-body extraction (trafilatura) is mandatory
**Tried**: Initial design fed Brave Search API's `description` field (150–300 char snippet) directly to Exaone for structured JSON summary.
**Result**: Snippets lack the context needed to extract BD-grade key_events / business_signals / pain_points. A 7.8B-class LLM is highly likely to hallucinate to fill the void.
**Lesson**: Insert **Phase 1.5 — body extractor** between Phase 1 (search) and Phase 2 (summarize). Use `trafilatura.extract(favor_precision=True)` parallelized via `ThreadPoolExecutor(max_workers=5)`. Measured on "AI 산업" bilingual 20-article run: 19/20 full extractions, average 3894 chars. Only Reuters fell back to snippet. On failure, keep `body_source="snippet"` flag so the pipeline doesn't break.

## [2026-04-20] Local LLMs are for deterministic preprocessing, not reasoning
**Tried**: Initial design assigned Exaone 7.8B the role of "article → BD-signal structured JSON (key_events / business_signals / pain_points / opportunities)" summarization.
**Result**: 7.8B-class models can do simple summarization or sentence extraction, but **"BD signal extraction" requires inference + domain knowledge** — high hallucination risk and a noticeable quality gap vs Sonnet. Worse, feeding Exaone summaries into Sonnet means **context is already compressed**, so Sonnet can't recover the original nuance either.
**Lesson**: Reposition local LLMs to **translation + 9-tag classification + embedding-based dedup** — deterministic preprocessing tasks that have a "right answer". BD signal extraction and proposal drafting are owned by Sonnet 4.6, which receives translated full bodies directly. This avoids context loss, isolates local hallucination risk, and lets each model own its strength. (Principle: "small models for deterministic tasks, frontier models for reasoning")

## [2026-04-20] Split `requirements.txt` by phase
**Tried**: Initial single `requirements.txt` included heavy ML deps: `torch`, `bitsandbytes`, `chromadb`, `sentence-transformers`, etc.
**Result**: On Windows, `bitsandbytes` needs CUDA runtime, and `torch` only ships CPU wheels by default on PyPI — GPU users need `--index-url https://download.pytorch.org/whl/cu121`. Phase 1 (Brave) doesn't need any of this.
**Lesson**: Split into `requirements.txt` = lightweight core (Phase 1+: httpx/pydantic-settings/pyyaml/anthropic/langgraph/notion-client/pypdf/typer/pytest) and `requirements-ml.txt` = Phase 2+ heavy (torch/transformers/accelerate/bitsandbytes/chromadb/sentence-transformers). User picks CUDA or CPU torch via `pip install torch --index-url ...` before installing ml deps. Phase 1 testing now starts in seconds without 10+ minute ML wheel installs.

## [2026-04-20] Exaone 3.5 chat template called with `return_tensors="pt"` breaks `generate()` shape lookup
**Tried**: `tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt")` to get input_ids tensor in one shot, passed to `model.generate()`.
**Result**: A `BatchEncoding` is returned, but transformers' `generate()` accesses `inputs_tensor.shape[0]` directly → `AttributeError: shape`. `BatchEncoding` is dict-like and has no `.shape` (some model/template combos return it this way).
**Lesson**: **Split chat templating into two steps** — `apply_chat_template(..., tokenize=False)` for the raw string, then `tokenizer(text, return_tensors="pt")` to tokenize separately. Pull out both `input_ids` and `attention_mask` and call `model.generate(input_ids, attention_mask=..., **kwargs)`. This pattern matches HF docs and is safe across tokenizer implementations.

## [2026-04-20] Confirmed Exaone 3.5 7.8B (4-bit) loads on RTX 4070 16GB VRAM
**Tried**: `BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=float16, bnb_4bit_use_double_quant=True)` + `device_map="auto"`, downloaded `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct` from HuggingFace (~15GB) and loaded.
**Result**: First run downloaded 7 shards in ~3:55, then warm cache loaded 291 weights in ~28s. Korean→English translation ("삼성전자가 3분기 매출 70조원을 기록했다.") and tag JSON generation both work. CUDA usage stable.
**Lesson**: 4-bit nf4 + double-quant comfortably fits 7.8B on a 16GB card (measured ~5–6 GB). Subsequent runs are fast since download is cached, so reuse the model via a singleton cache (`_CACHE` dict). On Windows, `huggingface_hub` warns about symlinks but functions fine — enabling Developer Mode or running as admin saves disk space.

## [2026-04-20] bge-m3 load rejected by CVE-2025-32434 on torch 2.5
**Tried**: `sentence-transformers.SentenceTransformer("BAAI/bge-m3")` for Phase 2 dedup embedder.
**Result**: `ValueError: Due to a serious vulnerability issue in torch.load, even with weights_only=True, we now require users to upgrade torch to at least v2.6`. Installed torch is `2.5.1+cu121`; the bge-m3 HF snapshot has both `.safetensors` and `pytorch_model.bin`, and sentence-transformers picked the `.bin` and tripped the CVE gate.
**Lesson**: Force safetensors via `SentenceTransformer(..., model_kwargs={"use_safetensors": True})`. The safetensors format is not affected by CVE-2025-32434 and loads fine on torch 2.5. No need to wait for torch 2.6 — single flag is the workaround. Also a supply-chain win: avoids `.bin` pickle execution risk. Applied permanently in the `src/rag/embeddings.py` singleton, recorded in `docs/security-audit.md`.

## [2026-04-20] Exaone 7.8B tag classification is for "narrowing candidates" — don't expect precision
**Tried**: Phase 2 validation, ran 9-tag classification over 20 articles for "한국 공공기관 AI 전환".
**Result**: Government R&D RFPs ("MSIT to invest ₩10B in AI projects") were over-tagged with `m_and_a`. The right tags would be `funding` or `regulatory`. The 7.8B model picks `m_and_a` based on the surface signal of "money is moving".
**Lesson**: Treat tags as a **coarse filter** for Phase 4 Sonnet to pick the article subset. Actual deal classification and signal interpretation come from Sonnet reading the full body. Instead of tuning few-shot prompts to lift tag quality, the real quality knob is the tier policy: any of the high-value 7 tags routes the article to Sonnet at full body. (Principle: local model classification favors recall; precision is Sonnet's job.)

## [2026-04-20] Exaone translation echoed `<article>` prompt-boundary tags
**Tried**: With `src/prompts/{en,ko}/translate.txt` wrapping article body in `<article>...</article>` for prompt-injection defense, ran Korean→English translation.
**Result**: Some outputs included `<article>` literally on the first line. The model learned the boundary marker as part of "valid output format". Translation quality itself was fine.
**Lesson**: Prompt boundary tags are **security-critical** (injection defense) but small LLMs may echo them — **strip them in post-processing**. Will add `<article>/</article>` strip line to `translate.py` (backlog before Phase 3). Generalization: keep prompt boundaries, but assume model output may include the marker, and strip them in a post-processing layer.

## [2026-04-20] Big phases: 4 work streams + checkbox-based plan file
**Tried**: Tried to do all of Phase 3 RAG (LocalFile + Notion connectors, ChromaDB, incremental indexing, retrieve API) in a single session.
**Result**: Initial plan was structurally fine but rejected for missing 7 operational details (atomicity, hash stabilization, Notion title rules, PDF page boundaries, etc.). Also realized doing the full implementation in one session piles context pressure on the back half and risks early decisions fragmenting.
**Lesson**: Split a phase into **3–5 work streams by layer**, each with a **TO-BE / DONE checklist** in a plan file (`~/.claude/plans/*.md`). Align stream boundaries with `/compact` points (usually ~2 of them). Even with session breaks, the next session resumes accurately by reading "in progress" in `status.md` + plan-file checkboxes. Phase 3 was split into schema-normalization-chunking / store-retrieval / connectors / indexer-CLI. Same pattern expected for Phases 4, 5, 7.

## [2026-04-21] LangGraph `TypedDict(total=False)` + optional-key assert order
**Tried**: Phase 5 happy-path test had `assert result["failed_stage"] is None or "failed_stage" not in result`.
**Result**: `KeyError: 'failed_stage'`. Short-circuit evaluation of `or` evaluates the first operand first, and missing-key access blows up.
**Lesson**: For optional keys on `total=False` TypedDict, **check existence first**: `assert "failed_stage" not in result or result["failed_stage"] is None`. Pattern is simple but applies to every happy-path test, since LangGraph defaults to partial state merges.

## [2026-04-21] LangGraph has no `__version__` — use `pip show`
**Tried**: `python -c "import langgraph; print(langgraph.__version__)"` to check the installed LangGraph version.
**Result**: `AttributeError`. LangGraph doesn't expose a module-level `__version__` (thin namespace wrapper).
**Lesson**: For Python package versions, use `~/miniconda3/envs/bd-coldcall/python.exe -m pip show langgraph` or `importlib.metadata.version("langgraph")`. The `__version__` convention varies by package — don't trust it.

## [2026-04-21] LangGraph monkeypatches must resolve via the module path inside `pipeline.py`
**Tried**: `src/graph/nodes.py` had `from src.search.brave import BraveSearch` at module level; `tests/test_pipeline.py` did `monkeypatch.setattr(nodes, "BraveSearch", _FakeBrave)`.
**Result**: After `build_graph()` compiled the nodes, invoking the graph called the original class, not the test double. Because `pipeline.py` did `from src.graph.nodes import search_node`, the symbol reference was frozen and monkeypatch couldn't break through.
**Lesson**: In `pipeline.py`, **import the module itself** (`from src.graph import nodes as _nodes`) and reach in with `_nodes.search_node` — runtime attribute lookup. Then test monkeypatches of `nodes.search_node` are visible at graph-execution time. Generalization: any dependency that may be monkeypatched should be **module-imported + attribute-accessed**, not from-imported.

**2026-04-22 follow-up**: Decided this isn't a style preference but a foundation for test reliability — graph/pipeline layers have heavy monkeypatch-based tests, and a binding mistake silently calls the real dependency, causing a **false green** (network/API/LLM calls leaking out of tests). Recurrence rate, severity, and detection difficulty are all high → promoted to CLAUDE.md `## DO NOT`. Wording is scoped (patch targets + side-effectful external calls + orchestration layers) and pairs "why" with "allowed pattern". Constants/types/exception classes are not patch targets and are exempt — forcing all imports to go via module would muddy the code for no practical gain.

## [2026-04-21] Typer + Rich `--help` renders Korean at module load
**Tried**: Inside the Typer command body in `main.py`, called `sys.stdout.reconfigure(encoding="utf-8")` — then ran `main.py --help`.
**Result**: `UnicodeEncodeError: 'cp949' codec can't encode character '—'` — em-dash from a docstring dumped to cp949 console. Rich's help renderer runs **before** the command body, so the in-body reconfigure is too late.
**Lesson**: Typer entrypoints must force stdout/stderr to UTF-8 **at module load time**. Place this at the very top of `main.py`: `for _stream in (sys.stdout, sys.stderr): _stream.reconfigure(encoding="utf-8")`. Unlike manual argparse parsing, declarative frameworks format help strings at import time.

## [2026-04-21] When multiple nodes overwrite a single state key, post-mortem info on failure is lost
**Tried**: Initial `AgentState.articles` was a single key overwritten by search_node → fetch_node → preprocess_node in sequence. Each node read the prior value and replaced it with an enriched list.
**Result**: If retrieve fails, state.articles is the "post-preprocess" version (OK), but if fetch fails, just looking at state can't tell whether articles is "search original" or "fetch midpoint". `run_summary`'s `articles_after_preprocess.json` becomes a misleading filename. External advisor flagged the same.
**Lesson**: Each transformation stage in the pipeline gets its **own dedicated output key** — split into `searched_articles` / `fetched_articles` / `processed_articles`. Subsequent nodes consume prior keys **read-only**. Persistence builds a canonical output via `latest_articles(state)` (processed > fetched > searched fallback) and dumps stage-specific snapshots on the failure path. Principle: "nodes don't overwrite their input, they only add their own output". Applies to LangGraph and any DAG pipeline — without this, downstream stages can't observe upstream artifacts and post-mortem doesn't work.

## [2026-04-22] DO NOT rule broke again in FastAPI routes
**Tried**: Phase 7 `src/api/routes/runs.py` had `from src.api.runner import execute_run`, binding the symbol and passing it to BackgroundTasks. Tests injected a fake runner via `monkeypatch.setattr("src.api.runner.execute_run", fake)` to avoid Exaone/Sonnet calls.
**Result**: First run actually loaded Exaone 7.8B (4-bit) and called Sonnet, taking 150+ seconds and returning a real `proposal_md`. The routes module had already bound the local `execute_run` name to the original function, so monkeypatching `src.api.runner.execute_run` did nothing — the route kept calling the original. **Same mistake as 2026-04-21 (graph/nodes), now in API routes.** `src/api/routes/ingest.py::_manifest_path`'s `from src.config.loader import get_settings` had the identical issue, so test settings overrides didn't apply and the real vectorstore path leaked through as a false green.
**Lesson**: The DO NOT rule applies to **every orchestration layer that triggers external calls** — graph/pipeline plus FastAPI routes. Use `from src.api import runner as _runner` + `_runner.execute_run(...)`, `from src.config import loader as _config_loader` + `_config_loader.get_settings()` consistently. Any thin adapter layer the test path traverses just before "execution" falls under this rule — pure schema/const imports are exempt. Follow-up: confirmed CLAUDE.md's promoted DO NOT rule is broad enough (no further escalation needed).

## [2026-04-22] Why we didn't use a coroutine-thread-safe queue for SSE
**Tried**: Phase 7 backend had to relay each super-step from `orchestrator.run_streaming()` (running in BackgroundTasks / anyio worker thread) to SSE (event loop). Initial sketch attached `asyncio.Queue` to `RunRecord` and pushed via `asyncio.run_coroutine_threadsafe(queue.put, loop)` from the worker.
**Result**: Overkill for the MVP. `asyncio.Queue` is not thread-safe — calling `put_nowait` directly from a worker thread can break it; `run_coroutine_threadsafe` requires the caller to know the main loop, which entangles the design. Adding per-SSE subscriber bookkeeping, backpressure, and a bounded queue blows up the code.
**Lesson**: When events are **few and append-only** (7 stages + ~5 metas = ≤~15 events/run), `RunRecord.events: list[RunEvent]` + `threading.Lock` + SSE-side **150ms polling** is simplest and least error-prone. Use `last_seq` cursor for incremental yield, detect terminal state, close the stream. For "rare events with a known terminal state", poll-log beats queue pub/sub. When we eventually move to Celery/RQ + Redis (long-term), this structure swaps cleanly into pub/sub.

## [2026-04-22] SqliteSaver requires `check_same_thread=False`
**Tried**: First `build_sqlite_checkpointer()` opened the connection with default `sqlite3.connect(db_path)` and stored `SqliteSaver(conn)` in lifespan.
**Result**: When `/runs` POST dispatched to BackgroundTasks, the anyio worker thread accessed the checkpointer while the event loop (different thread) also held a reference → `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.
**Lesson**: For FastAPI + BackgroundTasks + `SqliteSaver`, open the connection with `sqlite3.connect(path, check_same_thread=False)` and pass it to `SqliteSaver(conn)`. Concurrent-write protection is handled internally by langgraph-checkpoint-sqlite locking. Use `close_checkpointer()` helper to explicitly close on lifespan shutdown. Long-term, this conflicts with `SqliteSaver`'s `from_conn_string()` context-manager idiom — revisit when re-architecting around `async with`.

## [2026-04-22] Next.js 15 + React 19 GA conflicts with Next 15.0.x peer
**Tried**: Phase 7 `web/package.json` pinned `next@15.0.3` + `react@19.0.0`.
**Result**: `npm install` rejected with ERESOLVE: `peer react@"^18.2.0 || 19.0.0-rc-66855b96-20241106" from next@15.0.3`. Next 15.0.x only recognizes a specific React 19 RC hash, not GA 19.
**Lesson**: React 19 GA needs **Next.js 15.1+**. New projects should pin `next@^15.1.0` + `react@^19.0.0` with caret so npm naturally picks compatible versions. Avoid `--legacy-peer-deps` workarounds — they paper over the issue and downstream hydration bugs can surface subtly.

## [2026-04-21] Notion MCP `update_content` payload-size boundary
**Tried**: Used `/patchnotes` skill to insert v0.5.0 patch note entry into Notion, with full entry in a single `update_content` request `new_str`.
**Result**: First attempt for v0.3.0 batch failed at `~10KB+` payload, blocked by Cloudflare WAF. This time trimmed to 3–5 bullets per section (~3KB) and it went through.
**Lesson**: Notion MCP `update_content` can be blocked by an external WAF/reverse-proxy when the single-request payload is large. Soft limit: **3–5 bullets per section** for patch note entries. For larger updates, split into multiple smaller `update_content` calls (or split by section). Prevention: already captured in memory (`feedback_patchnotes_payload.md`); duplicated here so future maintenance sessions catch it.

## [2026-04-20] RAG chunking is sentence-greedy with sentence-level overlap, not char-based
**Tried**: First draft was the standard RAG-tutorial pattern — `chunk_size=500`, `chunk_overlap=50` with a plain char-sliding window.
**Result**: Plan review flagged "sentences cut mid-string, paragraph meaning duplicated unnaturally". Korean is especially fragile because sentence-final endings come last — char-cuts in the middle damage meaning units more. bge-m3 retrieval quality is heavily decided by the chunker.
**Lesson**: **Sentences are the primary unit, packed greedily**, with overlap also sentence-level (tail of next chunk). Only fall back to char-level hard-split + char-overlap when a single sentence exceeds `chunk_size`. Sentence boundary regex: `[.!?。！？]\s+` + `\n\s*\n` (paragraph boundary). Implementation: `src/rag/chunker.py::chunk_document()`. Regression: `tests/test_chunker.py` 12 cases (sentence overlap, long-sentence fallback, Korean paragraph split, chunk_overlap=0, shared-field propagation, id uniqueness). Normalization (`normalize_content`) is unified in this stage to also stabilize hashes.

## [2026-04-28] DO NOT rule recurred in a new module (`src/core/scoring.py`) — third time
**Tried**: When adding `src/core/scoring.py` for Phase 9.1, used direct function imports: `from src.config.loader import load_tier_rules_config, load_weights_config`. Tests (`tests/test_scoring.py`) tried `monkeypatch.setattr(_loader, "load_weights_config", ...)` to fake yaml loading.
**Result**: 4 of 13 cases failed. The scoring module froze function references at import time, so monkeypatch didn't apply — same trap as 2026-04-21 (graph/nodes) and 2026-04-22 (api/routes), now the third recurrence. CLAUDE.md DO NOT explicitly listed graph/pipeline/api/orchestration, but I wrote new core code without thinking.
**Lesson**: Extend the rule's scope from "patch targets + side-effectful external calls + orchestration layers" to **every external dependency tests monkeypatch**. New modules under `core/` etc. must always go module-via (`from src.config import loader as _loader` + `_loader.load_X()`) when importing yaml loaders, external calls, LLM clients, etc. Self-check at first-import: "Could this function be monkeypatched in tests?" If yes (or unsure) → module-via. Without this discipline it'll recur — grep this lesson when adding a new module.

## [2026-04-28] Auto-normalized weights × integer scores: float drift breaks exact threshold compare
**Tried**: Phase 9.1 scoring engine. `weights.yaml::products.databricks` override summed to 1.10 → auto-normalize → each weight = user_value / 1.10. Verified `decide_tier(7.0, rules)`.
**Result**: Candidate with scores=[7,7,7,7,7,7] should produce final_score = 7 × sum(normalized weights) = 7 × 1.0 = 7.0, but measured 6.999999999999999. tier_rules' A threshold was 7.0, so `7.0 >= 7.0` evaluated `False` and the candidate was demoted to B (caught in smoke test).
**Lesson**: Float multiplication and summation lose round-trip precision (general case, like `0.1 + 0.1 + 0.1 != 0.3`). Threshold-based decision functions should **always allow epsilon** — `final_score >= threshold - 1e-6`. Users will write clean integer thresholds like `8.0` in yaml, so the code should match that intent — not "user wrote 7.0, must be exactly ≥ 7.0", which almost always breaks under normalize/weighted-sum paths. Generalization: if division/sum touches the value at any point, threshold compares need epsilon. But never `==` — even with epsilon, `==` is hopeless. Stick to `>=`/`<=`.

## [2026-04-28] Phase 9 first-pass theoretical-fit bias → fixed by separating scoring from LLM
**Tried**: Phase 9 RAG-only target discovery MVP — single Sonnet call, 25 candidates (5 industries × 5 companies), tier judged directly by the model. Prompt defined "S = direct trigger / A = strong fit / B = adjacent / C = long-shot" abstractly.
**Result**: 8 S / 10 A / 7 B / 0 C. Mostly Fortune-500 mega-caps (JPMorgan / Goldman / Amazon / Walmart / NVIDIA) + Snowflake (a direct competitor) at A tier; zero Korean companies. The model judged "theoretical data fit" — but in practice these are hard to actually sell to (AWS proper, self-built platform lock-in). C tier absent → no Strategic Edge signal. External advisor: "cold-calling is decided by landability (orgs/budget/replaceability), not data scale. Strongly recommend separating weights.yaml."
**Lesson**: Before "fix it with prompt tuning", check whether **decidable parts can be peeled off into code**. Narrowed LLM's role to "6-dim 0–10 scoring", and final_score / tier are computed by code (weighted sum + threshold rule). Phase 9.1 rerun: mega-caps dropped from S, mid-caps (Stripe / Adyen / Tempus AI) entered S, 7 Korean companies entered, Snowflake demoted to B. Recomputing the same LLM response under different weights costs $0. General principle: **don't try to suppress LLM hallucination with prompts — isolate the decidable parts**. Registered as `playbook.md#14`.

## [2026-04-28] Shared `_extract_json` array-first ordering grabs inner list when caller wants dict
**Tried**: Phase 9 `parse_discovery` reused `proposal_schemas._extract_json` to parse Sonnet's `{"industry_meta": {...}, "candidates": [...]}` response. Added regression for prose-mixed responses ("Here you go: {...} Let me know.").
**Result**: `_extract_json`'s 4-tier fallback tries `_ARRAY_RE` (`\[.*\]`) **before** `_OBJECT_RE` (`\{.*\}`). For top-level dict responses, the inner `candidates` list was matched first and returned, so parse_discovery's dict-validation failed with `expected JSON object ... got list`. Existing caller (`parse_proposal_points`) wanted top-level list, so it was unaffected — but the dict caller had inverted needs.
**Lesson**: For a 4-tier fallback util, **array vs object priority depends on caller schema** — modifying the shared util breaks existing list callers, so **dict callers get their own thin helper**. Branched into `src/core/discover_types.py::_extract_json_object` (raw → fenced → object only). Generalization: regex-greedy + try-parse-each fallbacks share structure but the first match wins, so different callers may need differently-ordered helpers. Note "list-first" in the shared util's docstring so the next person doesn't fall in.

## [2026-04-28] New LLM step reused old `max_tokens` setting → output truncated, both retries failed
**Tried**: Phase 9 discover called `chat_cached(..., max_tokens=settings.llm.claude_max_tokens_synthesize)`. Reusing `max_tokens=2000` felt natural since input pattern was similar to synthesize.
**Result**: Both retries failed with `ValueError: discover_targets failed after 2 attempts: no JSON found in discovery output`. Capturing raw responses showed output_tokens=2511 / 2852 — synthesize emits 5 ProposalPoints (~1.5K out, 2000 cap was fine), but discover emits 5 industries + 25 candidates + 1–2 sentence rationales each, ~2.5K out, consistently exceeding the cap. JSON was cut mid-stream and the second retry hit the same size.
**Lesson**: When adding a new LLM step, **estimate output distribution separately** even when input pattern is similar, and create a new setting key. Added `claude_max_tokens_discover=4000` (synthesize 2000 / draft 4000 / discover 4000). Estimation formula: `n_items × (avg rationale tokens + structural overhead) × 1.3 safety`. 25 × (~80 + 20) × 1.3 ≈ 3300 → round up to 4000. Retries can't recover from truncated responses — when `max_tokens` is the bug, retry is useless.

## [2026-04-28] Set-init breaks dict iteration order → flaky pytest assertion
**Tried**: `parse_discovery`'s industry-distribution check used `industry_keys = set(industry_meta.keys())` + `counts: dict[str, int] = {k: 0 for k in industry_keys}`. For invalid distributions ('a':3, 'b':1), asserted via `pytest.raises(ValueError, match="industry 'a' has 3")`.
**Result**: First run raised on 'a' (passed); next run checked 'b' first and raised "industry 'b' has 1 candidates, expected 2" (assertion failed). `set` iteration order is hash-driven and nondeterministic, and dict order inherited from a set comprehension is too.
**Lesson**: To leverage Python 3.7+ dict insertion-order guarantee, **iterate the dict directly** (`for ind in industry_meta`). Going through a set kills the order. This pattern only works when "input order" is the desired order — for explicit sorting use `sorted()`. Generalization: when validation/error messages/test assertions depend on dict order, trace back to find any set-pass-through that broke it.

## [2026-04-28] Phase 8 multi-channel 39-article dedup OOM on RTX 4070 16GB
**Tried**: Sum of channel caps = 40 (target 20 + related 15 + competitor 5) for multi-channel search_node. preprocess dedup called `embed_texts(texts)` with default batch_size → embedded 39 articles × ~3500 char body in one shot.
**Result**: First full smoke run hit `torch.OutOfMemoryError: Tried to allocate 5.60 GiB. GPU 0 has a total capacity of 15.99 GiB ... 19.80 GiB is allocated by PyTorch`. Exaone 4-bit (~6GB) was holding the GPU and bge-m3 tried to push 39 sequences in a single batch. Phase 5 baseline (20 articles) didn't expose this — silent regression.
**Lesson**: Doubling raw input via more channels causes nonlinear GPU pressure spike for dedup embedding. Three guards applied together:
1. `embed_texts(..., batch_size=8)` — cap sequences per batch. Conservative for Exaone + bge-m3 coexistence on 16GB.
2. Truncate dedup input texts to first 3000 chars — embedding meaning is mostly in lede/first paragraph; 0.90-threshold dedup accuracy is barely affected.
3. `torch.cuda.empty_cache()` right before dedup — reclaim Exaone's fragmented blocks.
The plan's risk analysis predicted this exact case (cap-sum 40 vs RTX 4070 16GB) — **predicted risks fire at least once unless locked behind a fixture/CI**. When increasing channel caps in the future, recompute batch_size and truncate too. Implementation: `src/rag/embeddings.py::embed_texts` / `dedup_articles`. Existing `tests/test_dedup.py` 7 cases unaffected (small batches, cap-irrelevant).


## [2026-04-30] FastAPI lifespan auto-migration touched real user `data/` during tests
**Tried**: Phase 10 P10-2a called `migrate_flat_layout(vectorstore_root, company_docs_root)` from `app.py::lifespan` as best-effort, with no env-var toggle.
**Result**: During pytest, tests like `tests/test_api_db.py::test_lifespan_initializes_app_db` triggered `create_app()` and woke lifespan, which moved the user's actual flat layout at `PROJECT_ROOT / "data" / "vectorstore"` (absolute path) into `data/vectorstore/default/`. The migration was idempotent + dest.exists() skip, so nothing was lost — but **tests touching user data is a red flag**.
**Lesson**: Side-effectful "environment mutation" code (FastAPI lifespan auto-migration) should be (1) gated behind an env-var toggle, default off, (2) accept overridable PROJECT_ROOT via a test fixture, or (3) fire only via an explicit CLI command. This case was a one-time migration so didn't need much follow-up, but for similar future mutations adopt `os.environ.get("APP_AUTO_MIGRATE", "0") == "1"` guards by default. Migration functions themselves must be idempotent + best-effort + dest-preserving (no overwrite) — those three properties prevented this from becoming a loss.


## [2026-05-02] CORS allow_methods missing DELETE/PATCH/PUT → silent browser failure for months
**Tried**: Phase 7 `src/api/app.py::create_app()` set CORSMiddleware to `allow_methods=["GET","POST","OPTIONS"]` (legacy from when only GET/POST existed). Phase 10 added P10-1 (targets PATCH/DELETE), P10-3 (rag DELETE/folders DELETE), P10-7 (settings PUT) — but allow_methods stayed.
**Result**: pytest's `TestClient` skips CORS preflight, so all 466 tests stayed green. But in the real browser, the user clicked the trash icon in the Phase 10 RAG tab → browser sent OPTIONS preflight → CORS rejected with `400 Disallowed CORS method` → browser never sent the DELETE → `TypeError: Failed to fetch`. **Many PATCH/DELETE/PUT routes had been silently dead for nearly 6 months, masked by GET/POST-only screens**.
**Lesson**: FastAPI CORS should use `allow_methods=["*"]` or list every verb in use (`GET/POST/PUT/PATCH/DELETE/OPTIONS`). When adding a new verb route, check CORS settings too. For regression prevention, include at least one OPTIONS preflight in tests — `TestClient` skips it but `httpx.Client` with explicit headers can verify. Generalization: **the CORS behavior gap between test environment (TestClient/curl) and real browser** is the biggest false-green source — for verbs that need preflight (DELETE/PATCH/PUT/Custom-Header POST), click them in a real browser at least once (or `OPTIONS` curl returns 200).

## [2026-05-02] `ensure_namespace` skipped manifest seed → new namespace disappeared from listing
**Tried**: P10-2a `src/rag/namespace.py::ensure_namespace()` only mkdir'd `vectorstore_root/<ns>/` + `company_docs_root/<ns>/`. `list_namespaces()` identifies namespaces by manifest.json existence. POST `/rag/namespaces` happy-path was unit-tested.
**Result**: User scenario — `POST /rag/namespaces "test-ns"` → 201 + `_summarize` returns valid empty-manifest summary → immediate `GET /rag/namespaces` → **new namespace missing from list**. Invisible until first Re-index writes the manifest. User stuck: "I just made it, where'd it go?"
**Lesson**: When two artifacts (manifest existence vs directory existence) are treated by different functions for different intents, the code path that creates one must also satisfy the other's invariant. Fix: `ensure_namespace` writes empty manifest (`{"version":1,"updated_at":null,"documents":{}}`) atomically (tmp + replace) at the same time. Generalization: **"this artifact is the source-of-truth for X"-style invariants don't get caught by happy-path unit tests** — they surface only in cross-function integration scenarios (POST then GET). When writing entity-creation code, always ask: "How does another function discover this entity? Is that discovery path satisfied right now?"

## [2026-05-01] Windows uvicorn context: `subprocess.Popen(["explorer", path])` silent fails
**Tried**: P10-9 "open current folder in OS file manager" endpoint, first cut — `subprocess.Popen(["explorer", abs_path])` (aimed at cross-platform). Unit test monkeypatched `subprocess.Popen` and passed.
**Result**: When user clicked the 🗂 Explorer button in the RAG tab, the endpoint returned 200 + `opened=True` but no Explorer window opened. uvicorn spawning `explorer.exe` from a console-detached (background) context seems to swallow stderr, no exception raised. From user's view: "the button is broken".
**Lesson**: On Windows, OS-level operations (file manager, default-app launch) should use `os.startfile(path)` — that's canonical. `subprocess.Popen([...])` is only reliable in console-attached contexts. OS-branch code goes into a single wrapper `_launch_file_manager(abs_path) -> bool` and the endpoint exposes only the result boolean — tests monkeypatch the wrapper itself (Popen is brittle because each OS branch follows its own logic). See `playbook.md#16`. Same principle applies to `os.startfile`, `webbrowser.open`, notification libraries, etc.

## [2026-05-04] uvicorn `--reload` doesn't pick up new router imports, and a dead reloader's child worker held :8000
**Tried**: While working on Cost Explorer, added `from src.api.routes import cost as cost_routes` + `app.include_router(cost_routes.router, ...)` to `src/api/app.py`. Expected uvicorn `--reload`'s file watcher to auto-pick it up → verified with `curl /cost/summary` after the change.
**Result**: `404 Not Found`. `/openapi.json` also missing the cost route. Direct python import confirmed the route was registered properly → **uvicorn worker was stale**. Tracing: launched first uvicorn earlier in the session (PID A reloader → PID B worker), then later launched a second uvicorn (PID C reloader → PID D worker) — PID A reloader died but its child PID B worker survived as orphan, holding :8000. New PID C/D spawned but the port was taken → couldn't listen → curl hit the still-alive PID B (old code, no cost route) and got 404. Windows `Get-NetTCPConnection -LocalPort 8000` showed PID as the reloader, which was misleading.
**Lesson**: Don't assume reload "just handles it" for backgrounded uvicorn. Adding routers, modifying `include_router`, adding schemas — anything **evaluated only at app-object construction time** — often isn't picked up by reload (the file watcher re-imports changed modules but doesn't force app-object reconstruction). Workflow:
1. After adding a router, confirm registration with `curl /openapi.json | grep <new-path>`
2. If missing, **kill all python processes and restart** (including orphan workers). PowerShell: `Get-WmiObject Win32_Process -Filter "Name='python.exe'" | Where { $_.CommandLine -match 'uvicorn' } | Stop-Process -Force` + clean up leftover python
3. After restart, `curl /openapi.json` to confirm the new route → then validate business logic
Generalization: **know the boundary between "things --reload catches" and "things needing process restart"**. include_router / lifespan / pydantic schema definitions / middleware add_middleware / cli typer add_command all fall into the latter.

## [2026-05-04] retriever singleton cache wasn't invalidated after ingest → ChromaDB HNSW reader stale → "Nothing found on disk"
**Tried**: User created namespace `test260502` → called AI Summary once (filling cache) → uploaded files → Re-index → ran Discovery. Discovery failed with `Error executing plan: Internal error: Error creating hnsw segment reader: Nothing found on disk`. UI showed `seed 0 docs / 0 chunks`.
**Result**: Disk state was healthy — `data/vectorstore/test260502/manifest.json` had 46 chunks, `chroma.sqlite3` 729KB, 4 HNSW segment files all valid. **A separate-process fresh `chromadb.PersistentClient`** querying the same path returned 46 chunks fine — index itself was intact. Cause was the `src/rag/retriever.py:_STORES` singleton inside the uvicorn process. Route `POST /rag/.../namespaces/.../summary` (routes/rag.py:1138) on an empty namespace called `_retriever._store(ws_slug, ns)` → `VectorStore` cache entry pinned a stale ChromaDB 1.5.8 Rust-core in-memory HNSW reader. Even though a separate indexer client wrote new segments to the same sqlite, the cached retriever client never refreshed. `count()` reads SQLite directly so it was fresh, but `_collection.query()` walks the old in-memory state → error. UI's "0 docs" was a side effect — retrieve failed before `_read_seed_meta` (discover.py:316 vs 341), so RunRecord's default 0 stayed.
**Lesson**: ChromaDB 1.x `PersistentClient` keeps **per-instance independent in-memory state**, so two clients pointing at the same path within one process can desync. Our retriever singleton, once filled, never resets (`reset_store_singleton` was test-only) — staled after the indexer ran. **Fix**: Added a single line `_retriever.reset_store_singleton()` to the `code == 0` branch of `src/api/runner.py:execute_ingest`. Over-invalidates (clears caches for other namespaces too), but the next retrieve's fresh-client warmup cost is negligible. **Generalization**: when external libraries (Chroma/SQLite WAL/lmdb etc.) allow multi-client access to the same path within one process, a writer client must invalidate the others. Per-key precise invalidation is in backlog.

## [2026-05-04] Integration test clobbered real `config/pricing.yaml` without an isolation fixture
**Tried**: First version of `tests/test_api_cost.py` had only a `_reset_env` fixture, then called `client.put("/settings/pricing", json={"raw_yaml": ...})`. Regression green (`6 passed`). Opening `config/pricing.yaml` after, found the **real production yaml overwritten with test inputs** (`input_per_mtok: 5.0` etc.). `cost_budget.yaml` was the same.
**Result**: Caught immediately by user → manually restored to defaults (Sonnet $3/$15/$0.30/$3.75). Had this slipped, that commit would have shipped wrong unit prices to all users, breaking Cost Explorer with 5x rates. Cause: the `tests/test_api_settings.py::isolated_config` fixture in the same directory already had `monkeypatch.setattr(_loader, "CONFIG_DIR", cfg)` for tmp-directory isolation — but the new test was written without applying that pattern, hitting prod CONFIG_DIR directly.
**Lesson**: For integration tests of **filesystem-mutating endpoints** like `PUT /settings/{kind}`, isolation fixtures around prod config dir are mandatory. When creating a new test file, search the same domain (`test_api_*`) for existing fixture patterns first. This case was solved by reusing the `isolated_config` fixture as-is. Generalization: **if a test can mutate prod artifacts (config/cache/DB), make an isolation fixture autouse by default** — without it, force an explicit `# uses prod CONFIG_DIR — read-only only` comment policy. Even safer: give mutating helpers like `_atomic_write_text` / `putSettings` a read-only mode flag, and tests can lock with `MUTATION_GUARD=read-only`.
