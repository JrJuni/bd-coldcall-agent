# BD Cold-Call Agent — Web UI

Phase 7 MVP frontend. Next.js 15 App Router + Tailwind CSS + TypeScript.

Talks to the FastAPI backend in `src/api/` — base URL comes from
`NEXT_PUBLIC_API_BASE_URL` (defaults to `http://localhost:8000`).

## Dev

```bash
# From the repo root, in a terminal *outside* the Python env:
cd web
npm install
npm run dev           # http://localhost:3000
```

Start the FastAPI backend in a separate terminal:

```bash
~/miniconda3/envs/bd-coldcall/python.exe -m uvicorn src.api.app:app --reload
# or, to skip the Exaone warm-load during UI dev:
API_SKIP_WARMUP=1 ~/miniconda3/envs/bd-coldcall/python.exe -m uvicorn src.api.app:app --reload
```

## Pages

- `/` — landing form (company / industry / language) → `POST /runs`, redirects to run detail
- `/runs/[id]` — SSE-bound progress (stages, errors, usage), renders the final
  Markdown proposal once the pipeline reports `completed`
- `/rag` — indexing status (reads `GET /ingest/status`), trigger button for
  `POST /ingest` (minimal MVP — upload / delete deferred to backlog)

## Out of scope (post-MVP)

Authentication, multi-user support, upload / delete UI, long-lived workers
(Celery/RQ), deployment configs. See `docs/status.md` 장기 과제.
