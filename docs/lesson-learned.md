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

## [2026-04-20] RAG 청킹은 문자 기준이 아니라 문장 단위 greedy + 문장 단위 overlap
**시도**: 초안에서 `chunk_size=500`, `chunk_overlap=50` 을 단순 문자 슬라이딩 윈도우로 구현 (많은 RAG 튜토리얼의 기본 패턴).
**결과**: 플랜 리뷰에서 "문장 중간이 잘리거나 문단 의미가 부자연스럽게 중복"될 수 있다는 지적. 특히 한글은 종결어미가 뒤에 오는 구조라 문자 중간 cut 시 의미 단위 파손이 더 큼. bge-m3 retrieval 품질이 chunker 에서 크게 갈린다는 관찰.
**배운 점**: **문장을 1차 단위로 greedy 패킹**하고, 다음 청크의 **overlap 도 문장 단위 tail** 로 구성. 단일 문장이 `chunk_size` 를 넘길 때만 예외적으로 문자 단위 hard-split + 문자 overlap fallback. 문장 경계는 `[.!?。！？]\s+` + `\n\s*\n` (단락 boundary). 구현: `src/rag/chunker.py` `chunk_document()`. 회귀: `tests/test_chunker.py` 12건 (문장 오버랩, 긴 문장 fallback, 한글 단락 분리, chunk_overlap=0, 공용 필드 전파, id 유니크). 전처리 normalize (`normalize_content`) 도 이 단계에서 통일해 해시 안정화까지 같이 잡음.
