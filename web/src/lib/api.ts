import type {
  DiscoveryCandidate,
  DiscoveryCandidateUpdateInput,
  DiscoveryPromoteResponse,
  DiscoveryRecomputeInput,
  DiscoveryRecomputeResponse,
  DiscoveryRunCreateInput,
  DiscoveryRunDetail,
  DiscoveryRunListResponse,
  DiscoveryRunSummary,
  IngestStatus,
  IngestTriggerResponse,
  RagNamespaceListResponse,
  RunCreateResponse,
  RunSummary,
  Target,
  TargetCreateInput,
  TargetListResponse,
  TargetUpdateInput,
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

// ── Phase 10 P10-1 — Targets ────────────────────────────────────────────

export async function listTargets(): Promise<TargetListResponse> {
  const r = await fetch(`${API_BASE}/targets`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /targets ${r.status}`);
  return r.json();
}

export async function createTarget(body: TargetCreateInput): Promise<Target> {
  const r = await fetch(`${API_BASE}/targets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST /targets ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function getTarget(id: number): Promise<Target> {
  const r = await fetch(`${API_BASE}/targets/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /targets/${id} ${r.status}`);
  return r.json();
}

export async function patchTarget(
  id: number,
  body: TargetUpdateInput,
): Promise<Target> {
  const r = await fetch(`${API_BASE}/targets/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`PATCH /targets/${id} ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function deleteTarget(id: number): Promise<void> {
  const r = await fetch(`${API_BASE}/targets/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204)
    throw new Error(`DELETE /targets/${id} ${r.status}`);
}

// ── Phase 10 P10-2a — RAG namespaces ────────────────────────────────────

export async function listRagNamespaces(): Promise<RagNamespaceListResponse> {
  const r = await fetch(`${API_BASE}/rag/namespaces`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /rag/namespaces ${r.status}`);
  return r.json();
}

// ── Phase 10 P10-2b — Discovery ─────────────────────────────────────────

export async function createDiscoveryRun(
  body: DiscoveryRunCreateInput,
): Promise<DiscoveryRunSummary> {
  const r = await fetch(`${API_BASE}/discovery/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(`POST /discovery/runs ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function listDiscoveryRuns(): Promise<DiscoveryRunListResponse> {
  const r = await fetch(`${API_BASE}/discovery/runs`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /discovery/runs ${r.status}`);
  return r.json();
}

export async function getDiscoveryRun(
  runId: string,
): Promise<DiscoveryRunDetail> {
  const r = await fetch(
    `${API_BASE}/discovery/runs/${encodeURIComponent(runId)}`,
    { cache: "no-store" },
  );
  if (!r.ok) throw new Error(`GET /discovery/runs/${runId} ${r.status}`);
  return r.json();
}

export async function deleteDiscoveryRun(runId: string): Promise<void> {
  const r = await fetch(
    `${API_BASE}/discovery/runs/${encodeURIComponent(runId)}`,
    { method: "DELETE" },
  );
  if (!r.ok && r.status !== 204)
    throw new Error(`DELETE /discovery/runs/${runId} ${r.status}`);
}

export function discoveryEventsUrl(runId: string): string {
  return `${API_BASE}/discovery/runs/${encodeURIComponent(runId)}/events`;
}

export async function patchDiscoveryCandidate(
  id: number,
  body: DiscoveryCandidateUpdateInput,
): Promise<DiscoveryCandidate> {
  const r = await fetch(`${API_BASE}/discovery/candidates/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(
      `PATCH /discovery/candidates/${id} ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function deleteDiscoveryCandidate(id: number): Promise<void> {
  const r = await fetch(`${API_BASE}/discovery/candidates/${id}`, {
    method: "DELETE",
  });
  if (!r.ok && r.status !== 204)
    throw new Error(`DELETE /discovery/candidates/${id} ${r.status}`);
}

export async function recomputeDiscovery(
  runId: string,
  body: DiscoveryRecomputeInput,
): Promise<DiscoveryRecomputeResponse> {
  const r = await fetch(
    `${API_BASE}/discovery/runs/${encodeURIComponent(runId)}/recompute`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!r.ok)
    throw new Error(
      `POST /discovery/runs/${runId}/recompute ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function promoteDiscoveryCandidate(
  id: number,
): Promise<DiscoveryPromoteResponse> {
  const r = await fetch(`${API_BASE}/discovery/candidates/${id}/promote`, {
    method: "POST",
  });
  if (!r.ok)
    throw new Error(
      `POST /discovery/candidates/${id}/promote ${r.status}: ${await r.text()}`,
    );
  return r.json();
}
