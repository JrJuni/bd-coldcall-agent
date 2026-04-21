import type {
  IngestStatus,
  IngestTriggerResponse,
  RunCreateResponse,
  RunSummary,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export async function createRun(body: {
  company: string;
  industry: string;
  lang: "en" | "ko";
  top_k?: number;
}): Promise<RunCreateResponse> {
  const r = await fetch(`${API_BASE}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST /runs ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function getRun(runId: string): Promise<RunSummary> {
  const r = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`GET /runs/${runId} ${r.status}`);
  return r.json();
}

export async function getIngestStatus(): Promise<IngestStatus> {
  const r = await fetch(`${API_BASE}/ingest/status`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /ingest/status ${r.status}`);
  return r.json();
}

export async function triggerIngest(body: {
  notion: boolean;
  force: boolean;
  dry_run: boolean;
}): Promise<IngestTriggerResponse> {
  const r = await fetch(`${API_BASE}/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST /ingest ${r.status}`);
  return r.json();
}

export function sseUrl(runId: string): string {
  return `${API_BASE}/runs/${encodeURIComponent(runId)}/events`;
}
