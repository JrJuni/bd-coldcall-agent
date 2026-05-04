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
  Interaction,
  InteractionCreateInput,
  InteractionListResponse,
  InteractionUpdateInput,
  NewsRefreshInput,
  NewsRefreshResponse,
  NewsRunDetail,
  DashboardResponse,
  CostSummaryResponse,
  ActiveModelView,
  RagDocumentListResponse,
  RagDocumentUploadResponse,
  RagFolderActionResponse,
  RagNamespaceDeleteResponse,
  RagNamespaceListResponse,
  RagNamespaceSummary,
  RagOpenFolderResponse,
  RagRootFileListResponse,
  RagRootOpenResponse,
  RagSummaryCachedResponse,
  RagSummaryRequestInput,
  RagSummaryResponse,
  RagTreeResponse,
  DiscoveryProductsResponse,
  RegionsConfig,
  RunCreateResponse,
  SecretsView,
  SettingsKind,
  SettingsKindList,
  SettingsRead,
  RunSummary,
  Target,
  TargetCreateInput,
  TargetListResponse,
  TargetUpdateInput,
  Workspace,
  WorkspaceListResponse,
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

export async function listRuns(): Promise<{ runs: RunSummary[] }> {
  const r = await fetch(`${API_BASE}/runs`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /runs ${r.status}`);
  return r.json();
}

export async function patchRun(
  runId: string,
  body: { proposal_md?: string },
): Promise<RunSummary> {
  const r = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(`PATCH /runs/${runId} ${r.status}: ${await r.text()}`);
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
  workspace?: string;
  namespace?: string;
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

// ── Phase 11 P11-0/2 — Workspaces (multi-root RAG) ─────────────────────

export async function listWorkspaces(): Promise<WorkspaceListResponse> {
  const r = await fetch(`${API_BASE}/workspaces`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /workspaces ${r.status}`);
  return r.json();
}

export async function createWorkspace(body: {
  label: string;
  abs_path: string;
}): Promise<Workspace> {
  const r = await fetch(`${API_BASE}/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(`POST /workspaces ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function patchWorkspace(
  workspaceId: number,
  body: { label?: string },
): Promise<Workspace> {
  const r = await fetch(`${API_BASE}/workspaces/${workspaceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(
      `PATCH /workspaces/${workspaceId} ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function deleteWorkspace(
  workspaceId: number,
  opts?: { wipe_index?: boolean },
): Promise<void> {
  const qs = opts?.wipe_index ? "?wipe_index=true" : "";
  const r = await fetch(`${API_BASE}/workspaces/${workspaceId}${qs}`, {
    method: "DELETE",
  });
  if (!r.ok && r.status !== 204)
    throw new Error(
      `DELETE /workspaces/${workspaceId} ${r.status}: ${await r.text()}`,
    );
}

// ── Phase 10 P10-2a — RAG namespaces (now ws-prefixed) ──────────────────

const _wsBase = (slug: string) =>
  `${API_BASE}/rag/workspaces/${encodeURIComponent(slug)}`;

export async function listRagNamespaces(
  wsSlug: string = "default",
): Promise<RagNamespaceListResponse> {
  const r = await fetch(`${_wsBase(wsSlug)}/namespaces`, {
    cache: "no-store",
  });
  if (!r.ok)
    throw new Error(`GET ${_wsBase(wsSlug)}/namespaces ${r.status}`);
  return r.json();
}

// ── Phase 10 P10-3 — RAG documents ──────────────────────────────────────

export async function createRagNamespace(
  wsSlug: string,
  name: string,
): Promise<RagNamespaceSummary> {
  const r = await fetch(`${_wsBase(wsSlug)}/namespaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok)
    throw new Error(
      `POST ${_wsBase(wsSlug)}/namespaces ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function deleteRagNamespace(
  wsSlug: string,
  name: string,
  opts?: { force?: boolean },
): Promise<RagNamespaceDeleteResponse> {
  const qs = opts?.force ? "?force=true" : "";
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(name)}${qs}`,
    { method: "DELETE" },
  );
  if (!r.ok)
    throw new Error(
      `DELETE ${_wsBase(wsSlug)}/namespaces/${name} ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function listRagDocuments(
  wsSlug: string,
  namespace: string,
): Promise<RagDocumentListResponse> {
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/documents`,
    { cache: "no-store" },
  );
  if (!r.ok)
    throw new Error(
      `GET ${_wsBase(wsSlug)}/namespaces/${namespace}/documents ${r.status}`,
    );
  return r.json();
}

export async function uploadRagDocument(
  wsSlug: string,
  namespace: string,
  file: File,
  path: string = "",
): Promise<RagDocumentUploadResponse> {
  const fd = new FormData();
  fd.append("file", file, file.name);
  if (path) fd.append("path", path);
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/documents`,
    { method: "POST", body: fd },
  );
  if (!r.ok)
    throw new Error(
      `POST ${_wsBase(wsSlug)}/namespaces/${namespace}/documents ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function deleteRagDocument(
  wsSlug: string,
  namespace: string,
  filename: string,
): Promise<void> {
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/documents/${filename
      .split("/")
      .map(encodeURIComponent)
      .join("/")}`,
    { method: "DELETE" },
  );
  if (!r.ok && r.status !== 204)
    throw new Error(
      `DELETE ${_wsBase(wsSlug)}/namespaces/${namespace}/documents/${filename} ${r.status}`,
    );
}

function encodeSubpath(p: string): string {
  return p.split("/").map(encodeURIComponent).join("/");
}

export async function listRagTree(
  wsSlug: string,
  namespace: string,
  path: string = "",
): Promise<RagTreeResponse> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : "";
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/tree${qs}`,
    { cache: "no-store" },
  );
  if (!r.ok)
    throw new Error(
      `GET ${_wsBase(wsSlug)}/namespaces/${namespace}/tree ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function createRagFolder(
  wsSlug: string,
  namespace: string,
  path: string,
): Promise<RagFolderActionResponse> {
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/folders`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    },
  );
  if (!r.ok)
    throw new Error(
      `POST ${_wsBase(wsSlug)}/namespaces/${namespace}/folders ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function deleteRagFolder(
  wsSlug: string,
  namespace: string,
  path: string,
): Promise<RagFolderActionResponse> {
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/folders/${encodeSubpath(path)}`,
    { method: "DELETE" },
  );
  if (!r.ok)
    throw new Error(
      `DELETE ${_wsBase(wsSlug)}/namespaces/${namespace}/folders/${path} ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function openRagFolder(
  wsSlug: string,
  namespace: string,
  path: string = "",
): Promise<RagOpenFolderResponse> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : "";
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/open${qs}`,
    { method: "POST" },
  );
  if (!r.ok)
    throw new Error(
      `POST ${_wsBase(wsSlug)}/namespaces/${namespace}/open ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function openRagRoot(
  wsSlug: string,
): Promise<RagRootOpenResponse> {
  const r = await fetch(`${_wsBase(wsSlug)}/root/open`, { method: "POST" });
  if (!r.ok)
    throw new Error(
      `POST ${_wsBase(wsSlug)}/root/open ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function listRootFiles(
  wsSlug: string,
): Promise<RagRootFileListResponse> {
  const r = await fetch(`${_wsBase(wsSlug)}/root/files`, {
    cache: "no-store",
  });
  if (!r.ok)
    throw new Error(
      `GET ${_wsBase(wsSlug)}/root/files ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function uploadRootFile(
  wsSlug: string,
  file: File,
): Promise<RagDocumentUploadResponse> {
  const fd = new FormData();
  fd.append("file", file, file.name);
  const r = await fetch(`${_wsBase(wsSlug)}/root/files`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok)
    throw new Error(
      `POST ${_wsBase(wsSlug)}/root/files ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function deleteRootFile(
  wsSlug: string,
  filename: string,
): Promise<void> {
  const r = await fetch(
    `${_wsBase(wsSlug)}/root/files/${encodeURIComponent(filename)}`,
    { method: "DELETE" },
  );
  if (!r.ok && r.status !== 204)
    throw new Error(
      `DELETE ${_wsBase(wsSlug)}/root/files/${filename} ${r.status}: ${await r.text()}`,
    );
}

export async function getCachedRagSummary(
  wsSlug: string,
  namespace: string,
  path: string = "",
): Promise<RagSummaryCachedResponse> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : "";
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/summary${qs}`,
    { cache: "no-store" },
  );
  if (!r.ok)
    throw new Error(
      `GET ${_wsBase(wsSlug)}/namespaces/${namespace}/summary ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function summarizeRagPath(
  wsSlug: string,
  namespace: string,
  body: RagSummaryRequestInput = {},
): Promise<RagSummaryResponse> {
  const r = await fetch(
    `${_wsBase(wsSlug)}/namespaces/${encodeURIComponent(namespace)}/summary`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: body.path ?? "",
        lang: body.lang ?? "ko",
        sample_size: body.sample_size ?? 20,
        max_tokens: body.max_tokens ?? 900,
      }),
    },
  );
  if (!r.ok)
    throw new Error(
      `POST ${_wsBase(wsSlug)}/namespaces/${namespace}/summary ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

// ── Phase 10 P10-5 — Daily News ────────────────────────────────────────

export async function refreshNews(
  body: NewsRefreshInput,
): Promise<NewsRefreshResponse> {
  const r = await fetch(`${API_BASE}/news/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(`POST /news/refresh ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function getNewsToday(
  namespace: string,
): Promise<NewsRunDetail | null> {
  const r = await fetch(
    `${API_BASE}/news/today?namespace=${encodeURIComponent(namespace)}`,
    { cache: "no-store" },
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GET /news/today ${r.status}`);
  return r.json();
}

export async function getNewsRun(taskId: string): Promise<NewsRunDetail> {
  const r = await fetch(
    `${API_BASE}/news/runs/${encodeURIComponent(taskId)}`,
    { cache: "no-store" },
  );
  if (!r.ok) throw new Error(`GET /news/runs/${taskId} ${r.status}`);
  return r.json();
}

// ── Phase 10 P10-6 — Interactions (사업 기록) ────────────────────────

export async function listInteractions(opts?: {
  company?: string;
  q?: string;
  target_id?: number;
  limit?: number;
}): Promise<InteractionListResponse> {
  const qs = new URLSearchParams();
  if (opts?.company) qs.set("company", opts.company);
  if (opts?.q) qs.set("q", opts.q);
  if (opts?.target_id != null)
    qs.set("target_id", String(opts.target_id));
  if (opts?.limit != null) qs.set("limit", String(opts.limit));
  const url = qs.toString()
    ? `${API_BASE}/interactions?${qs.toString()}`
    : `${API_BASE}/interactions`;
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /interactions ${r.status}`);
  return r.json();
}

export async function createInteraction(
  body: InteractionCreateInput,
): Promise<Interaction> {
  const r = await fetch(`${API_BASE}/interactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(`POST /interactions ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function patchInteraction(
  id: number,
  body: InteractionUpdateInput,
): Promise<Interaction> {
  const r = await fetch(`${API_BASE}/interactions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(
      `PATCH /interactions/${id} ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function deleteInteraction(id: number): Promise<void> {
  const r = await fetch(`${API_BASE}/interactions/${id}`, {
    method: "DELETE",
  });
  if (!r.ok && r.status !== 204)
    throw new Error(`DELETE /interactions/${id} ${r.status}`);
}

// ── Phase 10 P10-7 — Settings ──────────────────────────────────────────

export async function listSettingsKinds(): Promise<SettingsKindList> {
  const r = await fetch(`${API_BASE}/settings`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /settings ${r.status}`);
  return r.json();
}

export async function getSettings(kind: SettingsKind): Promise<SettingsRead> {
  const r = await fetch(`${API_BASE}/settings/${encodeURIComponent(kind)}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`GET /settings/${kind} ${r.status}`);
  return r.json();
}

export async function putSettings(
  kind: SettingsKind,
  rawYaml: string,
): Promise<SettingsRead> {
  const r = await fetch(`${API_BASE}/settings/${encodeURIComponent(kind)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_yaml: rawYaml }),
  });
  if (!r.ok)
    throw new Error(
      `PUT /settings/${kind} ${r.status}: ${await r.text()}`,
    );
  return r.json();
}

export async function getSecretsView(): Promise<SecretsView> {
  const r = await fetch(`${API_BASE}/settings/secrets`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /settings/secrets ${r.status}`);
  return r.json();
}

// ── Phase 10 P10-8 — Home dashboard ────────────────────────────────────

export async function getDashboard(): Promise<DashboardResponse> {
  const r = await fetch(`${API_BASE}/dashboard`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /dashboard ${r.status}`);
  return r.json();
}

// ── Phase 11+ — Cost Explorer ──────────────────────────────────────────

export async function getCostSummary(
  days: number = 30,
): Promise<CostSummaryResponse> {
  const r = await fetch(`${API_BASE}/cost/summary?days=${days}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`GET /cost/summary ${r.status}`);
  return r.json();
}

export async function getActiveModel(): Promise<ActiveModelView> {
  const r = await fetch(`${API_BASE}/cost/active-model`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /cost/active-model ${r.status}`);
  return r.json();
}

export async function setActiveModel(model: string): Promise<ActiveModelView> {
  const r = await fetch(`${API_BASE}/cost/active-model`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  if (!r.ok)
    throw new Error(`POST /cost/active-model ${r.status}: ${await r.text()}`);
  return r.json();
}

// ── Phase 10 P10-2b — Discovery ─────────────────────────────────────────

export async function getDiscoveryRegions(): Promise<RegionsConfig> {
  const r = await fetch(`${API_BASE}/discovery/regions`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /discovery/regions ${r.status}`);
  return r.json();
}

export async function getDiscoveryProducts(): Promise<DiscoveryProductsResponse> {
  const r = await fetch(`${API_BASE}/discovery/products`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`GET /discovery/products ${r.status}`);
  return r.json();
}

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
