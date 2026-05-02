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
| `llm-judgment-decompose` `weighted-scoring` `external-yaml` `reproducibility` | [14. LLM 판단을 점수+규칙으로 분해](#14-llm-판단을-점수규칙으로-분해) | LLM hallucination 을 prompt 정교화로 누르기 전, 결정 가능한 수치를 코드로 빼낼 수 있는지 먼저 검토. weight 외부 yaml 화로 재현·재사용·재계산 0원 |
| `non-dev-persona` `ui-design` `abstraction-leak` `internal-vs-external` | [15. 비개발자 UI 는 백엔드 추상화 노출 금지](#15-비개발자-ui-는-백엔드-추상화-노출-금지) | namespace / chunks / manifest 같은 내부 개념은 화면에서 빼라. 사용자가 본다고 의사결정 못 함 |
| `os-launch` `windows` `headless` `testability-wrapper` | [16. OS 파일 매니저 호출은 래퍼로 분리](#16-os-파일-매니저-호출은-래퍼로-분리) | Windows 에선 subprocess.Popen 대신 os.startfile. 단일 함수로 묶어서 테스트 monkeypatch 가능하게 |
| `manifest` `staleness` `derived-aggregate` `rag` `incremental` | [17. per-item 타임스탬프 → 폴더 단위 stale 검출](#17-per-item-타임스탬프--폴더-단위-stale-검출) | manifest.indexed_at + filesystem mtime 비교로 폴더 needs_reindex 파생. 메타 추가 없이 사용자 신호 추가 |
| `multi-tenant` `path-resolution` `legacy-preserve` `asymmetric-default` | [18. multi-tenant 도입 시 default tier 만 레거시 layout 보존](#18-multi-tenant-도입-시-default-tier-만-레거시-layout-보존) | 새 prefix 를 추가할 때 default 만 "no suffix" 처리하면 기존 데이터 0건 이동으로 호환 |
| `display-toggle` `optional-cleanup` `non-destructive-default` `recover-by-readd` | [19. display-only 등록 + opt-in cleanup](#19-display-only-등록--opt-in-cleanup) | 등록/제거는 DB row 만 건드리고, 부수 artifact 정리는 명시 옵션. 사용자 실수 복구 = 같은 이름 재등록 |

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

---

## 14. LLM 판단을 점수+규칙으로 분해

**태그**: `llm-judgment-decompose` `weighted-scoring` `external-yaml` `reproducibility`

**Problem**: LLM 결과 품질이 부족할 때 첫 본능은 prompt 정교화. 하지만 이게 비결정·비검증 — 같은 입력에도 결과 변동, 왜 그 판단인지 분해 안 되고, 다른 도메인 (다른 제품·산업) 으로 재사용 어려움. Phase 9 첫 산출 (`outputs/discovery_20260428` v1) 이 정확히 이 함정 — Sonnet 이 25 회사를 직접 S/A/B/C 로 분류, 결과는 mega-cap 편향 + 0 C tier + 같은 회사 재실행 시 결과 변동.

**Solution**: LLM 한테 high-level 판단 (tier / 추천 / 분류) 시키기 전에 분해 가능한지 자문:
1. 이 판단을 N개 차원의 0-10 점수로 분해 가능한가?
2. 각 차원에 weight + threshold 적용으로 같은 결과 재현 가능한가?
3. weight·threshold 를 외부 yaml 로 분리하면 다른 도메인 재사용 가능한가?

분해 가능하면 LLM 은 점수만 매기고, final_score 와 최종 판단은 코드가 weighted sum + rule 로 결정. weight·threshold 는 yaml 외부화.

Phase 9.1 적용 사례:
- LLM: scores{6 dim 0-10} + rationale 만 출력 (tier 출력 silently dropped)
- 코드: `final_score = sum(score[k] * weight[k])` + `decide_tier(final_score, rules)` (epsilon 1e-6)
- yaml: `config/weights.yaml` (default + product override + auto-normalize) + `config/tier_rules.yaml` (S/A/B/C threshold)
- 결과: Snowflake A → B 강등 (LLM 이 displacement_ease 점수 낮게 매겼고 코드가 그걸 반영), mid-cap (Stripe / Adyen / 토스) S 진입

**Why it works**: 같은 LLM 응답 (`scores`) 으로 weight 만 바꿔 재계산 비용 = $0. 다른 제품 (Snowflake / Salesforce 등) 도 `products.<name>` override 추가만으로 재사용. "왜 S?" 질문에 차원별 점수 + weight 합산식 보여주면 답 끝. LLM 호출 단계가 격리돼서 hallucination 가 결정 단계로 누설되지 않음.

**Reusable in**: tier 분류, 추천 엔진, 후보 우선순위, 평가·rubric 기반 채점 (LLM-as-judge backlog P2-6), 어떤 multi-criteria decision 도. 패턴 적용 가능 신호: (a) 결정이 여러 비교 가능한 차원의 합으로 표현 가능, (b) 도메인·고객별 weight 가 다를 가능성, (c) 같은 입력으로 재실행 시 결정 일관성이 가치 있음.

---

## 15. 비개발자 UI 는 백엔드 추상화 노출 금지

**태그**: `non-dev-persona` `ui-design` `abstraction-leak` `internal-vs-external`

**Problem**: P10-3 의 RAG 탭이 namespace 드롭다운 / "X chunks" / manifest 경로 / "Indexed/Pending" / Danger zone 등 백엔드 개념을 그대로 UI 에 노출. 개발자는 의미 알지만, 비개발자에게는 "이 숫자가 무슨 의미? 내가 뭘 해야 하지?" 만 남음. 페르소나 (OS 탐색기를 못 여는 비개발 BD) 와 UI 추상화가 어긋남.

**Solution**: UI 가 보여주는 모든 라벨·필드·경고 문구를 다음 두 질문으로 필터:
1. **"이 정보를 보고 사용자가 의사결정을 할 수 있는가?"** — yes 만 남김. chunk count / manifest 경로 / cache token 같은 건 사용자가 봐도 다음 액션이 안 정해짐 → 제거
2. **"이 단어가 우리 시스템 내부에서만 의미를 가지는가?"** — yes 면 일반어로 환산. namespace → 폴더, indexed → Ready, "Re-index" 는 일상어라 OK 로 판단

P10-9 (RAG 탭 filesystem-mirror UX) 적용 사례:
- 단어 추방: namespace, chunks, manifest, "indexed" → 폴더, files, (제거), Ready
- 컬럼 제거: Chunks (전체) / SummaryPane footer 의 token usage / ExplorerPane 의 manifest 경로
- 라벨 환산: "Indexed/Pending" → "Ready/Pending"
- 기능 제거: namespace 영구 삭제 모달 (사용자가 실수로 ChromaDB 통째 날릴 위험 + 실제 삭제 빈도 0 에 가까움) — 정 필요하면 OS 탐색기 (이미 버튼 있음)
- 문구 통일: "+ 새 namespace" / "+ 새 폴더" 분기 → 항상 "+ 새 폴더". 백엔드는 namespace 생성을 호출하지만 사용자는 모름

**Why it works**: 사용자가 보는 단어들이 사용자의 일상 어휘와 일치 → 학습 곡선 ~0. 노출되지 않은 추상화는 사용자가 굳이 이해할 필요가 없음 (격리). UI 단순화는 가짜 단순화가 아니라 "없어도 의사결정에 영향 없는 정보를 진짜로 제거" 하는 거라서 정보 손실 없음.

**Reusable in**: 데이터·AI 도구의 비개발자 노출 모든 UI. 점검 트리거 — 백엔드에 새 개념 (cache layer, queue, shard 등) 이 추가될 때마다 "이게 UI 에 새 단어로 등장해도 되나?" 자문. 기본 답은 NO. 같은 원칙은 admin/dev console 과 user-facing UI 분리에도 적용 (admin 은 추상화 노출 OK).

---

## 16. OS 파일 매니저 호출은 래퍼로 분리

**태그**: `os-launch` `windows` `headless` `testability-wrapper`

**Problem**: 로컬 GUI 를 띄우는 백엔드 endpoint (예: "이 폴더를 OS 탐색기에서 열기") 구현 시 두 가지 함정. (1) Windows 에서 `subprocess.Popen(["explorer", path])` 가 콘솔 미부착 서버 (uvicorn 백그라운드) 컨텍스트에서 silent fail — stderr 는 유실되고 endpoint 는 200 반환하는데 정작 창이 안 뜸. (2) OS 별 분기 (Windows / macOS / Linux) 코드가 핸들러 안에 박혀 있으면 테스트가 실제 OS 호출을 트리거 → 테스트 실행 시 진짜 창이 떠버리거나 CI 에서 실패.

**Solution**: 단일 래퍼 함수로 OS 분기 + 안전한 호출 + 실패 boolean 반환:

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

Endpoint 는 `opened = _launch_file_manager(abs_path)` 결과만 응답에 실어 UI 가 명확한 메시지 표시. 테스트는 `monkeypatch.setattr(_routes, "_launch_file_manager", lambda p: True)` 로 함수 자체를 fake 치환 — `subprocess.Popen` patch 는 OS 별 분기 다 따라가야 해서 깨지기 쉬움.

P10-9 적용:
- Windows `os.startfile` (canonical) 채택. `Popen(["explorer", ...])` 는 detach·콘솔 미부착 시 silent fail 검증됨
- 테스트 5건이 `_launch_file_manager` monkeypatch 로 실제 창 안 띄우면서도 호출 인자·반환값 검증

**Why it works**: 래퍼가 OS 분기 + 예외 처리 + 결과 boolean 의 세 가지를 한 곳에 모음. endpoint 는 비즈니스 로직 (path 검증·resolve) 만 하고 OS 호출은 단일 진입점. 테스트는 한 줄 patch 로 부수효과 차단.

**Reusable in**: 데스크톱 앱 백엔드 (FastAPI on localhost) 가 OS 기능 (탐색기 열기, 기본 브라우저로 URL, 시스템 알림 등) 을 호출하는 모든 곳. 같은 패턴은 클립보드 (`pyperclip`), 토스트 (`win10toast`/`pync`/`notify-send`) 등에도 적용. 핵심: "OS 분기 + 부수효과 + 테스트 가능성" 세 요건이 충돌할 때 단일 함수로 묶어라.

---

## 17. per-item 타임스탬프 → 폴더 단위 stale 검출

**태그**: `manifest` `staleness` `derived-aggregate` `rag` `incremental`

**Problem**: 증분 인덱싱 (incremental indexing) 시스템에서 사용자가 "이 폴더에 새로운 파일이 들어왔는데 아직 인덱싱 안 된 게 있나?" 를 알아야 함 (P10-9.1 RAG 탭 #4(a)). 단순한 접근은 폴더에 별도 메타 (`folder_indexed_at`) 추가 — 그러나 manifest 스키마 확장은 마이그레이션 + 기존 코드 (indexer / retriever / connectors) 다 건드림. 또 폴더는 사용자가 자유롭게 만들고 옮기므로 폴더 단위 메타는 동기화 부담이 큼.

**Solution**: per-document 타임스탬프 (`manifest.documents[doc_id].indexed_at`) 를 source of truth 로 두고, 폴더 단위 staleness 는 **파생 집계** 로 계산:

```python
def _folder_needs_reindex(folder_abs, ns_root, indexed_lookup) -> bool:
    """True if any descendant file is missing from manifest OR mtime > indexed_at."""
    for child in folder_abs.rglob("*"):
        if not child.is_file() or child.suffix not in _ALLOWED_EXTENSIONS:
            continue
        rel = child.resolve().relative_to(ns_root.resolve()).as_posix()
        entry = indexed_lookup.get(rel)
        if entry is None or not entry.indexed_at:
            return True  # 새 파일
        mtime_iso = datetime.fromtimestamp(child.stat().st_mtime, tz=utc).isoformat()
        if mtime_iso > entry.indexed_at:
            return True  # 수정 후 미반영
    return False
```

폴더 단위 "마지막 인덱싱 시점" 도 같은 방식으로 파생: `MAX(indexed_at for rel in manifest if rel.startswith(folder_prefix))`. 이걸 AI Summary 영속화의 stale 베이스라인으로 활용 (`indexed_at_at_generation` 와 비교).

`_IndexedDoc(NamedTuple)` 한 타입으로 chunk_count + indexed_at 묶어서 통과 — `dict[str, int]` → `dict[str, _IndexedDoc]` 한 번 바꾸면 호출자들도 깔끔하게 흡수.

**Why it works**: (1) **스키마 변경 없음** — manifest 의 기존 `indexed_at` 키 그대로 활용, indexer / connectors / retriever 무영향. (2) **사용자가 자유롭게 폴더 조작해도 자동 정합** — 파일을 다른 폴더로 옮기면 `rglob` 가 새 부모에서 발견, 옛 부모는 자연스럽게 stale 안 됨. (3) **계산 비용 적당** — 폴더당 O(파일 수) stat 호출, 대부분 RAG 코퍼스 (수십~수백 파일) 수준이면 수십 ms. tree 응답에 자연스럽게 함께 채울 수 있음. (4) **mtime / indexed_at 같은 ISO timestamp string 비교는 lexicographic 으로 order-preserving** (둘 다 `datetime.isoformat(tz=utc)` 로 만들면 microsecond 까지 동일 포맷).

**Reusable in**: 어떤 증분 처리 파이프라인이든 — RAG 인덱서 외에도 (a) 빌드 시스템의 "stale target" 검출 (Make / Bazel 의 timestamp 비교 일반화), (b) 캐시 무효화 (cached summary 가 underlying 데이터 갱신 후 stale), (c) ETL 파이프라인의 partition 단위 reprocess 결정. 핵심 원칙: **per-item state 를 source-of-truth 로 두면, 임의 그룹 (폴더 / partition / shard) 의 상태는 항상 파생 집계로 일관되게 계산 가능 — 그룹 단위 별도 메타를 만들지 마라**. 별도 메타는 동기화 버그의 진원지.


---

## 18. multi-tenant 도입 시 default tier 만 레거시 layout 보존

**태그**: `multi-tenant` `path-resolution` `legacy-preserve` `asymmetric-default`

**Problem**: 단일 root (`data/vectorstore/<namespace>/`) 로 운영 중인 시스템에 multi-tenant 개념 (워크스페이스) 추가. 새 prefix `<ws_slug>` 를 모든 path 에 끼워 넣으면 기존 데이터를 `data/vectorstore/default/<namespace>/` 로 이동 + 모든 manifest path 재작성 + 사용자 인덱스 무효화 = 충격 큼.

**Solution**: tier resolution 함수 (`src/rag/workspaces.py::workspace_paths`) 가 default tier 만 **asymmetric** 으로 처리:

```python
def workspace_paths(ws_slug: str) -> tuple[Path, Path]:
    if ws_slug == "default":
        # 레거시 layout 그대로: 기존 data/vectorstore/<ns>/ 가 곧 그 자리
        vs_root = _resolve_vectorstore_root()      # = data/vectorstore
        cd_root = PROJECT_ROOT / "data" / "company_docs"
    else:
        # 새 외부 tier: per-slug prefix
        vs_root = _resolve_vectorstore_root() / ws_slug
        cd_root = Path(workspace_row["abs_path"])
    return vs_root, cd_root
```

호출자 (retriever/indexer/route) 는 `vectorstore_root_for(ws_root, namespace)` 를 일관되게 사용 — default tier 면 결과가 `data/vectorstore/<ns>/` (no slug), 외부 tier 면 `data/vectorstore/<slug>/<ns>/` 로 자연스럽게 분기. 코드 한 군데만 분기를 안고 나머지는 깨끗.

**Why it works**: (1) **기존 데이터 이동 0 건** — `default` 의 layout 이 그대로 의미를 유지. (2) **새 외부 tier 는 per-slug 격리** — slug 충돌 없으면 충돌 위험 없음. (3) **호출자가 분기를 알 필요 없음** — `workspace_paths(slug)` 만 부르면 결과가 슬롯 인터페이스. (4) **migration 함수도 default 에만** — `migrate_flat_layout` 은 default tier 에서만 실행 (외부 tier 는 평면 레거시 데이터 자체가 없음).

이 비대칭은 의도적 transitional 상태. 미래에 일관된 prefix 로 정상화하고 싶으면 그때 한 번 데이터 이동 + 함수 단순화. 그 전까지는 user-facing breakage 없이 multi-tenant 진입.

**Reusable in**: 단일 → 멀티 tenant 전환의 모든 경우 — 멀티 DB 분리, 멀티 워크스페이스, 멀티 프로젝트, 멀티 organization. 파일 path 외에도 DB schema (default tenant 행은 tenant_id NULL 허용 → 새 tenant 만 NOT NULL) 등 동일 원칙 적용 가능. **핵심**: legacy 가 default 로 자연스럽게 매핑되면, breaking change 없이 새 tenant 만 격리 추가.

---

## 19. display-only 등록 + opt-in cleanup

**태그**: `display-toggle` `optional-cleanup` `non-destructive-default` `recover-by-readd`

**Problem**: 사용자가 "이 폴더를 RAG 트리에 추가하고 싶다" 고 할 때 백엔드는 두 가지 부수효과를 동반: (a) DB 에 워크스페이스 행 등록 (b) 인덱싱 후 `data/vectorstore/<slug>/` 에 chroma + manifest 생성. 제거 시 어디까지 되돌릴지가 결정 필요. 모두 다 지우면 사용자 실수에 복구 불가, 안 지우면 disk leak.

**Solution**: 등록/제거는 기본적으로 **DB row 만** 건드림. 부수 artifact (vectorstore 디렉토리 등) 정리는 **명시적 opt-in 옵션** (`?wipe_index=true` 또는 모달 체크박스) 으로 분리. 사용자 source 폴더 (등록한 abs_path) 는 어느 경우에도 절대 안 건드림.

```python
def delete(self, workspace_id, *, wipe_index: bool = False) -> bool:
    # ... DB row 삭제 ...
    if removed and wipe_index:
        # opt-in: 인덱스 + 캐시 wipe
        rmtree(vectorstore_root / slug, ignore_errors=True)
        conn.execute("DELETE FROM rag_summaries WHERE ws_slug=?", (slug,))
    return removed
```

UI 흐름:
- "Remove" 버튼 → 모달 표시 (제거 대상 + abs_path + "절대 삭제 안 됨" 안내)
- 체크박스 (기본 unchecked): "인덱스도 함께 삭제 (체크하지 않으면 vectorstore 보존 — 같은 이름으로 다시 추가 시 인덱스 재사용 가능)"
- [취소] [제거]

**Why it works**: (1) **사용자 실수 복구 = 같은 이름으로 재등록** — slug 가 label 에서 자동 파생되므로, label 만 일치시키면 같은 slug 가 재생성되고 보존된 인덱스에 즉시 매핑됨. (2) **Disk leak 우려는 명시 토글로 해결** — 청소 의지가 있는 사용자는 체크 한 번. (3) **destructive 와 non-destructive 의 경계가 UI 에 가시적** — 체크박스 + 안내 문구가 사용자 동의의 단일 지점. (4) **테스트 가능** — `wipe_index=True/False` 둘 다 별도 테스트 케이스로 잠금 (`test_delete_wipe_index_removes_vectorstore` / `test_delete_without_wipe_keeps_vectorstore`).

**Reusable in**: "사용자 등록 + 부수 artifact" 패턴이 있는 모든 곳. (a) 클라우드 콘솔의 리소스 삭제 (DB 인스턴스 vs 백업 vs 스냅샷), (b) 패키지 매니저의 uninstall (`apt remove` vs `apt purge`), (c) VCS 의 branch delete (`-d` vs `-D` vs working tree), (d) container orchestration 의 service vs volume. 핵심 원칙: **default 는 항상 non-destructive, destructive 는 명시 옵션 + 결과 가시화**.
