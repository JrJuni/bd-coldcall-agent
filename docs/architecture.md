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

## 컴포넌트 상세

### 1. Search (`src/search/`)
- `SearchProvider` ABC — 무료 스크래퍼를 장기적으로 플러그인 가능
- `BraveSearch` — `/v1/news/search` + `/v1/web/search` 구현
- `bilingual.py` — 한글 쿼리일 때 번역 룩업으로 영문도 병행 검색, foreign ≥ 50% 보장
- 출력: `Article(title, url, snippet, source, lang, published_at, metadata)` — body 는 비어 있음

### 2. Fetch (`src/search/fetcher.py` — Phase 1.5)
- `ThreadPoolExecutor(max_workers=5)` 로 `httpx` + `trafilatura.extract(favor_precision=True)` 병렬 호출
- 커스텀 UA, per-url 10s timeout. 실패 시 snippet 을 body 로 복사하고 `body_source="snippet"` 표시
- 배치 통계(`body_stats`) 로 full/snippet/empty 비율 로그

### 3. Preprocess (`src/llm/preprocess.py` — Phase 2)
`src/llm/local_exaone.py` 가 싱글턴으로 Exaone 3.5 7.8B Instruct(4bit nf4, double quant)를 GPU 에 상주시키고, 세 단계를 순차 호출:

**3-1. Translate** (`src/llm/translate.py`)
- `article.lang == target_lang` 이면 passthrough (LLM 호출 0회)
- 다르면 `src/prompts/{en,ko}/translate.txt` 로 원문→target 번역. 고유명사·수치·인용·직함 보존
- 실패 시 원문 body 를 그대로 `translated_body` 에 복사 (파이프라인 중단 방지)

**3-2. Tag** (`src/llm/tag.py`)
- 9-태그 고정 ENUM (earnings / product_launch / partnership / leadership / regulatory / funding / m_and_a / tech_launch / other)
- JSON 출력 강제. `parse_tags()` 가 코드펜스·프로즈 포함 출력도 정규식으로 추출, ENUM 화이트리스트 필터링, 실패 시 `["other"]` fallback

**3-3. Dedup** (`src/rag/embeddings.py`)
- `BAAI/bge-m3` 싱글턴으로 `translated_body` 를 임베딩 (L2 정규화)
- 상삼각 코사인 행렬 → threshold 이상 쌍을 유사도 내림차순으로 정렬
- Union-find: 대표(rep) 선정은 `-len(body) → -published_at → index` 키
- **Floor-aware**: 그룹 수가 `min_articles_after_dedup` 와 같거나 낮아지면 merge 중단 — `stopped_by_floor=True` 로 리포트
- 각 article 에 `dedup_group_id` (≥0 = 그룹 소속, -1 = solo) 기록

### 4. RAG (`src/rag/`)

**스키마 (`types.py`):** `Document` / `Chunk` / `RetrievedChunk`. 공통 필드(title, source_type, source_ref, last_modified, mime_type) 명시 승격, 자유 필드는 `extra_metadata` 에 담아 Chroma 메타에서 단일 `extra_json` 키로 JSON 직렬화.

**정규화·청킹:**
- `normalize.py` — 줄별 rstrip → 연속 개행 ≥3을 2로 → 전체 strip. 내부 공백/indent 보존. 해시 안정화 공용 유틸
- `chunker.py` — 문단(`\n\n`) + 문장 단위 greedy 패킹. overlap 도 문장 단위 tail. 단일 문장이 `chunk_size` 초과 시 문자 hard-split + 문자 overlap fallback

**커넥터 (`connectors/`):**
- `SourceConnector` ABC (`source_type` ClassVar + `iter_documents()` 추상)
- `LocalFileConnector` — 재귀 rglob, `.md/.txt/.pdf` 화이트리스트. PDF 는 pypdf 페이지별 추출 후 `[Page N]` 구분자 삽입. 스캔 PDF(전 페이지 empty) skip, 빈/stat 실패 파일 warn+skip
- `NotionConnector` — token 또는 주입 client. `pages.retrieve` + `databases.query` 페이징. 블록 트리 DFS 로 `rich_text.plain_text` 추출, `child_page` 는 별도 Document 로 분리(중복 방지). title 규칙: page = title property → heading fallback → `Untitled`, DB row = title property only

**벡터 저장소 (`store.py`):**
- `VectorStore(persist_path, collection_name)` — `chromadb.PersistentClient` + `get_or_create_collection(metadata={"hnsw:space":"cosine"})`
- 메타 평탄화: `doc_id/chunk_index/title/source_type/source_ref/last_modified_iso/mime_type/extra_json`
- `similarity_score = 1 - distance/2` 로 코사인 distance 를 0~1 유사도(클수록 유사) 로 변환 — 외부 인터페이스에 raw distance 노출 안 함

**증분 인덱서 (`indexer.py`):**
- `run_indexer(connectors, store, manifest_path, ...)` — normalize → sha256 → manifest 비교 → chunk → embed → delete → upsert → manifest 갱신
- **원자성:** embed 가 먼저 성공해야 store/manifest 를 건드림. 중간 실패 → 상태 불변, 다음 실행에서 `updated` 로 복구
- **증분 매니페스트:** `data/vectorstore/manifest.json` (v1). `{doc_id: {content_hash, last_modified, indexed_at, chunk_count, source_type}}`. tmp → `os.replace` 로 atomic swap
- **커넥터 격리 삭제:** 활성 `source_type` 셋에 속한 엔트리만 삭제 후보. `--notion` 단독 실행이 로컬 엔트리를 evict 하지 않음
- CLI: `--local-dir` / `--no-local` / `--notion` / `--force` / `--dry-run` / `--verify`

**Retriever (`retriever.py`):**
- 모듈 싱글턴으로 `VectorStore` 재사용, `embed_texts([query])` → `store.query(emb, top_k)` → `list[RetrievedChunk]` (similarity_score 내림차순). 빈 query 가드. Phase 4 합성 노드가 추가 조회 없이 프롬프트 조립 가능한 형태

**임베딩:** `BAAI/bge-m3` (Preprocess dedup 과 모델 공유 — `embeddings.get_embedder()` 싱글턴)

### 5. Claude Agent (`src/llm/{claude_client,synthesize,draft}.py`)

**클라이언트 (`claude_client.py`):**
- `get_claude()` — Anthropic SDK 싱글턴 (lazy load, `ANTHROPIC_API_KEY` 검증)
- `chat_cached(system, cached_context, volatile_context, task, max_tokens, temperature, model, client)` — user content 를 3블록으로 분할, **첫 블록(tech_docs) 에만 `cache_control: ephemeral` 부착**. 반환 dict 에 `usage.cache_read_input_tokens` / `cache_creation_input_tokens` 포함
- `chat_once(system, user, max_tokens, temperature, model, client)` — 비캐시 단일 호출 (draft 용, 타겟별 고유 프롬프트라 캐싱 이득 없음)

**합성 (`synthesize.py`):**
- `synthesize_proposal_points(articles, tech_chunks, *, target_company, industry, lang, client=None) -> list[ProposalPoint]`
- 프롬프트: `<tech_docs>` (캐시됨) + `<articles>` (tag-tier 적용 body/snippet) + `<target>` + task
- **Tag tier (입력 토큰 ~35% 절감)**: high-value 7개(earnings, m_and_a, partnership, funding, regulatory, product_launch, tech_launch) 는 `translated_body` 전체, low-value 2개(leadership, other) 는 snippet 만. `src/llm/tag_tier.py::select_body_or_snippet` / `has_high_value_tag`
- article id 는 `art_i` attribute, URL 도 element attribute 로 노출 → 모델이 `evidence_article_urls` 에 URL 그대로 넣음
- JSON parse 실패 시 `temperature +0.1` (cap 1.0) 로 1회 재시도, 두 번째도 실패하면 `ValueError`
- pydantic `ProposalPoint` 검증: angle Literal 5종 (pain_point/growth_signal/tech_fit/risk_flag/intro), intro 외 evidence URL ≥1 필수

**초안 (`draft.py`):**
- `draft_proposal(points, articles, *, target_company, lang, client=None) -> ProposalDraft`
- 4섹션 Markdown (Overview / Key Points / Why Our Product / Next Steps)
- **Footnote 파이프라인**: 코드에서 인용 URL 을 첫 등장 순서로 `[^1]..[^N]` 사전 할당 → Sonnet 에 citation_map 전달 → 응답의 `[^N]` 관대 재번호 (map hit 우선, 미스는 unused_pool fallback, 풀 비면 drop) → Sonnet 이 실수로 쓴 `[^N]: URL` 정의 블록 strip → 시스템이 정확한 URL 로 footnote 정의 재생성
- `>1200 words` 초과 시 warn log 후 그대로 반환 (Phase 5 재시도 엣지에서 처리)

**스키마 (`proposal_schemas.py`):** `ProposalPoint` + `ProposalDraft` + `_extract_json` (raw → 코드펜스 → array regex → object regex 4단 fallback) + `parse_proposal_points` (`{"points": [...]}` 래핑도 수용)

### 6. LangGraph (`src/graph/` — Phase 5 완료)

**State (`state.py`):** `AgentState` TypedDict (`total=False`)
- inputs: `company, industry, lang, top_k`
- 아티팩트: `searched_articles` (search_node), `fetched_articles` (fetch_node), `processed_articles` (preprocess_node), `tech_chunks`, `proposal_points`, `proposal_md` — article 리스트가 스테이지별로 분리돼 실패 경로에서도 어느 단계 출력이 남아있는지 구분 가능
- 메타: `errors` (list[dict]), `usage` (Anthropic 4-token 누적), `stages_completed` (append-only), `failed_stage` (None | str), `status` (`"running" | "failed" | "completed"`), `current_stage` (None | str), `run_id`, `output_dir`, `started_at`, `ended_at`
- `new_state()` 시드 팩토리 + `merge_usage()` 순수 리듀서. `USAGE_KEYS` 단일 소스는 `src/llm/claude_client.py`

**Errors (`errors.py`):** `TransientError` / `FatalError` 엑셉션 + `StageError` dataclass (`{stage, error_type, message, ts}`) — `from_exception(stage, exc)` 로 직렬화 가능한 레코드 생성

**Nodes (`nodes.py`):** 7개 얇은 어댑터. 실제 로직은 Phase 1~4 함수(`bilingual_news_search`, `fetch_bodies_parallel`, `preprocess_articles`, `retrieve`, `synthesize_proposal_points`, `draft_proposal`) 그대로 재사용
- `@_stage(name)` 데코레이터 — 예외를 잡아 `failed_stage` + `errors` 에 기록, 성공/실패 양쪽에서 `current_stage = name` 세팅, 성공 시 `stages_completed` 에 append. TransientError 미분리 (Phase 5 는 RetryPolicy 생략)
- `search_node` — ko 기본은 bilingual blend, en 은 monolingual. `BraveSearch` 를 context manager 로 운용 (세션 끝나면 close)
- `fetch_node` / `preprocess_node` — 빈 articles 면 no-op passthrough
- `retrieve_node` — `top_k = state.top_k or settings.llm.claude_rag_top_k`
- `synthesize_node` / `draft_node` — 각 Sonnet 호출의 usage 를 `merge_usage(state.usage, call_usage)` 로 상태에 누적
- `persist_node` — 항상 실행 (실패 경로에서도). 부분 state 로 `intermediate/*.json` + `run_summary.json` 작성. `articles_after_preprocess.json` 에는 `processed > fetched > searched` 우선순위의 최신 스테이지 articles 를 기록 (헬퍼 `latest_articles()`), 실패 경로에선 `articles_searched.json` / `articles_fetched.json` 보조 덤프로 단계별 스냅샷도 보존. 최종적으로 `status` (`failed` / `completed`), `ended_at`, `current_stage` (완료면 None, 실패면 raising stage) 를 확정. `_to_jsonable` 재귀 직렬화(dataclass/pydantic/datetime/Path)
- `route_after_stage` 라우터 — `failed_stage` 있으면 `"persist"` (모든 하위 스테이지 스킵), 없으면 `"continue"`

**Pipeline (`pipeline.py::build_graph()`):** `StateGraph(AgentState)` 컴파일
```
START → search ─┬─[continue]→ fetch ─┬─[continue]→ preprocess ─┬─[continue]→ retrieve ─┬─[continue]→ synthesize ─┬─[continue]→ draft → persist → END
                │                     │                         │                       │                         │                          ↑
                └───────[persist]─────┴───────[persist]──────────┴─────[persist]─────────┴────[persist]────────────┴────[persist]─────────────┘
```
- 스테이지 1~5 는 모두 `add_conditional_edges(stage, route_after_stage, {"continue": next, "persist": persist})`. draft → persist 는 무조건
- `MemorySaver` 체크포인터 (Phase 7 에서 `SqliteSaver` 로 스왑, 재개 가능 실행 대응)
- **RetryPolicy 생략** (Phase 5 결정): synthesize/draft 내부가 이미 temperature +0.1 로 1회 재시도. 네트워크 전이 실패는 드물어서 현재 비용으로 감당. Phase 7 에서 SSE 장기 실행 시 재검토

**Orchestrator (`src/core/orchestrator.py::run()`):** CLI(Phase 6) / FastAPI(Phase 7) 공용 진입점
- `run(company, industry, lang, *, output_root=None, top_k=None, run_id=None) -> AgentState`
- `run_id` 자동 생성 (`{YYYYMMDD-HHMMSS}-{company}`), `output_dir = {root}/{company}_{YYYYMMDD}`
- `graph.invoke(state, config={"configurable": {"thread_id": run_id}})` — 체크포인터가 step 별 state 스냅샷

**산출물:** `outputs/{company}_{YYYYMMDD}/`
- `proposal.md` — 최종 draft (실패 시 생략)
- `intermediate/articles_after_preprocess.json` — 최신 스테이지 articles (보통 번역·태그·dedup 후, 실패 경로에선 이전 단계 스냅샷)
- `intermediate/articles_{searched,fetched}.json` — 실패 경로에서만. 단계별 차분 분석용
- `intermediate/tech_chunks.json` — retrieve top-k
- `intermediate/points.json` — 검증된 ProposalPoint 리스트
- `intermediate/run_summary.json` — `{run_id, company, industry, lang, status, duration_s, started_at, ended_at, usage, errors, failed_stage, current_stage, stages_completed, proposal_md_path, generated_at}`

### 7. Web API (`src/api/` — Phase 7)

FastAPI 프로세스가 Exaone + bge-m3 싱글턴을 warm-stay 시키고, CLI 와 **같은 `orchestrator`** 를 백그라운드에서 돌리면서 SSE 로 진행을 스트림하는 얇은 레이어.

**Lifespan (`app.py::lifespan`):**
- `anyio.to_thread.run_sync(local_exaone.load)` + `embeddings.get_embedder()` 로 첫 요청 지연을 제거 (~30s → 0). `API_SKIP_WARMUP=1` 로 테스트·개발시 skip
- `build_sqlite_checkpointer(API_CHECKPOINT_DB)` 가 `sqlite3.connect(..., check_same_thread=False)` 로 커넥션을 열고 `SqliteSaver` 로 감싸 `app.state.checkpointer` 에 보관 — BackgroundTasks(worker thread) 와 SSE(event loop) 가 같은 커넥션 공유, 프로세스 재시작 후에도 `run_id` 로 재개 가능
- CORS 허용 origin 은 `API_CORS_ORIGINS` (기본 `http://localhost:3000`)

**Orchestrator 이중 entry:**
- `run(...)` — 기존 `graph.invoke()` (CLI 용). 최종 `AgentState` 반환
- `run_streaming(...)` — `graph.stream(state, config, stream_mode="values")` 로 각 super-step state 를 yield. FastAPI `execute_run` 이 이걸 소비해 `RunRecord` 를 갱신 + 이벤트 append

**RunStore / IngestStore (인메모리, `src/api/store.py`):**
- `RunRecord` — 상태(`queued|running|completed|failed`) + `current_stage` + `stages_completed` + `article_counts{searched,fetched,processed}` + `usage` + `proposal_md` + append-only `events: list[RunEvent{seq,kind,ts,payload}]`. `threading.Lock` 으로 shared-state 가드
- SSE 엔드포인트는 `since_seq` 폴링(150ms) 방식 — 큐 / coroutine-threadsafe plumbing 없이, 증분만 yield 후 종결 상태 감지 시 stream close

**라우트 (`src/api/routes/`):**
```
GET  /healthz
POST /runs                     → 202 {run_id, status=queued, created_at}
GET  /runs                     → 최신순
GET  /runs/{run_id}            → 전체 summary + proposal_md
GET  /runs/{run_id}/events     → EventSourceResponse (SSE)
GET  /ingest/status            → manifest.json 집계
POST /ingest                   → 202 {task_id}
GET  /ingest/tasks/{task_id}   → 상태
```

**DO NOT 룰 실전:** `src/api/routes/runs.py` 는 `from src.api import runner as _runner` + `_runner.execute_run(...)` 로 모듈 경유 접근, 이렇게 해야 테스트에서 `monkeypatch.setattr("src.api.runner.execute_run", fake)` 가 먹어 실제 Exaone/Sonnet 호출을 회피할 수 있음. 초기에 `from src.api.runner import execute_run` 로 바인딩했다가 false-green (실제 LLM 가 호출됨) 을 맞고 수정. `ingest.py` 의 `get_settings` 도 동일 이유로 `from src.config import loader as _config_loader` 로 변경.

**산출물:**
- API 는 `RunRecord` 인메모리에만 보관 (프로세스 재시작 시 소멸). LangGraph 체크포인트만 `API_CHECKPOINT_DB` 에 영속화 — 실행 이력 전용 테이블은 장기 과제
- 프로토콜별 레이아웃은 백엔드가 `outputs/{company}_{YYYYMMDD}/` 로 그대로 쓰며, `/runs/{run_id}` 응답의 `output_dir` 필드로 노출

**Phase 10 확장 (진행 중) — `data/app.db` 분리:**
- `src/api/db.py` 가 langgraph `SqliteSaver` (체크포인트 전용) 와는 **다른** SQLite 파일에 8-탭 UI 상태를 영속화. 이유: SqliteSaver 는 자기 스키마 단독 소유를 가정하므로 app 테이블을 섞으면 업그레이드 시 충돌 위험
- 5 테이블: `discovery_runs` / `discovery_candidates` (FK CASCADE) / `targets` (FK SET NULL) / `interactions` (FK SET NULL) / `news_runs`
- `init_db()` 는 `CREATE TABLE IF NOT EXISTS` + `executescript` 로 idempotent — 매 boot 의 lifespan 에서 호출 가능
- `connect()` 컨텍스트 매니저: `row_factory=Row`, `PRAGMA foreign_keys=ON`, 정상 종료 시 commit / 예외 시 rollback / 항상 close
- env 노출: `API_APP_DB` (기본 `data/app.db`)

### 8. Web UI (`web/` — Phase 7, Next.js 15 App Router)

- `/` 폼 → `POST /runs` → `/runs/[id]` 리다이렉트
- `/runs/[id]` — `EventSource(/runs/{id}/events)` SSE. 이벤트마다 `GET /runs/{id}` 재조회로 권위 있는 상태 반영. `StageProgress` 컴포넌트가 7 stage 진행 뱃지, `react-markdown + remark-gfm` 이 `proposal_md` 렌더
- `/rag` — `GET /ingest/status` 조회 + `POST /ingest` 트리거 (notion/force/dry_run 토글). 업로드/삭제 UI 는 장기 과제

프론트는 `NEXT_PUBLIC_API_BASE_URL` 만 읽고 자체 state 는 없음 — 쉽게 교체/확장 가능.

**Phase 10 진행 중 — 8-탭 확장 (P10-0 머지됨):**
- `web/src/components/Nav.tsx` — `usePathname()` 기반 active state 의 8-탭 네비. `layout.tsx` 헤더에 마운트
- 8 탭: Home (`/`) / Daily News (`/news`) / Discovery (`/discover`) / Targets (`/targets`) / Proposals (`/proposals`) / RAG Docs (`/rag`) / 사업 기록 (`/interactions`) / Settings (`/settings`)
- P10-0 시점에 stub 페이지 6개 + 공유 `StubPage.tsx` (제목 + ship PR 라벨 + 책임 설명) 로 골격 완성. 실제 기능은 P10-1 ~ P10-8 에서 점진 채움
- 기존 `/` (Run 폼) + `/runs/[id]` + `/rag` 는 그대로 동작 — Phase 10 은 추가 확장이지 breaking change 아님 (P10-4 에서 Run 폼이 `/proposals/new` 로 이전 예정)

---

### 9. Target Discovery (`src/core/discover.py` — Phase 9 + 9.1, RAG-only sibling flow)

타겟사가 정해지지 않은 상태에서 "우리 제품이 누구에게 팔릴까" 를 RAG 만으로 역추론하는 별도 entry. 6단 파이프라인 (search/fetch/preprocess/...) 을 거치지 않고 retrieve 만 사용 → Sonnet 1회 → flat yaml + grouped md 페어 출력.

**Phase 9.1 핵심 변경**: LLM 의 역할을 "tier 판단" 에서 "6 차원 0-10 점수 매기기" 로 좁히고, `final_score` 와 `tier` 는 코드가 `config/weights.yaml` + `config/tier_rules.yaml` 로 deterministic 결정. mega-cap 편향 보완을 위해 `config/sector_leaders.yaml` 시드 + region flag.

```
[Input: lang, n_industries=5, n_per_industry=5, seed_summary?,
        product="databricks", region="any", include_sector_leaders=True]
        │
        ▼
  ┌──────────────────────────┐
  │  retrieve(seed_query, top_k=20)   │  ChromaDB + bge-m3 (재사용)
  │  manifest_path_for / load_manifest │  seed_doc_count / seed_chunk_count
  └──────────────────────────┘
        │
        ▼
  cached_context = <knowledge_base>     (Sonnet ephemeral cache)
  volatile_context =
    <product_summary>...                (선택, seed_summary)
    <region_constraint>{region}          (region != "any" 시)
    <sector_leader_seeds region="...">   (include_sector_leaders 시)
        │
        ▼
  ┌──────────────────────────┐
  │  chat_cached (Sonnet 4.6)         │  output: scores{6 dim 0-10}+rationale
  │   + retry 1회 (temp +0.1)         │  parse_discovery 가 LLM 의 tier 응답 silently drop
  └──────────────────────────┘
        │
        ▼
  ┌──────────────────────────┐
  │  scoring (코드, $0)               │  weights = load_weights(product) + auto-normalize
  │  for c in candidates:             │  rules = load_tier_rules() (S/A/B/C threshold)
  │    c.final_score = weighted sum   │  c.tier = decide_tier(...) (epsilon 1e-6)
  │    c.tier = first-match           │
  └──────────────────────────┘
        │  DiscoveryResult (scores + final_score + tier 모두 채워짐)
        ▼
  outputs/discovery_{YYYYMMDD}/
    ├ candidates.yaml   (flat: name/industry/scores{6}/final_score/tier/rationale)
    └ report.md         (S/A/B 산업별 + ⚠️ Strategic Edge [C] 별도 섹션)
```

**스키마 (`discover_types.py`):**
- `Candidate` (pydantic) — `name`/`industry`/`scores: dict[str,int]`(6 dim 0-10)/`rationale`/`final_score: float`/`tier: Tier`. LLM 은 앞 4개만 출력, 뒤 2개는 코드가 채움
- `parse_discovery` 가 LLM 의 `tier` / `final_score` 출력을 silently drop (코드 결정권 보장)
- `_extract_json_object` (raw → fenced → object 만) — dict 호출자 우선

**스코링 (`scoring.py` — Phase 9.1 신설):**
- `WEIGHT_DIMENSIONS` 6개 (pain_severity / data_complexity / governance_need / ai_maturity / buying_trigger / displacement_ease)
- `load_weights(product=None)` — yaml 로드 → default + product override merge → 누락 검증 → 합 != 1.0 시 auto-normalize + warn
- `load_tier_rules()` — descending sort + 4 tier (S/A/B/C) 강제
- `calc_final_score(scores, weights)` — weighted sum
- `decide_tier(final_score, rules)` — first-match descending. epsilon 1e-6 으로 normalize float drift 흡수 (e.g. 7×normalized ≈ 6.9999... 도 A 로 처리)
- 코드 결정의 가치: **같은 LLM 응답을 다른 weight 로 재계산 = $0 추가 비용**. 다른 제품 (Snowflake/Salesforce 등) 도 weights.yaml 의 `products.<name>` override 로 재사용 가능

**Sector leaders 시드 (`config/sector_leaders.yaml` — Phase 9.1 신설):**
- flat list: `name` / `industry_hint` / `region` (ko/us/eu/global) / `notes?`
- `_render_volatile` 의 `<sector_leader_seeds region="...">` 블록으로 LLM 에 inspiration 주입 → mega-cap 편향 완화 (Stripe/Adyen/토스/KB금융/네이버/카카오 등 mid-market·local 진입)
- `region` flag (any/ko/us/eu/global) — "any" 면 모든 시드, 명시 region 은 해당 + global 만
- gitignored 운영 yaml (`competitors.yaml` / `intent_tiers.yaml` 패턴 동일). `scripts/draft_sector_leaders.py` 로 Sonnet 1회 초안 생성

**핵심 함수 (`discover.py`):**
- `discover_targets(*, lang, n_industries=5, n_per_industry=5, seed_summary=None, seed_query=..., product="databricks", region="any", include_sector_leaders=True, output_root=None, top_k=20, client=None, write_artifacts=True) -> DiscoveryResult`
- max_tokens 는 `claude_max_tokens_discover=6000` (Phase 9.1 에서 4000 → 6000 상향. scores 6 dim + sector_leaders 가 출력 토큰 ↑)
- prompt 에 "rationale 1문장 ~25어 강제" — scores 가 차원별 판단 담으니 rationale 은 헤드라인만

**얇은 어댑터:**
- `main.py discover` — `--lang/--n-industries/--n-per-industry/--seed-summary/--seed-query/--product/--region/--sector-leaders|--no-sector-leaders/--top-k/--output-root/--verbose`
- `scripts/discover_targets.py` 동일 (argparse)

**산출물 페어:**
- `candidates.yaml` — `{generated_at, seed{...}, industry_meta, candidates: [{name, industry, scores{6}, final_score, tier, rationale}], usage}`. 향후 backlog 항목 17 (편집 웹 UI) 의 입력 포맷
- `report.md` — 시드 메타 헤더 + 산업별 (S/A/B 만) + ⚠️ Strategic Edge (C tier) 별도 섹션 + Tokens 요약

**비용:** Sonnet 1회, ~$0.045-0.08 / ~40-50s. 같은 RAG 재실행 시 cache_read 적중으로 절반 이하. 같은 LLM 응답 재계산 (다른 weight) 은 $0.

**MVP 한계 (의도적):** factual 검증 없음 — 회사명 hallucination 가능성 인정. 사람 검수가 후속 단계로 가정. Phase 9.1 첫 산출에서 C tier 가 0 인 한계 — sector_leaders.yaml 시드에 hyperscaler/lock-in 케이스 부재가 원인, 후속에서 의도적 추가 검토. 풀 reverse matching (Brave 검증 + 산업별 활성 이슈) 은 backlog 항목 8.

---

## 설정 흐름
- `.env` 로드 → `pydantic-settings` 로 타입 검증된 `Settings` 객체 생성
- `Settings` 는 전 모듈에서 공유 (의존성 주입)
- 환경변수가 이미 설정되어 있으면 `.env` 값보다 우선

## 데이터 영속성
- 벡터스토어: `data/vectorstore/<namespace>/` (ChromaDB persistent, P10-2a 부터 namespace-scoped — `default` 가 기본). Phase 11 부터 외부 워크스페이스는 `data/vectorstore/<ws_slug>/<namespace>/` 로 한 단계 더 prefix
- 원본 문서: default ws 는 `data/company_docs/<namespace>/`, 외부 ws 는 사용자 등록 abs_path 그 자체 (`D:\my-docs\` 등). Notion 은 별도 (페이지 ID)
- 매니페스트: `data/vectorstore/<ws>/<namespace>/manifest.json` (default ws 는 `<ws>` 부분 생략 — 레거시 호환)
- 마이그레이션: 첫 부팅 / `indexer.main()` 시 평면 layout (`data/vectorstore/{chroma.sqlite3, manifest.json}` + `data/company_docs/*.pdf`) 가 감지되면 `migrate_flat_layout` 이 자동으로 `<root>/default/` 로 이동 (idempotent)
- 결과물: `outputs/{company}_{YYYYMMDD}.md`
- 중간 산출물: `outputs/{company}_{date}/intermediate/` (원시 기사, 요약 JSON, 검색 결과)
- 로그: `logs/` (일자별 파일)

---

## Phase 11 — Multi-workspace RAG (2026-05-02)

`data/company_docs/` 단일 루트 가정을 깨고 사용자가 임의 abs path (`D:\my-docs\` 등) 를 RAG 트리에 추가할 수 있도록 확장.

### 워크스페이스 레지스트리 (`src/api/db.py::workspaces` 테이블 + `src/api/store.py::WorkspaceStore`)
- 컬럼: `id PK / slug UNIQUE / label / abs_path UNIQUE / is_builtin / created_at / updated_at`
- `init_db` 의 `_seed_default_workspace` 가 `slug='default', label='Project Docs', abs_path=PROJECT_ROOT/data/company_docs, is_builtin=1` 을 idempotent 시드
- `WorkspaceStore.create` — slug 자동 생성 (`_slugify(label)` + `-2/-3` 충돌 회피), `_validate_abs_path` (절대·exists·is_dir·`PROJECT_ROOT/data` 내부 거부), abs_path UNIQUE 충돌 → `ValueError`
- `WorkspaceStore.delete(id, *, wipe_index=False)` — DB row 만 삭제가 기본, `wipe_index=True` 시 `data/vectorstore/<slug>/` rmtree + `rag_summaries` 의 ws_slug 행 삭제. 사용자 source 폴더 (등록 abs_path) 는 절대 안 건드림. `is_builtin=1` 행은 ValueError 로 거부

### Path resolution layer (`src/rag/workspaces.py`)
- `workspace_paths(ws_slug) -> (vs_root, cd_root)` — slug 별 vectorstore + source 디렉토리 매핑
- **Asymmetric default-ws** (의도적 transitional 처리, `playbook.md` #18 참고):
  - `default` → `(settings.rag.vectorstore_path, data/company_docs)` 그대로 — 기존 namespaces 가 `data/vectorstore/<ns>/` 에 살아 있는 layout 보존
  - 외부 ws → `(settings.rag.vectorstore_path/<slug>, row.abs_path)` — per-slug prefix
- DO NOT 룰: `from src.config import loader as _config_loader` 모듈경유로 `get_settings` 호출 (테스트 monkeypatch flow 보존)

### Retriever / Indexer / Discover 통합
- `src/rag/retriever.py::_STORES` cache 키가 `tuple[str, str]` `(ws_slug, namespace)` 로 확장. `retrieve(query, *, ws_slug='default', namespace='default', top_k=None)`
- `src/rag/indexer.py` — `--workspace <slug>` (default `'default'`) + `--all-workspaces` 플래그. body 가 `_run_one_workspace(slug)` 로 ws-iterate. `migrate_flat_layout` 은 default 에서만 호출
- `src/core/discover.py::discover_targets(*, ws_slug='default', namespace=DEFAULT_NAMESPACE, ...)` — `_read_seed_meta` / `_retriever.retrieve` 모두 ws_slug 통과
- `main.py ingest` typer 가 `--workspace` / `--all-workspaces` 포워딩

### API 라우트 (`src/api/routes/workspaces.py` + `/rag/*` 전체 ws-prefix)
- 신규 5 endpoint: `GET/POST /workspaces`, `GET /workspaces/{id}`, `PATCH /workspaces/{id}`, `DELETE /workspaces/{id}?wipe_index=true|false`
- 기존 17개 RAG endpoint 가 모두 `/rag/workspaces/{ws_slug}/...` 로 prefix 변경. 핸들러가 `ws_slug` path param 받아 `_vectorstore_root(ws_slug)` / `_company_docs_root(ws_slug)` / `_get_cached_summary(ws_slug, ns, path)` / `_upsert_summary(ws_slug, ...)` / `_delete_namespace_summaries(ws_slug, ns)` / `_retriever._store(ws_slug, ns)` 로 forwarding. 기존 path 는 삭제 (single-user dev tool, compat layer 가치 없음)
- `rag_summaries` 테이블에 `ws_slug TEXT NOT NULL DEFAULT 'default'` 컬럼 ALTER ADD. PK 는 SQLite ALTER 한계로 기존 `(namespace, path)` 유지 — 코드의 INSERT/UPDATE/DELETE SQL 이 PK shape 에 의존하지 않도록 `DELETE → INSERT` 패턴 사용

### Frontend (`web/src/app/rag/page.tsx` + 신규 컴포넌트)
- URL `?path=` 가 `<ws_slug>/<ns>/<sub>` 3-segment. `splitFullPath(fullPath) -> { ws, ns, sub }`
- 3 view level 분해:
  - **wsLevel** (`ws=""`) — 워크스페이스 리스트 표시. toolbar 가 `[+ Add Workspace]` (primary) + `[− Remove (N)]` (danger) + 새로고침 만 노출 (다른 file-ops 버튼 숨김)
  - **nsLevel** (`ws!="" && ns=""`) — namespace + root file 리스트. toolbar 는 namespace 생성·업로드·delete·explorer
  - **inside** (`ws!="" && ns!=""`) — 일반 폴더/파일 뷰
- `Breadcrumb` 첫 segment 는 slug → workspace.label 매핑 (사용자에게 친화적)
- `FolderTree` 루트 노드 `Workspaces`, 자식이 등록된 ws 들 (📦 + label), 손자가 namespace, 손손자부터 `listRagTree(ws, ns, sub)`
- `AddWorkspaceModal` — label + abs_path 입력 + server 422 inline 표시 + 성공 시 즉시 새 ws 로 navigate
- `RemoveWorkspaceModal` — 제거 대상 라벨 + abs_path 리스트 + "등록된 폴더는 절대 삭제되지 않습니다" 안내 + "인덱스도 함께 삭제" 체크박스 (기본 unchecked) → `deleteWorkspace(id, { wipe_index: true })` 옵션
- `RagDocumentDropzone` `wsSlug` prop 받음, `uploadAtRoot=nsLevel`

### 미해결 격차 (backlog 항목 22 로 분리)
- Re-index UI 가 default ws 고정 (`triggerIngest` 가 `--workspace` 미전달)
- Discovery/News 탭 namespace 드롭다운이 default ws 만 표시
- Dashboard `rag` aggregate 가 default ws 만 집계
- 외부 ws 시나리오 백엔드 테스트 5건 추가 필요

---

## Phase 11+ — Cost Explorer (`/cost` 탭) (2026-05-04)

토큰 누적치를 USD 환산·일자 추세·캐시 절감·예산·단가 메트릭으로 노출하는 별도 viewer 탭. 활성 모델 (Sonnet/Haiku) 도 같은 페이지에서 한 번 클릭으로 스왑.

### Pricing / Budget config (`config/pricing.yaml`, `config/cost_budget.yaml`)
- `Pricing.llm: dict[str, ModelRates]` — 모델 ID → 4 단가 (input/output/cache_read/cache_write per Mtok). `Pricing.search: dict[str, SearchRates]` — Brave 등 외부 검색 단가
- `CostBudget.monthly_usd / warn_pct` — 월 예산 USD + warn 임계 (0~1)
- 두 종 모두 Settings PUT 경로 (`PUT /settings/{kind}`) 에 등록 — `pricing` / `cost_budget` 키. 2-pass YAML+Pydantic 검증·atomic write·lru_cache 무효화 그대로 재사용. **Settings UI 에는 노출 안 함** (Cost 페이지의 `PricingBudgetEditor` 폼이 단일 진입점)

### Calculator (`src/cost/calculator.py`)
LLM·IO 의존 0인 순수 함수 집합:
- `usd_for_run(usage, model, pricing)` — 4 토큰 × 4 단가 → input/output/cache_read/cache_write/total/cache_savings USD. 모델 미등록 시 prefix-match → 실패 시 zero-rate. **`cache_savings_usd = cache_read_tokens × (input_rate − cache_read_rate) / 1M`** (Anthropic prompt caching 의 90% 할인을 "현금 가치" 로 변환)
- `kpi_block` — this_month / last_month / cumulative + 캐시 절감 + 절감 % (counterfactual 대비)
- `aggregate_daily(records, *, days, today)` — 트레일링 days 일 zero-fill 시리즈 (gap 없는 라인차트용)
- `aggregate_by(records, *, dim)` — `dim="model"` 또는 `"run_type"` 그룹화
- `per_unit(records)` — proposal=`completed`만 평균 / discovery=`candidate_count` 합 (없으면 25 fallback) 으로 후보당 USD
- `budget_state(records, budget, today)` — 이번 달 used USD + breach (≥warn_pct) + over_budget (≥1.0)
- `recent_runs_with_usd(records, *, limit=20)` — 최근순 + 토큰 4종 raw + USD

### Aggregator route (`src/api/routes/cost.py`)
- `_gather_records()` — 3 source normalize:
  - **Proposal**: `RunStore.list()` (in-memory). `RunRecord.claude_model` 우선, 없으면 settings fallback
  - **Discovery**: `DiscoveryStore.list_runs()` (SQLite `discovery_runs.usage_json` + `claude_model` 컬럼)
  - **RAG summary**: `rag_summaries` 테이블 직접 SELECT (`ws_slug`, `namespace`, `path`, `model`, `usage_json`, `generated_at`). run_type=`rag_summary`, run_id=`rag:<ws>:<ns>:<path>`
- `GET /cost/summary?days=30` — 위 7 함수 호출 후 `CostSummaryResponse` 조립
- `GET /cost/active-model` — `{ active, available[] }`. available 은 pricing.yaml `llm` dict 의 모델 ID + 4 단가
- **`POST /cost/active-model {"model": "..."}`** — pricing.yaml 등록 모델 enum 검증 → `r"^(\s*claude_model:\s*).*$"` 정규식으로 settings.yaml 의 `claude_model:` 라인 한 줄만 교체 (코멘트·indent·다른 키 보존) → post-swap Settings pydantic 재검증 → atomic write + `get_settings.cache_clear()`. 매칭 실패 fallback 만 yaml round-trip (코멘트 손실 인지)

### 모델 추적 — RunRecord/DiscoveryStore.claude_model
모델 스왑 후에도 과거 run 의 비용 정확도를 유지하기 위해 **run-start 시점 활성 모델을 스냅샷**:
- `RunRecord.claude_model: str | None` 필드 + `RunStore.create(claude_model=...)` 매개변수. `POST /runs` 핸들러가 `settings.claude_model` 을 즉시 읽어 record 에 박음
- `discovery_runs.claude_model TEXT` 컬럼 + `_DISCOVERY_RUNS_NEW_COLUMNS` 마이그레이션. `POST /discovery/runs` 도 동일 스냅샷
- Cost calculator 는 record 의 `claude_model` 우선 사용 → 활성 모델 변경 시 새 run 부터 새 단가, 과거 run 은 그 시점 단가로 그대로 환산

### Frontend (`web/src/app/cost/page.tsx` + `web/src/components/cost/*`)
8 컴포넌트:
- `KpiCards` — 4 카드 (이번달/지난달/누적/캐시 절감)
- `CostTrendChart` — 30/60/90일 토글 + recharts LineChart
- `CostBreakdownBars` — 모델별 ↔ 런타입별 토글 + horizontal stacked bars
- `PerUnitCard` — $/proposal, $/discovery target
- `BudgetBar` — month-to-date 진행바, warn 도달 amber / over rose
- `RecentRunsTable` — 페이지네이션 (10/page) + 4-색 토큰 비율 mini-bar. **proposal=blue / discovery=violet / rag_summary=amber**
- `PricingBudgetEditor` — 폼+YAML escape 패턴의 첫 구현. 모델별 4 input + 월 예산 + warn% / "YAML 편집" 토글로 raw textarea fallback / 저장은 `putSettings("pricing"/"cost_budget", yaml)`
- `ActiveModelSelector` — 헤더 우측 드롭다운. pricing.yaml 모델 목록 + 4 단가 같이 surface, 활성 표시 + 외부 클릭 닫힘. 변경 시 즉시 PUT → 토스트 → `getCostSummary` 자동 새로고침

`recharts ^2.13.3` 신규 의존성. `web/package.json`. Home 의 `CostBox` 도 새 USD-centric `DashboardCostSummary` 스키마로 슬림화 + `/cost` 링크 + 예산 임계 amber/rose 배지.

### Dashboard 박스 슬림화
`src/api/routes/dashboard.py::_cost_summary()` 가 토큰 4종 raw 8 필드 → `cost.calculator.kpi_block + budget_state` 의 USD 9 필드 (this_month_usd / last_month_usd / cumulative_usd / cache_savings_usd / cache_savings_pct / monthly_budget_usd / used_pct / breached / over_budget) 로 교체. 실패 시 zero-state 로 폴백.

### 데이터 흐름 요약
```
Anthropic SDK response.usage (4종)
  → claude_client.chat_cached/chat_once 가 dict 화
  → 호출자 (synthesize/draft/discover/rag_summary) 가 누적
  → RunStore / discovery_runs / rag_summaries 에 저장 (각 record 에 claude_model 동봉)
  → /cost/summary 가 3 source 모두 SELECT + pricing.yaml 곱셈 → USD
  → 프론트 KpiCards/Trend/Breakdown/PerUnit/Budget/RecentRuns 에 surface
```
