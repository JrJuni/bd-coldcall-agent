# Playbook

어려운 문제를 풀고 나서 **재사용 가능하다고 판단된 패턴** 을 기록하는 단일 원천.

- **`lesson-learned.md` 와의 관계**: lesson 은 "다시는 같은 실수 안 당하게" 의 축, playbook 은 "이 접근은 다른 상황에서도 통함" 의 축.
- **조회 트리거** — 에러·막힘에 부딪쳤을 때 **가장 먼저** 여기 키워드 인덱스부터 grep. 비슷한 문제 전에 풀었는지 확인 후 lesson / architecture / 코드 순으로 내려가기.
- **수록 기준**: (1) 실제 이 프로젝트에서 작동이 검증됐고, (2) 이 프로젝트 밖에서도 재사용 여지가 있는 것. 단발성 버그픽스는 대상 아님.
- **vs 메모리 `feedback_*.md`**: playbook 은 **프로젝트 코드·구조 관련** 패턴. 메모리 feedback 은 **사용자 협업 스타일·선호도**. 두 저장소는 구분.

---

## 키워드 인덱스

| 태그 | 제목 | 한 줄 요약 |
|------|------|-----------|
| `langgraph` `state-design` `post-mortem` `dag-pipeline` | [1. 스테이지별 전용 출력 키](#1-스테이지별-전용-출력-키로-post-mortem-보존) | 단일 키를 여러 노드가 덮어쓰지 말고 노드별 전용 키 + `latest_X(state)` 폴백 헬퍼 |
| `langgraph` `monkeypatch` `testing` `module-access` `false-green` | [2. 오케스트레이션 계층은 모듈 경유 import](#2-오케스트레이션-계층은-모듈-경유-import-로-테스트-가능성-확보) | `from X import Y` 대신 `from pkg import mod as _mod` + `_mod.Y` 런타임 속성 |
| `sse` `background-tasks` `polling` `event-log` `anyio` `concurrency` | [3. SSE 에 async queue 대신 폴링](#3-sse-에-async-queue-대신-append-only-event-log--폴링) | 이벤트 수 ≤ 수십 개이고 append-only 면 폴링이 coroutine-threadsafe 큐보다 단순 |
| `anthropic` `prompt-cache` `cost-optimization` `ephemeral` | [4. 캐시 경계는 고정 블록에만](#4-캐시-경계는-고정-블록에만-cache_control-ephemeral) | `cache_control: ephemeral` 은 **변동 없는** 블록(tech_docs) 에만. 변동 블록 섞이면 캐시 무효화 |
| `dual-model` `cost` `hallucination` `role-split` | [5. 로컬 모델 = 결정적 전처리, 클라우드 = 추론](#5-로컬-모델--결정적-전처리-클라우드--추론) | 7~8B 로컬은 번역·태깅·dedup 에만. BD/요약/합성은 큰 모델이 원문 받아 직접 추론 |
| `llm-input` `tag-tier` `token-budget` | [6. 태그 tier 로 body/snippet 분배](#6-태그-tier-로-body-vs-snippet-분배) | high-value tag → full body, low-value → snippet 만. 토큰 35%↓ without 정보 손실 |
| `incremental-indexing` `atomicity` `rag` `safety` | [7. embed-first 원자성](#7-embed-first-원자성으로-중간-실패-복구-가능) | chunk→embed 가 먼저 성공해야 store/manifest 건드림. 중간 실패 시 상태 불변 |
| `work-planning` `stream-split` `phase-design` `context-window` | [8. 큰 작업은 3~5 stream + TO-BE/DONE 체크박스](#8-큰-작업은-3--5-stream--to-bedone-체크박스) | 세션 단절·컨텍스트 압박 대응, 세션 간 재개 용이 |
| `windows` `stdout` `cp949` `framework-help` | [9. 선언적 CLI 프레임워크는 모듈 로드 시점에 stdio UTF-8](#9-선언적-cli-프레임워크는-모듈-로드-시점에-stdio-utf-8) | Typer/Rich 는 command body 전에 help 렌더 → 안쪽 reconfigure 늦음 |
| `multi-channel` `raw-data` `dedup` `rank-policy` `partial-success` | [10. 멀티 채널 raw collection 은 rank 기반 keep + partial-success](#10-멀티-채널-raw-collection-은-rank-기반-keep--partial-success) | 채널별 try/except + 채널 rank dedup. 한 채널 실패가 다른 채널을 죽이면 안 됨 |
| `static-tier` `human-in-the-loop` `runtime-deterministic` | [11. AI 초안 + 사람 검수 정적 티어 = 운영 안정성](#11-ai-초안--사람-검수-정적-티어--운영-안정성) | LLM 런타임 호출 대신 빌드타임 초안 → yaml 커밋. 결정성·비용 0·검수 가능 |
| `mvp-cut` `flat-schema` `human-review` `output-format` | [12. MVP 1-shot 산출은 flat 데이터 + grouped 리포트 페어](#12-mvp-1-shot-산출은-flat-데이터--grouped-리포트-페어) | 검증 없는 LLM 1회 산출이라도 flat yaml (편집·UI 친화) + 그룹 md (검수 친화) 두 형태로 동시 출력 |
| `llm-output-budget` `max-tokens` `step-isolation` `truncate-failure` | [13. LLM step 별 max_tokens 별도 setting](#13-llm-step-별-max_tokens-별도-setting) | 새 step 추가 시 input 비슷해도 output 분포 별도 추정. setting 키 신설이 retry 보다 안전 |

항목이 늘어나면 태그 알파벳순으로 재정렬. 항목 제거는 패턴이 무효화됐을 때만 (이 경우 원인도 기록).

---

## 1. 스테이지별 전용 출력 키로 post-mortem 보존

**태그**: `langgraph` `state-design` `post-mortem` `dag-pipeline`

**Problem**: LangGraph 파이프라인에서 단일 `articles` 키를 `search → fetch → preprocess` 가 차례로 덮어쓰는 구조. 중간 실패 시 state 만 봐서는 어느 단계 출력이 남았는지 구분 불가. 저장되는 파일 이름 `articles_after_preprocess.json` 이 상황에 따라 거짓말이 됨.

**Solution**: `src/graph/state.py::AgentState` 에 `searched_articles` / `fetched_articles` / `processed_articles` 3-key 분리. 각 노드는 **자기 출력만 추가**, 이전 키는 읽기 전용으로 consume. `persist_node` 는 `latest_articles(state)` 헬퍼 (processed > fetched > searched 폴백) 로 캐노니컬 출력 + 실패 경로에선 단계별 덤프 (`articles_searched.json`, `articles_fetched.json`) 도 쓴다.

**Why it works**: 상태가 append-only 가 되면 실패 지점에서도 이전 단계 전체 아티팩트를 관찰 가능. 파일 이름이 항상 "그 이름 그대로" 의 데이터를 담음.

**Reusable in**: LangGraph 뿐 아니라 어떤 DAG/pipeline 이든 후행 단계가 선행 단계 아티팩트를 관찰해야 post-mortem 이 성립하는 모든 상황. ETL, 배치 잡, ML 학습 파이프라인도 동일 원칙.

---

## 2. 오케스트레이션 계층은 모듈 경유 import 로 테스트 가능성 확보

**태그**: `langgraph` `monkeypatch` `testing` `module-access` `false-green`

**Problem**: `from src.api.runner import execute_run` 로 바인딩해놓고 테스트에서 `monkeypatch.setattr("src.api.runner.execute_run", fake)` 하면, 라우트 모듈은 import 시점에 고정된 원본 참조를 그대로 호출. 테스트가 "통과" 해도 실제 Exaone / Sonnet 이 호출됨 (false green, 네트워크·비용 누출).

**Solution**: orchestration 계층은 `from src.api import runner as _runner` + `_runner.execute_run(...)` 로 **런타임 속성 조회**. 테스트가 `_runner` 모듈의 `execute_run` 속성을 패치하면 라우트도 새 참조를 본다. `src/graph/pipeline.py` 가 `from src.graph import nodes as _nodes` 사용하는 것과 같은 패턴. CLAUDE.md `## DO NOT` 섹션에 규칙 승격.

**Why it works**: Python 에서 `from X import Y` 는 현 모듈 네임스페이스에 Y 를 새 바인딩으로 고정. 원본 모듈의 Y 속성을 바꿔도 이미 만들어진 바인딩은 안 따라감. 모듈 객체 참조를 들고 있으면 속성은 dict lookup 이라 매번 새로 본다.

**Reusable in**: 테스트에서 외부 호출·LLM·DB 클라이언트를 monkeypatch 하는 **모든 Python 프로젝트**. graph/pipeline/route/adapter 처럼 "얇은 orchestration 레이어" 는 기본값으로 이 규칙 적용. 상수·타입·예외 클래스 import 는 예외.

---

## 3. SSE 에 async queue 대신 append-only event log + 폴링

**태그**: `sse` `background-tasks` `polling` `event-log` `anyio` `concurrency`

**Problem**: FastAPI `BackgroundTasks` (anyio worker thread) 에서 돌리는 pipeline 의 진행 상태를 SSE (event loop) 로 전달할 때, 초안으로는 `asyncio.Queue` + `asyncio.run_coroutine_threadsafe(queue.put, loop)` 고려. 스레드 경계·caller 가 loop 를 알아야 함·백프레셔·queue 메모리 바운드 등 복잡도 상승.

**Solution**: `RunRecord.events: list[RunEvent]` (seq/kind/ts/payload) + `threading.Lock`. SSE 쪽은 `last_seq` 커서로 150 ms 마다 `snapshot_events(since_seq=last_seq)` 호출, 증분만 yield, 종결 상태 (`completed`/`failed`) 감지 후 stream close. `src/api/store.py` + `src/api/routes/runs.py::run_events`.

**Why it works**: 이벤트 수가 **작고** (≤ 수십 개 per run) **append-only** 일 때 폴링이 큐보다 단순. `threading.Lock` 은 리스트 append/slice 에만 필요, SSE 와 worker 가 서로의 스케줄을 신경 쓸 일 없음. 150 ms 폴링의 오버헤드는 이벤트 수가 작으면 무시 가능.

**Reusable in**: 이벤트가 드물고 끝이 있는 스트림 (빌드 잡 / 파이프라인 진행 / 긴 계산 상태 보고). 이벤트가 초당 수백건 이상이거나 장기 구독 (pub/sub) 이면 Redis Streams / Celery events 고려.

---

## 4. 캐시 경계는 고정 블록에만 (`cache_control: ephemeral`)

**태그**: `anthropic` `prompt-cache` `cost-optimization` `ephemeral`

**Problem**: Anthropic 프롬프트 캐시는 "앞에서부터 정확히 같은 블록" 에만 히트. 캐시 블록 뒤에 변동 콘텐츠를 덧붙여도 캐시는 유효하지만, 캐시하려는 블록 **안에** 변동 요소가 섞이면 매 호출마다 무효화되어 cache_write 비용만 내고 혜택 없음.

**Solution**: `src/llm/claude_client.py::chat_cached` 에서 user content 를 3블록으로 나누고 **첫 블록 (tech_docs) 에만** `cache_control: ephemeral` 부착. articles + task 는 uncached 로 뒤에 붙임. `src/llm/synthesize.py` 는 정확히 이 구조로 프롬프트 조립.

**Why it works**: tech_docs (RAG 청크) 는 같은 회사 타겟을 연속으로 돌리면 완전히 동일 → 캐시 100% 히트. articles 는 타겟마다 달라서 cached 영역 밖에 둬야 오염 없음. cache_read 는 input 토큰 단가의 10%, cache_write 는 125% — 재사용 2회 이상이면 손익분기.

**Reusable in**: Anthropic Sonnet / Opus 사용하는 모든 LLM 앱. 특히 "대용량 고정 컨텍스트 (문서·프롬프트·tools) + 소용량 변동 쿼리" 구조의 RAG 와 챗봇에.

---

## 5. 로컬 모델 = 결정적 전처리, 클라우드 = 추론

**태그**: `dual-model` `cost` `hallucination` `role-split`

**Problem**: 7~8B 클래스 로컬 LLM 이 "뉴스 요약 → BD 시그널 추출" 같은 추론 작업을 하면 hallucination + 맥락 손실 발생. 로컬이 만든 요약 JSON 을 다시 Sonnet 에 넘기면 "더블 압축" 으로 원문 뉘앙스 소실.

**Solution**: 로컬 Exaone 7.8B 4bit 은 **결정적 전처리만** — 번역 (lang != target_lang 일 때만), 9-tag ENUM 분류, bge-m3 cosine dedup. 태그 / 번역은 화이트리스트 + passthrough fallback 으로 항상 valid 출력 보장. Sonnet 은 `translated_body` 원문 그대로 받아 모든 BD 추론을 한 곳에서 수행. `src/llm/{translate,tag}.py` + `src/llm/synthesize.py` 경계.

**Why it works**: 작은 모델은 "선택·분류·변환" 에 강하지만 "판단·종합" 에 약함. 두 단계를 섞으면 약점이 뒤에 전파됨. 역할 분담으로 작은 모델 강점만 활용 + 큰 모델이 손실 없는 입력 받음 → 비용 절감과 품질 유지.

**Reusable in**: RAG 외 LLM 앱에서 "오픈소스 로컬 + 클라우드 API" 하이브리드 설계 시 일반 원칙. 번역·분류·추출은 로컬, 요약·합성·추론은 클라우드.

---

## 6. 태그 tier 로 body vs snippet 분배

**태그**: `llm-input` `tag-tier` `token-budget`

**Problem**: 수집한 기사 20건을 전부 full body 로 Sonnet 에 넣으면 입력 토큰이 수만 단위. 비용도 비용이지만 context window 경쟁으로 tech_docs 와 task 지시가 희석됨.

**Solution**: `src/llm/tag_tier.py::HIGH_VALUE_TAGS` frozenset 7종 (`earnings`, `m_and_a`, `partnership`, `funding`, `regulatory`, `product_launch`, `tech_launch`) 는 `translated_body` 전체, low-value 2종 (`leadership`, `other`) 은 `snippet` 만. `select_body_or_snippet()` 유틸로 합성 직전 스위칭.

**Why it works**: BD 관점에서 "거래 가능성 높은 시그널" 은 7개 카테고리에 집중. leadership / other 는 배경 정보여서 제목+스니펫만으로 충분. 측정: 입력 토큰 ~35% 절감, proposal 품질 차이 없음 (Phase 8 Tesla / Deloitte 실측).

**Reusable in**: LLM 에 "이 문서들 보고 뭔가 해" 주는 모든 상황. 문서마다 "얼마나 깊이 읽힐 가치가 있는지" 분류한 뒤 tier 별로 다른 크기로 인풋에 담기. 검색 RAG 외에 이메일 요약, 뉴스 브리프, CS 응대 등.

---

## 7. embed-first 원자성으로 중간 실패 복구 가능

**태그**: `incremental-indexing` `atomicity` `rag` `safety`

**Problem**: RAG 인덱서가 (a) chunk → (b) embed → (c) store upsert → (d) manifest 업데이트 4단계를 순서대로 밟는데, 중간 (예: embed 호출 중 OOM) 에서 실패하면 store 에는 일부 들어가 있고 manifest 는 옛날 상태 — 다음 실행이 "같은 hash 라 skip" 하면서 누락 발생.

**Solution**: `src/rag/indexer.py::_process_document` 에서 **embed 가 먼저 전체 성공해야** `delete_document → upsert_chunks → manifest[doc_id] 갱신` 으로 진행. embed 실패 시 store / manifest 모두 **불변** + error 카운터만 증가. manifest 는 tmp 파일 → `os.replace` 로 atomic swap.

**Why it works**: 가장 위험한 작업 (embed: 네트워크·OOM·CUDA 등 실패 다발) 을 맨 앞에 배치. 이후 store/manifest 는 모두 빠른 로컬 I/O 라 원자성 보장 쉬움. 실패해도 state 가 "실행 전" 으로 유지 → 다음 실행이 자연스럽게 복구.

**Reusable in**: 어떤 증분 인덱싱·배치 잡이든 "외부 호출 → 로컬 저장" 순서로 재배치해서 외부 실패 시 로컬 상태 불변 보장. 데이터 파이프라인 일반 원칙 ("prepare before commit").

---

## 8. 큰 작업은 3 ~ 5 stream + TO-BE/DONE 체크박스

**태그**: `work-planning` `stream-split` `phase-design` `context-window`

**Problem**: 한 Phase 전체를 단일 세션에서 밀면 후반부에 컨텍스트 압박 + 초기 결정이 흐려짐. 세션이 끊기거나 `/compact` 되면 "어디까지 했나" 찾기 어려움.

**Solution**: Phase 를 **레이어 기준 3~5 work stream** 으로 쪼개고, 각 스트림마다 **TO-BE / DONE 체크박스** 를 플랜 파일 (`~/.claude/plans/*.md`) 에 유지. 스트림 경계는 `/compact` 지점과 정렬 (세션당 2회 정도). 예: Phase 3 RAG = Stream 0 (설정) / 1 (스키마·청킹) / 2 (저장소·검색) / 3 (커넥터) / 4 (인덱서·CLI).

**Why it works**: 스트림은 "레이어 완결성 + 테스트 가능 단위" 라 순서 독립. 체크박스는 다음 세션이 플랜 파일 + status.md 만 읽고 정확히 재개 가능. 각 스트림 끝에 테스트 녹생 확인 → 다음 스트림이 안전하게 빌드 위에 쌓임.

**Reusable in**: 큰 구현·마이그레이션·리팩터링 전반. LLM 에이전트 협업뿐 아니라 사람 개발자도 "나중에 이어 붙이기" 가 있는 작업이면 동일.

---

## 9. 선언적 CLI 프레임워크는 모듈 로드 시점에 stdio UTF-8

**태그**: `windows` `stdout` `cp949` `framework-help`

**Problem**: Windows cp949 콘솔 + Typer/Rich 조합에서 커맨드 함수 안에 `sys.stdout.reconfigure(encoding="utf-8")` 두면, `--help` 는 커맨드 body 실행 **전에** Rich 가 help text 렌더링 → 이미 cp949 로 em-dash·한글 인코딩 실패.

**Solution**: `main.py` **최상단 (import 전후)** 에 `for _stream in (sys.stdout, sys.stderr): _stream.reconfigure(encoding="utf-8")` 블록 배치. 모듈 로드 시점에 이미 UTF-8 로 강제된 상태에서 typer/rich 가 시작.

**Why it works**: argparse 같은 절차적 CLI 는 커맨드 body 에 진입해야 help 를 돌리지만, typer/rich 같은 선언적 프레임워크는 import 시점에 데코레이터로 help 생성기를 등록하고 즉시 렌더링 가능. 인코딩 강제는 그보다 먼저 와야 함.

**Reusable in**: Typer, Click + Rich, Hydra 같은 선언적 CLI 프레임워크를 Windows 환경에서 쓸 때. 일반적으로 "프레임워크 import 전에 stdio 설정 완료" 원칙.

---

## 10. 멀티 채널 raw collection 은 rank 기반 keep + partial-success

**태그**: `multi-channel` `raw-data` `dedup` `rank-policy` `partial-success`

**Problem**: 동일한 raw signal (뉴스/문서/검색결과) 을 여러 의미축에서 모아야 할 때 — 단일 채널은 다양성 부족, 다중 채널은 (a) 채널 간 중복, (b) 한 채널 실패가 전체 실패로 번질 위험, (c) 어느 채널이 우선인지 불명확 의 세 문제 동시 발생.

**Solution**:
1. **Channel registry** 패턴 — `src/search/channels/__init__.py::run_all_channels` 가 채널 함수들을 dict 로 보유, `ThreadPoolExecutor` fan-out. 채널 추가/제거 = dict 한 줄.
2. **Per-channel try/except** — 각 채널 결과를 `(articles, meta)` 튜플로 받되, 예외는 `channel_errors` 에 기록만 하고 빈 리스트 반환. 노드는 모든 채널이 실패해야만 fail.
3. **Rank-based dedup** — `CHANNEL_RANK = {"target": 0, "related": 1, "competitor": 2}`. URL dedup 시 낮은 rank 가 keep. 의미적 dedup (`_pick_representative`) 의 sort key 에도 channel rank 추가.
4. **First-class channel field** — `Article.channel: Literal[...]` 을 dataclass 필드로 (metadata dict 아님). 직렬화 호환성 위해 default 값.

**Why it works**: rank 가 비교 가능한 정수면 dedup keep 정책이 단순해지고, 채널 추가 시 rank 한 칸만 끼우면 됨. partial-success 는 "한 채널의 일시 장애 (Brave 5xx) 가 전체 BD 실행을 죽이지 않는다" 는 운영 가치 직결.

**Reusable in**: 검색 외에도 멀티 소스 RAG (ChromaDB + Notion + Slack + GitHub), 멀티 모니터링 (Datadog + Sentry + CloudWatch), 멀티 모델 (앙상블) 등 — 여러 소스를 하나의 출력 stream 으로 머지하는 모든 곳. CV 발굴 피보팅 (backlog 항목 15) 도 같은 패턴 그대로 사용.

---

## 11. AI 초안 + 사람 검수 정적 티어 = 운영 안정성

**태그**: `static-tier` `human-in-the-loop` `runtime-deterministic`

**Problem**: 검색 의도·필터·프롬프트 같은 "도메인 지식 데이터" 를 두 극단 중 하나로 갈 때 — 옵션 (a) 런타임 LLM 동적 생성 = RAG 변화에 자동 적응하지만 비결정·비용·디버깅 어려움 / 옵션 (b) 하드코딩 정적 리스트 = 결정·무료·검수 가능하지만 사람이 처음부터 만들어야 함 → 빈 채로 시작 stuck.

**Solution**: **빌드타임 LLM 초안 + 런타임 정적 yaml** 의 하이브리드.
- 일회성 도구 (`scripts/draft_intent_tiers.py`) 가 RAG 인덱스 + 사용자 입력 product 한줄 요약을 받아 Sonnet 1회 호출 → yaml 형식 초안 출력
- 사람이 검수·다듬어 `config/intent_tiers.yaml` 로 커밋
- 런타임은 yaml 만 읽음 — LLM 호출 없음, 결정적, 캐시 무관

**Why it works**: 첫 사용자 경험 = 빈 yaml 이 아니라 "초안 받고 다듬는다" 의 출발점. 운영 단계에선 yaml 이 git-tracked → 변경 이력 추적 가능, A/B 비교 용이, 비용 0. 콘텐츠가 늘면 도구 다시 돌려서 새 초안 받기.

**Reusable in**: 프롬프트 라이브러리, 분류 규칙, 검색 의도 리스트, few-shot 예시, 평가 루브릭 등 — "LLM 이 잘 만들지만 사람이 보정해야 하는 텍스트 데이터" 일반. 동적 vs 정적 의 가성비를 사람-in-the-loop 로 합쳐줌.

---

## 12. MVP 1-shot 산출은 flat 데이터 + grouped 리포트 페어

**태그**: `mvp-cut` `flat-schema` `human-review` `output-format`

**Problem**: 검증 없는 LLM 1회 산출 (Phase 9 의 reverse matching MVP — Sonnet 1회로 25 후보 + 5 산업) 에서 두 가지 상충하는 요구가 동시에 발생: (a) 사람이 빠르게 훑고 쳐낼 수 있는 그룹별 보고서 / (b) 후속 자동화 (편집 UI / SQLite import / `targets.yaml` 자동 추가) 를 위한 flat 머신 친화 포맷. 한 형식으로 둘 다 만족 못 함 — flat 만 있으면 사람이 산업별 묶음을 다시 그루핑하느라 검수 5분이 30분, 그룹 md 만 있으면 인-place 편집·테이블 import 가 어려움.

**Solution**: 같은 LLM 응답을 **두 형태로 직렬화**해 페어로 저장.
- `outputs/discovery_<date>/candidates.yaml` — flat list (`name, industry, tier, rationale`) + 메타 (`generated_at, seed{}, industry_meta, usage`). 향후 SQLite import → 웹 편집 UI 입력 포맷.
- `outputs/discovery_<date>/report.md` — 산업별 그루핑, 시드 메타 헤더, Tier 정렬 (S→A→B→C) Markdown table, footnote 토큰 요약. 사람이 5분 안에 검수.
- 둘 다 같은 `DiscoveryResult` 인스턴스에서 파생 — `_candidates_to_yaml()` / `_render_report()` 두 순수 함수가 같은 dataclass 를 다른 view 로 펼침.

**Why it works**: flat 의 단점 (사람 가독성) 은 grouped md 가 보완하고, grouped 의 단점 (편집 UI 입력 어려움) 은 flat yaml 이 보완. 추가 LLM 호출 0회 — 같은 응답을 다른 view 로 두 번 직렬화하는 비용은 사실상 무료. "MVP 컷이라 검증 안 함" 이라는 결정이 산출물 품질을 떨어뜨리지 않게 만드는 보호막.

**Reusable in**: LLM 1-shot 분석 (이력서 → 적합 기업 발굴 [backlog 15], 영업 반응 → 클러스터 [backlog 16], 제품 → 경쟁 분석 등) 어디서든. 사람 검수가 필수인 산출물은 항상 (flat data, grouped report) 페어로 출력하는 게 후속 단계 (자동화·웹 UI·재import) 의 진입 비용을 낮춤.

---

## 13. LLM step 별 max_tokens 별도 setting

**태그**: `llm-output-budget` `max-tokens` `step-isolation` `truncate-failure`

**Problem**: 새 LLM step 의 input 패턴이 기존 step 과 비슷하면 (둘 다 RAG 시드 + 시스템 프롬프트) `max_tokens` setting 도 그대로 재사용하고 싶어짐. 그런데 **output 분포는 step 마다 다름** — synthesize 의 5 ProposalPoint (~1.5K out) 와 discover 의 5 산업 + 25 후보 rationale (~2.5K out) 와 draft 의 4-section markdown (~3K out) 은 입력이 비슷해도 출력 사이즈가 ×2 수준 차이. 한 setting 으로 묶으면 output 작은 step 은 cost OK 지만 큰 step 에선 truncate, 반대로 큰 쪽에 맞추면 작은 쪽이 idle headroom.

더 위험한 것: **truncate 된 응답은 retry 로 못 구함**. 동일 max_tokens 로 재시도해도 같은 자리에서 잘림. JSON 이 닫히지 않은 raw 출력은 parser 가 항상 실패 → ValueError 만 반복.

**Solution**: 새 step 추가 시 **output 별도 추정 → setting 키 신설**.
- 추정 공식: `n_items × (avg item tokens + structural overhead) × 1.3 safety`
- Phase 9 예: `25 × (~80 rationale + ~20 JSON 키) × 1.3 ≈ 3300 → 4000 round up`
- 결과: `claude_max_tokens_synthesize=2000` / `claude_max_tokens_draft=4000` / `claude_max_tokens_discover=4000` 로 step 별 분리 (`config/settings.yaml` + `LLMSettings`)
- 첫 실제 실행 시 `output_tokens` 측정 → setting 1.5× headroom 인지 확인 → 부족하면 재조정

**Why it works**: setting 키가 step 과 1:1 매핑되면 (a) 한 step 의 output 폭증이 다른 step 에 영향 없음 (b) git diff 로 어느 step 이 비싸지는지 즉시 보임 (c) retry 로 가짠 못 구하는 truncate 실패를 사전 차단. retry 는 모델 변동성 (JSON 형식 어김 / temperature) 만 흡수하지 max_tokens 같은 fixed budget 문제는 못 풉.

**Reusable in**: 새 LLM step 을 추가하는 모든 프로젝트. 특히 같은 모델·같은 입력 패턴에 묶여 있을 때 무심코 setting 재사용하기 쉬움. checklist 항목으로 "이 step 의 expected output_tokens 는?" 을 plan 단계에 넣는 게 좋음. 같은 원칙은 timeout, batch_size, top_k 등 step 별 budget 키 모두에 일반화.
