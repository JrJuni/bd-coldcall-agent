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

### 5. Claude Agent (`src/llm/claude_client.py`)
- `model="claude-sonnet-4-6"`, Anthropic SDK
- **Prompt caching**: tech chunks 를 `cache_control: {type: "ephemeral"}` 로 전달 → 여러 타겟사 실행 시 동일 컨텍스트 캐시 히트
- **Tag tier (입력 토큰 ~35% 절감)**: high-value 7개(earnings, m_and_a, partnership, funding, regulatory, product_launch, tech_launch) 는 `translated_body` 전체, low-value 2개(leadership, other) 는 snippet 만
- `synthesize_proposal_points(articles, tech_chunks, lang)` → pydantic 검증된 포인트 리스트
- `draft_proposal(points, articles, lang)` → Markdown + source 각주

### 6. LangGraph (`src/graph/`)
- `AgentState` TypedDict: `company, industry, lang, articles, tech_chunks, proposal_points, proposal_md, errors`
- 노드: `search_node → fetch_bodies_node → preprocess_node → retrieve_node → synthesize_node → draft_node`
- 단계별 실패 시 1회 재시도 엣지
- 중간 산출물을 `outputs/{company}_{date}/intermediate/` 에 저장 — `articles_after_preprocess.json` 에서 번역·태그·dedup 결과 검증 가능

---

## 설정 흐름
- `.env` 로드 → `pydantic-settings` 로 타입 검증된 `Settings` 객체 생성
- `Settings` 는 전 모듈에서 공유 (의존성 주입)
- 환경변수가 이미 설정되어 있으면 `.env` 값보다 우선

## 데이터 영속성
- 벡터스토어: `data/vectorstore/` (ChromaDB persistent)
- 원본 문서: `data/company_docs/` (로컬) + Notion (원격 페이지 ID 관리)
- 결과물: `outputs/{company}_{YYYYMMDD}.md`
- 중간 산출물: `outputs/{company}_{date}/intermediate/` (원시 기사, 요약 JSON, 검색 결과)
- 로그: `logs/` (일자별 파일)
