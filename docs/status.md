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

## 다음 MVP 범위 (Phase 9 이후)
- backlog 항목 17 — 티어리스트 편집 웹 UI (candidates.yaml 입력 → table 편집 → 재export / targets.yaml 자동 추가)
- backlog P1-1 — 제안서 톤 조정 + 민감 가드 (3 톤 프리셋 + self-critique review_node)
- backlog P1-2 — drag-drop 웹 RAG 입출력
- 추가 discover 실행 1~2회 (다른 RAG 또는 ko 언어) 로 결과 일반화 확인

---

---

*장기 계획·향후 아이디어·스코프 밖 과제는 [docs/backlog.md](backlog.md) 를 참고하세요.*
