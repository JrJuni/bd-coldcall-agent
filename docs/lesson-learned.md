# Lessons Learned

개발 중 시도한 접근 방식, 실패 원인, 잘 된 노하우를 날짜별로 누적.

## 기록 형식

```
## [YYYY-MM-DD] 주제 한 줄
**시도**: 어떤 접근을 취했는가
**결과**: 성공 / 실패 + 관찰한 현상
**배운 점**: 다음에 어떻게 할 것인가
```

---

## [2026-04-20] Windows `python` 명령이 Microsoft Store 스텁으로 연결됨
**시도**: `python --version` 실행으로 환경 확인.
**결과**: 실제 Python 미설치 상태에서 `C:\Users\<user>\AppData\Local\Microsoft\WindowsApps\python.exe` 스텁이 잡히고 "Python was not found" 메시지만 출력. `py` 런처도 없음.
**배운 점**: Windows 환경은 기본적으로 Python이 없다고 가정. 설치 전에는 `winget install Anaconda.Miniconda3 --silent --scope user` 또는 `winget install Python.Python.3.11` 로 명시 설치. Miniconda 경로는 `~/miniconda3/Scripts/conda.exe`.

## [2026-04-20] Miniconda 신규 설치 직후 채널 ToS 거절
**시도**: `conda create -n bd-coldcall python=3.11 -y` 로 신규 env 생성.
**결과**: `CondaToSNonInteractiveError` — `pkgs/main`, `pkgs/r`, `pkgs/msys2` 3개 채널 ToS 미수락 상태에서 어떤 env 생성도 실패.
**배운 점**: Miniconda `py313_26.1.1` (2025-11 이후 배포) 부터 ToS 사전 수락 필수. 설치 직후 다음 3줄을 먼저 실행:
```
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/msys2
```

## [2026-04-20] Windows Python stdout 한글 깨짐 (cp949)
**시도**: `python -m src.search.brave --query "AI 산업" --lang ko` 실행, Brave 응답을 콘솔에 출력.
**결과**: 응답 JSON에는 정상 UTF-8로 한글이 들어있으나 콘솔은 cp949 코드페이지로 디코딩해 모지바케 발생. 파일 리디렉션해도 동일.
**배운 점**: CLI 진입점에서 최초에 `sys.stdout.reconfigure(encoding="utf-8")` 로 강제. `PYTHONIOENCODING=utf-8` 환경변수도 가능하지만 엔트리포인트에 직접 박는 게 재현성이 좋음. 이후 모든 CLI (`main.py`, `src/cli/*`) 에 동일 처리 필요.

## [2026-04-20] 스니펫만으로는 BD 요약 불가능 — trafilatura 본문 추출 불가피
**시도**: Brave Search API 응답의 `description` (150~300자 snippet) 을 그대로 Exaone 에 넣어 구조화 JSON 요약을 생성하는 최초 설계.
**결과**: Snippet 만으로는 BD 관점 key_events / business_signals / pain_points 를 추출할 맥락이 부족. 7.8B급 LLM 은 빈 공간을 채우려 hallucinate 할 확률이 높다고 판단.
**배운 점**: Phase 1 (검색) 과 Phase 2 (요약) 사이에 **Phase 1.5 — 본문 추출기** 를 삽입. `trafilatura.extract(favor_precision=True)` 를 `ThreadPoolExecutor(max_workers=5)` 로 병렬 호출. 실측 "AI 산업" bilingual 20건 기준 19/20 full 추출, 평균 3894자. Reuters 만 snippet fallback. 실패 시 `body_source="snippet"` 플래그 유지해서 파이프라인 중단 없음.

## [2026-04-20] 로컬 LLM 은 reasoning 보다 결정적 전처리가 본업
**시도**: 초기 설계에서 Exaone 7.8B 에 "기사 → BD 시그널 구조화 JSON (key_events / business_signals / pain_points / opportunities)" 요약 역할 부여.
**결과**: 7.8B급 모델은 단순 요약이나 핵심 문장 추출은 가능하지만 **"BD 시그널 추출"은 추론 + 도메인 지식이 요구되는 태스크**. hallucination 위험이 크고 Sonnet 대비 품질 차이가 큼. 또한 Exaone 요약을 Sonnet 에 넘기면 **맥락이 이미 compress 된 상태** 라 Sonnet 도 원문 수준의 뉘앙스 복원 불가.
**배운 점**: 로컬 LLM 의 역할을 **번역 + 9-태그 분류 + 임베딩 중복제거** 같은 "정답이 있는 결정적 전처리"로 재배치. BD 시그널 추출과 제안 작성은 Sonnet 4.6 이 번역된 full body 를 직접 받아 수행. 이렇게 하면 맥락 손실 X + 로컬 모델 hallucination 위험 격리 + 각 모델이 자기 강점 영역만 담당. (원칙: "small models for deterministic tasks, frontier models for reasoning")

## [2026-04-20] requirements.txt 를 Phase별로 분리
**시도**: 초기 단일 `requirements.txt` 에 `torch`, `bitsandbytes`, `chromadb`, `sentence-transformers` 등 ML 중량 deps 포함.
**결과**: Windows 환경에서 `bitsandbytes` 는 CUDA 런타임 필요, `torch` 는 기본 PyPI CPU 휠만 제공되어 GPU 쓰려면 `--index-url https://download.pytorch.org/whl/cu121` 별도 지정 필요. Phase 1 (Brave) 에는 전혀 불필요한 deps.
**배운 점**: `requirements.txt` = 경량 핵심 (Phase 1+: httpx/pydantic-settings/pyyaml/anthropic/langgraph/notion-client/pypdf/typer/pytest) + `requirements-ml.txt` = Phase 2+ 중량 (torch/transformers/accelerate/bitsandbytes/chromadb/sentence-transformers) 로 분리. torch 는 ml 설치 전에 `pip install torch --index-url ...` 로 사용자가 CUDA/CPU 선택. 이렇게 하면 Phase 1 테스트에 10분 넘는 설치 대기 없이 바로 진입 가능.

## [2026-04-20] Exaone 3.5 chat template 이 `return_tensors="pt"` 로 호출되면 `generate()` 에서 shape 실패
**시도**: `tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt")` 한 번에 input_ids 텐서를 받아서 `model.generate()` 에 전달.
**결과**: `BatchEncoding` 객체가 반환되는데 transformers `generate()` 가 `inputs_tensor.shape[0]` 로 바로 접근해 `AttributeError: shape` 발생. `BatchEncoding` 은 dict-like 라 `.shape` 가 없음 (모델/템플릿 조합에 따라 이렇게 dict 로 반환되는 케이스 있음).
**배운 점**: chat template 을 **두 단계로 분리** — `apply_chat_template(..., tokenize=False)` 로 순수 문자열 얻고 → `tokenizer(text, return_tensors="pt")` 로 별도 토크나이즈. `input_ids`, `attention_mask` 둘 다 꺼내서 `model.generate(input_ids, attention_mask=..., **kwargs)` 로 전달. 이 패턴은 HF 문서에서도 일반적이며 어떤 tokenizer 구현이든 안전.

## [2026-04-20] Exaone 3.5 7.8B (4bit) + RTX 4070 16GB VRAM 로드 확인
**시도**: `BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=float16, bnb_4bit_use_double_quant=True)` + `device_map="auto"` 로 HuggingFace 에서 `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct` 다운로드(약 15GB) 후 로드.
**결과**: 첫 실행 시 HF 에서 shard 7 파일 ~3:55 다운로드, 이후 warm-cache 로 291 weights 를 ~28초에 로드. 한→영 번역("삼성전자가 3분기 매출 70조원을 기록했다.") 과 태그 JSON 생성 모두 정상. CUDA 사용량 안정.
**배운 점**: 4bit nf4 + double-quant 조합으로 16GB VRAM 카드에서 7.8B 모델이 편하게 돌아감 (실측 사용 ~5-6GB). 첫 다운로드 후에는 재실행이 빠르므로 싱글턴 캐시(`_CACHE` dict)로 모델을 재활용. Windows 에서 `huggingface_hub` 가 심볼릭 링크 경고를 띄우지만 기능엔 문제 없음 — Developer Mode 켜거나 admin 으로 돌리면 공간 절감 가능.

## [2026-04-20] bge-m3 로딩이 torch 2.5 환경에서 CVE-2025-32434 로 거절됨
**시도**: `sentence-transformers.SentenceTransformer("BAAI/bge-m3")` 기본 호출로 Phase 2 dedup 용 임베더 로드.
**결과**: `ValueError: Due to a serious vulnerability issue in torch.load, even with weights_only=True, we now require users to upgrade torch to at least v2.6`. 설치된 torch 는 `2.5.1+cu121` 이고 bge-m3 의 HF 스냅샷에는 `.safetensors` 와 `pytorch_model.bin` 이 공존하는데 sentence-transformers 가 `.bin` 을 선택하면서 CVE 게이트에 걸림.
**배운 점**: `SentenceTransformer(..., model_kwargs={"use_safetensors": True})` 로 safetensors 강제. safetensors 포맷은 CVE-2025-32434 대상이 아니라 torch 2.5 환경에서도 바로 로드됨. torch 2.6 업그레이드를 기다릴 필요 없이 단일 플래그로 우회 가능 — 공급망 보안 관점에서도 `.bin` pickle 실행 리스크 제거 효과. `src/rag/embeddings.py` 싱글턴에 영구 적용, `docs/security-audit.md` 에도 기록.

## [2026-04-20] Exaone 7.8B 태그 분류는 "후보 좁히기" 용 — 정확도 기대 금지
**시도**: Phase 2 검증에서 "한국 공공기관 AI 전환" 뉴스 20건에 대해 9-태그 분류 실행.
**결과**: 정부 R&D 공모사업 기사("과기정통부 AI 과제 100억 지원") 여러 건에 `m_and_a` 태그가 과다 부여됨. 실제로는 공공 과제 공고 → 펀딩(`funding`) 또는 `regulatory` 가 맞음. 7.8B 모델이 "자금이 움직인다" 는 표면 시그널로 m_and_a 를 선택하는 경향.
**배운 점**: 태그는 Phase 4 Sonnet 이 기사 서브셋을 고를 때의 **조잡한 필터**로만 취급. 실제 딜 판별·시그널 해석은 Sonnet 이 full body 를 보고 수행. 태그 품질을 올리려 few-shot 프롬프트를 계속 튜닝하는 것보다, 고가치 태그 7개에 한 번이라도 걸리면 full body 로 Sonnet 에 보내는 tier 정책이 실질 품질을 결정. (원칙: 로컬 모델의 분류는 recall 우선, precision 은 Sonnet 담당)

## [2026-04-20] Exaone 번역 출력에 `<article>` 프롬프트 경계 태그가 에코됨
**시도**: `src/prompts/{en,ko}/translate.txt` 가 기사 본문을 `<article>...</article>` 로 감싸 prompt injection 경계를 만든 상태에서 한→영 번역 실행.
**결과**: 일부 출력의 첫 줄에 `<article>` 태그가 그대로 포함됨. 모델이 입력 경계 마커를 "정식 출력 형식의 일부" 로 학습·복제하는 케이스. 번역 품질 자체는 정상.
**배운 점**: 프롬프트 경계 태그는 **보안상 필수** (injection 방어)지만 소형 LLM 은 이를 에코할 수 있으므로 **출력 후처리에서 일괄 strip** 해야 함. `translate.py` 에 `<article>/</article>` strip 한 줄 추가 예정 (Phase 3 전 백로그). 일반화하면: 프롬프트 경계는 사용하되, 모델 출력이 그 마커를 포함할 수 있다고 가정하고 후처리 레이어에서 제거.

## [2026-04-20] 큰 Phase 는 work stream 4분할 + 플랜 파일 체크박스로 관리
**시도**: Phase 3 RAG (LocalFile + Notion 커넥터, ChromaDB, 증분 인덱싱, retrieve API) 전체를 단일 세션으로 진행하려 했음.
**결과**: 초기 플랜이 구조는 맞지만 운영 디테일(원자성·해시 안정화·Notion title 규칙·PDF 페이지 경계 등) 7개 부족 지적받아 반려. 동시에 한 세션에 전체 구현 시 후반부로 갈수록 컨텍스트 압박 + 초기 결정 파편화 리스크가 큰 사이즈임을 체감.
**배운 점**: Phase 를 레이어 기준 **3~5개 work stream** 으로 쪼개고 각 스트림마다 **TO-BE / DONE 체크박스**를 플랜 파일(`~/.claude/plans/*.md`) 에 유지. 스트림 경계를 `/compact` 지점과 정렬 (보통 2번 정도). 세션이 단절돼도 다음 세션은 `status.md` 의 "진행 중" + 플랜 파일 체크박스만 읽고 정확히 재개 가능. Phase 3 를 스키마·정규화·청킹 / 저장소·검색 / 커넥터 / 인덱서·CLI 4축으로 쪼개 적용. 향후 Phase 4, 5, 7 도 동일 패턴 예상.

## [2026-04-21] LangGraph `TypedDict(total=False)` + 선택 키 assert 순서
**시도**: Phase 5 happy-path 테스트에서 `assert result["failed_stage"] is None or "failed_stage" not in result` 로 실패 없음 확인.
**결과**: `KeyError: 'failed_stage'` — `or` 단락 평가로 첫 피연산자가 먼저 evaluate 되는데, 키 자체가 없으면 `result["failed_stage"]` 접근에서 터짐.
**배운 점**: `total=False` TypedDict 에서 선택 키를 단언할 때는 **존재 검사 먼저**: `assert "failed_stage" not in result or result["failed_stage"] is None`. 패턴은 단순하지만 LangGraph 는 부분 state 머지를 기본으로 하기 때문에 모든 happy-path 테스트에 반복 적용됨.

## [2026-04-21] `langgraph.__version__` 없음 — 버전 확인은 `pip show`
**시도**: 설치된 LangGraph 버전을 확인하려고 `python -c "import langgraph; print(langgraph.__version__)"`.
**결과**: `AttributeError`. LangGraph 패키지는 module-level `__version__` 을 노출하지 않음 (얇은 네임스페이스 래퍼).
**배운 점**: Python 패키지 버전 확인은 `~/miniconda3/envs/bd-coldcall/python.exe -m pip show langgraph` 또는 `importlib.metadata.version("langgraph")` 로. `__version__` 관례는 패키지마다 제각각이라 신뢰 금지.

## [2026-04-21] LangGraph monkeypatch 는 pipeline.py 안에서 모듈 경로로 해석돼야 함
**시도**: `src/graph/nodes.py` 에 `from src.search.brave import BraveSearch` 모듈-수준 import 를 놓고, `tests/test_pipeline.py` 에서 `monkeypatch.setattr(nodes, "BraveSearch", _FakeBrave)` 로 교체.
**결과**: 노드가 `build_graph()` 로 compile 된 후 invoke 할 때 test double 이 아닌 원래 클래스가 호출됨. `pipeline.py` 가 `from src.graph.nodes import search_node` 로 심볼을 가져가면 참조가 고정되어 monkeypatch 가 뚫지 못함.
**배운 점**: `pipeline.py` 에서는 개별 함수가 아니라 **모듈 자체를 import** (`from src.graph import nodes as _nodes`) 하고 `_nodes.search_node` 처럼 런타임 속성 조회. 이러면 테스트에서 `nodes.search_node` 속성을 바꾸면 그래프 실행 시점에도 새 참조가 보임. 일반화: monkeypatch 대상이 될 수 있는 의존성은 **from-import 대신 module-import + attribute access** 로.

**2026-04-22 후속**: 이 교훈은 단순 스타일 취향이 아니라 테스트 신뢰성 근간이라는 판단 — 특히 graph/pipeline 계층은 monkeypatch 기반 테스트가 많아 심볼 바인딩 실수 시 **원본 의존성이 조용히 호출되며 false green 이 난다** (네트워크·API·LLM 호출이 테스트에서 몰래 나갈 수 있음). 재발성·중대성·발견 난이도 모두 높다는 합의로 CLAUDE.md 의 `## DO NOT` 섹션에 승격. 문구는 스코프 한정(patch 대상 + 부수효과 있는 외부 호출 + orchestration 계층) + "왜 금지인지 + 허용 패턴" 을 함께 적어 일반화. 상수·타입·예외 클래스 등 patch 대상이 아닌 심볼은 규칙 적용 대상 아님 — 모든 import 를 강제하면 코드가 지저분해져 현실성 떨어짐.

## [2026-04-21] Typer + Rich 의 `--help` 는 모듈 로드 시점에 한글 렌더링
**시도**: `main.py` Typer 앱에서 커맨드 내부에 `sys.stdout.reconfigure(encoding="utf-8")` 를 호출하고 실행: `main.py --help`.
**결과**: `UnicodeEncodeError: 'cp949' codec can't encode character '\u2014'` — docstring 의 em-dash 가 cp949 콘솔에 쏟아짐. Rich 의 help 렌더러가 사용자 커맨드 본문이 돌기 **전에** 렌더하기 때문에, 커맨드 안의 reconfigure 는 이미 늦음.
**배운 점**: Typer 진입 스크립트는 **모듈 로드 시점**에 stdout/stderr 를 UTF-8 로 강제해야 함. `main.py` 최상단에 `for _stream in (sys.stdout, sys.stderr): _stream.reconfigure(encoding="utf-8")` 블록 배치. 일반 CLI (argparse 수동 파싱) 와 달리 선언적 프레임워크는 import 시점에 help 스트링을 포매팅한다는 점을 기억.

## [2026-04-21] 단일 state 키를 여러 노드가 덮어쓰면 실패 post-mortem 정보가 사라짐
**시도**: 초기 `AgentState.articles` 를 search_node → fetch_node → preprocess_node 가 차례로 덮어쓰는 단일 키로 구성. 각 노드는 이전 값을 읽어 풍부화한 새 리스트로 교체.
**결과**: retrieve 에서 실패하면 state.articles 는 "preprocess 후" 상태라 OK 지만, fetch 에서 실패하면 articles 가 "search 원본" 인지 "fetch 중간" 인지 state 만 봐선 구분 불가. run_summary 에 `articles_after_preprocess.json` 으로 저장되지만 이름이 거짓말이 됨. 외부 어드바이저도 같은 지적.
**배운 점**: 파이프라인의 **각 변환 스테이지는 자기 전용 출력 키** 를 가짐 — `searched_articles` / `fetched_articles` / `processed_articles` 3개로 분리. 다음 노드는 이전 스테이지 키를 **읽기 전용**으로 consume. persist 는 `latest_articles(state)` (processed > fetched > searched 폴백) 로 캐노니컬 출력을 만들고, 실패 경로에선 단계별 덤프도 같이. 원칙: "노드는 입력을 덮어쓰지 않는다, 자기 출력만 추가한다". LangGraph 뿐 아니라 어떤 DAG 파이프라인이든 후행 단계가 선행 단계 아티팩트를 관찰할 수 있어야 post-mortem 이 성립.

## [2026-04-22] FastAPI 라우트에서도 DO NOT 룰이 그대로 깨진다
**시도**: Phase 7 `src/api/routes/runs.py` 에 `from src.api.runner import execute_run` 으로 심볼을 bind 해 BackgroundTasks 에 넘김. 테스트는 `monkeypatch.setattr("src.api.runner.execute_run", fake)` 로 가짜 러너를 주입해 Exaone·Sonnet 호출을 피하려 했음.
**결과**: 첫 실행에서 테스트가 실제 Exaone 7.8B (4bit) 를 로드하고 Sonnet 까지 호출해 150+ 초 지연 + proposal_md 실측값 반환. routes 모듈이 자기 로컬 `execute_run` 이름을 이미 원본 함수에 바인딩했기 때문에 monkeypatch 가 `src.api.runner.execute_run` 속성만 바꿔도 라우트는 원본을 계속 부름 — **DO NOT 룰 2026-04-21 섹션과 정확히 같은 실수**. `src/api/routes/ingest.py::_manifest_path` 의 `from src.config.loader import get_settings` 도 동일한 이유로 테스트의 settings 오버라이드가 먹지 않아 실제 vectorstore 경로를 읽는 false-green 이 났음.
**배운 점**: DO NOT 룰은 graph/pipeline 뿐 아니라 **FastAPI 라우트처럼 외부 호출을 트리거하는 모든 orchestration 계층** 에 동일하게 적용. `from src.api import runner as _runner` + `_runner.execute_run(...)`, `from src.config import loader as _config_loader` + `_config_loader.get_settings()` 패턴 일관 사용. 테스트 경로가 "구동" 직전에 반드시 거치는 얇은 어댑터 레이어는 모두 이 규칙 대상 — 단순 schema/const import 는 예외. 후속: 이미 CLAUDE.md 에 승격된 DO NOT 룰의 적용 범위가 충분히 넓다는 확인 (추가 승격 불필요).

## [2026-04-22] SSE 에 코루틴-thread-safe 큐를 안 쓴 이유
**시도**: Phase 7 백엔드가 BackgroundTasks(anyio worker thread) 에서 돌리는 `orchestrator.run_streaming()` 의 각 super-step 을 SSE(event loop) 로 전달할 방법이 필요. 초안에서는 `asyncio.Queue` 를 `RunRecord` 에 달고 worker 가 `asyncio.run_coroutine_threadsafe(queue.put, loop)` 로 푸시하는 구조를 고려.
**결과**: 이 설계는 현재 MVP 에는 과도. `asyncio.Queue` 는 thread-safe 가 아니라 `put_nowait` 을 worker thread 에서 직접 호출하면 깨질 수 있고, `run_coroutine_threadsafe` 는 메인 루프를 caller 에서 알아야 해서 엉켜듬. SSE 세션별 구독자 관리·백프레셔·큐 메모리 바운드까지 고려하면 코드가 불필요하게 커짐.
**배운 점**: 이벤트 수가 **작고 append-only** (7 stage + ~5 meta = ≤~15 이벤트/run) 일 때는 `RunRecord.events: list[RunEvent]` + `threading.Lock` + SSE 쪽 **150ms 폴링** 이 가장 단순하고 틀릴 여지가 적음. `last_seq` 커서로 증분만 yield, 종결 상태 감지 후 stream close. "이벤트가 드물고 끝이 있는 스트림" 에서는 queue 기반 pub/sub 대신 poll-log 패턴이 더 알맞음. Celery/RQ + Redis 큐로 넘어갈 때 (장기 과제) 이 구조를 자연스럽게 pub/sub 으로 교체 가능.

## [2026-04-22] SqliteSaver 는 `check_same_thread=False` 가 필수
**시도**: Phase 7 `build_sqlite_checkpointer()` 초안에서 `sqlite3.connect(db_path)` 로 default 로 커넥션을 열고 `SqliteSaver(conn)` 을 lifespan 에 저장.
**결과**: `/runs` POST 가 BackgroundTasks 로 dispatch 되면 anyio worker thread 가 checkpointer 를 쓰는데, 같은 커넥션을 event loop(다른 스레드) 도 참조 → `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.
**배운 점**: FastAPI + BackgroundTasks + `SqliteSaver` 조합에서는 커넥션을 `sqlite3.connect(path, check_same_thread=False)` 로 열고 `SqliteSaver(conn)` 에 넘겨야 한다. 병행 write 보호는 langgraph-checkpoint-sqlite 내부 락이 담당. `close_checkpointer()` 헬퍼로 lifespan 종료 시 conn 명시 close. 장기적으로 SqliteSaver 의 context-manager 기반 `from_conn_string()` 관용 패턴과 충돌하므로, 추후 `async with` 기반 re-architecture 시 다시 검토 필요.

## [2026-04-22] Next.js 15 + React 19 GA 는 Next 15.0.x 와 peer 충돌
**시도**: Phase 7 `web/package.json` 에 `next@15.0.3` + `react@19.0.0` 고정 조합 사용.
**결과**: `npm install` 이 `peer react@"^18.2.0 || 19.0.0-rc-66855b96-20241106" from next@15.0.3` ERESOLVE 로 거절. Next 15.0.x 는 React 19 **RC 특정 해시** 만 인식하고 GA 19 를 받아들이지 못함.
**배운 점**: React 19 GA 는 **Next.js 15.1+** 부터 지원. 새 프로젝트 시작 시 `next@^15.1.0` + `react@^19.0.0` 를 caret 으로 지정해 npm 이 자연히 호환 버전 선택하게 두는 게 깔끔. `--legacy-peer-deps` 우회는 표면적 해결이며 downstream 에서 subtle한 hydration bug 가 날 수 있어 지양.

## [2026-04-21] Notion MCP `update_content` 의 `new_str` 크기 경계
**시도**: `/patchnotes` 스킬로 v0.5.0 패치노트 엔트리를 Notion 페이지에 삽입. 엔트리 전체를 단일 `update_content` 요청의 `new_str` 에 포함.
**결과**: 첫 시도에서 `~10KB+` 페이로드가 Cloudflare WAF 에 걸려 실패한 적이 있었음 (v0.3.0 배치 때). 이번엔 섹션당 3~5 bullet 로 깎아서 ~3KB 로 통과.
**배운 점**: Notion MCP `update_content` 는 단일 요청 페이로드가 커지면 외부 WAF/reverse-proxy 에 막힐 수 있음. 패치노트 엔트리는 **섹션당 3~5 bullet** 를 soft limit 으로. 더 큰 업데이트가 필요하면 여러 번의 작은 `update_content` 로 분할하거나, 섹션 기준 분할. 재발 방지: 이미 메모리(`feedback_patchnotes_payload.md`)에 규칙화돼 있으나 lesson 으로도 남겨 다음 유지보수 세션이 읽을 수 있게.

## [2026-04-20] RAG 청킹은 문자 기준이 아니라 문장 단위 greedy + 문장 단위 overlap
**시도**: 초안에서 `chunk_size=500`, `chunk_overlap=50` 을 단순 문자 슬라이딩 윈도우로 구현 (많은 RAG 튜토리얼의 기본 패턴).
**결과**: 플랜 리뷰에서 "문장 중간이 잘리거나 문단 의미가 부자연스럽게 중복"될 수 있다는 지적. 특히 한글은 종결어미가 뒤에 오는 구조라 문자 중간 cut 시 의미 단위 파손이 더 큼. bge-m3 retrieval 품질이 chunker 에서 크게 갈린다는 관찰.
**배운 점**: **문장을 1차 단위로 greedy 패킹**하고, 다음 청크의 **overlap 도 문장 단위 tail** 로 구성. 단일 문장이 `chunk_size` 를 넘길 때만 예외적으로 문자 단위 hard-split + 문자 overlap fallback. 문장 경계는 `[.!?。！？]\s+` + `\n\s*\n` (단락 boundary). 구현: `src/rag/chunker.py` `chunk_document()`. 회귀: `tests/test_chunker.py` 12건 (문장 오버랩, 긴 문장 fallback, 한글 단락 분리, chunk_overlap=0, 공용 필드 전파, id 유니크). 전처리 normalize (`normalize_content`) 도 이 단계에서 통일해 해시 안정화까지 같이 잡음.

## [2026-04-28] DO NOT 룰 새 모듈 (`src/core/scoring.py`) 에서도 재발 (3번째)
**시도**: Phase 9.1 `src/core/scoring.py` 신설 시 `from src.config.loader import load_tier_rules_config, load_weights_config` 로 함수 직접 import. 테스트 (`tests/test_scoring.py`) 가 `monkeypatch.setattr(_loader, "load_weights_config", ...)` 로 yaml 로딩 가짜화 시도.
**결과**: 13건 중 4건 fail. scoring 모듈이 import 시점에 함수 참조 고정해서 monkeypatch 가 안 먹음 — 2026-04-21 (graph/nodes), 2026-04-22 (api/routes) 에 이미 본 함정의 3번째 재발. CLAUDE.md DO NOT 룰이 graph/pipeline/api/orchestration 계층 명시했지만, 새 core 모듈 작성 시 무심코 재발.
**배운 점**: DO NOT 룰의 적용 영역은 "patch 대상 + 부수효과 있는 외부 호출 + orchestration 계층" 에서 실은 "**테스트가 monkeypatch 하는 모든 외부 의존성**" 으로 확장. core/ 같은 신규 모듈도 yaml 로딩·외부 호출·LLM 클라이언트 등을 import 할 때마다 무조건 모듈 경유 (`from src.config import loader as _loader` + `_loader.load_X()`). 새 모듈 작성 시 첫 import 단계에서 자문: "이 함수가 테스트에서 monkeypatch 될 가능성이 있나?" — 답이 "예" 거나 모르겠으면 모듈 경유. 의식적으로 하지 않으면 또 재발할 패턴이라 새 모듈 추가 시 이 lesson grep 후 진행.

## [2026-04-28] Auto-normalize 한 weight 와 정수 score 곱이 threshold 정확 비교 시 float drift
**시도**: Phase 9.1 scoring 엔진. `weights.yaml::products.databricks` override 합 1.10 → auto-normalize → 각 weight = 사용자값 / 1.10. `decide_tier(7.0, rules)` 검증.
**결과**: scores=[7,7,7,7,7,7] 인 후보가 final_score = 7 × sum(normalized weights) = 7 × 1.0 = 7.0 으로 나와야 하는데 실측 6.999999999999999. tier_rules 의 A 임계값이 7.0 인데 `7.0 >= 7.0` 비교가 `False` 로 떨어져 B 로 강등 (smoke test 에서 발견).
**배운 점**: float 곱·합산이 손실 없이 라운드 트립 안 되는 일반 케이스 (0.1 + 0.1 + 0.1 != 0.3 와 같은 부류). threshold 기반 결정 함수는 **항상 epsilon 허용** — `final_score >= threshold - 1e-6` 형태. 사용자가 yaml 에 `8.0` 같은 깔끔한 정수 threshold 를 쓸 거니까 코드도 그 의도 그대로 매치되게 만들어야지, "사용자가 7.0 이라 했으니 정확히 7.0 이상" 같은 strict 비교는 normalize·weighted-sum 경로에서 거의 항상 깨짐. 일반화: 정수 입력으로 시작했어도 중간에 division / sum 이 한 번이라도 들어가면 threshold 비교 시 epsilon 필요. 단, `==` 비교는 절대 X (epsilon 도 무용지물 패턴 — `>=`/`<=` 만 안전).

## [2026-04-28] Phase 9 첫 산출의 theoretical-fit 편향 → scoring 분리로 fix
**시도**: Phase 9 RAG-only target discovery MVP 를 Sonnet 1회 호출로 25 후보 (5 산업 × 5 회사) tier 직접 판정. prompt 에 "S = direct trigger / A = strong fit / B = adjacent / C = long-shot" 추상 정의.
**결과**: 8 S / 10 A / 7 B / 0 C. JPMorgan / Goldman / Amazon / Walmart / NVIDIA 같은 Fortune-500 mega-cap 위주 + Snowflake (직접 경쟁사) A tier + 한국 기업 0개. "이론상 데이터 핏" 으로 판정했지만 실제 영업 어려운 회사 (AWS 본체·자체 플랫폼 lock-in) 가 상위 점거. C tier 부재로 Strategic Edge 인지 안 됨. 외부 어드바이저 피드백: "콜드콜은 데이터 규모가 아니라 landability (받아줄 조직·예산·대체 가능성) 가 결정. weight.yaml 분리 강추".
**배운 점**: prompt 정교화로 fix 시도 전에 **결정 가능한 수치를 코드로 빼낼 수 있는지** 먼저 검토. LLM 의 역할을 "tier 직접 판단" → "6 차원 0-10 점수" 로 좁히고, final_score / tier 는 코드가 weighted sum + threshold rule 로 결정. 결과 (Phase 9.1 재실행): mega-cap S 사라짐, mid-cap (Stripe / Adyen / Tempus AI) S 진입, 한국 기업 7개 진입, Snowflake → B 강등. 같은 LLM 응답을 다른 weight 로 재계산하면 비용 0. 일반 원칙: **LLM hallucination 을 prompt 로 누르려 하지 말고, 결정 가능한 부분을 격리해라**. playbook.md #14 로 재사용 패턴 등록.

## [2026-04-28] 공유 `_extract_json` 의 array-first 우선순위가 dict 호출자에서 inner list 만 잡음
**시도**: Phase 9 `parse_discovery` 에서 Sonnet 의 `{"industry_meta": {...}, "candidates": [...]}` 응답을 파싱하려고 `proposal_schemas._extract_json` 재사용. prose 가 섞인 응답 ("Here you go: {...} Let me know.") 에 대한 회귀 테스트 추가.
**결과**: `_extract_json` 이 4단 fallback 중 `_ARRAY_RE` (`\[.*\]`) 를 `_OBJECT_RE` (`\{.*\}`) 보다 **먼저** 시도하기 때문에, top-level 이 dict 인 응답에서도 `candidates` 의 inner list 만 매치되어 list 가 반환됨. parse_discovery 의 dict 검증에서 `expected JSON object ... got list` 로 실패. 기존 호출자 (`parse_proposal_points`) 는 top-level list 를 기대하니 문제없었지만, dict 호출자에선 의미가 정반대.
**배운 점**: 4단 fallback util 의 array vs object **우선순위는 호출자 스키마에 종속** — 공유 util 을 수정하면 기존 list 호출자가 깨지므로, **dict 호출자는 자기만의 thin helper** 를 만든다. `src/core/discover_types.py::_extract_json_object` (raw → fenced → object 만 시도) 로 분기. 일반화: regex-greedy + try-parse-each 방식의 4단 fallback 은 구조가 같아 보이지만 첫 매치가 곧 결과라 호출자 schema 별로 다른 우선순위 helper 가 필요할 수 있다. 공유 util 의 docstring 에 "list 우선" 을 명시해 다음 사람이 같은 함정을 안 밟게.

## [2026-04-28] 새 LLM step 에 기존 `max_tokens` setting 재사용 → output truncate 로 양쪽 시도 다 실패
**시도**: Phase 9 discover 가 `chat_cached(..., max_tokens=settings.llm.claude_max_tokens_synthesize)` 로 호출. synthesize 와 입력 패턴이 비슷해서 같은 `max_tokens=2000` setting 재사용한 것이 자연스러워 보였음.
**결과**: 실제 1회 실행에서 두 번 다 `ValueError: discover_targets failed after 2 attempts: no JSON found in discovery output`. 디버그로 raw 응답 캡처해 보니 output_tokens=2511 / 2852 — synthesize 는 5 ProposalPoint (~1.5K out) 라 2000 cap 으로 충분했지만, discover 는 5 산업 + 25 후보 + 각 1~2문장 rationale 합산이 ~2.5K out 으로 일관되게 cap 초과. JSON 이 닫히지 않은 상태로 잘려 두 번째 retry 도 같은 사이즈로 실패.
**배운 점**: 새 LLM step 추가 시 입력 패턴이 비슷해도 **output 분포는 별도 추정** 후 setting 키 신설. `claude_max_tokens_discover=4000` 추가 (synthesize 2000 / draft 4000 / discover 4000). 추정 공식 안내: `n_items × (avg rationale tokens + structural overhead) × 1.3 safety`. 25 × (~80 + 20) × 1.3 ≈ 3300 → 4000 round up. retry 가 truncate 된 응답을 다시 truncate 만 하므로 max_tokens 부족은 retry 로 못 구함 — sched 인자 자체가 문제일 때 retry 는 무력화.

## [2026-04-28] dict iteration 순서가 set-init 으로 비결정 → pytest 어설션 flake
**시도**: `parse_discovery` 의 industry-distribution 검증에서 `industry_keys = set(industry_meta.keys())` + `counts: dict[str, int] = {k: 0 for k in industry_keys}`. 잘못된 분포 ('a':3, 'b':1) 에 대해 `pytest.raises(ValueError, match="industry 'a' has 3")` 로 어설션.
**결과**: 같은 입력으로 첫 실행은 'a' 가 raise 되어 통과, 다음 실행은 'b' 가 먼저 검사되어 "industry 'b' has 1 candidates, expected 2" 가 raise 되어 어설션 실패. set 의 iteration 순서가 hash 기반 비결정이라 dict 의 순서 (set comprehension 거치면 set 의 순서 계승) 도 비결정.
**배운 점**: dict 의 안정적 순서 (insertion order, Python 3.7+) 를 활용하려면 **dict 자체의 키를 직접 순회** (`for ind in industry_meta`) 해야 함. set 을 중간에 거치면 순서가 무효화됨. 이 패턴은 sorted-needed 가 아니라 단순히 "원본 입력 순서" 가 정답일 때 유효 — 정렬 필요한 경우엔 명시적 `sorted()` 가 더 안전. 일반화: 검증 / 에러 메시지 / 테스트 어설션이 dict 의 순서에 의존한다면, 그 dict 가 어디서 어떻게 만들어졌는지 거꾸로 추적해서 set 경유 여부 확인.

## [2026-04-28] Phase 8 multi-channel 39 기사 dedup 시 RTX 4070 16GB OOM
**시도**: 채널 cap 합 = 40 (target 20 + related 15 + competitor 5) 으로 search_node 다중 채널화. preprocess 의 dedup 단계가 `embed_texts(texts)` 를 batch_size 미지정 default 로 호출 → 39 articles × 평균 ~3500 자 body 한 번에 임베딩.
**결과**: 첫 풀 스모크 시 `torch.OutOfMemoryError: Tried to allocate 5.60 GiB. GPU 0 has a total capacity of 15.99 GiB ... 19.80 GiB is allocated by PyTorch`. Exaone 4bit (~6GB) 가 GPU 점유 중에 bge-m3 가 39 sequence batch 를 한 번에 올리려다 OOM. Phase 5 의 20-기사 baseline 에서는 안 보이던 회귀.
**배운 점**: 채널이 늘어 raw input 이 2배가 되면 dedup embedding 의 GPU 압박이 비선형으로 폭증. 세 가지 안전 장치 동시 적용:
1. `embed_texts(..., batch_size=8)` — 한 번에 올리는 sequence 수 cap. 16GB 카드에서 Exaone + bge-m3 공존 가능한 보수값.
2. dedup 입력 텍스트 첫 3000 자 truncate — 임베딩 의미는 lede / 첫 단락에 거의 다 있고, 0.90 threshold 의 dedup 정확도에는 영향 미미.
3. dedup 직전 `torch.cuda.empty_cache()` — Exaone 이 남긴 fragmented block 회수.
plan 의 위험 분석에서 정확히 예측한 케이스 (cap 합 40 vs RTX 4070 16GB) — **사전 분석한 위험은 fixture/CI 로 회귀 잠그지 않으면 1회는 반드시 발생함**. 향후 채널 cap 늘릴 때 batch_size·truncate 도 같이 재계산. 구현: `src/rag/embeddings.py::embed_texts` / `dedup_articles`. 기존 `tests/test_dedup.py` 7건 무영향 (작은 배치라 cap 무관).


## [2026-04-30] FastAPI lifespan 의 자동 마이그레이션이 테스트 중에 실제 사용자 data/ 를 건드렸다
**시도**: Phase 10 P10-2a 에서 `migrate_flat_layout(vectorstore_root, company_docs_root)` 을 `app.py::lifespan` 에 best-effort 로 호출. 환경변수 토글 없이 바로 동작.
**결과**: pytest 실행 중 `tests/test_api_db.py::test_lifespan_initializes_app_db` 등 `create_app()` 을 호출하는 테스트가 lifespan 까지 깨우면서, `PROJECT_ROOT / "data" / "vectorstore"` (절대 경로) 의 실제 평면 layout 을 `data/vectorstore/default/` 로 이동시켰다. 다행히 마이그레이션 함수가 idempotent + dest.exists() skip 이라 손실은 없었지만, 테스트가 사용자 데이터를 건드릴 수 있다는 점은 위험 신호.
**배운 점**: FastAPI lifespan 의 자동 마이그레이션 같은 "환경을 mutating" 하는 부수효과는 (1) 환경변수 toggle 로 default off 하거나 (2) 테스트 fixture 가 PROJECT_ROOT 를 override 가능하도록 인자화하거나 (3) 명시적 CLI 명령으로만 트리거. 본 케이스는 1회성 마이그레이션이라 큰 후속 처리는 안 했지만, 향후 비슷한 mutation 코드가 lifespan 에 들어가면 `os.environ.get("APP_AUTO_MIGRATE", "0") == "1"` 같은 가드를 default 로 채택. 또 마이그레이션 함수 자체는 idempotent + best-effort + dest 보존 (overwrite 금지) 가 필수 — 이 세 가지 덕분에 사고가 손실로 이어지지 않았다.
