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

- **상태 (2026-05-02)**: **P10-3 (drag-drop + namespace UI) + P10-9 (filesystem-mirror UX 확장: 폴더 탐색·root 파일·AI Summary·OS 탐색기 launch) 로 흡수 완료.** 이 항목은 close. 후속 (Notion 토글·인덱싱 타임라인·root 파일 자동 인덱싱) 은 별도 backlog 항목으로 분기 필요 시 추가.
- (이전 스케치 — 참고용 보존)
- **왜**: 현재 RAG 문서는 `data/company_docs/` 에 수동 배치 → `python -m src.rag.indexer` 실행. CLI 비사용 BD 인력에게 진입 장벽. 핵심은 "OS 파일탐색기 거치지 말고 브라우저에서 바로" 입출력.
- **구현 스케치**:
  - 프론트 `/rag` 페이지에 drag-drop zone 추가 (`react-dropzone` 또는 native HTML5).
  - `POST /ingest/upload` 신설 — multipart/form-data 수용, `data/company_docs/` 저장 + indexer 트리거.
  - `GET /ingest/documents` — 인덱싱된 문서 목록 (manifest 기반).
  - `DELETE /ingest/documents/{doc_id}` — 단건 삭제.
  - proposal 결과 다운로드 버튼 (`.md` 우선, 추후 `.pdf` / `.docx`).
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

### 8. 타겟 후보 발굴 (reverse matching) — 풀 5단

- **상태 (2026-04-28)**: **Phase 9 가 MVP 컷 (Sonnet 1회) 으로 흡수.** 5 산업 × 5 회사 = 25 후보 → `outputs/discovery_<date>/{candidates.yaml, report.md}`. 검증 없이 사람 검수 의존. 본 항목은 풀 5단 (Brave 검증 + 산업별 활성 이슈 체크 + product fit 점수화) 으로 확장하는 장기 과제.
- **확장 스케치** (신규 LangGraph 서브그래프, Phase 9 산출물에 검증 단계 추가):
  1. `describe_product` — Phase 9 의 RAG 시드 단계 (구현됨)
  2. `brainstorm_industries` — Phase 9 의 industry_meta 추출 (구현됨)
  3. `sample_news_per_industry` — 산업별 Brave 검색 3~5건, 활성 이슈 체크 (신규)
  4. `rank_candidates` — 산업 내 언급 빈도 + product fit 점수화 (신규, Phase 9 의 단순 tier 보강)
  5. `recommend` — top 3~5 회사 + pain point 1줄 (신규)
- **신규 entry**: `main.py discover --validate` (Phase 9 의 1회 호출 + Brave sanity check + Sonnet 추가 호출)
- **비용**: ~$0.3~$1/회 (Brave 다중 호출 + Sonnet 3~4회). MVP $0.04 와 비교 가치 vs 비용 검토.
- **의존성**: Phase 9 사용 데이터 누적 → 어떤 검증이 가장 hallucination 줄이는지 확인 후 진입.

### 17. 티어리스트 편집 웹 UI (Phase 9 후속)

- **상태 (2026-04-30)**: **Phase 10 의 P10-2 로 흡수 진행 중.** `data/app.db` (`src/api/db.py`) 의 `discovery_runs` / `discovery_candidates` 테이블은 P10-0 에서 이미 생성. 이 항목은 Phase 10 8-탭 구조의 일부로 `/discover` 페이지 + import/edit/recompute/promote 흐름이 구현되면 close.
- (이전 스케치 — 참고용 보존)
- **왜**: Phase 9 산출물 `candidates.yaml` (25 행 flat) 을 사람이 검수·편집해야 실제 BD 액션 (targets.yaml 등록) 이 됨. CLI 로 yaml 직접 편집은 비-개발자 BD 인력에게 진입 장벽.
- **스케치**:
  - **임포트** — `POST /discovery/import` 가 yaml 업로드 → SQLite `discovery_candidates` 테이블 (run_id / generated_at / industry / name / scores_json / final_score / tier / rationale / status [active|archived|promoted]).
  - **편집 UI** — `/discover` 페이지: sortable·filterable·editable table view. 컬럼: tier (드롭다운 S/A/B/C) / company / industry / scores 6개 / rationale / actions. 행 추가·이동·삭제·점수 인라인 편집.
  - **scoring 엔진 재계산** — weights 슬라이더 → `POST /discovery/recompute` (LLM 호출 0원, `src/core/scoring.py` 만 호출).
  - **export** — "Export YAML" 버튼 → 편집된 candidates.yaml 다시 다운로드.
  - **targets.yaml 자동 추가** — "Promote to targets" 액션 → `targets` 테이블 에 `{name, industry, notes: rationale, created_from: discovery_promote, discovery_candidate_id}` insert 후 candidate.status="promoted".

### 9. 검색 쿼리 고도화 (multi-intent merge)

- **상태 (2026-04-28)**: **Phase 8 Related 채널이 흡수.** intent 티어리스트 (S/A/B/C) 기반의 정적 multi-intent 쿼리가 `src/search/channels/related.py` 에 구현됨. 추가 작업 없으면 close.
- (이전 스케치) `bilingual.py` 앞단에 intent-split — 의도 3~5개별 쿼리 생성 → 각각 Brave 호출 → URL 기준 merge + dedup.

### 22. Phase 11 후속 — multi-workspace 마무리 (UI/CLI 격차)

- **상태 (2026-05-02)**: Phase 11 (multi-workspace RAG) merge 됨 — default + 외부 워크스페이스 추가/제거 + ws-prefixed `/rag/*` 라우트 + 3-segment URL 인코딩 + AddWorkspaceModal/RemoveWorkspaceModal 까지 동작. 단 Re-index UI 와 일부 다른 페이지가 여전히 default ws 하드코딩.
- **잔여 격차**:
  1. **Re-index UI 가 default ws 고정** — `triggerIngest` (POST /ingest) 가 `--workspace` 플래그 안 보내므로 외부 ws 인덱싱은 CLI (`python main.py ingest --workspace <slug>` 또는 `--all-workspaces`) 만 가능. `IngestTriggerRequest` 에 `workspace?: string` 또는 `all_workspaces?: bool` 필드 추가 + `src/api/runner.py::execute_ingest` argv forwarding + `/rag` 페이지 Re-index 버튼이 현재 ws_slug 자동 전달
  2. **Discovery / News 탭 namespace 드롭다운 ws 미인지** — `listRagNamespaces()` default 인자로 default ws 만 보여줌. 외부 ws 의 namespace 도 선택 가능하게 ws 드롭다운 + namespace 드롭다운 2단계로 분리하거나, 하나로 묶어 `<ws_slug>/<ns>` 표기
  3. **Dashboard `rag` aggregate 가 default ws 만 집계** — 외부 ws 의 manifest 도 합산. `/dashboard` route 가 `list_workspaces` 순회
  4. **외부 ws 시나리오 백엔드 테스트 5건** — `tests/test_api_rag_docs.py` 에 외부 ws 등록 → upload → tree → AI Summary → delete 흐름. 현재 18건 워크스페이스 테스트는 `/workspaces` CRUD 만 커버
  5. **워크스페이스 메타데이터** (선택) — description / 색상 라벨 / 태그. 워크스페이스가 늘면 구분 needs
- **의존성**: 없음. (1)·(3)·(4) 가 사용자 즉시 가치, (2) 는 discovery/news 활용 빈도 따라
- **범위 밖**: Notion 워크스페이스 (현재는 `data/company_docs` 한정), 멀티유저 권한 (P4 인증 필요)
- **참고**: `docs/playbook.md` #18 (multi-tenant default tier 보존) + #19 (display-only 등록) 패턴

### 21. RAG 폴더 단위 검색 분리 (sub-namespace retrieval scope)

- **상태 (2026-05-02)**: P10-9 / P10-9.1 에서 명시적 out-of-scope. 현재는 namespace 단위만 검색 분리, 폴더는 정리용일 뿐 (같은 namespace 안의 `customers/acme/spec.md` 와 `competitors/foo/spec.md` 가 retrieval 결과에 섞임). AI Summary 만 path prefix client-side 필터.
- **왜**: 한 namespace 안에 여러 사용 맥락 (고객사 / 경쟁사 / 사내 자료) 이 섞여 있을 때 사용자가 "고객사 폴더만 검색" 같은 의도를 자연스럽게 표현할 수 있어야 함. 현재는 namespace 를 더 잘게 쪼개라고 가이드하지만, 검색이 한 폴더 안에서만 일어나야 의미가 있는 use case (예: 같은 고객사의 여러 문서) 가 늘어남.
- **구현 스케치**:
  - `src/rag/retriever.py::retrieve(query, top_k, where=None)` 가 ChromaDB `where` 절 통과 — `source_ref` LIKE prefix 또는 metadata `folder` 필드 기반
  - 인덱서가 chunk metadata 에 `folder_path` 별도 필드 추가 (현재 `source_ref` 는 파일 경로 전체)
  - 라우트 / 그래프 노드에 `path` 인자 전파 — `POST /runs` body 에 `rag_folder?` 옵션
  - UI: RAG 탭 폴더 드롭다운 / 검색 scope 선택 UI
- **의존성**: P10-9.1 (folder needs_reindex) 에서 도입한 `_folder_last_indexed_at` 헬퍼 패턴 재사용 가능. retriever 의 `where` clause 통과는 `chromadb` 의 prefix matching 미지원이라 client-side filter 또는 별도 metadata 필드 필요
- **범위 밖**: 동적 path 변경 시 ChromaDB metadata reindex 자동화 (현재는 사용자가 폴더 옮기면 Re-index 수동). 이건 더 큰 과제

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

### 19. 패키지화 + 배포

- **왜**: 현재는 `~/miniconda3/envs/bd-coldcall/python.exe` + `npm run dev` 두 서버 수동 기동 → 비-개발자 BD 인력이 쓰려면 진입 장벽. Phase 10 8-탭 UI 가 안정화되면 다음 단계는 "한 번 클릭으로 켜지는 형태" 로 패키징.
- **3 트랙 (사용자 시나리오별)**:
  1. **로컬 단일머신 설치본 (Windows / macOS)** — 비-개발자가 zip 풀어서 `start.bat` 한 번 실행. 후보:
     - **Tauri / Electron 셸** — Next.js 빌드를 webview 로 띄우고, 백엔드는 같은 프로세스에서 PyInstaller `--onedir` 번들로 spawn
     - **PyInstaller / Nuitka** — uvicorn + 모델 경로 일체 동봉 (단점: torch/transformers 패키징 시 1~3GB)
     - GPU 의존성 (Exaone 4bit + bge-m3) 은 패키징 불가 → 첫 실행 시 자동 다운로드 + 설치 가이드 분리
  2. **Docker / Docker-compose** — 사내 서버·클라우드 VM 배포용. `Dockerfile.api` (CUDA base) + `Dockerfile.web` (node:20-alpine, `next build`) + `docker-compose.yml` (volume: `data/`, `outputs/`, `config/`). secrets 는 `.env` 마운트
  3. **사내 SaaS / 멀티유저** — P4 위 항목 (인증·워커·DB) 가 prereq. AWS/GCP 배포 가이드, GPU 인스턴스 (g5/g6) 또는 외부 inference API (NIM) 로 Exaone 대체
- **선결 과제**:
  - **버전 관리** — `pyproject.toml` + `web/package.json` 의 version 필드 동기화 (현재 `0.7.0` / `0.1.0` 불일치). `main.py --version` / `/healthz` 응답에 노출
  - **모델·데이터 경로** — 현재 `data/`, `outputs/`, `config/`, `models/` 가 cwd 기반 → 패키징 시 사용자별 디렉터리 (Windows `%APPDATA%`, macOS `~/Library/Application Support/bd-coldcall`) 로 분기 필요
  - **first-run wizard** — `.env` 자동 생성, Brave/Anthropic API 키 입력, RAG 폴더 선택, 모델 자동 다운로드 (~10GB) 를 GUI 로 안내
  - **자동 업데이트** — Tauri updater 또는 GitHub Releases + 셸 스크립트. 버전 호환 (DB 마이그레이션) 정책 동반 필요
  - **CI 빌드** — `.github/workflows/release.yml` — tag push 시 Windows/macOS 인스톨러 + Docker 이미지 + GitHub Release 자동 생성
- **단계적 출시 계획 (제안)**:
  - **B1** Docker-compose (개발자·사내 서버) — 가장 빠름, CI 빌드도 단순
  - **B2** Tauri 데스크톱 앱 (BD 인력 직배포) — first-run wizard + 모델 자동 다운로드
  - **B3** 사내 SaaS 멀티유저 (인증·워커·DB 통합)
- **의존성**: Phase 10 8-탭 UI 안정화 완료 → P4 인증/워커/이력 DB 우선 (B3 한정) → 본 항목 착수
- **범위 밖 (당분간)**: 모바일 앱, App Store / Play Store 배포 (BD 워크플로우상 데스크톱이 주). 자동 라이선스 관리·SSO 도 우선순위 낮음

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

### 15. 개인 CV/Resume → 적합 기업 발굴 → 자기소개서·커버레터·프로포절

- **왜**: 현 "회사 제품 → 타겟 기업 BD 제안서" 파이프라인을 입력만 CV/Resume 으로 바꾸면 "개인 → 적합 기업 → 지원서" 로 거의 그대로 피보팅. 코드 재사용 ROI 매우 큼.
- **재사용 매핑**:
  - product docs RAG → CV/Resume RAG (`src/rag/connectors/local_file.py` 그대로)
  - `scripts/draft_intent_tiers.py` (Phase 8) → "내 강점·경력 키워드 티어리스트" 초안 생성기로 재활용
  - 항목 8 reverse matching 의 5단 (`describe_product → brainstorm_industries → sample_news → rank_candidates → recommend`) → 적합 기업 발굴
  - 3 채널 검색 → target=발굴된 기업 / related=내 강점 매칭 / competitor=동종 지원자 동향(선택)
  - synthesize + draft → "자기소개서 / 커버레터 / 채용 제안서" 프롬프트 분기
- **신규 entry**: `main.py apply --resume PATH --count 5 [--auto-draft]`
- **의존성**: 항목 8 reverse matching 우선. Phase 8 의 intent 티어리스트 패턴 검증 후 follow.
- **분리 작업**: 프롬프트 (`src/prompts/{en,ko}/{cover_letter,sop}.txt`) + apply 서브그래프 + 출력 포맷 (Markdown / docx). UI 도 운영 시점엔 `/apply` 탭 분리.

### 16. 영업 반응 데이터화 + 임베딩 + 지식 그래프

- **왜**: proposal 송부 → 콜/미팅 → 고객 반응 (수락/거절/유보/추가질문/가격/경쟁사언급 등) 이 시스템 외부에서 휘발됨. 이 raw signal 을 구조화·저장·검색하면 (a) 다음 타겟 prompt 의 few-shot, (b) 톤/포지셔닝 보정, (c) 고객 페르소나 클러스터링, (d) 적합도 예측 모델 학습 데이터.
- **세 레이어 (단계적)**:
  1. **캡처** — `/runs/[id]` follow-up 입력 폼 (콜 메모 / 이메일 답장 / 미팅 트랜스크립트). `POST /runs/{id}/interactions` → SQLite `interactions` 테이블 (`run_id, kind, occurred_at, raw_text, outcome_label, contact_role, notes`). 음성은 처음엔 텍스트 paste, 추후 STT.
  2. **임베딩** — bge-m3 로 ChromaDB 별도 collection (`sales_interactions`). retriever 에 새 source_type, synthesize 가 "유사 과거 반응 top-k" 를 추가 컨텍스트로 받음.
  3. **지식 그래프** — entity: `Company` / `Contact` / `Interaction` / `Pain` / `Objection` / `Competitor` / `Product`. relations: `Company-HAS_CONTACT-Contact`, `Interaction-RAISED-Objection`, `Objection-RELATES_TO-Pain`, `Company-EVALUATED-Competitor`. 스택 후보: Neo4j(운영부담) vs SQLite + edge 테이블(저비용 PoC) vs 그래프 RAG. MVP 는 SQLite edge + Sonnet 1회 entity extraction.
- **재사용**: `src/rag/{store,retriever,connectors}` 그대로. `Article.tags` 9 태그 분류 패턴이 `Objection`/`Pain` 라벨링에 응용.
- **신규 entry**: `main.py log-call --run-id <id>` (CLI) + 웹 UI 폼.
- **장기 활용**: preference data → DPO/few-shot, 고객 클러스터링 → 톤 프리셋 자동 추천, 적합도 예측 (항목 8 발굴과 결합).
- **의존성**: 항목 4 (피드백 루프) prerequisite — interactions 테이블이 그 확장. 항목 12 (CRM 연동) 와는 외부 sync 가 별도 과제.

### 18. NVIDIA Nemotron 활용 검토 (4 sub-track, 별도 branch 실험)

- **상태 (2026-04-28)**: research 완료 (NVIDIA developer blog / NIM / HuggingFace 출처 확인). 자원 소모 + 대체 리스크 때문에 즉시 main branch 통합 보류 — 별도 branch 에서 실험 후 가치 검증되면 통합.
- **research summary**:
  - Open weights + commercial license, ~10T 토큰 사전학습 corpus 공개
  - Nemotron-4 340B Synthetic Data Pipeline (Base + Instruct + Reward 3 모델, 도메인별 합성 가능)
  - Llama Nemotron Nano/Super/Ultra — base 대비 +20% reasoning, 5× inference. Llama-3_1-Nemotron-Ultra-253B HF 공개
  - NIM API 무료 tier (build.nvidia.com), Azure AI Foundry / Accenture / Deloitte / SAP 도입
  - 2026 H1 Nemotron 3 Super/Ultra 출시 예정

#### 18a. Llama Nemotron Nano → Exaone 대체 검토 (preprocess 로컬)
- **왜**: reasoning 향상으로 9-tag classify 정확도 + intent_label 매핑 개선. RTX 4070 16GB 4bit 적합
- **장벽**: 한국어 native 지원 약점 (Exaone 강점). 한국 BD 비중에 따라 수용 결정
- **의존성**: 없음. preprocess 노드만 swap. **우선순위 P3**

#### 18b. Llama Nemotron Ultra (NIM) → Sonnet 부분 대체 (synthesize/draft/discover)
- **왜**: NIM 무료 tier + open license + 253B reasoning. 비용 절감 + 벤더 락-인 완화
- **장벽**: Anthropic prompt cache (`cache_control: ephemeral`) 호환성 미확인. schema 강제 (ProposalPoint validation, parse_discovery count enforce, scoring scores 6 dim) 에 대한 instruction following 정확도가 결정적. claude_client 추상화 강화 필요
- **의존성**: 없음. **우선순위 P3**

#### 18c. Nemotron-4 340B → 평가셋·few-shot 합성 ⭐ 추천
- **왜**: synthetic data 가 BD 도메인에서 가장 부족한 자원. backlog P2-6 (LLM-as-judge) 평가 셋 + P2-4 (피드백 루프) cold-start 데이터 동시 해결
- **장벽**: 340B self-host 어려움 → NIM 또는 cloud GPU rental (1회성). 도메인 specificity 검증 필요
- **의존성**: 없음. backlog P2-4 / P2-6 와 시너지. **우선순위 P3 또는 P2**

#### 18d. Multi-Nemotron 분업 (장기)
- **왜**: 단일 Sonnet 의 reasoning 을 여러 작은 모델 (Nano/Super) 분업 → cost·latency 분산
- **장벽**: 구조 변경 큼, ROI 불명확. orchestration overhead 가 절감 효과 상쇄 가능
- **의존성**: 18a/18b 결과 누적 후 평가. **우선순위 P5**

#### 참조
- [NVIDIA Nemotron - Developer](https://developer.nvidia.com/nemotron)
- [Nemotron-4 Synthetic Data Generation Pipeline](https://blogs.nvidia.com/blog/nemotron-4-synthetic-data-generation-llm-training/)
- [Llama Nemotron Reasoning Models](https://nvidianews.nvidia.com/news/nvidia-launches-family-of-open-reasoning-ai-models-for-developers-and-enterprises-to-build-agentic-ai-platforms)
- [Llama-3_1-Nemotron-Ultra-253B HuggingFace](https://huggingface.co/nvidia/Llama-3_1-Nemotron-Ultra-253B-v1)

### 20. ChatGPT OAuth 활용 (서드파티) — Sonnet 비용 절감 옵션

- **왜**: Sonnet 호출 비중이 큰 단계 (synthesize / draft / discover) 의 가변 비용 (~$0.10/proposal, ~$0.04/discover) 을 ChatGPT Plus 고정 구독 ($20/월) 으로 일부 대체. 1인 BD 도구 규모에서는 토큰 사용량이 Plus 한도에 안 걸릴 가능성 높음.
- **접근**: OpenAI 공식 API 가 아닌 ChatGPT 웹 OAuth 토큰을 흉내 내는 서드파티 라이브러리 (`revChatGPT` 계열, `chatgpt-api` 변형 등) 활용. 사용자 ChatGPT Plus 계정의 인증 토큰을 사용해 web UI 트래픽을 reverse-engineer 한 형태.
- **리스크 (모두 명시)**:
  1. **OpenAI ToS 위반 가능성** — 공식 허가된 방법 아님. 계정 정지 / IP 차단 가능
  2. **라이브러리 안정성** — OpenAI 가 주기적으로 클라이언트 변경 → 서드파티 라이브러리가 깨지는 사이클 (히스토리상 1~3개월). 프로덕션 의존성으로 두면 위험
  3. **응답 일관성** — 공식 API 처럼 schema 강제 어려움. ProposalPoint / parse_discovery 같은 JSON 스키마 검증이 실패할 확률 ↑ → 재시도 비용 증가
  4. **prompt cache 미지원** — Anthropic `cache_control: ephemeral` 같은 메커니즘 부재. 동일 RAG 다중 타겟 시 캐시 절감분 사라짐
  5. **속도 / latency** — 웹 UI 경유라 API 직접 호출보다 체감 느림
- **MVP 스케치**:
  - `src/llm/chatgpt_oauth.py` — `ChatGPTOAuthClient` 어댑터 (현 `claude_client.chat_cached` / `chat_once` 와 동일 시그니처)
  - `config/settings.yaml::llm.provider` — `anthropic` (기본) / `chatgpt_oauth` 토글
  - 프로바이더별 fallback chain — ChatGPT 실패 → Anthropic 자동 전환 (per-call 단위)
  - **Settings 탭** (P10-7) 에 자리만 마련: provider 드롭다운 + 토큰 입력란 + "이 방식은 OpenAI 비공식 — 계정 정지 위험" warning
- **차단 시 fallback 정책**: 라이브러리 부서지면 `provider="anthropic"` 환경변수 단발 swap 으로 즉시 복구. 개발 일정에 의존성 두지 말 것.
- **의존성**: 없음. 하지만 P10-7 Settings 탭에 UI 자리 마련 후 본격 구현이 자연스러움. **우선순위 P5 (실험)** — 즉시 main 통합 X, 별도 branch / 옵션 토글로만 도입.
- **범위 밖**: OpenAI 공식 API 키 사용 (이건 P3-14 모델 스왑 실험 분기 — 별도 항목)
