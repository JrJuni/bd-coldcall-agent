# Phase 13 - Agent-first RFP vertical + Postgres migration

Working doc for the Phase 13 refactor. See
`.claude/plans/frolicking-growing-bubble.md` for the full plan.

## Sub-phases

- **13A** - RFP vertical on existing SQLite + minimal ORM island. Ships
  the FastMCP stdio server, two new ORM-native tables (`rfp_answers`,
  `notion_sync_map`), the Notion writer for the BDINT_Teamspace RFP Q&A
  database, and the end-to-end `answer_rfp_question` MCP tool.
- **13B** - Postgres migration. Port the existing 7 stores to ORM
  store-by-store, then cut over to Neon.
- **13C** - LangGraph PostgresSaver + RunStore persistence decision.

## Claude Desktop setup (13A)

Claude Desktop launches the MCP server as a subprocess. Edit
`claude_desktop_config.json` (Settings -> Developer -> Edit Config):

```json
{
  "mcpServers": {
    "bd-coldcall-agent": {
      "command": "C:\\Users\\JuniBecky\\miniconda3\\envs\\bd-coldcall\\python.exe",
      "args": [
        "C:\\Users\\JuniBecky\\Downloads\\bd-coldcall-agent\\main.py",
        "mcp"
      ]
    }
  }
}
```

After saving, restart Claude Desktop. The `version` tool should appear
under the bd-coldcall-agent server. Calling it returns a dict with the
app version, python version, platform, and git sha - that confirms the
conda env is wired up correctly.

## Notion integration setup (M5)

The BDINT workspace pair is already created:

- [BDINT_publicspace](https://www.notion.so/BDINT_publicspace-365b5106a4a780e1a87df08587aa293e)
  - Curated knowledge layer. Written to in Phase 13.5+.
- [BDINT_Teamspace](https://www.notion.so/BDINT_Teamspace-365b5106a4a7805198d4e5a09b82badd)
  - Working / evaluation layer. Phase 13A writes RFP draft answers here.

For each workspace:

1. Visit <https://www.notion.so/my-integrations>, create an internal
   integration (one per workspace), copy the secret.
2. Put the secrets in `.env`:
   ```
   NOTION_TEAMSPACE_TOKEN=secret_xxx
   NOTION_PUBLICSPACE_TOKEN=secret_yyy
   ```
3. In Notion, open the BDINT root page for each workspace -> `...` ->
   Connections -> add the matching integration. This grants the
   integration access to the page and all its children.
4. Copy the root page IDs into `config/notion.yaml` (gitignored - copy
   `config/notion.example.yaml` and fill in real values).
5. Run `python scripts/bootstrap_notion.py` (M5) - it scans for the
   RFP Q&A database under each root page and creates it if missing,
   writing the database ID back into `config/notion.yaml`.

## Database setup

### SQLite (default)

No setup needed - `data/app.db` is created on first boot. Run migrations:

```bash
~/miniconda3/envs/bd-coldcall/python.exe -m alembic upgrade head
```

### Postgres (13B+)

Sign up for Neon free tier, create a project, copy the pooled URL into
`.env`:

```
DATABASE_URL=postgresql+psycopg://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require
```

Then `alembic upgrade head` again - the same migrations run on both
engines thanks to the `JSON().with_variant(JSONB, "postgresql")` pattern
in `src/api/orm.py`.

### Neon cutover procedure (M7d)

The migration script copies every Phase 13 ORM-mapped table from the
SQLite `data/app.db` to the configured Neon Postgres URL.

1. **Backup the SQLite file.** Copy `data/app.db` somewhere safe; M7d is
   reversible only as long as that file is intact.

2. **Prepare the destination schema.** With `DATABASE_URL` pointing at
   Neon, run:
   ```bash
   DATABASE_URL=postgresql+psycopg://... \
     ~/miniconda3/envs/bd-coldcall/python.exe -m alembic upgrade head
   ```
   That brings the Neon DB to revision 0004_discovery_news.

3. **Dry-run the copy.** This prints per-table row counts from both
   ends without inserting anything:
   ```bash
   ~/miniconda3/envs/bd-coldcall/python.exe scripts/migrate_sqlite_to_postgres.py \
     --source sqlite:///data/app.db \
     --target "postgresql+psycopg://...neon.tech/neondb?sslmode=require"
   ```

4. **Apply the copy.** Add `--apply`. If the Neon DB had stub rows from
   an earlier attempt, also add `--force-empty-target` (drops existing
   rows in each destination table before inserting):
   ```bash
   ~/miniconda3/envs/bd-coldcall/python.exe scripts/migrate_sqlite_to_postgres.py \
     --source sqlite:///data/app.db \
     --target "postgresql+psycopg://...neon.tech/neondb?sslmode=require" \
     --apply
   ```
   The script copies in dependency order (workspaces -> rag_summaries ->
   discovery -> targets / interactions -> news -> rfp), bumps SERIAL
   sequences to MAX(id), and commits in 500-row batches.

5. **Flip the env.** With `DATABASE_URL` set to the Neon URL, restart
   the FastAPI / MCP server. Verify Web UI smoke (`/targets`,
   `/interactions`, `/discovery`, `/news`, `/cost`, `/dashboard` all
   show the SQLite-time data).

6. **Rollback path.** Remove `DATABASE_URL` from `.env` (or set it back
   to `sqlite:///data/app.db`) and restart. The SQLite file is
   unchanged by the copy step.

## RunStore persistence decision (M9)

**Decision: Option (c) Hybrid.** In-flight runs stay in the
process-local `RunStore` dict (with its per-record event log + lock).
When a run transitions to a terminal status (`completed` or `failed`),
`RunStore.update` writes a metadata snapshot to the new `runs` table.

**Options considered:**

| Option | Description | Why rejected / picked |
|---|---|---|
| (a) DB-persist everything | A `runs` table + `run_events` table; every event INSERT flows through SQL. Survives restarts including in-flight resume. | Rejected. The event log churns at ~10–20 rows per run; persisting it would force a connection per stage transition and add a lot of surface (live SSE consumers reading from DB). Phase 13's narrative is "agent-first MCP+Notion" — Web UI is observability, not a system of record, so cross-restart in-flight resume isn't worth the cost. |
| (b) Scope reduction | Accept that process restart loses all run history. Mark legacy in-flight runs as 'orphaned' on next list. | Rejected. After the 13B dual-engine ORM investment, having the Web UI's `/runs` page silently lose history on every restart felt regressive. There would also be no in-memory state to "mark as orphaned" — the dict starts empty. |
| **(c) Hybrid** | In-flight = in-memory dict. Terminal-status transitions write a snapshot to a `runs` table. The Web UI run-history page reads the table for durability; in-flight runs come from the dict. | **Picked.** Minimum extra surface (one ORM model, one Alembic migration, one hook in `RunStore.update`). Persistence failures don't bubble — the in-memory record is authoritative; the DB row is purely the survive-restart artifact. |

**Minimum implementation:**

- `src/api/models/run.py` — `Run` ORM model (run-record snapshot, no event log).
- `alembic/versions/0005_runs.py` — idempotent table creation.
- `src/api/store.py::RunStore` — accepts an optional `session_factory`;
  `update()` persists when `record.status in {"completed", "failed"}`.
  `list_persisted()` returns rows newest-first; helper for the route layer.
- `src/api/store.py::get_run_store()` — wires the singleton to
  `_orm.get_session_factory()` so the FastAPI process has durable
  history by default.
- `src/api/routes/runs.py::list_runs_history` — new
  `GET /runs/history?limit=N` endpoint surfaces the persisted snapshots
  without changing the semantics of the existing `/runs` (in-flight)
  list. The Web UI can adopt this as a follow-up.
- `tests/test_run_persistence_phase13c.py` — 6 cases covering:
  in-flight ≠ persisted, terminal write, post-terminal update overwrite,
  failed-run errors persistence, list ordering, factory-less fallback.

**Out of scope for this milestone (deliberate):**

- Merging `/runs` (in-flight) with `/runs/history` (persisted) at the
  route layer.
- Persisting the per-record event log.
- "Orphaned" relabeling of pre-restart in-flight runs (they were never
  in the dict after restart, so there's nothing to relabel).

## Verification matrix

| When | Check |
|---|---|
| After M1 | `alembic current` runs without error; pytest still passes |
| After M2 | `alembic upgrade head` creates `rfp_answers` and `notion_sync_map`; `tests/test_api_orm_phase13a.py` passes |
| After M3 | Claude Desktop lists the `version` tool; calling it returns a dict |
| After M4 | Claude Desktop lists `query_rag`; calling it returns chunks from the existing RAG index |
| After M5 | A pytest fixture can create + update a Teamspace RFP Q&A page (or sandbox equivalent) idempotently |
| After M6 | One Claude Desktop call to `answer_rfp_question` produces a cited answer, an `rfp_answers` row, and a Teamspace page |
| After M7a | `alembic upgrade head` reaches 0002 on both fresh and `init_db`-seeded SQLite; workspaces / rag-summary tests pass via the new ORM stores |
| After M7b | 0003 applies cleanly on both engines; targets + interactions tests pass via ORM; Web UI nav shows a "legacy" badge next to /targets and /interactions |
| After M7c | 0004 applies cleanly; discovery + news tests pass via ORM; `_db.connect` is no longer referenced from `src/api/store.py` |
| After M7d | `scripts/migrate_sqlite_to_postgres.py --apply` copies SQLite -> Neon with row counts matching; Web UI smoke (`/targets`, `/interactions`, `/discovery`, `/news`, `/cost`, `/dashboard`) shows pre-cutover data |
| After M8  | `tests/test_checkpoint_dispatch.py` passes; with `DATABASE_URL=postgresql+psycopg://...` the lifespan log shows `checkpoint: PostgresSaver`. Graph-level resume verified manually against Neon (LangGraph thread_id picks up the last checkpoint after a deliberate kill / restart cycle). |
| After M9  | `tests/test_run_persistence_phase13c.py` passes; one completed run via `POST /runs` writes one row to `runs`; `GET /runs/history` returns it after a FastAPI restart. |
| After M10 | `README.md` headline reads "agent-first / MCP" rather than "Web UI / CRM"; CLAUDE.md mentions the Phase 13 architecture; `docs/status.md` reflects Phase 13A/B/C completion. |
