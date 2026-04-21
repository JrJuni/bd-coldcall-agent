# Backlog

장기 계획·향후 아이디어·스코프 밖 과제의 단일 원천.

- **`docs/status.md` 와의 관계**: status 는 **현재 진행 중 / 완료된 작업** 스냅샷. 장기 계획·큰 그림은 이 파일로 분리.
- **갱신 주체**: `/projectrecord` 스킬이 프로젝트 진행에 따라 항목 추가·완료 처리·스코프 변경 반영.
- **우선순위 (P1~P5)** 는 현 시점 추정치 — 실무 피드백·데이터에 따라 수시 변동 가능.
- **완료 처리**: 항목이 실제로 구현되면 `status.md` 의 "완료" 섹션으로 이관 후 여기서는 제거.

---

## P1 — Phase 9 직후 우선 착수 후보

### 1. 제안서 톤 조정 + 민감 가드

- **왜**: Phase 8 Deloitte 실행에서 집단소송·육아휴직 같은 민감 뉴스를 pain-point 로 직접 인용 → 실제 outbound 자료로는 너무 공격적. 고객사가 꺼리거나 아파할 지점을 그대로 찌르는 이슈 확인.
- **Tone preset 3종**: `conservative` (기회·파트너십 관점만) / `balanced` (현재 톤) / `aggressive` (pain 직접 찌름). `src/prompts/{en,ko}/synthesize.txt` / `draft.txt` 에 `{{tone_guidance}}` placeholder 도입 → 프리셋별 분기 파일 또는 런타임 치환.
- **Self-critique 단계**: `draft_node` 이후 `review_node` 추가. Sonnet 에 "이 제안서에서 고객사가 offensive/intrusive 로 느낄 부분을 식별하고, 필요한 경우 톤만 완화한 재작성본을 반환" 요청. 비용 ~+33% (draft call 동급).
- **CLI/API 인터페이스**: `--tone conservative|balanced|aggressive` (기본 `balanced`).
- **의존성**: 없음. 즉시 착수 가능.
- **범위 밖 (이번엔 스킵)**: 민감 태그 (`litigation`, `layoff` 등) 확장, per-target 블랙리스트 — 모델이 자체 판단하는 접근을 우선.

### 2. UX 사용성 개선 — 웹 drag-and-drop 입출력

- **왜**: 현재 RAG 문서는 `data/company_docs/` 에 수동 배치 → `python -m src.rag.indexer` 실행. CLI 비사용 BD 인력에게 진입 장벽. 핵심은 "OS 파일탐색기 거치지 말고 브라우저에서 바로" 입출력.
- **구현 스케치**:
  - 프론트 `/rag` 페이지에 drag-drop zone 추가 (`react-dropzone` 또는 native HTML5).
  - `POST /ingest/upload` 신설 — multipart/form-data 수용, `data/company_docs/` 저장 + indexer 트리거.
  - `GET /ingest/documents` — 인덱싱된 문서 목록 (manifest 기반).
  - `DELETE /ingest/documents/{doc_id}` — 단건 삭제.
  - proposal 결과 다운로드 버튼 (`.md` 우선, 추후 `.pdf` / `.docx`).
- **의존성**: Phase 7 인프라 위에 순수 추가. `src/rag/connectors/local_file.py` 재활용.
- **범위 밖 (당분간)**: Notion 페이지 개별 토글, 인덱싱 타임라인 UI, 실행 이력 목록·자동완성 (사용자가 "나중"으로 분류).

### 3. 뉴스 스크래퍼 확장 (Brave 대체)

- **왜**: Brave 구독이 없는 사용자 대응 + 쿼터 초과 fallback.
- **구현 스케치 (기존 `SearchProvider` ABC 재활용)**:
  - `GoogleNewsRssProvider` (`src/search/google_news.py`) — en/ko, 간단한 RSS 피드 파싱.
  - `NaverNewsProvider` (`src/search/naver.py`) — BS4 정적 파싱, 국내 매체 커버리지.
  - **Fallback chain**: `src/search/bilingual.py` 에 `providers=[BraveSearch, GoogleNewsRSS, NaverNews]` 순회, 쿼터 초과·5xx 시 다음 공급자로 자동 전환.
  - **Source-rank filter**: `config/source_ranks.yaml` 로 매체별 tier (tier1=Reuters/WSJ, tier2=TechCrunch, tier3=블로그) → preprocess 전 tier3 기본 drop (설정 토글).
  - CLI: `--provider brave|google|naver|auto`.
- **의존성**: 없음.
- **범위 밖**: Playwright 동적 렌더링 (JS 필요 매체·paywall 우회) — 별도 하위 항목으로 분리, 당분간 제외.

---

## P2 — 사용성·운영 확장

### 4. 피드백 루프 (👍 / ✏️ / 👎)

- **왜**: BD 팀 반복 사용하면서 proposal 품질 개선 데이터 누적 필요. 좋음/수정/나쁨 라벨이 향후 few-shot 재료.
- **스케치**: `/runs/[id]` 결과 페이지에 버튼 3개 → `POST /runs/{id}/feedback` 에 `{rating, comment, edited_md}` 저장 → SQLite `run_feedback` 테이블.
- **장기 활용**: preference data 로 DPO / few-shot, "자주 편집되는 패턴" 분석.
- **의존성**: 실행 이력 영속화 (P4) 선행 권장.

### 5. 비용/쿼터 대시보드

- **왜**: Sonnet·Brave 실제 비용 + 월 합계 실시간 확인. 운영·회계 필수.
- **스케치**: `/dashboard` 페이지 — 월별 run 수, in/out/cache token 합계, Brave 호출 수, 추정 달러 (단가 상수 + usage × 단가). 기초 데이터는 RunStore / 실행 이력 DB 에서 집계.
- **의존성**: 실행 이력 영속화 (P4) 가 있으면 정확, 없어도 현재 세션분만 가시화는 가능.

### 6. LLM-as-judge 자동 평가 (Phase 8 자동화)

- **왜**: Phase 8 처럼 사람이 1~5점 매기는 대신 다른 모델 (예: Opus / Gemini) 이 자동 채점 → 회귀 감지.
- **스케치**: `scripts/eval_suite.py` — 정해진 타겟 셋 (Tesla, NVIDIA, Deloitte 등) E2E 실행 → judge 모델이 proposal 을 axis 별 (주제 적합성 / 근거 정확성 / 톤 / Next Steps 구체성) 채점 → CSV 리포트.
- **의존성**: Phase 8 첫 수동 데이터 확보 후 착수 (judge 보정용).

### 7. 브리핑 모드 (`main.py brief`)

- **왜**: 콜 직전 "이 회사 최근 어떰?" 만 30초 안에. 풀 proposal 생성 (2~3분 · ~$0.1) 은 과잉.
- **스케치**: `main.py brief --company X [--industry Y]` — search → fetch → preprocess 까지만 → "최근 주요 이슈 5개 bullet" Sonnet 1회 호출 → stdout + 짧은 Markdown. synthesize / draft 스킵.
- **의존성**: 없음. 기존 파이프라인 서브셋으로 즉시 구현 가능.

---

## P3 — 신규 파이프라인 / 기능 확장

### 8. 타겟 후보 발굴 (reverse matching)

- **왜**: 현재 outbound 파이프라인은 타겟이 정해진 전제. 실무 sales 는 "어떤 회사에 접촉할지" 부터가 문제.
- **스케치** (신규 LangGraph 서브그래프):
  1. `describe_product` — product docs (RAG) → Sonnet 에 "우리 제품의 기능·가치 제안 3~5개" 추출.
  2. `brainstorm_industries` — Sonnet 에 "이 기능이 가장 아픈 산업 10개 + 그 이유" 요청.
  3. `sample_news_per_industry` — 산업별 Brave 검색 3~5건, 활성 이슈 체크.
  4. `rank_candidates` — 산업 내 언급 빈도 높은 기업 + product fit 점수화.
  5. `recommend` — top 3~5 회사 + 각 회사별 핵심 pain point 1줄.
- **신규 entry**: `main.py discover --count 5` + `--auto-run` (추천 타겟에 기존 `run()` 자동 연쇄).
- **비용**: ~$0.3~$1/회 (Brave 다중 호출 + Sonnet 3~4회).
- **의존성**: 없음. Phase 10+ 주제.

### 9. 검색 쿼리 고도화 (multi-intent merge)

- **왜**: 현재 `company + industry` 단일 쿼리. 기사 다양성 부족. 특정 각도 (funding / leadership change / regulatory / product launch) 는 다른 쿼리 문구로 검색해야 잘 잡힘.
- **스케치**: `bilingual.py` 앞단에 intent-split — 의도 3~5개별 쿼리 생성 → 각각 Brave 호출 → URL 기준 merge + dedup.
- **비용**: Brave 호출 3~5배 (단, 의도별 5~8건씩이면 총 뉴스량은 유사).
- **의존성**: 없음.

### 10. 다국어 확장 (ja / zh)

- **왜**: 글로벌 타겟 (일본 SaaS, 중국 제조 등) 확대.
- **스케치**: `src/prompts/{ja,zh,...}/` 추가. `lang` Literal 확장. 산업 키워드 번역 룩업 확장 (`src/search/bilingual.py::TRANSLATIONS`). Exaone 대신 해당 언어에 강한 모델 스왑 필요할 수도 (P5-14 와 연동).
- **의존성**: 보조적. 실제 타겟 수요 생긴 뒤.

---

## P4 — Phase 7 MVP 이후 Web UI 확장

Phase 7 MVP 는 로컬 전용·최소 RAG 관리만. 배포 단계에서 다음을 추가.

- **인증/권한** — FastAPI OAuth2/JWT + 프론트 세션 관리. 멀티 유저 분리, API 키 발급.
- **백그라운드 워커** — FastAPI `BackgroundTasks` 대신 Celery/RQ + Redis 큐. 프로세스 재시작·수평 확장 대응.
- **실행 이력 영속화** — 현재 SqliteSaver 체크포인터 외에 실행 메타 (`run_id/company/status/created_at`) 전용 테이블 + 목록/검색 UI. P2-4/5 의 기반.
- **풀 RAG 관리 UI** — Notion 페이지 개별 토글, 인덱싱 이력 타임라인 (P1-2 drag-drop 이후 확장).

---

## P5 — 장기 기능·연구

### 12. CRM / 팔로업 관리

콜 이후 단계 지원.
- 콜 로그(수기 메모 또는 음성 전사) → 요약.
- 다음 액션 추천 (재시도 시점, 제공 자료, 후속 이메일 초안).
- 외부 CRM 연동 (Salesforce, HubSpot).

### 13. 멀티 에이전트 협업

현재 단일 파이프라인을 research / writing / review 역할 분리로 개선. LangGraph 서브그래프 + 상호 리뷰 루프. P1-1 Self-critique 가 자연스러운 씨앗.

### 14. 모델 스왑 실험

Exaone 요약·분류 품질 한계 시 Qwen / Gemma / Llama 계열 벤치마크 → 교체. 다국어 확장 (P3-10) 과 연동 가능.
