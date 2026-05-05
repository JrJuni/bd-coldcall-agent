# Playbook

The single source of truth for **patterns judged reusable** after solving a hard problem.

- **Relation to `lesson-learned.md`**: lessons are the "never make this mistake again" axis; playbook is the "this approach also works elsewhere" axis.
- **Lookup trigger**: when you hit an error or get stuck, **grep the keyword index here first**. Confirm whether you've solved a similar problem before, then drill down to lessons / architecture / code.
- **Inclusion bar**: (1) actually validated working in this project, AND (2) reusable outside this project. One-off bug fixes don't qualify.
- **vs memory `feedback_*.md`**: playbook is for **project code/structure** patterns. Memory feedback is for **user collaboration style/preferences**. Keep the two stores distinct.

---

## Keyword Index

| Tags | Title | One-line summary |
|------|------|-----------|
| `langgraph` `state-design` `post-mortem` `dag-pipeline` | [1. Stage-dedicated output keys](#1-stage-dedicated-output-keys-preserve-post-mortem) | Don't let multiple nodes overwrite a single key — give each node its own key + a `latest_X(state)` fallback helper |
| `langgraph` `monkeypatch` `testing` `module-access` `false-green` | [2. Orchestration layers import via module](#2-orchestration-layers-import-via-module-for-testability) | Use `from pkg import mod as _mod` + `_mod.Y` runtime attribute, not `from X import Y` |
| `sse` `background-tasks` `polling` `event-log` `anyio` `concurrency` | [3. SSE: append-only event log + polling, not async queue](#3-sse-append-only-event-log--polling-not-async-queue) | When events ≤ a few dozen and append-only, polling is simpler than coroutine-threadsafe queues |
| `anthropic` `prompt-cache` `cost-optimization` `ephemeral` | [4. Cache boundary on fixed blocks only](#4-cache-boundary-on-fixed-blocks-only-cache_control-ephemeral) | `cache_control: ephemeral` only on **immutable** blocks (tech_docs). Mixed-in volatile content invalidates the cache |
| `dual-model` `cost` `hallucination` `role-split` | [5. Local model = deterministic preprocessing, cloud = reasoning](#5-local-model--deterministic-preprocessing-cloud--reasoning) | 7~8B local does translate / tag / dedup only. BD / summary / synthesis is done by the bigger model on raw input |
| `llm-input` `tag-tier` `token-budget` | [6. Tag-tier body vs snippet allocation](#6-tag-tier-body-vs-snippet-allocation) | High-value tag → full body, low-value → snippet only. ~35% token reduction with no info loss |
| `incremental-indexing` `atomicity` `rag` `safety` | [7. Embed-first atomicity for mid-failure recovery](#7-embed-first-atomicity-for-mid-failure-recovery) | chunk→embed must succeed first before touching store/manifest. Mid-failure → state unchanged |
| `work-planning` `stream-split` `phase-design` `context-window` | [8. Big work = 3–5 streams + TO-BE/DONE checklist](#8-big-work--35-streams--to-bedone-checklist) | Survives session breaks and context pressure; resumable across sessions |
| `windows` `stdout` `cp949` `framework-help` | [9. Declarative CLI frameworks: stdio UTF-8 at module load](#9-declarative-cli-frameworks-stdio-utf-8-at-module-load) | Typer/Rich render help before command body → in-body reconfigure is too late |
| `multi-channel` `raw-data` `dedup` `rank-policy` `partial-success` | [10. Multi-channel raw collection: rank-based keep + partial-success](#10-multi-channel-raw-collection-rank-based-keep--partial-success) | Per-channel try/except + rank-based dedup. One channel's failure shouldn't kill the others |
| `static-tier` `human-in-the-loop` `runtime-deterministic` | [11. AI draft + human-curated static tier = ops stability](#11-ai-draft--human-curated-static-tier--ops-stability) | Use build-time LLM drafts → committed yaml, instead of runtime LLM calls. Deterministic, free, reviewable |
| `mvp-cut` `flat-schema` `human-review` `output-format` | [12. MVP one-shot output = flat data + grouped report pair](#12-mvp-one-shot-output--flat-data--grouped-report-pair) | Even unverified LLM 1-shot output should be emitted as both flat yaml (edit/UI-friendly) and grouped md (review-friendly) |
| `llm-output-budget` `max-tokens` `step-isolation` `truncate-failure` | [13. Per-step `max_tokens` setting](#13-per-step-max_tokens-setting) | When adding a new step, estimate output distribution separately even if input pattern is similar. New setting key beats retry |
| `llm-judgment-decompose` `weighted-scoring` `external-yaml` `reproducibility` | [14. Decompose LLM judgment into scores + rules](#14-decompose-llm-judgment-into-scores--rules) | Before suppressing LLM hallucination via prompt tuning, check if decidable parts can be peeled off into code. External yaml for weights enables reproducibility, reuse, and $0 recompute |
| `non-dev-persona` `ui-design` `abstraction-leak` `internal-vs-external` | [15. Don't leak backend abstractions into non-developer UIs](#15-dont-leak-backend-abstractions-into-non-developer-uis) | Internal concepts (namespace, chunks, manifest) must stay off-screen — users don't make decisions from them |
| `os-launch` `windows` `headless` `testability-wrapper` | [16. Wrap OS file-manager calls into a single function](#16-wrap-os-file-manager-calls-into-a-single-function) | On Windows use `os.startfile`, not `subprocess.Popen`. Wrap into one function so tests can monkeypatch |
| `manifest` `staleness` `derived-aggregate` `rag` `incremental` | [17. Per-item timestamp → folder-level stale detection](#17-per-item-timestamp--folder-level-stale-detection) | Compare manifest.indexed_at + filesystem mtime to derive `needs_reindex` per folder. New user signal without new metadata |
| `multi-tenant` `path-resolution` `legacy-preserve` `asymmetric-default` | [18. When introducing multi-tenancy, only the default tier preserves legacy layout](#18-when-introducing-multi-tenancy-only-the-default-tier-preserves-legacy-layout) | Treating `default` as "no suffix" lets the existing data stay in place — zero migration |
| `display-toggle` `optional-cleanup` `non-destructive-default` `recover-by-readd` | [19. Display-only registration + opt-in cleanup](#19-display-only-registration--opt-in-cleanup) | Register/remove only touches DB rows; cleanup of side artifacts is an explicit option. Recovery from user mistakes = re-add by same name |
| `yaml-edit` `single-key-swap` `comment-preserve` `regex-line-replace` | [20. Single-line regex replace for one-key yaml edits](#20-single-line-regex-replace-for-one-key-yaml-edits) | PyYAML round-trip loses comments / indent / key order. When only one line needs changing, regex is safer |
| `non-dev-ux` `form-with-escape` `progressive-disclosure` `config-editor` | [21. Friendly form + YAML escape toggle for both personas](#21-friendly-form--yaml-escape-toggle-for-both-personas) | Default to input form; "Edit YAML" toggle exposes raw textarea fallback. Same PUT path either way |

When entries grow, re-sort by tag alphabetical order. Remove only when a pattern is invalidated (and record why).

---

## 1. Stage-dedicated output keys preserve post-mortem

**Tags**: `langgraph` `state-design` `post-mortem` `dag-pipeline`

**Problem**: A LangGraph pipeline where `search → fetch → preprocess` overwrites a single `articles` key in sequence. On mid-failure, the state alone can't tell which stage's output is left, and the saved file `articles_after_preprocess.json` becomes a misleading name depending on the situation.

**Solution**: Split into 3 keys on `src/graph/state.py::AgentState`: `searched_articles` / `fetched_articles` / `processed_articles`. Each node **only adds its own output**, and consumes prior keys read-only. `persist_node` writes the canonical output via `latest_articles(state)` helper (`processed > fetched > searched` fallback) and on failure path also dumps stage snapshots (`articles_searched.json`, `articles_fetched.json`).

**Why it works**: Append-only state means even at the failure point you can observe the entire prior-stage artifact. Filenames always carry "the data the name promises".

**Reusable in**: Any DAG/pipeline where downstream stages need to observe upstream artifacts for post-mortem — not just LangGraph. ETL, batch jobs, ML training pipelines all share the same principle.

---

## 2. Orchestration layers import via module for testability

**Tags**: `langgraph` `monkeypatch` `testing` `module-access` `false-green`

**Problem**: Bind via `from src.api.runner import execute_run`, then have a test do `monkeypatch.setattr("src.api.runner.execute_run", fake)` — the route module already has the original reference frozen at import time and keeps calling it. Tests "pass" but real Exaone / Sonnet calls leak through (false green; network and cost leak).

**Solution**: Orchestration layers do **runtime attribute lookup** via `from src.api import runner as _runner` + `_runner.execute_run(...)`. When tests patch `_runner.execute_run`, the route sees the new reference. `src/graph/pipeline.py` follows the same pattern with `from src.graph import nodes as _nodes`. Promoted to CLAUDE.md `## DO NOT`.

**Why it works**: In Python, `from X import Y` pins Y in the current module's namespace as a new binding. Changing `Y` on the original module does not propagate. Holding a module reference means each attribute access is a dict lookup — always fresh.

**Reusable in**: **Every Python project** that monkeypatches external calls / LLM / DB clients in tests. Apply by default to thin orchestration layers like graph/pipeline/route/adapter. Constants/types/exception class imports are exempt.

---

## 3. SSE: append-only event log + polling, not async queue

**Tags**: `sse` `background-tasks` `polling` `event-log` `anyio` `concurrency`

**Problem**: To relay pipeline progress from FastAPI `BackgroundTasks` (anyio worker thread) to SSE (event loop), the first sketch was `asyncio.Queue` + `asyncio.run_coroutine_threadsafe(queue.put, loop)`. Thread boundaries, caller awareness of the loop, backpressure, and bounded-queue memory all push complexity up.

**Solution**: `RunRecord.events: list[RunEvent]` (seq/kind/ts/payload) + `threading.Lock`. SSE side calls `snapshot_events(since_seq=last_seq)` every 150ms via a `last_seq` cursor, yields incrementally, and closes the stream on terminal state (`completed`/`failed`). `src/api/store.py` + `src/api/routes/runs.py::run_events`.

**Why it works**: When events are **few** (≤ a few dozen per run) and **append-only**, polling beats a queue for simplicity. `threading.Lock` is only needed for list append/slice; SSE and worker don't have to coordinate scheduling. The 150ms polling overhead is negligible at small event counts.

**Reusable in**: Streams that are sparse and have a known end (build jobs, pipeline progress, long-computation status reports). For 100s of events/sec or long-lived subscriptions (pub/sub), consider Redis Streams / Celery events.

---

## 4. Cache boundary on fixed blocks only (`cache_control: ephemeral`)

**Tags**: `anthropic` `prompt-cache` `cost-optimization` `ephemeral`

**Problem**: Anthropic prompt caching only hits "exactly the same blocks from the front". You can append volatile content **after** a cached block fine, but if volatile content is mixed **inside** the cached block, the cache invalidates every call and you only pay for cache_write with no benefit.

**Solution**: `src/llm/claude_client.py::chat_cached` splits user content into 3 blocks and **only the first block (tech_docs)** carries `cache_control: ephemeral`. Articles + task come uncached afterward. `src/llm/synthesize.py` builds prompts with this exact structure.

**Why it works**: tech_docs (RAG chunks) is identical when running multiple targets against the same company — 100% cache hit. Articles vary per target, so they must stay outside the cached region. cache_read is 10% of input rate, cache_write is 125% — break-even at 2 reuses.

**Reusable in**: Every LLM app using Anthropic Sonnet / Opus. Especially RAG and chatbots with the "large fixed context (docs/prompts/tools) + small variable query" shape.

---

## 5. Local model = deterministic preprocessing, cloud = reasoning

**Tags**: `dual-model` `cost` `hallucination` `role-split`

**Problem**: Asking a 7~8B-class local LLM to do reasoning tasks like "news summary → BD signal extraction" produces hallucination + context loss. Feeding the local model's summary JSON back into Sonnet "double-compresses" and loses the original nuance.

**Solution**: Local Exaone 7.8B 4-bit does **deterministic preprocessing only** — translation (only when `lang != target_lang`), 9-tag ENUM classification, bge-m3 cosine dedup. Tag/translate guarantee valid output via whitelist + passthrough fallback. Sonnet receives `translated_body` raw and does all BD reasoning in one place. Boundary at `src/llm/{translate,tag}.py` + `src/llm/synthesize.py`.

**Why it works**: Small models are good at "selection / classification / transformation" but weak at "judgment / synthesis". Mixing both stages propagates the weakness downstream. Role split exploits the small model's strengths and feeds the big model lossless input — cost down, quality preserved.

**Reusable in**: General principle for "open-source local + cloud API" hybrid designs in any LLM app, not just RAG. Translate / classify / extract → local; summarize / synthesize / reason → cloud.

---

## 6. Tag-tier body vs snippet allocation

**Tags**: `llm-input` `tag-tier` `token-budget`

**Problem**: Feeding 20 collected articles to Sonnet at full body → tens of thousands of input tokens. Cost aside, context-window competition dilutes tech_docs and the task instruction.

**Solution**: 7 high-value tags in `src/llm/tag_tier.py::HIGH_VALUE_TAGS` frozenset (`earnings`, `m_and_a`, `partnership`, `funding`, `regulatory`, `product_launch`, `tech_launch`) → full `translated_body`; 2 low-value tags (`leadership`, `other`) → `snippet` only. Switching happens just before synthesis via `select_body_or_snippet()`.

**Why it works**: From a BD perspective, "high deal-likelihood signals" concentrate in 7 categories. leadership / other are background — title + snippet is enough. Measured: ~35% input-token savings, no proposal-quality difference (Phase 8 Tesla / Deloitte real-world).

**Reusable in**: Any "give the LLM these documents and do something" situation. Classify documents by "how deeply worth reading" and feed different sizes per tier. Beyond search RAG: email summarization, news briefs, customer-support response, etc.

---

## 7. Embed-first atomicity for mid-failure recovery

**Tags**: `incremental-indexing` `atomicity` `rag` `safety`

**Problem**: A RAG indexer steps through (a) chunk → (b) embed → (c) store upsert → (d) manifest update. If it dies mid-way (e.g. OOM during embed), some entries are in the store but the manifest is still old — the next run sees "same hash, skip" and silently leaves the gap.

**Solution**: In `src/rag/indexer.py::_process_document`, **embed must fully succeed first** before proceeding to `delete_document → upsert_chunks → manifest[doc_id]` update. On embed failure, store / manifest are **both unchanged** — only the error counter increments. Manifest writes use tmp file → `os.replace` for atomic swap.

**Why it works**: Place the most failure-prone step (embed: network, OOM, CUDA, etc.) first. Subsequent store/manifest are local I/O — atomicity is easy. On failure, state stays "pre-run" so the next attempt naturally recovers.

**Reusable in**: Any incremental indexing / batch job. Reorder "external call → local store" so external failure leaves local state intact. General data-pipeline principle ("prepare before commit").

---

## 8. Big work = 3–5 streams + TO-BE/DONE checklist

**Tags**: `work-planning` `stream-split` `phase-design` `context-window`

**Problem**: Pushing an entire phase in one session means context pressure on the back half + early decisions get fuzzy. Session interruption or `/compact` makes "where did I leave off?" hard to find.

**Solution**: Split a phase into **3–5 work streams by layer**, with **TO-BE / DONE checklists** in a plan file (`~/.claude/plans/*.md`) per stream. Align stream boundaries to `/compact` points (~2 per session). Example: Phase 3 RAG = Stream 0 (config) / 1 (schema/chunking) / 2 (store/retrieval) / 3 (connectors) / 4 (indexer/CLI).

**Why it works**: Streams are "layer-complete + testable units" — order-independent. Checkboxes let the next session resume exactly by reading just the plan file + status.md. Each stream ends with a green test → next stream builds safely on top.

**Reusable in**: Big implementation / migration / refactoring in general. Applies to LLM-agent collaboration and to human developers alike whenever "pick up later" is a factor.

---

## 9. Declarative CLI frameworks: stdio UTF-8 at module load

**Tags**: `windows` `stdout` `cp949` `framework-help`

**Problem**: On Windows cp949 console + Typer/Rich combo, putting `sys.stdout.reconfigure(encoding="utf-8")` inside the command function means Rich renders help text **before** the body runs → em-dash / Korean already encoded as cp949 and fail.

**Solution**: Place the block at the **top of `main.py`** (around imports): `for _stream in (sys.stdout, sys.stderr): _stream.reconfigure(encoding="utf-8")`. Typer/rich starts already in UTF-8.

**Why it works**: Procedural CLIs like argparse only run help inside the command body, but declarative frameworks like typer/rich register and immediately render help via decorators at import time. Encoding setup must come earlier.

**Reusable in**: Any declarative CLI framework on Windows — Typer, Click + Rich, Hydra. General principle: "configure stdio before importing the framework".

---

## 10. Multi-channel raw collection: rank-based keep + partial-success

**Tags**: `multi-channel` `raw-data` `dedup` `rank-policy` `partial-success`

**Problem**: When the same raw signal (news / docs / search results) must be gathered along multiple semantic axes — one channel lacks diversity, multiple channels cause (a) cross-channel duplication, (b) one channel failing can take the whole thing down, (c) channel priority is unclear. Three problems hit at once.

**Solution**:
1. **Channel registry** pattern — `src/search/channels/__init__.py::run_all_channels` holds channel functions in a dict and fans out via `ThreadPoolExecutor`. Adding/removing a channel = one dict line.
2. **Per-channel try/except** — each channel returns `(articles, meta)`; exceptions are recorded into `channel_errors` and the channel returns an empty list. The node fails only when all channels fail.
3. **Rank-based dedup** — `CHANNEL_RANK = {"target": 0, "related": 1, "competitor": 2}`. URL dedup keeps the lower rank. Semantic dedup (`_pick_representative`) also adds channel rank to its sort key.
4. **First-class channel field** — `Article.channel: Literal[...]` is a dataclass field (not a metadata dict entry). Default value for serialization compatibility.

**Why it works**: When rank is a comparable integer, dedup-keep policy stays simple, and adding a new channel is just inserting a rank slot. partial-success is a direct ops win — "one channel's transient failure (e.g. Brave 5xx) doesn't kill the whole BD run".

**Reusable in**: Beyond search — multi-source RAG (ChromaDB + Notion + Slack + GitHub), multi-monitoring (Datadog + Sentry + CloudWatch), multi-model ensembles, etc. Anywhere you merge multiple sources into one output stream. CV-mining pivot (backlog item 15) reuses the same pattern as-is.

---

## 11. AI draft + human-curated static tier = ops stability

**Tags**: `static-tier` `human-in-the-loop` `runtime-deterministic`

**Problem**: For "domain knowledge data" like search intent / filters / prompts, the two extremes are: (a) runtime LLM dynamic generation = adapts automatically to RAG changes, but nondeterministic, expensive, hard to debug / (b) hardcoded static list = deterministic, free, reviewable, but somebody has to author it from scratch → stuck on empty start.

**Solution**: **Build-time LLM draft + runtime static yaml** hybrid.
- A one-shot script (`scripts/draft_intent_tiers.py`) takes the RAG index + a one-line product summary, calls Sonnet once → produces yaml-format draft
- Human reviews and refines, commits as `config/intent_tiers.yaml`
- Runtime reads the yaml only — no LLM calls, deterministic, cache-irrelevant

**Why it works**: First user experience starts not from "empty yaml" but from "received a draft, refining it". In ops, yaml is git-tracked → change history, easy A/B compare, $0 cost. When content grows, re-run the drafter.

**Reusable in**: Prompt libraries, classification rules, search-intent lists, few-shot examples, evaluation rubrics — any "text data the LLM drafts well but humans must correct". Combines dynamic vs static cost-efficiency via a human-in-the-loop bridge.

---

## 12. MVP one-shot output = flat data + grouped report pair

**Tags**: `mvp-cut` `flat-schema` `human-review` `output-format`

**Problem**: With unverified LLM 1-shot output (Phase 9 reverse-matching MVP — Sonnet 1 call producing 25 candidates + 5 industries), two conflicting needs arise: (a) a grouped-by-section report a human can quickly skim and prune / (b) a flat machine-friendly format for downstream automation (editor UI / SQLite import / `targets.yaml` auto-add). One format can't satisfy both — flat-only forces the human to re-group by industry (5-min review balloons to 30 min); grouped-md-only makes in-place editing and tabular import painful.

**Solution**: Serialize the same LLM response into **two forms** and store as a pair.
- `outputs/discovery_<date>/candidates.yaml` — flat list (`name, industry, tier, rationale`) + meta (`generated_at, seed{}, industry_meta, usage`). Future input format for SQLite import → web editor UI.
- `outputs/discovery_<date>/report.md` — grouped by industry, seed-meta header, Markdown table sorted by Tier (S→A→B→C), token-summary footnotes. 5-minute human review.
- Both derive from the same `DiscoveryResult` instance — `_candidates_to_yaml()` / `_render_report()` are pure functions that unfold the same dataclass into different views.

**Why it works**: Flat's downside (human readability) is covered by grouped md; grouped's downside (editor input difficulty) is covered by flat yaml. Zero extra LLM calls — re-serializing the same response into two views is essentially free. The decision "MVP cut, no verification" doesn't drop output quality, because this pairing is a guardrail.

**Reusable in**: LLM 1-shot analysis anywhere — resume → fitting companies (backlog 15), sales response → cluster (backlog 16), product → competitive analysis. Whenever human review is mandatory, output as (flat data, grouped report) pair to lower entry costs for downstream automation / web UI / re-import.

---

## 13. Per-step `max_tokens` setting

**Tags**: `llm-output-budget` `max-tokens` `step-isolation` `truncate-failure`

**Problem**: When a new LLM step's input pattern looks similar to an existing step (both RAG seed + system prompt), it's tempting to reuse the same `max_tokens` setting. But **output distribution differs per step** — synthesize's 5 ProposalPoints (~1.5K out), discover's 5 industries + 25 candidate rationales (~2.5K out), draft's 4-section markdown (~3K out) all have similar inputs but ×2 output spread. One shared setting either truncates the larger steps or wastes headroom on smaller ones.

Worse: **truncated responses cannot be recovered by retry**. Retrying the same `max_tokens` truncates at the same place. Unclosed JSON outputs fail every parser → only ValueError repeats.

**Solution**: When adding a new step, **estimate output separately → create a new setting key**.
- Estimation formula: `n_items × (avg item tokens + structural overhead) × 1.3 safety`
- Phase 9 example: `25 × (~80 rationale + ~20 JSON keys) × 1.3 ≈ 3300 → round up to 4000`
- Result: per-step keys `claude_max_tokens_synthesize=2000` / `claude_max_tokens_draft=4000` / `claude_max_tokens_discover=4000` (`config/settings.yaml` + `LLMSettings`)
- After first real run, measure `output_tokens` → confirm 1.5× headroom → tune if short

**Why it works**: 1:1 step↔setting mapping means (a) one step's output explosion doesn't hit other steps, (b) git diff makes "which step is getting expensive" visible, (c) blocks truncate-fail-by-fixed-budget that retry can't recover. Retry can absorb model variability (JSON-format slip / temperature) but not fixed budget shortfalls like max_tokens.

**Reusable in**: Every project that adds a new LLM step. Especially when same model + same input pattern tempt mindless setting reuse. Add "what is this step's expected output_tokens?" to plan-stage checklist. Same principle generalizes to per-step budget keys: timeout, batch_size, top_k, etc.

---

## 14. Decompose LLM judgment into scores + rules

**Tags**: `llm-judgment-decompose` `weighted-scoring` `external-yaml` `reproducibility`

**Problem**: The first instinct when LLM output quality lags is prompt tuning. But that's nondeterministic and unverifiable — same input, different result; can't decompose "why this judgment"; hard to reuse across domains (other product / industry). Phase 9's first run (`outputs/discovery_20260428` v1) hit this trap exactly — Sonnet directly classified 25 companies into S/A/B/C with mega-cap bias + 0 C-tier + result drift on rerun.

**Solution**: Before asking the LLM for high-level judgment (tier / recommendation / classification), check if it's decomposable:
1. Can this judgment be split into N-dimensional 0–10 scores?
2. Can weight + threshold per dim reproduce the same result?
3. Can weight·threshold be externalized to yaml for cross-domain reuse?

If decomposable, the LLM only scores and the code decides `final_score` and final tier via weighted sum + rule. weight·threshold are externalized to yaml.

Phase 9.1 application:
- LLM: outputs only `scores{6 dim 0-10}` + rationale (LLM's tier output silently dropped)
- Code: `final_score = sum(score[k] * weight[k])` + `decide_tier(final_score, rules)` (epsilon 1e-6)
- yaml: `config/weights.yaml` (default + product override + auto-normalize) + `config/tier_rules.yaml` (S/A/B/C threshold)
- Result: Snowflake A → B (LLM scored displacement_ease low; code reflected that), mid-caps (Stripe / Adyen / Toss) entered S

**Why it works**: Recomputing the same LLM response (`scores`) under different weights = $0. Other products (Snowflake / Salesforce) reuse via just adding `products.<name>` overrides. To answer "why S?", show per-dim score + weighted-sum formula — answer's done. The LLM call stage is isolated, so hallucination doesn't leak into the decision stage.

**Reusable in**: Tier classification, recommendation engines, candidate prioritization, evaluation/rubric-based scoring (LLM-as-judge backlog P2-6) — any multi-criteria decision. Pattern fit signals: (a) decision expressible as a weighted sum across comparable dimensions, (b) weights vary per domain/customer, (c) reproducibility on re-runs has value.

---

## 15. Don't leak backend abstractions into non-developer UIs

**Tags**: `non-dev-persona` `ui-design` `abstraction-leak` `internal-vs-external`

**Problem**: P10-3's RAG tab exposed backend concepts directly: namespace dropdown / "X chunks" / manifest path / "Indexed/Pending" / Danger zone. Developers know the meaning, but for non-developers it's all "what does this number mean? what should I do?" The persona (a non-dev BD person who can't even open OS Explorer) clashes with the UI's abstraction level.

**Solution**: Filter every label / field / warning visible in the UI through two questions:
1. **"Can the user make a decision based on this information?"** — keep only yeses. chunk count / manifest path / cache tokens don't lead users to a next action → remove
2. **"Does this word only have meaning inside our system?"** — yes → translate to common language. namespace → folder; indexed → Ready; "Re-index" is everyday enough → OK

P10-9 (RAG tab filesystem-mirror UX) application:
- Banished words: namespace, chunks, manifest, "indexed" → folder, files, (removed), Ready
- Removed columns: Chunks (whole) / SummaryPane footer's token usage / ExplorerPane manifest path
- Label translation: "Indexed/Pending" → "Ready/Pending"
- Removed feature: namespace permanent-delete modal (risk of users accidentally wiping ChromaDB + actual delete frequency near zero) — if really needed, OS Explorer (button already there)
- Phrase unification: "+ new namespace" / "+ new folder" branch → always "+ new folder". Backend still calls namespace creation, but the user doesn't know

**Why it works**: When the words on screen match the user's everyday vocabulary, learning curve ≈ 0. Hidden abstractions don't need user comprehension (isolation). UI simplification isn't fake simplification — it really removes "info that doesn't affect decision-making" without information loss.

**Reusable in**: Any non-developer-facing data/AI tool UI. Trigger inspection — every time the backend grows a new concept (cache layer, queue, shard), ask "should this surface as a new word in UI?" Default answer is NO. Same principle splits admin/dev console from user-facing UI (admin → abstractions OK).

---

## 16. Wrap OS file-manager calls into a single function

**Tags**: `os-launch` `windows` `headless` `testability-wrapper`

**Problem**: A backend endpoint that pops a local GUI (e.g. "open this folder in OS Explorer") has two traps. (1) On Windows, `subprocess.Popen(["explorer", path])` silent-fails in console-detached server contexts (uvicorn background) — stderr is swallowed, endpoint returns 200, no window opens. (2) OS-branch code (Windows / macOS / Linux) embedded in the handler causes tests to actually trigger OS calls — windows pop during tests or CI fails.

**Solution**: Wrap into a single function that handles OS branching + safe call + boolean failure:

```python
def _launch_file_manager(abs_path: str) -> bool:
    try:
        if sys.platform.startswith("win"):
            os.startfile(abs_path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_path])
        else:
            subprocess.Popen(["xdg-open", abs_path])
        return True
    except (OSError, FileNotFoundError, AttributeError) as exc:
        _LOGGER.warning("...: %s", exc)
        return False
```

The endpoint surfaces only `opened = _launch_file_manager(abs_path)` so the UI can show a clear message. Tests do `monkeypatch.setattr(_routes, "_launch_file_manager", lambda p: True)` to fake the function itself — patching `subprocess.Popen` would have to follow every OS branch and is brittle.

P10-9 application:
- Adopted Windows `os.startfile` (canonical). `Popen(["explorer", ...])` silent-fail confirmed in detached / console-detached contexts
- 5 tests use `_launch_file_manager` monkeypatch, validating call args + return value without popping real windows

**Why it works**: The wrapper colocates OS branching + exception handling + boolean result. The endpoint stays focused on business logic (path validation/resolution), with a single OS-call entry point. Tests block side effects with one-line patches.

**Reusable in**: Anywhere a desktop-app backend (FastAPI on localhost) calls OS features — open Explorer, default-browser URLs, system notifications, etc. Same pattern applies to clipboard (`pyperclip`), toasts (`win10toast`/`pync`/`notify-send`). Core: when "OS branching + side effects + testability" are in tension, a single function is the answer.

---

## 17. Per-item timestamp → folder-level stale detection

**Tags**: `manifest` `staleness` `derived-aggregate` `rag` `incremental`

**Problem**: An incremental indexing system needs the user to know "is there anything new in this folder that's not indexed yet?" (P10-9.1 RAG tab #4(a)). Naive approach: add separate folder metadata (`folder_indexed_at`) — but expanding the manifest schema means migration + touching indexer / retriever / connectors. And folders are user-mutable (move, rename), so folder-level metadata is an ongoing sync burden.

**Solution**: Keep per-document timestamps (`manifest.documents[doc_id].indexed_at`) as source of truth and compute folder-level staleness as a **derived aggregate**:

```python
def _folder_needs_reindex(folder_abs, ns_root, indexed_lookup) -> bool:
    """True if any descendant file is missing from manifest OR mtime > indexed_at."""
    for child in folder_abs.rglob("*"):
        if not child.is_file() or child.suffix not in _ALLOWED_EXTENSIONS:
            continue
        rel = child.resolve().relative_to(ns_root.resolve()).as_posix()
        entry = indexed_lookup.get(rel)
        if entry is None or not entry.indexed_at:
            return True  # new file
        mtime_iso = datetime.fromtimestamp(child.stat().st_mtime, tz=utc).isoformat()
        if mtime_iso > entry.indexed_at:
            return True  # modified after last index
    return False
```

Folder-level "last indexed at" is similarly derived: `MAX(indexed_at for rel in manifest if rel.startswith(folder_prefix))`. Use it as the stale-baseline for AI Summary persistence (compare against `indexed_at_at_generation`).

`_IndexedDoc(NamedTuple)` packs `chunk_count + indexed_at` into one type — switching `dict[str, int]` → `dict[str, _IndexedDoc]` once cleanly absorbs all callers.

**Why it works**: (1) **No schema changes** — reuses the existing `indexed_at` key in the manifest; indexer / connectors / retriever are untouched. (2) **Auto-consistent across user folder operations** — moving a file makes `rglob` find it under the new parent; the old parent naturally stops being stale. (3) **Cost is reasonable** — O(#files) stat per folder, mostly tens of ms for typical RAG corpora (tens to hundreds of files). Folds naturally into the tree response. (4) **Comparing `mtime` and `indexed_at` ISO timestamp strings is order-preserving lexicographically** (both formatted as `datetime.isoformat(tz=utc)` down to microsecond, identical format).

**Reusable in**: Any incremental-processing pipeline beyond RAG indexers — (a) build-system "stale target" detection (Make / Bazel timestamp compare generalized), (b) cache invalidation (cached summary stale after underlying data update), (c) ETL pipeline partition-level reprocess decisions. Core principle: **with per-item state as source of truth, the state of any group (folder / partition / shard) can always be computed consistently as a derived aggregate — don't add separate group-level metadata**. Separate metadata is the source of sync bugs.


---

## 18. When introducing multi-tenancy, only the default tier preserves legacy layout

**Tags**: `multi-tenant` `path-resolution` `legacy-preserve` `asymmetric-default`

**Problem**: A system running on a single root (`data/vectorstore/<namespace>/`) gains multi-tenancy (workspaces). Inserting a new prefix `<ws_slug>` into every path means moving existing data to `data/vectorstore/default/<namespace>/` + rewriting all manifest paths + invalidating user indexes — high impact.

**Solution**: The tier resolution function (`src/rag/workspaces.py::workspace_paths`) treats default tier **asymmetrically**:

```python
def workspace_paths(ws_slug: str) -> tuple[Path, Path]:
    if ws_slug == "default":
        # Legacy layout intact: existing data/vectorstore/<ns>/ stays where it is
        vs_root = _resolve_vectorstore_root()      # = data/vectorstore
        cd_root = PROJECT_ROOT / "data" / "company_docs"
    else:
        # New external tier: per-slug prefix
        vs_root = _resolve_vectorstore_root() / ws_slug
        cd_root = Path(workspace_row["abs_path"])
    return vs_root, cd_root
```

Callers (retriever/indexer/route) consistently use `vectorstore_root_for(ws_root, namespace)` — for default tier the result is `data/vectorstore/<ns>/` (no slug); for external tiers, `data/vectorstore/<slug>/<ns>/`. One place holds the branch; the rest stays clean.

**Why it works**: (1) **Zero existing-data migration** — `default`'s layout keeps its meaning. (2) **External tiers get per-slug isolation** — no slug collisions, no risk. (3) **Callers don't see the branch** — calling `workspace_paths(slug)` returns a slot interface. (4) **Migration functions also default-only** — `migrate_flat_layout` runs only for default tier (external tiers have no flat legacy data to begin with).

The asymmetry is intentional, transitional. Future normalization to a uniform prefix can happen later in a single data-move + function simplification. Until then, multi-tenancy entry without user-facing breakage.

**Reusable in**: Every single → multi-tenant transition — multi-DB split, multi-workspace, multi-project, multi-organization. Beyond file paths: DB schema (default tenant's rows allow tenant_id NULL → new tenants are NOT NULL), etc. **Core**: when legacy maps naturally to default, you can add new tenant isolation without breaking anything.

---

## 19. Display-only registration + opt-in cleanup

**Tags**: `display-toggle` `optional-cleanup` `non-destructive-default` `recover-by-readd`

**Problem**: When a user says "add this folder to the RAG tree", the backend has two side effects: (a) register a workspace row in the DB, (b) after indexing, create chroma + manifest under `data/vectorstore/<slug>/`. On removal, how far to roll back is the question. Wipe everything → no recovery from user mistakes; wipe nothing → disk leak.

**Solution**: Registration / removal touches the **DB row only** by default. Cleanup of side artifacts (vectorstore directories etc.) is split out as an **explicit opt-in option** (`?wipe_index=true` or modal checkbox). The user's source folder (registered abs_path) is **never** touched, in any case.

```python
def delete(self, workspace_id, *, wipe_index: bool = False) -> bool:
    # ... DB row delete ...
    if removed and wipe_index:
        # opt-in: wipe index + cache
        rmtree(vectorstore_root / slug, ignore_errors=True)
        conn.execute("DELETE FROM rag_summaries WHERE ws_slug=?", (slug,))
    return removed
```

UI flow:
- "Remove" button → modal (target + abs_path + "never deleted" notice)
- Checkbox (default unchecked): "Also delete the index (if unchecked, vectorstore is preserved — re-adding the same name reuses the existing index)"
- [Cancel] [Remove]

**Why it works**: (1) **User-mistake recovery = re-add by same name** — slug is auto-derived from the label, so matching the label regenerates the same slug and immediately maps to the preserved index. (2) **Disk-leak concern is solved by explicit toggle** — users who want cleanup check the box once. (3) **Destructive vs non-destructive boundary is visible in UI** — checkbox + helper text are the single point of user consent. (4) **Testable** — both `wipe_index=True/False` are pinned by separate test cases (`test_delete_wipe_index_removes_vectorstore` / `test_delete_without_wipe_keeps_vectorstore`).

**Reusable in**: Anywhere "user-registration + side artifacts" applies. (a) Cloud console resource deletion (DB instance vs backups vs snapshots), (b) package manager uninstall (`apt remove` vs `apt purge`), (c) VCS branch delete (`-d` vs `-D` vs working tree), (d) container orchestration service vs volume. Core principle: **default is always non-destructive; destructive is an explicit option + visible outcome**.


---

## 20. Single-line regex replace for one-key yaml edits

**Tags**: `yaml-edit` `single-key-swap` `comment-preserve` `regex-line-replace`

**Problem**: When the user clicks the "active model" dropdown in the frontend, only one line — `config/settings.yaml::llm.claude_model` — should change. The natural implementation is PyYAML round-trip (`safe_load → mutate dict → safe_dump`), but that loses (1) `# comments`, (2) key ordering, (3) flow vs block style preferences, (4) potentially affects unrelated parts of the same yaml. For human-edited yaml like settings.yaml, comments carry meaning, so round-trip loss is a user-visible regression.

**Solution**: When only one key needs changing, use **line-level regex in-place replacement**:

```python
_CLAUDE_MODEL_LINE_RE = re.compile(
    r"^(?P<indent>\s*)claude_model:\s*[^\n#]*(?P<trail>\s*(?:#.*)?)$",
    re.MULTILINE,
)

def _swap_claude_model_line(raw_yaml: str, new_model: str) -> str:
    if _CLAUDE_MODEL_LINE_RE.search(raw_yaml):
        return _CLAUDE_MODEL_LINE_RE.sub(
            lambda m: f"{m.group(\"indent\")}claude_model: {new_model}{m.group(\"trail\")}",
            raw_yaml, count=1,
        )
    # Fallback: round-trip only on regex miss (acknowledging comment loss)
    data = yaml.safe_load(raw_yaml) or {}
    data.setdefault("llm", {})["claude_model"] = new_model
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
```

Key details:
- `^...$` + `re.MULTILINE` matches **only that line** (other yaml untouched)
- `(?P<indent>\s*)` / `(?P<trail>\s*(?:#.*)?)` preserve indent + trailing comment
- `count=1` defends against accidental multi-matches
- **After swap, always re-validate via pydantic** — regex doesn't guarantee yaml syntax; `Settings(**yaml.safe_load(new_raw))` blocks 422
- Atomic write (`tmp → os.replace`) + lru_cache invalidation so the next read sees the new value

**Why it works**: (1) A single yaml line is "key: value" + optional comment — simple grammar that fits one regex. (2) Adopting a round-trip library (ruamel.yaml) adds dependency cost for a one-key-one-place use case — overkill. (3) Falling back to round-trip on regex miss explicitly preserves correctness for unusual cases (flow-style mappings, etc.); comment loss is isolated to the fallback case — observable regression as an intentional trade-off. (4) "Other keys in the same yaml are absolutely untouched" is guaranteed at the regex level.

**Reusable in**: Any human-edited yaml/toml/properties file where you need to programmatically change just one key. (a) `pyproject.toml` version bump, (b) `.env` single-var swap, (c) k8s manifest image-tag swap, (d) Apache/Nginx config single-directive change. For multi-key edits or new section additions, round-trip libraries (ruamel.yaml, tomlkit) are appropriate. **Decision rule**: "comment/format preservation vs single-line swap" trade-off → regex; "structural change + comment preservation" both required → round-trip library.

---

## 21. Friendly form + YAML escape toggle for both personas

**Tags**: `non-dev-ux` `form-with-escape` `progressive-disclosure` `config-editor`

**Problem**: Users split into two personas. (a) Non-developer BD staff — don't know yaml syntax, just want to fill an input like "what's Sonnet's price". (b) Power user — adds multiple models at once, writes comments, compares structures. Catering to one blocks the other — yaml-only puts a wall in front of non-devs; form-only frustrates power users.

**Solution**: **Friendly form is default; "Edit YAML" toggle exposes a raw textarea fallback**. Both modes share the same PUT endpoint (`PUT /settings/{kind}`) and same validation (2-pass: yaml syntax + pydantic schema).

```tsx
const [mode, setMode] = useState<"form" | "yaml">("form");

// On mode switch: form → fill textarea via yaml-serialize / yaml → setState via yaml.parse
function save() {
  const raw = mode === "form" ? toYaml(formState) : yamlText;
  await putSettings(kind, raw);  // backend validates yaml syntax + pydantic
}
```

UI flow:
- Default = form mode (input/select/checkbox-driven). Per-model 4 rates, monthly budget + warn% as narrow inputs
- Toggle in top-right: `[Edit Form] [Edit YAML]`
- Click "Edit YAML" → same spot becomes a textarea + inline validation errors. On save, surface the 422 message verbatim
- Save is the same endpoint either way; the backend doesn't know which mode produced the yaml

**Why it works**: (1) **Single source of truth = the yaml file** — the form is just a view atop the yaml; saves always converge to yaml. (2) **One validation path** — yaml syntax + pydantic schema both gated in the PUT handler, so form / YAML routes share the same safety net. (3) **No dead-end for power users** — fields the form lacks (e.g. add a new model, search rates) can be added immediately via YAML escape. (4) **No entry barrier for non-devs** — first screen is an input form; no need to learn yaml schema. (5) **Mode switches preserve dirty state** — form→yaml serialization / yaml→form via round-trip parse + setState. No changes lost.

**Reusable in**: Web UIs for any human-edited config. First applied in Cost Explorer's `PricingBudgetEditor` (model rates + monthly budget). Porting candidates: existing 7 Settings tabs (weights / tier_rules / competitors / intent_tiers / sector_leaders / targets / settings) — currently yaml-only, hard for non-devs. **Core principle**: "default to the simpler persona, give the complex persona an escape hatch". Same pattern as Slack's simple/advanced workflow editor, GitHub Actions' visual editor + raw yaml, Notion's database form + raw json view.
