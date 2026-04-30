# Status

프로젝트 진행 상황과 장단기 계획의 단일 원천.

---

## 완료

- **Phase 0** — 프로젝트 스캐폴딩
- **Phase 1** — Brave Search API 연동 + 설정 3단 구조
  - `.env` (secrets) / `config/settings.yaml` (defaults, 커밋) / `config/targets.yaml` (user data, gitignored)
  - `src/config/{schemas,loader}.py` — Pydantic + YAML 로더
  - `src/search/{base,brave,bilingual}.py` — Brave 클라이언트 + 한↔영 번역 룩업 기반 bilingual 혼합 검색 (foreign ≥ 50% 보장)
  - `tests/{test_brave,test_bilingual}.py` — 14건 통과
- **Phase 1.5** — 본문 추출기 (trafilatura + ThreadPool)
  - `src/search/fetcher.py` — `fetch_bodies_parallel` (max_workers=5, per-url timeout 10s, 실패 시 snippet fallback)
  - `src/search/base.py` `Article` 에 `body` + `body_source` 필드 추가
  - `src/search/brave.py` CLI 에 `--fetch-bodies` 플래그 (opt-in)
  - `tests/test_fetcher.py` — 7건 통과
  - 실측: "AI 산업" bilingual 20건 기준 **full 추출 19/20 (95%), 평균 본문 3894자**. Reuters만 paywall/bot-block 로 snippet fallback — Phase 2 Exaone 투입에 충분한 context 확보

- **Phase 2** — 로컬 전처리 파이프라인 (번역 + 태깅 + 중복제거)
  - `src/llm/local_exaone.py` — HF Transformers + bitsandbytes 4bit 싱글턴 로더 (settings.llm.local_model 에서 모델 id 수신)
  - `src/llm/translate.py` + `src/prompts/{en,ko}/translate.txt` — body lang != target_lang 일 때만 번역, 같으면 passthrough
  - `src/llm/tag.py` + `src/prompts/{en,ko}/tag.txt` — 9-태그 ENUM 분류, JSON 파싱 실패 시 `["other"]` fallback
  - `src/rag/embeddings.py` — bge-m3 싱글턴 + union-find 기반 중복 제거 (threshold 0.90, min_articles_after_dedup=10 하한, 대표 기사는 긴 body/최신 date 우선)
  - `src/llm/preprocess.py` — translate → tag → dedup 오케스트레이션 + CLI (`--input <brave.json> --lang en|ko --save`)
  - `src/search/base.py` `Article` 에 `translated_body` / `tags` / `dedup_group_id` 필드 추가
  - `config/settings.yaml` + `SearchSettings` 에 `max_articles`, `dedup_similarity_threshold`, `min_articles_after_dedup` 노출
  - `tests/{test_tag,test_dedup}.py` — 16건 통과 (총 37건 all green)
  - 스모크 (4bit Exaone, RTX 4070 16GB):
    - **Bilingual 검증** ("AI 산업" ko+en 20건, target=en): 번역 20/20 (영문 10 passthrough + 한글 10 실제 번역), 태깅 20/20, dedup 20→20. 결과 `outputs/preprocess/20260420-163433_en.json`
    - **Ko-only 검증** ("한국 공공기관 AI 전환" 20건, `--no-bilingual`, target=ko): 번역 passthrough, 태깅 20/20, dedup **20→19** (과기정통부 기사 복수매체 재가공 1쌍 병합). 결과 `outputs/preprocess/20260420-171851_ko.json`
  - 품질 관찰: Exaone 7.8B 이 R&D 공모사업에 `m_and_a` 태그 과다 부여 경향 — 실제 딜 판별은 Phase 4 Sonnet 단계에 위임. 태그는 "후보 좁히기" 용도로 충분.
  - 번역 마이너 이슈: Exaone 출력 첫/끝 줄에 프롬프트 템플릿 `<article>` 태그 에코되는 케이스 — `_strip_prompt_echo` 후처리로 해결 (아래 Phase 2.5 참고).

- **Phase 2.5** — 작은 개선 2건 정리
  - `src/llm/translate.py` `_strip_prompt_echo` 추가 — 번역 출력에서 `<article>` / `</article>` 태그 누출 제거 (대소문자·공백 관대)
  - `config/schemas.py` — `CollectionOverride` 에 `bilingual: bool | None`, `foreign_ratio: float | None` 추가. `Industry` 에 `collection: CollectionOverride` 내장 (per-industry 오버라이드). 공공부문 KR 같이 해외 소스 0% 가 자연스러운 도메인용
  - `src/search/brave.py` CLI 에 `--foreign-ratio` 플래그 — 전역 `settings.search.min_foreign_ratio` 오버라이드
  - `config/targets.example.yaml` — `public_sector_kr` per-industry override 샘플 추가
  - `tests/{test_translate,test_config}.py` — 11건 추가, 총 **48건 전부 통과**

- **Phase 3** — RAG 인덱싱 (LocalFile + Notion, ChromaDB + bge-m3, 증분 manifest)
  - **Stream 0 ✅** — `RAGSettings` 에 `vectorstore_path`, `collection_name`, `min_document_chars` 추가 + `config/settings.yaml` 반영
  - **Stream 1 ✅** — `src/rag/{types,normalize,chunker}.py` + `tests/{test_normalize,test_chunker}.py` (21건 신규, 총 **69건 all green**)
    - `types.py` — `Document`, `Chunk`, `RetrievedChunk` dataclass. 공통 필드(title/source_type/source_ref/last_modified/mime_type) 명시 승격, 나머지만 `extra_metadata`
    - `normalize.py` — 줄별 rstrip → 연속 개행 ≥3을 2로 cap → 전체 strip. 내부 공백/indent 보존 (코드·표 안전). 해시 안정화 공용 유틸
    - `chunker.py` — 문장 단위 greedy 패킹 + 문장 단위 overlap (tail). 단일 문장이 `chunk_size` 초과 시 문자 단위 hard-split + 문자 overlap fallback
  - **Stream 2 ✅** — `src/rag/{store,retriever}.py` + `tests/{test_store,test_retriever}.py` (20건 신규, 총 **89건 all green**)
    - `store.py` — ChromaDB PersistentClient 래퍼. metadata 평탄화(doc_id/chunk_index/title/source_type/source_ref/last_modified_iso/mime_type + extra_json) + `similarity_score = 1 - distance/2` 변환으로 점수 방향 통일(클수록 유사)
    - `retriever.py` — `retrieve(query, top_k=None)` + 모듈 싱글턴 `_store()`. 빈 query 가드. top_k 기본은 `settings.rag.top_k`
    - 엣지 회귀 잠금: 중첩 extra_metadata JSON 왕복, `last_modified=None` 왕복, 동일 id upsert 덮어쓰기, 길이 mismatch 는 ValueError, top_k > count 시 전체 반환
  - **Stream 3 ✅** — `src/rag/connectors/{__init__,base,local_file,notion}.py` + `tests/{test_local_connector,test_notion_connector}.py` (19건 신규, 총 **108건 all green**)
    - `base.py` — `SourceConnector` ABC (`source_type` ClassVar + `iter_documents()` 추상). 에러 정책: per-item warn+continue, aggregate raise
    - `local_file.py` — 재귀 `rglob` + 확장자 whitelist(`.md/.txt/.pdf`). PDF 는 pypdf 페이지별 추출 → `[Page N]` 구분자 삽입, 전 페이지 empty 면 scan PDF 로 판단하여 skip (부분 empty 는 keep). 빈 파일 / stat 실패 / missing root 전부 warn+skip
    - `notion.py` — `token/client` 둘 중 하나 필수. pages + databases + 하위 `child_page` 분리. title 규칙: page 는 title property → first non-empty line → `Untitled`, DB row 는 title property 만 (heading fallback 금지). `blocks.children.list` 페이징 + `has_children` DFS 재귀. 단일 page/DB 실패 격리
    - 테스트 전략: PDF 는 `pypdf.PdfReader` monkeypatch 로 안정화(실 PDF 생성 회피), Notion 은 `client` 주입으로 MagicMock 치환 (실 HTTP 차단)
  - **Stream 4 ✅** — `src/rag/indexer.py` + manifest.json + CLI + 로컬 스모크 + docs 갱신 (19건 신규, 총 **127건 all green**)
    - `indexer.py` — `run_indexer(connectors, store, manifest_path, ...)` 오케스트레이터 + `IndexReport` + `load_manifest` / `save_manifest` (tmp → `os.replace` 원자적 swap) + `verify(store, manifest)` + `main()` CLI
    - 원자성: chunk → embed 가 먼저 성공해야 `delete_document` → `upsert_chunks` → `manifest[doc_id] 갱신` 진행. embed 중 실패 시 store/manifest 모두 불변 + error 카운트
    - 증분: `sha256(normalize_content(doc.content))` 전체 hex 저장. 일치 → `skipped`, 다름 → `updated`, 신규 → `added`
    - 삭제 감지: `active_source_types = {c.source_type for c in connectors}` 로 스코프 제한. `--notion` 단독 실행은 로컬 매니페스트 엔트리 건드리지 않음 (반대 동일)
    - CLI 플래그: `--local-dir PATH` (기본 `data/company_docs`, 없으면 warn+skip) / `--no-local` / `--notion` / `--force` / `--dry-run` / `--verify`. Windows stdout utf-8 재설정 포함
    - manifest.json 스키마 v1: `{version, updated_at, documents: {doc_id: {content_hash, last_modified, indexed_at, chunk_count, source_type}}}`
    - `test_indexer.py` 19건: manifest I/O (버전 불일치·깨진 JSON → fresh 리셋, atomic roundtrip), 초회 add / 재실행 skip / 수정 update / 삭제 detect / 커넥터 격리 / embed 실패 불변 / `--force` / `--dry-run` no-mutation / empty skip / short_document warn / verify drift
    - 테스트 embed 는 sha256 → unit vector 페이크로 bge-m3 로딩 회피 (CI·재현성)
    - 로컬 스모크 (샘플 MD 4개): 초회 `added=4 chunks_total=12 elapsed=20.78s` (bge-m3 최초 로딩 포함) → 재실행 `skipped=4 elapsed=0.00s` → 1개 수정 `updated=1 skipped=3 chunks_total=3 elapsed=15.58s` → 1개 삭제 `deleted=1 skipped=3 elapsed=0.04s` → `--dry-run` / `--verify` no-op 확인
    - retrieve 스모크 (3개 쿼리): "Korean-native tokenization for enterprise" → `product_overview.md::2` @ 0.790, "on-premise air-gapped compliance" → `pricing.md::1` @ 0.763, "pricing for 50 seats" → `pricing.md::1` @ 0.807. similarity_score 내림차순 유지
  - 플랜 파일(세션 휘발성): `~/.claude/plans/phase-3-swirling-codd.md` 체크박스 추적

- **Phase 4** — Claude Sonnet 4.6 합성 에이전트 (synthesize + draft + 실제 스모크)
  - **Stream 0 ✅** — 설정·클라이언트·스키마 먼저 잠금
    - `LLMSettings` 에 `claude_max_tokens_synthesize=2000` / `claude_max_tokens_draft=4000` / `claude_temperature=0.3` / `claude_rag_top_k=8` 추가 + `config/settings.yaml` 반영
    - `src/llm/claude_client.py` — `get_claude()` 싱글턴 + `chat_cached()` (tech_docs 블록에만 `cache_control: ephemeral`, usage 에 cache_read/creation 토큰 포함) + 이후 Stream 2 에서 `chat_once()` 비캐시 헬퍼 추가
    - `src/llm/proposal_schemas.py` — `ProposalPoint` (angle Literal 5종, intro 외 evidence 필수) + `ProposalDraft` + `_extract_json` 4단 fallback (raw → 코드펜스 → array regex → object regex) + `parse_proposal_points` (`{"points": [...]}` 래핑 수용)
    - `src/llm/tag_tier.py` — `HIGH_VALUE_TAGS` frozenset 7종 + `select_body_or_snippet()` + `has_high_value_tag()` (low-value=leadership/other → snippet 만)
    - `tests/{test_proposal_schemas,test_tag_tier}.py` — 28건 신규, 총 **155건 all green**
  - **Stream 1 ✅** — `synthesize_proposal_points`
    - `src/llm/synthesize.py` — 프롬프트 조립: `<tech_docs>` 캐시 블록 + `<articles>` (tag-tier 로 high=translated_body / low=snippet) + `<target>` + task. article id 는 `art_i`, URL 은 element attribute 로 노출. JSON parse 실패 시 temperature +0.1 로 1회 재시도, 두 번 실패면 `ValueError`
    - `src/prompts/{en,ko}/synthesize.txt` — `---TASK---` 구분자로 system/task 분리 (단일 파일)
    - `tests/test_synthesize.py` — FakeClient 10건 (정상/펜스/프로즈/retry/2회실패/tier high·low/cache_control/chunk id/ko 로드), 총 **165건 all green**
  - **Stream 2 ✅** — `draft_proposal` + footnote 파이프라인
    - `src/llm/draft.py` — 인용된 URL 을 첫 등장 순서로 `[^1]..[^N]` 사전 할당 → Sonnet 에 citation_map 전달 → 응답에서 `[^N]` 관대 재번호 (map hit 아니면 unused_pool fallback, 풀 비면 drop) → Sonnet 수제 footnote 정의 블록 strip → 시스템이 정확한 URL 로 `[^N]: URL` 블록 재생성. `>1200 words` 는 warn log 후 그대로 반환
    - `src/llm/claude_client.py::chat_once` — 비캐시 단일 호출 헬퍼 추가 (draft 는 타겟별로 고유하므로 캐싱 불필요)
    - `src/prompts/{en,ko}/draft.txt` — Overview / Key Points / Why Our Product / Next Steps 4섹션 계약, Sonnet 의 자체 footnote 블록 작성 금지 명시
    - `tests/test_draft.py` — 14건 (순수 헬퍼 6 + E2E 8: 4섹션 / off-by-one 재번호 / 수제 footnote strip / citation_map 프롬프트 주입 / 길이 warn / 한글 ratio / 빈 입력 가드), 총 **179건 all green**
  - **Stream 3 ✅** — end-to-end 스모크 + 산출물
    - `scripts/smoke_phase4.py` — preprocess JSON 재로드 → retriever top-k → synthesize → draft → `outputs/{company}_{YYYYMMDD}.md` + `outputs/intermediate/{company}_{YYYYMMDD}_points.json`. retrieval / synth / draft 각 레이턴시 출력
    - 실측 (NVIDIA / semiconductor / en, `outputs/preprocess/20260420-163433_en.json` 20건 + tech chunks top-8): retrieve 14.5s (bge-m3 초회 로드 포함) / synthesize 27.2s → 5 points (intro/pain_point/growth_signal/risk_flag/tech_fit 각 1) / draft 16.5s → 592 단어 / 총 58.2s
    - 산출물: `outputs/NVIDIA_20260421.md` — 4섹션 구조 무결 + 6개 고유 footnote 자동 번호링 + 인용 URL ↔ `[^N]` 맵핑 정확 + 기사 본문·제품 docs 모두 반영됨
    - 플랜 파일(세션 휘발성): `~/.claude/plans/phase-4-sonnet-agent.md` 체크박스 전부 완료
    - 추후 보강 후보: Sonnet 호출의 `usage.cache_read/creation` 숫자를 smoke CLI 에 surface (현재는 함수 시그니처상 리턴 X — Phase 5 오케스트레이터에서 state 로 모아 리포팅)

- **Phase 5** — LangGraph StateGraph 오케스트레이션 (6 스테이지 + persist, fail-fast 라우팅, usage 집계)
  - **Stream 0 ✅** — `src/graph/{__init__,state,errors}.py` + `tests/test_graph_state.py`
    - `AgentState` TypedDict (`total=False`) — inputs(company/industry/lang/top_k) + 아티팩트(articles/tech_chunks/proposal_points/proposal_md) + 메타(errors/usage/stages_completed/failed_stage/run_id/output_dir/started_at)
    - `TransientError` / `FatalError` 엑셉션 taxonomy (Phase 7 에서 RetryPolicy `retry_on` 으로 쓸 자리)
    - `StageError` dataclass — `{stage, error_type, message, ts}` 로 직렬화. 테스트 10건 신규
  - **Stream 1 ✅** — `src/graph/nodes.py` 7개 어댑터 + `src/llm/{synthesize,draft}.py` 시그니처 확장
    - `@_stage(name)` 데코레이터 — 노드 예외를 잡아 `failed_stage` + `errors` state 에 기록, 성공 시 `stages_completed` 추가
    - 7 노드: `search / fetch / preprocess / retrieve / synthesize / draft / persist` — 각각 기존 Phase 1~4 함수에 대한 얇은 state ↔ args 어댑터
    - `synthesize_proposal_points` / `draft_proposal` 시그니처 `-> tuple[Result, usage_dict]` 로 확장. `scripts/smoke_phase4.py` 및 기존 테스트(24건)도 unpack 으로 업데이트
    - `USAGE_KEYS` 는 `src/llm/claude_client.py` 가 단일 소스. `merge_usage` 가 state.usage 누적
    - `persist_node` — `outputs/{company}_{YYYYMMDD}/proposal.md` + `intermediate/{articles_after_preprocess,tech_chunks,points,run_summary}.json`. 실패해도 부분 state 로 항상 디스크에 흔적 남김. `_to_jsonable` 재귀 직렬화(dataclass·pydantic·datetime·Path)
    - `route_after_stage` 라우터 — `failed_stage` 있으면 `"persist"`, 없으면 `"continue"`
    - 테스트 18건 신규 (데코레이터 / 7개 노드 / 라우터 / 직렬화 helper)
  - **Stream 2 ✅** — `src/graph/pipeline.py::build_graph()` + `tests/test_pipeline.py`
    - `StateGraph(AgentState)` 컴파일 — 7 노드 등록, 스테이지 1~5 는 `add_conditional_edges(..., route_after_stage, {"continue": next, "persist": persist})` 로 fail-fast 라우팅, `draft → persist` 는 무조건, `persist → END`
    - `MemorySaver` 체크포인터 (Phase 7 에서 `SqliteSaver` 로 스왑)
    - 의도적 단순화: `RetryPolicy` 생략. synthesize/draft 가 이미 내부에서 temp +0.1 으로 1회 재시도 — 네트워크 전이 실패는 Phase 7 에서 필요하면 추가
    - 테스트 4건 신규 — happy path / 중간 실패 라우팅 / search 실패 run_summary 작성 / 노드 등록 확인
  - **Stream 3 ✅** — `src/core/orchestrator.py::run()` + `scripts/smoke_phase5.py` + 실제 end-to-end
    - `run(company, industry, lang, *, output_root, top_k, run_id)` — CLI(Phase 6) / FastAPI(Phase 7) 공통 진입점. `run_id` 자동 생성, `output_dir = {root}/{company}_{YYYYMMDD}`, `started_at=time.perf_counter()` 스탬프
    - `scripts/smoke_phase5.py` — 전체 6단 + persist 단일 CLI. `--verbose` 플래그로 stage-by-stage INFO 로그 출력
    - 실측 (NVIDIA / semiconductor / en, Brave 20개 + Exaone 4bit + bge-m3 + Sonnet 2회): **7/7 stages_completed**, articles 20 → tech_chunks 8 → proposal_points 5 (intro/pain_point/growth_signal/risk_flag/tech_fit 각 1) → 588-word draft, footnote 6개 정확, 총 **182.7s** (모델 로딩 포함). usage `input=18533 / output=2415 / cache_write=3493 / cache_read=0` (첫 실행이라 캐시 쓰기만 발생, 동일 tech_docs 로 다음 타겟 돌리면 cache_read 가 대체)
    - 산출물: `outputs/NVIDIA_20260421/proposal.md` + `intermediate/{articles_after_preprocess,tech_chunks,points,run_summary}.json`
    - 회귀: **179 → 211 passed all green** (Stream 0 +10, Stream 1 +18, Stream 2 +4)
  - **후속 ✅** — `persist_node` 에 `output_dir` 결측 방어 추가 (KeyError → 에러 로그 + stage completed 처리), 테스트 +1 → **212 passed**
- **Phase 6 ✅** — Typer 기반 단일 진입점 `main.py`
  - `main.py run --company <X> --industry <Y> --lang en|ko [--top-k N] [--output-root PATH] [--verbose]` → `src.core.orchestrator.run()` 위임 + 결과 요약/실패 시 exit 1
  - `main.py ingest [--local-dir PATH] [--no-local] [--notion] [--force] [--dry-run] [--verify]` → `src.rag.indexer.main()` 에 argv 포워딩
  - 모듈 로드 시점에 `sys.stdout.reconfigure(encoding="utf-8")` — Windows cp949 에서 em-dash/한글 help 렌더링 실패 방지
  - 테스트 6건 신규 (`tests/test_cli.py`): run 필수 인자 / lang override + top_k / 잘못된 lang 거부 / failed_stage 시 exit 1 / ingest flag 포워딩 / indexer exit code 전파. **212 → 218 passed**
- **Phase 5 보강 ✅ (Step 4)** — AgentState 계약 강화
  - `AgentState` 에 `status` (`Literal["running", "failed", "completed"]`), `current_stage` (`str | None`), `ended_at` (`float | None`) 필드 추가. `new_state()` 는 `status="running"` + `current_stage=None` 로 시드
  - `@_stage` 데코레이터가 성공/실패 양쪽에서 `current_stage = name` 을 patch 에 포함 — 체크포인터로 실시간 관찰 시 현재 진행 스테이지 추적 가능 (Phase 7 SSE 대비)
  - `persist_node` 가 종료 시 `status` 결정 (`failed_stage` 있으면 `"failed"`, 없으면 `"completed"`) + `ended_at = time.perf_counter()` 스탬프 + `current_stage` 를 완료면 `None`, 실패면 raising stage 로 고정
  - `run_summary.json` 에 `status` / `started_at` / `ended_at` / `current_stage` 추가 (기존 `duration_s` 유지)
  - 테스트 2건 신규 + 기존 assert 보강 (state: status 초기화, nodes: 실패 시 current_stage 세팅, pipeline: status 전이). **218 → 220 passed**
- **Phase 7 ✅** — Web UI MVP (FastAPI backend + Next.js 15 frontend)
  - **백엔드 (`src/api/`)** — FastAPI + lifespan 기반
    - `src/api/app.py::create_app()` — `lifespan` 에서 Exaone (`local_exaone.load()`) + bge-m3 (`embeddings.get_embedder()`) 를 `anyio.to_thread.run_sync` 로 warm-load. `API_SKIP_WARMUP=1` 로 스킵(테스트용). CORS 미들웨어 (`API_CORS_ORIGINS`, 기본 `http://localhost:3000`)
    - `src/api/checkpoint.py::build_sqlite_checkpointer()` — `SqliteSaver(sqlite3.connect(..., check_same_thread=False))` 을 `app.state.checkpointer` 로 유지. `/runs` POST 시 BackgroundTasks 로 dispatch 되는 anyio worker thread 와 이벤트 루프가 같은 커넥션을 공유
    - `src/api/config.py::ApiSettings` — env-driven 런타임 설정 (`API_SKIP_WARMUP` / `API_CHECKPOINT_DB` / `API_CORS_ORIGINS`). `settings.yaml` 과 분리 — 배포/테스트 knob 용
    - `src/api/store.py::RunStore` / `IngestStore` — 인메모리 레지스트리. `RunRecord.events` 는 append-only 이벤트 로그 (seq / kind / ts / payload). 스레드 공유는 `threading.Lock` 으로 가드. 실행 이력 영속화(별도 DB 테이블)는 장기 과제
    - `src/api/runner.py::execute_run()` — `orchestrator.run_streaming()` 을 소비해 각 super-step 마다 RunStore 업데이트 + 이벤트 append. `execute_ingest()` 는 `src.rag.indexer.main()` 포워딩
  - **Orchestrator 리팩터 (`src/core/orchestrator.py`)** — 공통 셋업 `_prepare_run()` 분리 + `run()` / `run_streaming()` 두 entry 노출. `run_streaming(...)` 는 `graph.stream(state, config, stream_mode="values")` 로 스테이지별 state yield. CLI 는 기존 `run()` 유지, 테스트도 그대로
  - **`build_graph(checkpointer=...)`** — 타입 힌트를 `Any | None` 으로 일반화 (SqliteSaver / MemorySaver 양쪽 수용). CLI / 테스트는 MemorySaver default, API 는 SqliteSaver 주입
  - **라우트:**
    - `GET /healthz` — `warmup_skipped` / `exaone_loaded` / `embedder_loaded` 플래그
    - `POST /runs` (202) → `run_id` 반환 + BackgroundTasks 큐잉
    - `GET /runs` (최신순) / `GET /runs/{run_id}` (summary + proposal_md)
    - `GET /runs/{run_id}/events` — sse-starlette `EventSourceResponse`. 레코드 이벤트 로그를 `since_seq` 기반 폴링(150ms) 으로 증분 전송. 완료/실패 후 잔여 이벤트까지 flush 하고 종료
    - `GET /ingest/status` — `data/vectorstore/manifest.json` 파싱해서 document/chunk/source_type 집계
    - `POST /ingest` (202) + `GET /ingest/tasks/{task_id}` — 인덱서 트리거 + 상태 폴링
  - **프론트엔드 (`web/` — Next.js 15 App Router + TypeScript + Tailwind v3)**
    - `/` (`src/app/page.tsx`) — company/industry/lang/top_k 폼 → `POST /runs` → `/runs/[id]` 리다이렉트
    - `/runs/[id]` (`src/app/runs/[id]/page.tsx`) — 초기 `GET /runs/{id}` 스냅샷 + `EventSource(/runs/{id}/events)` SSE 바인딩. 이벤트 수신 시마다 권위 있는 전체 summary 재조회. `StageProgress` 컴포넌트로 7-단계 상태 뱃지 + `react-markdown + remark-gfm` 으로 완료된 proposal 렌더
    - `/rag` (`src/app/rag/page.tsx`) — 최소 RAG 관리. 매니페스트 상태 + dry-run/re-index 버튼(notion/force 토글). 업로드/삭제는 의도적으로 제외
    - `web/README.md` — 로컬 개발 플로우 (uvicorn 서버 + `npm run dev`)
  - **테스트 (12건 신규, `tests/test_api_runs.py` + `tests/test_api_ingest.py`)** — `TestClient` 기반. `src.api.runner.execute_run` / `execute_ingest` 를 module-attr 로 monkeypatch (DO NOT 룰 준수) 해서 Brave/Exaone/Sonnet/Chroma 없이 라우트 로직만 검증. **235 passed all green** (223 → +12)
  - **DO NOT 룰 실전 강화** — Stream 6 테스트 중 `from src.api.runner import execute_run` 바인딩이 `monkeypatch.setattr("src.api.runner.execute_run", ...)` 와 충돌해 실제 Exaone 이 로딩되는 false-green 발생. `src.api.routes.{runs,ingest}` 및 `src.api.routes.ingest` 의 `from src.config.loader import get_settings` 모두 모듈-경유 접근으로 전환 (`from src.api import runner as _runner` / `from src.config import loader as _config_loader`)
  - **장기 과제로 분리** — 인증, 백그라운드 워커(Celery/RQ), 풀 RAG 관리 UI(업로드/삭제/Notion 페이지별 토글/인덱싱 이력 타임라인), 실행 이력 전용 DB 는 `docs/backlog.md` 에 기록

- **Phase 8 ✅** — Raw data collection 강화 (3채널 검색 + RAG 시드 정리)
  - **배경**: Phase 5~7 의 단일 채널 검색 (`bilingual_news_search(company)`) 으로는 톤만 조정해도 raw 입력 다양성 한계. 회사 단일 채널 → 3채널 (target / related / competitor) 로 분기.
  - **Stream 0 — RAG 시드 정리 + 스키마 잠금**
    - `data/company_docs/README.md` 삭제 (실험용 가이드 → 인덱싱 노이즈 제거), `.gitignore` `.gitkeep` 패턴으로 빈 폴더 보존
    - `config/targets.yaml::rag.notion_page_ids` 빈 리스트 (Notion 임시 비활성, 페이지 ID 는 주석으로 보존)
    - `data/vectorstore/` reset → `python -m src.rag.indexer --force` → **Databricks_AI Platform.pdf (20MB) → 64 청크** 신규 인덱싱 (이전 12 청크 대비 5배 풍부)
    - `Article.channel: Literal["target","related","competitor"]` 필드 추가 (default `"target"`, 기존 산출물 호환)
    - `AgentState.search_meta: dict` 키 추가 (채널별 pool/returned/errors 메타)
    - `IntentSpec` / `CompetitorSpec` dataclass + `CompetitorsConfig` / `IntentTiersConfig` Pydantic 스키마
    - `config/{competitors,intent_tiers}.example.yaml` 템플릿
  - **Stream 1 — Competitor 채널 (B)**
    - `src/search/channels/competitor.py::run_competitor` — `direct` weight=1.0 / `adjacent` weight=0.6, round-robin merge 로 cap (default 5) 균등 분배. URL dedup, per-경쟁사 실패 격리.
    - `src/config/loader.py::load_competitors` — yaml 부재 시 빈 객체 + warn (채널만 비활성, 파이프라인은 정상)
    - 단위 테스트 10건
  - **Stream 2 — Related 채널 (A) — AI 초안 + 사람 검수 정적 티어**
    - 사용자 결정: 런타임 LLM intent 생성 대신 **빌드타임 AI 초안 + 런타임 정적 yaml**. 결정성·비용 0 + 사람-in-the-loop 보정 가능.
    - `src/search/channels/related.py` — 티어 가중치 (S=5/A=4/B=3/C=2) 비례 분배 + remainder 우선 분배. 첫 키워드만 쿼리화 (단순). intent 별 실패 격리.
    - `scripts/draft_intent_tiers.py` — Sonnet 1회 (`chat_cached` 사용) 로 `intent_tiers.yaml` 초안 stdout/file 출력. RAG 빈약 시 warn. 운영 도구 (런타임과 분리).
    - `src/config/loader.py::load_intent_tiers` — yaml 부재 시 빈 객체 + warn
    - 단위 테스트 11건
  - **Stream 3 — search_node 통합 + dedup 채널 우선순위**
    - `src/search/channels/__init__.py::run_all_channels` — `BraveSearch` 컨텍스트 내에서 `ThreadPoolExecutor(max_workers=3)` fan-out (target/related/competitor 병렬). 채널별 try/except → `channel_errors` 누적, partial-success 라우팅.
    - Cross-channel URL dedup — rank 순서 (target > related > competitor) 로 keep
    - `src/rag/embeddings.py::_pick_representative` — sort key 에 `_CHANNEL_RANK` 추가. 의미 중복 (같은 기사 다른 URL) 도 target 우선.
    - `src/graph/nodes.py::search_node` — `_channels.run_all_channels` 모듈-경유 호출 (DO NOT 룰 준수). `bilingual_news_search` / `BraveSearch` import 제거.
    - `fetch_node` — competitor 채널은 snippet-only fast path (HTTP fetch 스킵). `settings.search.fetch_workers` 노출.
    - `settings.yaml` — `max_articles_per_channel: {target: 20, related: 15, competitor: 5}`, `fetch_workers: 5`
    - 기존 monkeypatch 테스트들 (`test_graph_nodes`, `test_pipeline`) 새 인터페이스로 마이그레이션
    - 신규 통합 테스트 5건 (multi-channel merge / x-channel dedup / partial failure / per-channel cap forwarding / dedup channel rank)
  - **Stream 4 — Synthesize 다중 블록 + 프롬프트**
    - `src/llm/synthesize.py::_render_articles_by_channel` — `<target_articles>` / `<related_articles>` / `<competitor_news>` 분기. 빈 채널은 블록 자체 생략.
    - 채널별 tier 차등: target = 기존 정책 (high-tag → body, low-tag → snippet) / related = 항상 snippet (intent_label/intent_tier attr) / competitor = snippet only (competitor/relation attr)
    - `src/prompts/{en,ko}/synthesize.txt` task 섹션에 새 블록 처리 지침 추가: target=PRIMARY, related=SUPPORTING, competitor=차별화 한정·직접 인용 금지·경쟁사명 명시 자제
    - ProposalPoint 스키마 변경 없음 (호환성)
    - 단위 테스트 7건
  - **회귀 + 신규**: 기존 235 → **270 passed all green** (+35: Stream 1 +10, Stream 2 +11, Stream 3 +5, fetch_node +1, search_node +1, Stream 4 +7)
  - **Stream 5 — E2E 스모크 + 운영 시드 ✅**
    - `config/competitors.yaml` 작성 (direct: Snowflake / Vertex AI / SageMaker, adjacent: Cloudera / Hugging Face / MLflow)
    - `scripts/draft_intent_tiers.py` 1회 실행 → `config/intent_tiers.yaml` 6 의도 초안 (S 2 / A 2 / B 2). Sonnet 토큰: input=87 / output=822 → ~$0.005. 사람 검수 후 수정 가능한 운영 yaml 로 커밋
    - **첫 풀 스모크 OOM** — 39 기사 dedup 시 RTX 4070 16GB 에서 bge-m3 가 5.6GB 추가 할당 실패. plan 위험 분석에서 정확히 예측한 케이스. 3 안전장치로 fix:
      - `embed_texts(..., batch_size=8)` 강제
      - dedup 입력 텍스트 첫 3000 자 truncate (의미 영향 미미)
      - dedup 직전 `torch.cuda.empty_cache()` 호출
    - **재실행 측정값** (NVIDIA / semiconductor / en):
      | 항목 | 값 |
      |---|---|
      | Total wall time | **195.96s** (plan 280-340s 예상보다 **빠름**, batch+truncate 효과) |
      | Brave 호출 | 13회 (target 1 + related 6 intents + competitor 6 specs) |
      | search → fetch → preprocess → retrieve → synthesize → draft | 3s + 6s + 140s + <1s + 29s + 16s |
      | articles | searched 39 / fetched 39 (full 27 + snippet 12, competitor fast-path 5) / processed 20 |
      | tech chunks | 8 / proposal points 5 / draft 585 단어 |
      | Sonnet 토큰 | input=16268 / output=2286 / cache_read=0 / cache_write=2656 |
      | 추정 비용 | **~$0.093** (plan 예상 $0.13-0.16 보다 **저렴** — competitor snippet-only fast path + body truncate 합산 효과). 동일 RAG 로 다음 타겟은 cache_read 로 더 저렴 |
    - **proposal 품질 검증** — `outputs/NVIDIA_20260428/proposal.md`:
      - 5 angle 모두 분포 (intro / pain_point / growth_signal / tech_fit / risk_flag)
      - **Databricks 제품 기능 정확 인용**: MLflow / Feature Store / Model Serving / Unity Catalog / Foundation Model APIs (Llama 4 / Claude / Gemma / DeepSeek) / BI layer — 64-청크 PDF RAG 시드 효과
      - **NVIDIA 실제 뉴스 정확 인용**: $5.26T 시총, $78B Q1 FY2027, $1T 칩 로드맵, Sequoia $1.1B 라운드, Nokia 6G — target_articles 기반
      - footnote 7개 자동 번호링 + URL 매핑 정확
      - **competitor 채널 정확히 차별화 한정** — proposal 본문에 경쟁사명 미명시 (프롬프트 지침 준수)
  - **docs 갱신**: `backlog.md` (항목 9 multi-intent 흡수 처리, 항목 8 reverse matching 에 빌딩 블록 메모, 신규 항목 15 [개인 CV 피보팅] / 16 [영업 반응 KG] 추가) / `playbook.md` (#10 멀티 채널 rank-based keep, #11 AI 초안+사람 검수 정적 티어) / `lesson-learned.md` (Phase 8 OOM 사건)
  - **다음**: 1~2 추가 타겟 (Tesla / Deloitte 재실행 등) 으로 channel mix 효과 일반화 확인 → 측정값 누적 후 P1-1 톤 조정 또는 P1-2 drag-drop UX 진행 검토.

- **Phase 5 보강 ✅ (Step 5)** — articles 스테이지 분리
  - `AgentState.articles` 단일 키를 **`searched_articles` / `fetched_articles` / `processed_articles`** 3개로 분할 — 실패 경로에서 어느 단계까지 진행됐는지 state 만 보고 판단 가능
  - 노드별 read/write 재배선: search_node → searched / fetch_node reads searched → writes fetched / preprocess_node reads fetched → writes processed / synthesize·draft 는 processed 를 참조
  - `persist_node`: 캐노니컬 `articles_after_preprocess.json` 에는 `latest_articles(state)` (processed > fetched > searched 폴백) 를, 실패 경로에선 추가로 `articles_searched.json` / `articles_fetched.json` 단계별 덤프
  - 새 헬퍼 `src/graph/state.py::latest_articles(state)` — CLI 요약 출력과 persist 양쪽에서 재사용
  - `main.py run` / `scripts/smoke_phase5.py` 요약 출력이 `searched=N fetched=N processed=N` 3개 카운트 표시로 변경
  - 테스트 3건 신규 (`latest_articles` 우선순위 / persist 가 fetch 실패 시 searched 폴백 + per-stage 덤프 / preprocess 실패 시 fetched 덤프 + searched 덤프 동시) + 기존 테스트 전부 새 키로 재배선. **220 → 223 passed**

- **Phase 9 ✅** — Target Discovery (RAG-only reverse matching, MVP)
  - **배경**: Phase 8 까지는 "타겟사가 정해진" 전제. 사용자가 새 방향 제시 — `data/company_docs` (64-청크 Databricks PDF) RAG 만으로 잠재 BD 타겟 + 티어리스트 자동 생성. backlog 항목 8 (reverse matching) 의 MVP 컷.
  - **결정 잠금**: Sonnet 1회 호출만 (검증 없음, 부정확한 회사명 가능성 인정 — 사람이 후속 단계로 검수) / 5 산업 × 5 회사 = 25 (CLI 플래그 오버라이드) / candidates.yaml (flat) + report.md (산업 그루핑) 둘 다 / `src/core/discover.py` 순수 함수 + 얇은 CLI/scripts 어댑터 / en + ko 양쪽 prompt
  - **Stream 0 — 스키마 + 프롬프트**
    - `src/core/discover_types.py` — `Candidate` (pydantic, name/industry/tier/rationale) + `DiscoveryResult` (dataclass, generated_at/seed_doc_count/seed_chunk_count/seed_summary/industry_meta/candidates/usage) + `Tier = Literal["S","A","B","C"]` + `parse_discovery(raw, n_industries, n_per_industry)` (object-first JSON 추출 + 카운트·산업키·티어 검증, 위반 시 ValueError)
    - 자체 `_extract_json_object` 헬퍼 — `proposal_schemas._extract_json` 은 array regex 우선이라 prose 래핑 시 inner candidates list 만 잡는 케이스 회피
    - `src/prompts/{en,ko}/discover.txt` — system + ---TASK--- 분리, `{n_industries}`/`{n_per_industry}`/`{expected_total}` placeholder 로 카운트 동적 주입
  - **Stream 1 — `src/core/discover.py` 핵심 함수**
    - `discover_targets(*, lang, n_industries=5, n_per_industry=5, seed_summary=None, seed_query="core capabilities and target use cases", output_root=None, top_k=20, client=None, write_artifacts=True) -> DiscoveryResult`
    - manifest.json 직접 read → `seed_doc_count` / `seed_chunk_count` (`indexer.manifest_path_for` + `load_manifest` 재사용, 매니페스트 결측 시 (0,0) + warn)
    - `retrieve(seed_query, top_k=20)` 호출, RAG 빈 결과 시 warn (Sonnet 부정확 산출물 경고)
    - `<knowledge_base>` 블록 → `cached_context`, `<product_summary>seed_summary</product_summary>` → `volatile_context`, `chat_cached` 1회 + 스키마 실패 시 temp +0.1 재시도 1회 (synthesize 패턴 그대로). 두 번 실패 시 ValueError
    - `outputs/discovery_{YYYYMMDD}/candidates.yaml` (flat: generated_at + seed{} + industry_meta + candidates 평면 리스트 + usage) + `report.md` (산업별 그루핑, 시드 메타 헤더, Tier 정렬 (S→A→B→C) Markdown table)
    - `claude_max_tokens_discover` 신규 setting (4000) — 25 후보 rationale 합산 ~2500 출력 토큰이라 synthesize 의 2000 으로는 부족
  - **Stream 2 — 얇은 어댑터**
    - `main.py discover` Typer 서브커맨드 — `--lang/--n-industries/--n-per-industry/--seed-summary/--seed-query/--top-k/--output-root/--verbose`. body 는 `discover_targets()` 호출 + 결과 요약 stdout
    - `scripts/discover_targets.py` argparse 어댑터 (`draft_intent_tiers.py` 와 같은 형식, Windows utf-8 inside-main 재설정)
  - **Stream 3 — 테스트 + 1회 실제 실행 + docs**
    - `tests/test_discover.py` 9건: 정상 / yaml+md 산출물 / fenced JSON / retry 1회 후 성공 / 두 번 실패 → ValueError / cache_control 은 knowledge_base 블록만 / lang=ko prompt 로드 / 카운트 placeholder 치환 / `parse_discovery` 산업 분포 검증
    - `tests/test_cli.py` +2: discover 인자 포워딩 / 잘못된 lang 거부
    - **회귀**: 270 → **281 passed all green** (+11)
    - **실제 1회 실행** (Databricks RAG, en):
      | 항목 | 값 |
      |---|---|
      | Total wall time | ~40s (bge-m3 로딩 + retrieve + Sonnet 1회) |
      | Sonnet 토큰 | input=3 / output=2520 / **cache_read=6566** / cache_write=83 — 같은 RAG 재실행 시 cache 적중 확인 |
      | 추정 비용 | **~$0.040** (plan 예상치 정확히 일치) |
      | 산출물 | `outputs/discovery_20260428/{candidates.yaml, report.md}` |
    - **품질 관찰**: 5 산업 (Financial Services / Retail & E-Commerce / Healthcare & Life Sciences / Technology & Software / Manufacturing & Supply Chain) × 5 회사. 모든 회사명 실재 (JPMorgan / Goldman / Visa / Pfizer / NVIDIA / Snowflake / Siemens / Bosch 등). Rationale 이 Databricks 구체 기능 (Unity Catalog / MLflow / Mosaic AI / Delta Live Tables / AI Gateway / Knowledge Assistant) 직접 인용. 티어 분포 8 S / 10 A / 7 B / 0 C — 약간 상위 편향 (C 부재). 2 카운트 검증 (5 distinct industry / 산업당 정확히 5 회사) 통과
    - **docs 갱신**: `status.md` Phase 9 섹션 / `backlog.md` 신규 항목 17 (티어리스트 편집 웹 UI: candidates.yaml → SQLite import → /discover 페이지 sortable·editable table → yaml export 또는 targets.yaml 자동 추가)

- **Phase 9.1 ✅** — Discovery scoring 엔진 + sector_leaders + region (mega-cap 편향 fix)
  - **배경**: Phase 9 첫 산출 (`outputs/discovery_20260428` v1) 사람 검수 결과 8S/10A/7B/0C 상위 편향 + Fortune-500 mega-cap 위주 (JPMorgan/Goldman/Amazon/Walmart/NVIDIA 등). LLM 이 "이론상 fit" (데이터 규모) 으로 tier 판단 → 실 영업 가능성 (landability) 과 괴리. 사용자 피드백: "무작정 prompt 재작성보다는 scoring 로직을 짜는게 좋을것 같아".
  - **근본 fix**: LLM 의 역할을 "tier 판단" → **"6 차원 0-10 점수"** 로 좁히고 final_score / tier 는 코드가 weighted sum + threshold rule 로 결정. weight 외부 yaml 화 → 재현·재사용·재계산 0원.
  - **Stream 0 — config 신설**
    - `config/weights.yaml` — default + databricks override (data_complexity 0.25 / governance_need 0.20 / displacement_ease 0.10). 합 != 1.0 자동 정규화.
    - `config/tier_rules.yaml` — S>=8.0 / A>=7.0 / B>=6.0 / C>=5.0, C 미만 clamp.
  - **Stream 1 — `src/core/scoring.py` 신설**
    - `WEIGHT_DIMENSIONS` 6개 잠금 (pain_severity / data_complexity / governance_need / ai_maturity / buying_trigger / displacement_ease)
    - `load_weights(product)` — yaml 로드 + override merge + 누락 검증 + auto-normalize warn
    - `load_tier_rules()` — descending sort + 4 tier 강제
    - `calc_final_score` weighted sum, `decide_tier` first-match (epsilon 1e-6 으로 float drift 흡수)
    - `src/config/{schemas,loader}.py` — WeightsConfig / TierRulesConfig / SectorLeadersConfig + 3 load 함수
  - **Stream 2 — discover_types + discover.py 통합**
    - `Candidate` 스키마 변경: `tier` LLM 출력 → 코드 채움. `scores: dict[str,int]` (6 dim 0-10) + `final_score: float` + `rationale: str`. `parse_discovery` 가 LLM 의 `tier`/`final_score` 응답 silently drop.
    - `discover_targets()` 시그니처 +`product: str = "databricks"`, parse 후 scoring 단계 추가 (코드 결정).
    - `_render_report` — Strategic Edge (C tier) 별도 섹션 분리 + Signals 컬럼 (top-2 dimension scores). yaml 에 scores+final_score+tier 모두 노출.
  - **Stream 3 — 프롬프트 + 어댑터**
    - `src/prompts/{en,ko}/discover.txt` 재작성 — 6 차원 의미 명시 + 0-10 정수 + "tier 출력 금지" + "rationale 1문장 ~25어 (scores 가 차원별 판단 담음)"
    - `main.py discover` / `scripts/discover_targets.py` — `--product` 플래그 추가
  - **Stream 4 — sector_leaders 시드 + region (mega-cap 편향 보완)**
    - `config/sector_leaders.{example,operational}.yaml` — flat list (name/industry_hint/region/notes). 16 회사 시드 (Stripe, Adyen, 토스, KB금융, 네이버, 카카오, 셀트리온, 한화에어로 등 mid-market·local).
    - `discover_targets(*, region: Literal["any","ko","us","eu","global"]="any", include_sector_leaders: bool = True)`. region 명시 시 해당 + global 시드만, "any" 는 모든 시드 노출.
    - `_render_volatile` 에 `<sector_leader_seeds region="...">` + `<region_constraint>` 블록 추가. 빈 채널은 자동 생략.
    - `scripts/draft_sector_leaders.py` — Sonnet 1회로 yaml 초안 생성 (Phase 8 `draft_intent_tiers.py` 패턴 그대로)
    - main.py / scripts: `--region` + `--sector-leaders/--no-sector-leaders` 플래그
  - **Stream 5 — 테스트 + 1회 재실행 + docs**
    - `tests/test_scoring.py` 13건 (load_weights / merge / 정규화 / 누락 raise / tier_rules 정렬 / boundary 8.0 / C clamp / epsilon)
    - `tests/test_discover.py` 6건 보강 (LLM tier silently dropped / out-of-range scores reject → retry / sector_leaders inject / no-sector-leaders skip / region 주입 / region=any 미주입)
    - `tests/test_cli.py` +2 (discover --product/--region/--no-sector-leaders 인자 포워딩 / 잘못된 region 거부)
    - **회귀**: 281 → **302 all green** (+21)
    - **실제 1회 재실행** (Databricks RAG, en, region=any, sector_leaders 활성):
      | 항목 | 첫 산출 (Phase 9 v1) | Phase 9.1 |
      |---|---|---|
      | Tier 분포 | 8S / 10A / 7B / 0C | **3S / 18A / 4B / 0C** |
      | S tier 회사 | JPMorgan, Goldman, Amazon, Walmart, Pfizer, NVIDIA, UnitedHealth, Siemens (mega-cap) | **Stripe, Adyen, Tempus AI** (mid-cap, BD-friendly) |
      | 한국 기업 | 0 | **7** (토스, KB금융, 네이버, 카카오, 한화에어로, 셀트리온, 두산 등) |
      | Snowflake (직접 경쟁사) | A tier | **B tier** (강등 — 코드가 displacement_ease 낮은 점수 반영) |
      | 비용 | $0.040 | **$0.081** (첫 cache_write; 다음 실행은 cache_read 로 ~$0.05) |
      | output_tokens | 2520 | 3713 (scores 6 dim + sector_leaders 영향) |
      | claude_max_tokens_discover | 4000 | **6000** (rationale 1문장 강제 후에도 안전 마진) |
    - **재현성·재사용성 데모**: 같은 LLM 응답 (`scores`) 으로 weight 만 바꿔 재계산하면 추가 LLM 호출 0원으로 tier 분포 변동 가능. 다른 제품 (Snowflake/Salesforce 등) 도 `weights.yaml::products.<name>` 추가만으로 재사용 가능 — 본 phase 의 핵심 가치.
    - **남은 한계**: C tier 가 0개. AWS/Azure/GCP 본체·Palantir 자체 lock-in 같은 Strategic Edge 케이스는 sector_leaders.yaml 시드에 안 들어가서 LLM 이 자연 배제 → C 후보 자체가 안 뜸. 후속에서 sector_leaders 에 일부 hyperscaler/lock-in 케이스 의도적 추가 또는 prompt 에 "include 1+ challenger case per industry" 룰 추가 검토.

- **Phase 10 — 8-탭 웹 UI 확장 (진행 중)**
  - **배경**: Phase 7 웹 UI 는 단일 Run 폼 + Run 상세 + RAG 상태 3 페이지 MVP 컷으로 멈춰 있고, Phase 8/9/9.1 자산 (3채널 검색 / discovery / scoring 엔진) 은 CLI + yaml 산출물에만 노출. 비-개발자 BD 인력의 일상 운영 (아침 뉴스 → 후보 검수 → 제안서 → 콜 기록) 을 yaml 직접 편집 없이 하려면 8-탭 UI 가 필요.
  - **8-탭 구조 (잠금)**: Home / Daily News / Discovery / Targets / Proposals / RAG Docs / 사업 기록 / Settings. PR 시리즈 P10-0 ~ P10-8 **모두 완료 (2026-04-30)**.
  - **Stream 9 ✅ (P10-8) — Home 6-박스 대시보드 + 집계 endpoint**
    - **2026-04-30** — Phase 10 의 마지막 Stream. 8개 탭의 활동을 한 화면에서 요약 + 새로고침 버튼으로 재집계
    - **백엔드 routes/dashboard.py** 신규 — `GET /dashboard` 한 endpoint 가 6개 sub-aggregate 를 모음:
      1. **recent_runs** — RunStore newest-first top 5
      2. **recent_discovery** — DiscoveryStore latest run + tier_distribution 재계산 (S/A/B/C count)
      3. **pipeline_by_stage** — Targets 단계별 카운트
      4. **rag** — vectorstore 디렉토리 스캔 → namespace 별 manifest read → document_count/chunk_count/is_indexed 플래그. `default` 항상 포함
      5. **news** — NewsStore.latest_for_namespace("default", status="completed") + 상위 3 title
      6. **cost** — RunStore + DiscoveryStore usage_json 합산 (proposal_in/out/cache_read/cache_write + discovery_in/out/cache)
    - 각 sub-aggregate 는 best-effort: 실패 시 warn + 빈 값 fallback (한 모듈 장애가 전체 dashboard 를 500 으로 만들지 않음)
    - **schemas.py**: `DashboardRecentRun` / `DashboardRecentDiscovery` / `DashboardNewsMini` / `DashboardRagStatus` / `DashboardCostSummary` / `DashboardResponse`
    - **프론트** `web/src/app/page.tsx` — 6-카드 placeholder landing 을 진짜 대시보드로 재작성. 6 박스: Quick Run (CTA → /proposals/new) / 오늘의 뉴스 mini (top 3 title) / Pipeline 요약 (Targets stage 별 + TargetStageBadge) / Recent Proposals & Discovery (top 3 runs + latest discovery tier 분포) / RAG 상태 (namespace 별 doc/chunk count) / 비용 (in/out/cache 토큰 합). 새로고침 버튼으로 즉시 재페치
    - **API 클라이언트**: `getDashboard()` 단일 함수
    - **테스트**: `tests/test_api_dashboard.py` 6건 — empty install (모든 aggregate 비어있음 + default namespace 항상 surface) / targets pipeline 카운트 / interactions 카운트 / RAG manifest pickup / news mini after refresh / recent_runs newest-first. **410 → 416 passed all green** (+6)
    - **DO NOT 룰**: dashboard.py 가 `_store` / `_config_loader` 모듈 attr 만 사용. 테스트는 `monkeypatch.setattr(_dash._config_loader, "get_settings", lambda: _Fake())` 로 vectorstore tmp 격리 + `monkeypatch.setattr("src.api.runner.execute_news_refresh", _fake)` 로 news/run 시드
    - **Phase 10 완료 메트릭**: P10-0/1/2a/2b/3/4/5/6/7/8 = **9 스트림** 머지. 311 → **416 tests** all green (+105 신규). 신규 라우터 8개 (targets / rag / discovery / news / interactions / settings / dashboard + 기존 ingest/runs/health 확장). 신규 frontend 페이지 6개 + Suspense·SSE·polling·dropzone·multipart·yaml editor 까지 포함
  - **Stream 8 ✅ (P10-7) — Settings (sub-tab + yaml 편집/검증)**
    - **2026-04-30** — `config/*.yaml` 7종을 sub-tab 으로 직접 편집. YAML syntax + pydantic 모델 두 단계 검증 후 atomic 쓰기. API 키는 .env 전용 (이 화면은 존재 여부만 표시 — 값은 절대 응답에 포함 X)
    - **백엔드 routes/settings.py** 신규 — `GET /settings` (지원 kind 목록) / `GET /settings/secrets` (3개 키 boolean view) / `GET /settings/{kind}` (raw_yaml + parsed dict, 파일 없으면 exists=False) / `PUT /settings/{kind}` (yaml.safe_load 422 → top-level dict 검증 → 해당 pydantic model 검증 → atomic tmp+replace 쓰기 → loader lru_cache 무효화)
    - **kind ↔ 파일 매핑**: settings/weights/tier_rules/competitors/intent_tiers/sector_leaders/targets → 동일 이름 yaml. 각 kind 마다 검증용 pydantic 클래스 (`Settings`/`WeightsConfig`/`TierRulesConfig`/...) `_KIND_TO_VALIDATOR` 테이블
    - **schemas.py**: `SettingsKind` Literal + `SETTINGS_KINDS` 튜플 + `SettingsRead` (kind/path/exists/raw_yaml/parsed) + `SettingsUpdate` (raw_yaml 200KB cap) + `SettingsKindList` + `SecretsView` (3개 boolean)
    - **캐시 무효화**: `_config_loader.get_settings.cache_clear()` + `get_secrets.cache_clear()` PUT 후 호출 → 다음 호출부터 새 yaml 반영. 다른 `load_*` 헬퍼는 lru_cache 미사용 (매번 read)
    - **프론트** `web/src/app/settings/page.tsx` — stub 대체. 8개 sub-tab (7 yaml + API keys). 각 yaml tab: textarea + 다시 불러오기 + 저장 버튼. 422 응답 시 raw 에러 메시지 (`YAML parse error: ...` / `validation failed for weights: ...`) 그대로 surfacing. API keys tab: boolean 뱃지 (set/missing) + .env 가이드. 파일 없으면 "저장 시 새로 생성" 뱃지 표시
    - **API 클라이언트**: `listSettingsKinds()` / `getSettings(kind)` / `putSettings(kind, rawYaml)` / `getSecretsView()`
    - **테스트**: `tests/test_api_settings.py` 10건 — kind 목록 / GET 정상 / GET 파일 없음 exists=False / GET 알 수 없는 kind 404 / PUT 정상 + 라운드트립 / PUT YAML syntax 422 / PUT top-level list 422 / PUT pydantic 422 / PUT 알 수 없는 kind 404 / GET secrets boolean 뷰 + 키 값 응답에 포함 X. **400 → 410 passed all green** (+10)
    - **DO NOT 룰**: routes/settings.py 가 `from src.config import loader as _config_loader` 모듈 attr. 테스트는 `monkeypatch.setattr(_loader, "CONFIG_DIR", tmp_cfg)` + `monkeypatch.setattr(_settings_routes._config_loader, "get_secrets", lambda: _Fake())` 로 격리 (직접 .env 가 pydantic-settings 우선순위로 envvar 를 이긴 케이스 → 모듈 attr monkeypatch 가 깔끔)
    - **다음 (P10-7 머지 후)**: P10-8 (Home 6-박스 대시보드 + 집계 endpoint) — 마지막 Stream
  - **Stream 7 ✅ (P10-6) — 사업 기록 (interactions CRUD + LIKE 검색)**
    - **2026-04-30** — BD 일상 운영의 콜/미팅/이메일/메모 캡처 탭. SQLite `interactions` 테이블 + 회사 정확 매치 / 텍스트 LIKE 검색. Targets 와 느슨한 연결 (`target_id` FK NULL 가능, 회사가 등록 전이어도 기록 가능)
    - **백엔드 store** `src/api/store.py::InteractionStore` — SQLite-only CRUD + LIKE search. `list(company=, target_id=, q=, limit=)` 가 `company_name`/`raw_text`/`contact_role` 3 필드에 LIKE 매치. `delete(id) → bool`. lazy 싱글턴 `get_interaction_store()` + `reset_stores()` 가 캐시 무효화
    - **routes/interactions.py** 신규 5 엔드포인트 — `GET /interactions?company=&target_id=&q=&limit=` (newest first, 정렬 `occurred_at DESC, id DESC`) / `POST /interactions` (201) / `GET /interactions/{id}` / `PATCH /interactions/{id}` (partial via exclude_unset) / `DELETE /interactions/{id}` (204). 모든 store 접근은 모듈 attr (`_store.get_interaction_store()`)
    - **schemas.py**: `InteractionKind` Literal (call/meeting/email/note) + `InteractionOutcome` Literal (positive/neutral/negative/pending) + `INTERACTION_KINDS`/`OUTCOMES` 상수 + `InteractionCreate`/`Update`/`Summary`/`ListResponse`. raw_text 20KB cap
    - **프론트** `web/src/app/interactions/page.tsx` — stub 대체. 단일 페이지 캡처 폼 (Company / Kind / Outcome / When date / Contact role / Notes textarea) + 회사 정확 필터 + 텍스트 검색 (form submit으로 search 적용) + 테이블 (When/Company/KindBadge/OutcomeBadge/Contact/Notes 2-line clamp/편집·삭제). 행 편집은 인라인 (폼 hydrate → PATCH). 빈 상태시 EmptyState
    - **API 클라이언트**: `listInteractions(opts)` / `createInteraction` / `patchInteraction` / `deleteInteraction`
    - **테스트**: `tests/test_api_interactions.py` 14건 — 생성 (full/minimal/blank 422/bad kind 422/bad outcome 422) / 목록 (company filter / q LIKE / newest-first) / get 404 / patch (partial / 404 / bad kind 422) / delete (204 / 404). **386 → 400 passed all green** (+14)
    - **DO NOT 룰**: routes 가 `_store` 모듈 attr 만 사용. 테스트는 env-driven `API_APP_DB` + `reset_stores()` 로 DB 격리, 모듈 monkeypatch 불필요 (외부 호출 없는 순수 SQLite store)
    - **다음 (P10-6 머지 후)**: P10-7 (Settings — sub-tab + yaml 편집/검증) → P10-8 (Home 대시보드 + 집계 endpoint)
  - **Stream 6 ✅ (P10-5) — Daily News (Brave 시드 검색 + namespace 캐시)**
    - **2026-04-30** — Namespace 별 시드 키워드 → Brave 1회 (en) 또는 2회 (ko bilingual blend) 호출 → SQLite `news_runs` 캐시. Sonnet 코멘트는 후속 PR (Sonnet 1회 추가 시 ~$0.05). 신규 유저는 빈 cache 에서 Refresh 한 번으로 시작
    - **DB 스키마**: `news_runs` 에 `namespace`/`seed_query`/`lang`/`days`/`status`/`article_count`/`started_at`/`ended_at`/`error_message`/`created_at` 컬럼 추가 (`_NEWS_RUNS_NEW_COLUMNS` ALTER 백필 + `idx_news_runs_namespace_generated` 복합 인덱스). P10-0 의 기존 `articles_json`/`sonnet_summary`/`usage_json`/`ttl_hours` 는 그대로 유지
    - **백엔드 store** `src/api/store.py::NewsStore` — SQLite-only CRUD (`create`/`update(articles=)`/`get`/`latest_for_namespace(status="completed")`/`list(namespace=,limit=)`). lazy 싱글턴 `get_news_store()` + `reset_stores()` 가 캐시 무효화
    - **runner** `src/api/runner.py::execute_news_refresh` — `from src.config import loader as _config_loader` + `from src.search import brave as _brave` 모듈 경유. ko 인 경우 `bilingual_news_search`, en 인 경우 단일 Brave 호출. 결과는 `_article_to_news_dict` 로 직렬화 후 `store.update(articles=...)` 로 일괄 갱신. 실패 시 `error_message` 저장
    - **routes/news.py** 신규 4 엔드포인트 — `POST /news/refresh` (202 + task_id, BackgroundTasks) / `GET /news/today?namespace=` (latest completed, 404 if empty) / `GET /news/runs/{task_id}` (단건 detail) / `GET /news/runs?namespace=&limit=` (list newest first). 모든 store/runner 접근은 모듈 attr (`_store.get_news_store()`, `_runner.execute_news_refresh`)
    - **schemas.py**: `NewsArticle` / `NewsRefreshRequest` (seed_query 필수 1-200자, lang en|ko, days 1-365, count 1-20) / `NewsRunSummary` / `NewsRunDetail` (extends summary + articles[]) / `NewsRunListResponse` / `NewsRefreshResponse`
    - **프론트** `web/src/app/news/page.tsx` — stub 대체. namespace 드롭다운 (RAG 와 공유), seed_query / lang / days / count 입력, Refresh 버튼이 1.5s 간격 polling (90s timeout) 으로 task 완료 감지 → article 카드 (title link / hostname / lang / published / snippet). 빈 namespace 시 EmptyState
    - **API 클라이언트**: `refreshNews(input)` / `getNewsToday(ns)` (404 → null) / `getNewsRun(taskId)`
    - **테스트**: `tests/test_api_news.py` 9건 — refresh queues + completes / today returns latest / 404 empty / 404 unknown task / blank query 422 / invalid namespace 422 / failed surfaces error / list newest-first / namespace filter. **377 → 386 passed all green** (+9)
    - **DO NOT 룰**: routes/news.py 가 `_runner` / `_store` 모듈 경유. 테스트는 `monkeypatch.setattr("src.api.runner.execute_news_refresh", _fake)` 로 fake 주입 → Brave/Sonnet 미사용
    - **다음 (P10-5 머지 후)**: P10-6 (사업 기록 — interactions CRUD + LIKE 검색) → P10-7 (Settings — sub-tab + yaml 편집) → P10-8 (Home 대시보드 + 집계 endpoint)
  - **Stream 5 ✅ (P10-4) — Proposals 탭 (Run 폼 이전 + Targets 점프 + 편집/다운로드)**
    - **2026-04-30** — Phase 7 의 단일-페이지 Run 폼을 `/proposals/new` 로 이전. `/proposals` 는 작성 이력 목록, `/` 는 6-카드 랜딩 (P10-8 대시보드 자리)
    - **백엔드**: `PATCH /runs/{run_id}` 엔드포인트 추가 — `proposal_md` 편집 (`RunUpdate` 스키마, max 200KB, exclude_unset partial). 스토어는 in-memory RunStore — 프로세스 재시작 시 휘발. DB 영속화는 후속 PR
    - **schemas.py**: `RunUpdate(proposal_md: str | None = Field(max_length=200_000))`
    - **프론트 라우팅 재구성**:
      - `web/src/app/page.tsx` — 6-카드 quick-link 그리드 (Proposals/Discovery/Targets/RAG/News/Interactions). Home 6-박스 대시보드는 P10-8 합류 예정
      - `web/src/app/proposals/page.tsx` — runs 목록 (newest first, status pill, 클릭 → `/runs/{id}`). 빈 상태 시 EmptyState + CTA → `/proposals/new`
      - `web/src/app/proposals/new/page.tsx` — Run 폼 + `Suspense` 래퍼 (Next 15 의 `useSearchParams` 요구사항). 쿼리 prefill: `?company=&industry=&lang=` → 폼 초기값
      - `web/src/app/runs/[id]/page.tsx` — 편집 토글 (`편집` → textarea), 저장 (`PATCH /runs/{id}` → 반환된 권위 있는 RunSummary 로 state hydrate), `.md 다운로드` (Blob → `<company>_<YYYYMMDD>.md`, filename sanitize)
    - **API 클라이언트**: `listRuns()` / `patchRun(runId, {proposal_md})`
    - **Targets → Proposal 점프**: 행 우측에 `제안서 →` 링크 (`/proposals/new?company=X&industry=Y`). 기존 `편집 →` 와 병존
    - **테스트**: `tests/test_api_runs.py` 에 PATCH 3건 추가 — proposal_md 업데이트 / 404 / empty payload no-op. **374 → 377 passed all green** (+3)
    - **DO NOT 룰**: `runs.py` 가 기존 `from src.api import runner as _runner` 패턴 유지. PATCH 는 store 만 건드리므로 추가 monkeypatch 불필요
    - **다음 (P10-4 머지 후)**: P10-5 (Daily News — RAG 시드 → Brave 1회 + 캐시) → P10-6 (사업 기록) → P10-7 (Settings) → P10-8 (Home 대시보드)
  - **Stream 4 ✅ (P10-3) — RAG 문서 관리 (drag-drop + namespace UI)**
    - **2026-04-30** — P10-2a 의 namespace 인프라 위에 IDE-workspace 식 UX 를 올림. 신규 유저는 빈 `default` namespace 에서도 자연스럽게 시작 가능 (drag-drop → Re-index → Discovery 사용)
    - **백엔드 (`src/api/routes/rag.py` 확장)**: 기존 `GET /rag/namespaces` 위에 5개 신규 엔드포인트 — `POST /rag/namespaces` (201, 중복 409, invalid name 422) / `DELETE /rag/namespaces/{ns}` (default 보호 400, 비어있지 않으면 409, `?force=true` 로 강제) / `GET /rag/namespaces/{ns}/documents` (rglob 으로 파일 목록 + manifest 와 cross-ref 해서 `indexed`/`chunk_count` 표시) / `POST /rag/namespaces/{ns}/documents` (multipart UploadFile, 25MB cap, 1MB 청크 스트리밍, 확장자 .md/.txt/.pdf 화이트리스트, traversal 차단) / `DELETE /rag/namespaces/{ns}/documents/{filename:path}` (resolve-and-check inside namespace root, 404)
    - **schemas.py 신규**: `RagNamespaceCreate` / `RagDocumentSummary` (filename·size·modified·extension·indexed·chunk_count) / `RagDocumentListResponse` (namespace + indexed_doc_count) / `RagDocumentUploadResponse` / `RagNamespaceDeleteResponse`
    - **path 헬퍼**: `_vectorstore_root()` / `_company_docs_root()` / `_validate_namespace_name` / `_validate_upload_filename` (path separator 차단) / `_resolve_inside` (traversal 차단). 테스트는 `_company_docs_root` 를 monkeypatch 해서 tmp_path 로 리다이렉트
    - **의존성**: `python-multipart>=0.0.9` 추가 (`requirements.txt`) — FastAPI `UploadFile` 의 multipart/form-data 파서. 기존 conda env 에 설치
    - **프론트 (`web/src/`)**: `react-dropzone@^15.0.0` 신규 의존성 + `RagDocumentDropzone.tsx` 컴포넌트 (drag-drop, ext 화이트리스트, 25MB cap, 진행 상태 표시, rejected 파일 에러 누적). 기존 stub `/rag` 페이지를 namespace switcher + meta + Drop zone + 문서 테이블 (Indexed/Pending 뱃지 + chunk_count + Delete) + Re-index 버튼 (dry/real) 으로 전면 재작성
    - **신규 유저 관점 (feedback_new_user_lens)**: namespace 비어있을 때 "이 namespace 는 비어있습니다 — 위 드롭 영역으로 .md/.txt/.pdf 업로드 후 Re-index" empty state. `default` 항상 노출 (드롭다운 fallback). 새 namespace 생성은 `prompt()` 인라인. namespace 삭제는 `default` 비활성 + force confirm + 인덱스/소스 모두 정리
    - **API 클라이언트** (`web/src/lib/api.ts`): `createRagNamespace` / `deleteRagNamespace(name, {force})` / `listRagDocuments` / `uploadRagDocument(ns, File)` (FormData) / `deleteRagDocument(ns, filename)` (segment-wise encodeURIComponent 으로 traversal 안전)
    - **테스트**: `tests/test_api_rag_docs.py` 20건 — 생성 (성공·duplicate 409·invalid name 422·blank 422) / 삭제 (default 400·404·non-empty 409·force 200·empty 무force 200) / 목록 (empty·indexed 마킹) / 업로드 (성공·새 namespace 자동 생성·traversal 차단·unsupported ext 415·path separator 차단) / 문서 삭제 (성공·404·traversal·namespace missing). 회귀: **354 → 374 passed all green** (+20)
    - **DO NOT 룰**: 라우트가 `from src.config import loader as _config_loader` 로만 접근. 테스트는 `monkeypatch.setattr(_rag_routes._config_loader, "get_settings", ...)` 와 `monkeypatch.setattr(_rag_routes, "_company_docs_root", lambda: cd_root)` 로 isolation
    - **다음 (P10-3 머지 후)**: P10-4 (Proposals 이전) → P10-5 (Daily News) → P10-6 (사업 기록) → P10-7 (Settings) → P10-8 (Home 대시보드). 향후 sub-folder UX·namespace 메타데이터 (생성일/소유자/설명) 는 `docs/backlog.md` 17 (RAG SaaS workspace) 항목에서 다룸
  - **Stream 0 ✅ (P10-0) — DB 스키마 + Nav 골격**
    - `src/api/db.py` — 신규. `data/app.db` (langgraph checkpoint DB 와 분리) + `init_db()` (idempotent) + `connect()` 컨텍스트 매니저 (row_factory=Row, FK ON, 자동 commit/rollback)
    - 5 테이블: `discovery_runs` / `discovery_candidates` (FK CASCADE) / `targets` (`discovery_candidate_id` FK SET NULL) / `interactions` (`target_id` FK SET NULL) / `news_runs` + 5 인덱스
    - `src/api/config.py::ApiSettings` 에 `app_db: Path` 추가 (`API_APP_DB`, default `data/app.db`)
    - `src/api/app.py` lifespan 에 `init_db()` 훅 (best-effort, 실패 시 warn + continue, `app.state.app_db_path` 노출)
    - **프론트**: `web/src/components/Nav.tsx` 신규 — 8-탭 네비, `usePathname()` 기반 active 표시. `layout.tsx` 가 헤더에 마운트 (max-w-6xl 로 확장)
    - **stub 페이지 6개** (`web/src/app/{news,discover,targets,proposals,interactions,settings}/page.tsx`) + 공유 `StubPage.tsx` (제목 + ship PR 표시 + description). 기존 `/` Run 폼 + `/rag` 인덱싱 페이지는 그대로 유지
    - **테스트**: `tests/test_api_db.py` 9건 — schema 생성·idempotent·parent dir·FK·commit·rollback·CASCADE·SET NULL·lifespan integration. **302 → 311 passed all green**
  - **Stream 3 ✅ (P10-2b) — Discovery 탭 UI**
    - **2영역 레이아웃 (`/discover`)**: 위쪽 입력 폼 (RAG namespace 드롭다운 / region / product / seed prompt / seed keyword / Advanced 토글 — top_k·n_industries·n_per_industry·lang·sector_leaders) + Run 클릭 시 confirm dialog (`~$0.04 · ~30s · Sonnet 1 call`). 아래쪽 결과 관리 — run 드롭다운 + 메타 (status pill / namespace / seed / tier 분포 / 토큰 사용량) + WeightSliders (LLM 0원 recompute) + CandidateTable (sortable, inline 점수·rationale 편집, promote, delete)
    - **신규 컴포넌트 (`web/src/components/`)**: `TierBadge` (S/A/B/C 색상) / `EmptyState` (재사용 빈 상태) / `DiscoveryRunForm` (입력 폼 + confirm) / `WeightSliders` (6-dim 슬라이더 + auto-normalize 표시 + 기본값 복귀) / `CandidateTable` (행 클릭 → 인라인 에디터 expand, scores/rationale 저장, promote/delete)
    - **신규 페이지 `web/src/app/discover/page.tsx`** — `useEffect` 초기 load (runs 목록 + 가장 최근 run hydrate) + SSE 구독 (`EventSource(/discovery/runs/{id}/events)`, run_started/run_completed/run_failed 이벤트 시 권위 있는 detail 재조회) + recompute → bulk_update_tiers
    - **API client (`web/src/lib/api.ts` + `lib/types.ts`)**: `listRagNamespaces` / `createDiscoveryRun` / `listDiscoveryRuns` / `getDiscoveryRun` / `deleteDiscoveryRun` / `discoveryEventsUrl` / `patchDiscoveryCandidate` / `deleteDiscoveryCandidate` / `recomputeDiscovery` / `promoteDiscoveryCandidate` + 풀 타입 (DiscoveryRunSummary / Detail / Candidate / Recompute / Promote / Tier / WeightDimension / Region 등)
    - **백엔드**:
      - `src/api/db.py` — `discovery_runs` 에 `namespace`/`status`/`started_at`/`ended_at`/`failed_stage`/`error_message` 컬럼 추가. `_migrate_discovery_runs()` 가 `PRAGMA table_info` 로 검사 후 `ALTER TABLE ADD COLUMN` 백필 (P10-0 이후 누적된 app.db 도 안전)
      - `src/api/store.py::DiscoveryStore` — runs CRUD + candidates CRUD + bulk_update_tiers (recompute) + in-memory event log (`append_event`/`snapshot_events`, RunStore 패턴 미러). lazy 싱글턴 `get_discovery_store()`
      - `src/api/runner.py::execute_discovery_run` — 모듈경유 `_discover.discover_targets(write_artifacts=False, namespace=..., ...)` 호출 → `DiscoveryResult.candidates` 를 `discovery_candidates` 테이블에 bulk insert + `discovery_runs` 의 generated_at/usage/seed_meta/status 갱신. 실패 시 `failed_stage="discover_targets"` + `error_message` 저장. `_runner.execute_discovery_recompute(run_id, weights_override?)` — 동기 함수, scoring engine 만 호출 (LLM 0원), 자동 정규화
      - `src/api/routes/discovery.py` 신규 9 endpoint — `POST /discovery/runs` (202, BackgroundTasks, `discover-{stamp}-{uuid6}` run_id) / `GET /discovery/runs` (newest first) / `GET /discovery/runs/{run_id}` (DiscoveryRunDetail) / `DELETE /discovery/runs/{run_id}` (CASCADE) / `GET /discovery/runs/{run_id}/events` (SSE, runs.py 패턴 미러) / `PATCH /discovery/candidates/{id}` / `DELETE /discovery/candidates/{id}` / `POST /discovery/runs/{run_id}/recompute` (LLM 0원, 즉시 응답) / `POST /discovery/candidates/{id}/promote` (TargetStore.create + candidate.status="promoted"). 모든 store/runner 접근은 모듈 경유 (`_store.get_discovery_store()` / `_runner.execute_discovery_run`) — DO NOT 룰 준수
      - `src/api/app.py` — `discovery_routes` 등록
    - **테스트**: `tests/test_api_discovery.py` 14건 — 정상 생성·실패 surfaced·validation·newest-first·404·CASCADE delete·candidate PATCH/DELETE·recompute (equal weights, off-one auto-normalize, 404)·promote (Targets 행 생성 + candidate.status). 회귀: **340 → 354 passed all green** (+14)
    - **DO NOT 룰 강화**: `routes/discovery.py` 가 `_runner.execute_discovery_run` 모듈 경유. 테스트에서 `monkeypatch.setattr("src.api.runner.execute_discovery_run", _fake)` 로 fake 주입 → 실제 Sonnet/RAG 미사용
    - **다음 (P10-2 머지 후)**: P10-3 (RAG drag-drop + namespace 생성·전환 UI) 또는 P10-4 (Proposal 탭). E2E 수동 검증은 README 의 `npm run dev` + `uvicorn` 흐름으로 확인
  - **Stream 2 ✅ (P10-2a) — RAG namespace 인프라**
    - **왜**: P10-2b Discovery UI 의 "참고 docu 폴더 선택" + IDE/SaaS workspace 비전 (`docs/backlog.md` 17 + plan). 단일 ChromaDB 컬렉션 전제를 깨고 `data/{vectorstore,company_docs}/<namespace>/` 식으로 격리.
    - **신규 모듈** `src/rag/namespace.py` — `DEFAULT_NAMESPACE="default"` / `MANIFEST_FILENAME` / `vectorstore_root_for(root, ns)` / `company_docs_root_for(root, ns)` / `manifest_path_for_namespace` / `list_namespaces` (manifest 존재 디렉토리만) / `ensure_namespace` (idempotent mkdir) / `migrate_flat_layout` (legacy 평면 → `<root>/default/`, idempotent, dest.exists() 시 skip)
    - **`src/rag/retriever.py`** — `_STORES: dict[str, VectorStore]` 으로 namespace 별 cache. `_store(namespace="default")` / `retrieve(query, *, namespace="default", top_k=None)`. `reset_store_singleton()` 가 dict 비움
    - **`src/rag/indexer.py`** — `from src.rag.namespace import MANIFEST_FILENAME` 로 상수 이동 (순환 import 회피). `main()` 에 `--namespace` / `--list-namespaces` / `--create-namespace` 신규 플래그. `--local-dir` 미지정 시 namespace-aware 디폴트 (`data/company_docs/<namespace>`). 시작 시 `migrate_flat_layout` 자동 호출 (no-op 후 비용 0)
    - **`src/api/routes/rag.py`** 신규 — `GET /rag/namespaces` 가 `list_namespaces` + 각 namespace manifest 메타 (document_count/chunk_count/by_source_type) 반환. `default` 가 빈 vectorstore 라도 항상 노출 (드롭다운 fallback)
    - **`src/api/routes/ingest.py`** — `_manifest_path(namespace=DEFAULT_NAMESPACE)` 로 default namespace manifest 를 읽음. `GET /ingest/status?namespace=` 옵션 추가
    - **`src/api/app.py`** — `lifespan` 에 `migrate_flat_layout` best-effort 호출 (실패 시 warn + continue). `rag_routes.router` 등록
    - **`src/core/discover.py`** — `discover_targets(*, namespace=DEFAULT_NAMESPACE, ...)` 시그니처 추가, `_read_seed_meta(namespace)` 로 namespace manifest 읽음, `_retriever.retrieve(seed_query, namespace=namespace, top_k=top_k)` 로 전달. P10-2b UI 가 namespace 선택해서 호출 가능
    - **마이그레이션 실측**: `data/vectorstore/{chroma.sqlite3, b005d517-..., manifest.json}` 평면 → `data/vectorstore/default/` 로 이동 (lifespan 호출 시 발생). `data/company_docs/Databricks_AI Platform.pdf` 평면 → `data/company_docs/default/` 이동. `.gitkeep` 은 root 보존. 이후 `python -m src.rag.indexer --verify` 결과 `matched=1 manifest_only=0 store_only=0`, dry-run 결과 `skipped=1` (재인덱싱 불필요 확인)
    - **테스트**: `tests/test_rag_namespace.py` 13건 (path/name builders, list_namespaces, ensure_namespace, migrate idempotent + 기존 namespace 보존 + 빈 케이스 + missing root, retriever cache split per namespace) + `tests/test_api_rag.py` 3건 (빈/다중/default 자동 추가). 회귀: `test_retriever.py` fixture lambda 시그니처에 `namespace="default"` 추가, `test_api_ingest.py` fixture 가 `vs/default/manifest.json` 으로 이동, `test_discover.py::patched_rag` lambda 도 새 시그니처. **324 → 340 passed all green** (+16: 13 namespace + 3 api)
    - **DO NOT 룰**: `routes/rag.py` 가 `from src.config import loader as _config_loader` 모듈 경유. namespace.py 가 indexer.py 를 import 하지 않음 (MANIFEST_FILENAME 을 namespace.py 에 정의)
    - **다음 (P10-2b)**: Discovery 탭 UI — DiscoveryStore + `POST /discovery/runs` (kick off) + SSE + candidates editable table + weights 슬라이더 recompute (LLM 0원) + promote → Targets
  - **Stream 1 ✅ (P10-1) — Targets CRUD**
    - `src/api/store.py::TargetStore` — SQLite-only CRUD (`db.connect()` 단발 컨텍스트). list/create/get/update/delete + aliases JSON 직렬화. lazy 싱글턴 `get_target_store()` (env-driven app_db 경로 재해석 위해 `reset_stores()` 가 캐시 무효화)
    - `src/api/schemas.py` — `TargetStage` Literal (planned/contacted/proposal_sent/meeting/won/lost) + `TARGET_STAGES` 튜플 + `TargetCreate` / `TargetUpdate` (모든 필드 optional, partial patch) / `TargetSummary` / `TargetListResponse`
    - `src/api/routes/targets.py` — 5 엔드포인트: `GET /targets` (newest first by id) / `POST /targets` (201) / `GET /targets/{id}` / `PATCH /targets/{id}` / `DELETE /targets/{id}` (204). 모듈 경유 `_store.get_target_store()` (DO NOT 룰 준수)
    - `src/api/app.py` — `targets_routes` 등록
    - **프론트**: `web/src/components/TargetStageBadge.tsx` (6 stage × 색상 매핑) + `web/src/lib/types.ts` 에 `Target`/`TargetStage`/`TARGET_STAGES`/`TargetCreateInput`/`TargetUpdateInput` 추가 + `web/src/lib/api.ts` 에 `listTargets`/`createTarget`/`getTarget`/`patchTarget`/`deleteTarget`
    - `web/src/app/targets/page.tsx` — 목록 + 인라인 추가 폼 (stub 대체). aliases 는 쉼표 구분 텍스트로 입출력. 행 클릭 → `/targets/[id]`
    - `web/src/app/targets/[id]/page.tsx` — 편집 폼 + 삭제 (confirm prompt). PATCH 후 권위 있는 응답으로 폼 재시드
    - **테스트**: `tests/test_api_targets.py` 13건 — 201 생성 / blank name 422 / bad stage 422 / list newest-first / 404 / aliases roundtrip / partial PATCH / 404 PATCH / bad stage PATCH / DELETE 204 / 404 DELETE / aliases 빈 리스트 default. **311 → 324 passed all green**
    - **DO NOT 룰**: 라우트가 `from src.api import store as _store` 로만 접근 → 테스트가 `reset_stores()` 로 싱글턴을 비우면 새 env (`API_APP_DB=tmp_path`) 로 재초기화됨
  - **Phase 10 완료 — 다음 단계**: P1-1 (제안서 톤 조정) 또는 backlog 18 (Nemotron 검토) 또는 backlog 19 (패키지/배포). 추가 discover 실행 1~2회 (다른 RAG namespace 또는 ko 언어) 로 결과 일반화 검증

## 다음 MVP 범위 (Phase 10 이후)
- Phase 10 PR 시리즈 진행 (P10-1 ~ P10-8)
- backlog 항목 18 — NVIDIA Nemotron 활용 검토 (4 sub-track: Exaone 대체 / Sonnet 대체 / synthetic data / multi-model 분업) — 별도 branch 실험
- backlog P1-1 — 제안서 톤 조정 + 민감 가드 (3 톤 프리셋 + self-critique review_node) — Phase 10 Settings 탭에 자리 마련 후 구현
- 추가 discover 실행 1~2회 (다른 RAG 또는 ko 언어) 로 결과 일반화 확인

---

---

*장기 계획·향후 아이디어·스코프 밖 과제는 [docs/backlog.md](backlog.md) 를 참고하세요.*
