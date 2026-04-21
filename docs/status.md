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

## 진행 중

- (Phase 4 준비) Claude Sonnet 4.6 합성 노드. 현재 RAG 인덱스·retriever API 준비 완료.

## 다음 MVP 범위 (Phase 4 ~ 9)
- **Phase 4** — Claude Sonnet 4.6 에이전트 (제안 포인트 종합 + 제안서 초안, prompt caching)
- **Phase 5** — LangGraph StateGraph 오케스트레이션
- **Phase 6** — CLI 통합 (`main.py ingest`, `main.py run --company ... --lang en|ko`)
- **Phase 7** — Web UI (FastAPI + Next.js — 타겟 CRUD, 실행 + SSE 진행 스트림, 결과 뷰어, RAG 관리)
- **Phase 8** — 평가·회고 (타겟사 3~5건 스모크 테스트, 결과는 `lesson-learned.md` 에 누적)
- **Phase 9** — 문서 최종화 (status / architecture / security-audit 갱신)

---

## 장기 과제 (MVP 범위 외)

### 무료 웹 스크래퍼
Brave Search 구독이 없는 사용자를 위한 대체 소스. `SearchProvider` 인터페이스 뒤에 플러그인으로 추가.
- Google News RSS (en/ko)
- 네이버 뉴스 검색 (BeautifulSoup 정적 파싱)
- Playwright 기반 동적 렌더링 (JS 필요 사이트)
- robots.txt / rate limit 정책 준수

### CRM / 팔로업 관리
콜 이후 단계 지원.
- 콜 로그(수기 메모 또는 음성 전사) → 요약
- 다음 액션 추천 (재시도 시점, 제공 자료, 후속 이메일 초안)
- 외부 CRM 연동 (Salesforce, HubSpot 등)

### 멀티 에이전트 협업
현재 단일 파이프라인을 research / writing / review 역할 분리로 개선. LangGraph 서브그래프 + 상호 리뷰 루프.

### 모델 스왑 실험
Exaone 요약 품질이 충분치 않으면 Qwen / Gemma / Llama 계열로 벤치마크 → 교체.
