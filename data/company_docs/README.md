# Company Docs

당사 기술·제품·사례 문서를 이 폴더에 두면 RAG 인덱싱 대상이 됩니다. Phase 4 Sonnet 합성 노드가 이 문서에서 top-k 청크를 뽑아 `cache_control: ephemeral` 프롬프트 캐시로 사용합니다.

## 지원 형식
- Markdown (`.md`)
- 일반 텍스트 (`.txt`)
- PDF (`.pdf`) — pypdf 로 페이지별 추출 후 `[Page N]` 구분자 삽입

## 인덱싱

```bash
# 로컬 문서 최초/증분 인덱싱 (매니페스트 해시 비교)
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer

# 해시 무시하고 전체 재인덱싱
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --force

# 변경만 리포트 (store/manifest 안 건드림)
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --dry-run

# manifest ↔ 실제 store 정합성 체크
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --verify

# Notion 페이지·DB 포함
~/miniconda3/envs/bd-coldcall/python.exe -m src.rag.indexer --notion
```

## Notion 연동

1. <https://www.notion.so/my-integrations> → **New integration** → Internal → secret 복사
2. `.env` 의 `NOTION_TOKEN=secret_...` 채우기
3. 인덱싱할 페이지/DB 를 Notion UI 에서 `Add connections` 로 해당 integration 과 공유
4. `config/targets.yaml` 의 `rag.notion_page_ids` / `rag.notion_database_ids` 에 UUID 기입

## 동작 원리

- 각 문서를 `normalize_content → sha256` 해시 → `data/vectorstore/manifest.json` 에 저장
- 해시 동일: `skipped`, 변경: `updated`, 신규: `added`, 매니페스트에만 있고 이번 실행에서 안 보이면 `deleted`
- 커넥터별 격리: `--notion` 단독 실행은 로컬 문서를 삭제 대상에서 제외 (반대도 동일)
- 원자성: 임베딩 성공 후에야 store/manifest 를 건드림. embed 중 실패 → 상태 불변, 다음 실행에서 `updated` 로 재시도

## 주의

- 이 폴더의 실제 문서 파일은 `.gitignore` 처리돼 리포에 커밋되지 않습니다 (이 README 만 예외)
- 운영용 기술 문서는 Notion 에서 관리하고 로컬은 임시·스모크용으로 쓰는 것을 권장
