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
