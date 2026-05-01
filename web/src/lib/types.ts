export type RunStatus = "queued" | "running" | "completed" | "failed";

export interface RunSummary {
  run_id: string;
  company: string;
  industry: string;
  lang: string;
  status: RunStatus;
  current_stage: string | null;
  stages_completed: string[];
  failed_stage: string | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  duration_s: number | null;
  errors: Array<Record<string, unknown>>;
  usage: Record<string, number>;
  article_counts: Record<string, number>;
  proposal_points_count: number;
  proposal_md: string | null;
  output_dir: string | null;
}

export interface RunCreateResponse {
  run_id: string;
  status: RunStatus;
  created_at: string;
}

export interface IngestStatus {
  manifest_path: string;
  manifest_exists: boolean;
  version: number | null;
  updated_at: string | null;
  document_count: number;
  chunk_count: number;
  by_source_type: Record<string, number>;
}

export interface IngestTriggerResponse {
  task_id: string;
  status: string;
  message: string | null;
}

export const PIPELINE_STAGES = [
  "search",
  "fetch",
  "preprocess",
  "retrieve",
  "synthesize",
  "draft",
  "persist",
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];

// ── Phase 10 P10-1 — Targets ────────────────────────────────────────────

export const TARGET_STAGES = [
  "planned",
  "contacted",
  "proposal_sent",
  "meeting",
  "won",
  "lost",
] as const;

export type TargetStage = (typeof TARGET_STAGES)[number];

export type CreatedFrom = "manual" | "discovery_promote";

export interface Target {
  id: number;
  name: string;
  industry: string;
  aliases: string[];
  notes: string | null;
  stage: TargetStage;
  created_from: CreatedFrom;
  discovery_candidate_id: number | null;
  last_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TargetCreateInput {
  name: string;
  industry: string;
  aliases?: string[];
  notes?: string | null;
  stage?: TargetStage;
}

export interface TargetUpdateInput {
  name?: string;
  industry?: string;
  aliases?: string[];
  notes?: string | null;
  stage?: TargetStage;
}

export interface TargetListResponse {
  targets: Target[];
}

// ── Phase 10 P10-2a — RAG namespaces ────────────────────────────────────

export interface RagNamespaceSummary {
  name: string;
  document_count: number;
  chunk_count: number;
  updated_at: string | null;
  by_source_type: Record<string, number>;
  is_default: boolean;
  needs_reindex: boolean;
}

export interface RagNamespaceListResponse {
  namespaces: RagNamespaceSummary[];
  default: string;
}

// ── Phase 10 P10-3 — RAG document management ───────────────────────────

export interface RagNamespaceCreateInput {
  name: string;
}

export interface RagDocumentSummary {
  filename: string;
  size_bytes: number;
  modified_at: string | null;
  extension: string;
  indexed: boolean;
  chunk_count: number;
}

export interface RagDocumentListResponse {
  namespace: string;
  documents: RagDocumentSummary[];
  indexed_doc_count: number;
}

export interface RagDocumentUploadResponse {
  namespace: string;
  filename: string;
  size_bytes: number;
}

export interface RagNamespaceDeleteResponse {
  name: string;
  removed: boolean;
}

export type RagTreeEntryType = "folder" | "file";

export interface RagTreeEntry {
  type: RagTreeEntryType;
  name: string;
  size_bytes: number | null;
  modified_at: string | null;
  extension: string | null;
  indexed: boolean | null;
  chunk_count: number | null;
  child_count: number | null;
  needs_reindex: boolean | null;
}

export interface RagTreeResponse {
  namespace: string;
  path: string;
  parent: string | null;
  entries: RagTreeEntry[];
}

export interface RagFolderActionResponse {
  namespace: string;
  path: string;
  removed: boolean;
  created: boolean;
}

export interface RagOpenFolderResponse {
  namespace: string;
  path: string;
  abs_path: string;
  opened: boolean;
}

export interface RagRootOpenResponse {
  abs_path: string;
  opened: boolean;
}

export interface RagRootFileListResponse {
  files: RagDocumentSummary[];
}

export interface RagSummaryRequestInput {
  path?: string;
  lang?: "en" | "ko";
  sample_size?: number;
  max_tokens?: number;
}

export interface RagSummaryResponse {
  namespace: string;
  path: string;
  chunk_count: number;
  chunks_in_namespace: number;
  summary: string;
  model: string | null;
  usage: Record<string, number>;
  generated_at: string;
  is_stale: boolean;
}

export interface RagSummaryCachedResponse {
  summary: RagSummaryResponse | null;
}

// ── Phase 10 P10-5 — Daily News ────────────────────────────────────────

export type NewsStatus = "queued" | "running" | "completed" | "failed";

export interface NewsArticle {
  title: string;
  url: string;
  snippet: string | null;
  hostname: string | null;
  lang: string | null;
  published: string | null;
}

export interface NewsRunSummary {
  task_id: string;
  namespace: string;
  generated_at: string;
  seed_summary: string | null;
  seed_query: string | null;
  lang: string;
  days: number;
  status: NewsStatus;
  article_count: number;
  started_at: string | null;
  ended_at: string | null;
  error_message: string | null;
  sonnet_summary: string | null;
  ttl_hours: number;
  usage: Record<string, number>;
}

export interface NewsRunDetail extends NewsRunSummary {
  articles: NewsArticle[];
}

export interface NewsRefreshInput {
  namespace: string;
  seed_query: string;
  lang: "en" | "ko";
  days?: number;
  count?: number;
  seed_summary?: string | null;
}

export interface NewsRefreshResponse {
  task_id: string;
  status: NewsStatus;
  namespace: string;
}

// ── Phase 10 P10-6 — Interactions (사업 기록) ─────────────────────────

export const INTERACTION_KINDS = [
  "call",
  "meeting",
  "email",
  "note",
] as const;
export type InteractionKind = (typeof INTERACTION_KINDS)[number];

export const INTERACTION_OUTCOMES = [
  "positive",
  "neutral",
  "negative",
  "pending",
] as const;
export type InteractionOutcome = (typeof INTERACTION_OUTCOMES)[number];

export interface Interaction {
  id: number;
  target_id: number | null;
  company_name: string;
  kind: InteractionKind;
  occurred_at: string;
  outcome: InteractionOutcome | null;
  raw_text: string | null;
  contact_role: string | null;
  created_at: string;
}

export interface InteractionCreateInput {
  company_name: string;
  kind: InteractionKind;
  occurred_at: string;
  outcome?: InteractionOutcome | null;
  raw_text?: string | null;
  contact_role?: string | null;
  target_id?: number | null;
}

export interface InteractionUpdateInput {
  company_name?: string;
  kind?: InteractionKind;
  occurred_at?: string;
  outcome?: InteractionOutcome | null;
  raw_text?: string | null;
  contact_role?: string | null;
  target_id?: number | null;
}

export interface InteractionListResponse {
  interactions: Interaction[];
}

// ── Phase 10 P10-7 — Settings ──────────────────────────────────────────

export const SETTINGS_KINDS = [
  "settings",
  "weights",
  "tier_rules",
  "competitors",
  "intent_tiers",
  "sector_leaders",
  "targets",
] as const;
export type SettingsKind = (typeof SETTINGS_KINDS)[number];

export interface SettingsRead {
  kind: SettingsKind;
  path: string;
  exists: boolean;
  raw_yaml: string;
  parsed: Record<string, unknown> | null;
}

export interface SettingsKindList {
  kinds: SettingsKind[];
}

export interface SecretsView {
  anthropic_api_key: boolean;
  brave_search_api_key: boolean;
  notion_token: boolean;
}

// ── Phase 10 P10-8 — Home dashboard ────────────────────────────────────

export interface DashboardRecentRun {
  run_id: string;
  company: string;
  industry: string;
  status: string;
  created_at: string;
}

export interface DashboardRecentDiscovery {
  run_id: string;
  namespace: string;
  product: string;
  status: string;
  candidate_count: number;
  tier_distribution: Record<string, number>;
  generated_at: string;
}

export interface DashboardNewsMini {
  namespace: string;
  generated_at: string;
  article_count: number;
  seed_query: string | null;
  top_titles: string[];
}

export interface DashboardRagStatus {
  namespace: string;
  document_count: number;
  chunk_count: number;
  is_indexed: boolean;
}

export interface DashboardCostSummary {
  proposal_input_tokens: number;
  proposal_output_tokens: number;
  proposal_cache_read_tokens: number;
  proposal_cache_write_tokens: number;
  discovery_input_tokens: number;
  discovery_output_tokens: number;
  discovery_cache_read_tokens: number;
  discovery_cache_write_tokens: number;
}

export interface DashboardResponse {
  recent_runs: DashboardRecentRun[];
  recent_discovery: DashboardRecentDiscovery | null;
  pipeline_by_stage: Record<string, number>;
  rag: DashboardRagStatus[];
  news: DashboardNewsMini | null;
  interactions_count: number;
  cost: DashboardCostSummary;
  generated_at: string;
}

// ── Phase 10 P10-2b — Discovery ─────────────────────────────────────────

export const WEIGHT_DIMENSIONS = [
  "pain_severity",
  "data_complexity",
  "governance_need",
  "ai_maturity",
  "buying_trigger",
  "displacement_ease",
] as const;

export type WeightDimension = (typeof WEIGHT_DIMENSIONS)[number];

export const DISCOVERY_REGIONS = ["any", "ko", "us", "eu", "global"] as const;
export type DiscoveryRegion = (typeof DISCOVERY_REGIONS)[number];

export type DiscoveryStatus = "queued" | "running" | "completed" | "failed";
export type CandidateStatus = "active" | "archived" | "promoted";
export type Tier = "S" | "A" | "B" | "C";

export const TIER_VALUES: readonly Tier[] = ["S", "A", "B", "C"] as const;

export interface DiscoveryRunCreateInput {
  namespace: string;
  region: DiscoveryRegion;
  product: string;
  seed_summary?: string | null;
  seed_query?: string | null;
  top_k?: number | null;
  n_industries?: number;
  n_per_industry?: number;
  lang?: "en" | "ko";
  include_sector_leaders?: boolean;
}

export interface DiscoveryRunSummary {
  run_id: string;
  generated_at: string;
  status: DiscoveryStatus;
  namespace: string;
  product: string;
  region: DiscoveryRegion;
  lang: string;
  seed_doc_count: number;
  seed_chunk_count: number;
  seed_summary: string | null;
  started_at: string | null;
  ended_at: string | null;
  failed_stage: string | null;
  error_message: string | null;
  usage: Record<string, number>;
  created_at: string;
  candidate_count: number;
  tier_distribution: Record<string, number>;
}

export interface DiscoveryCandidate {
  id: number;
  run_id: string;
  name: string;
  industry: string;
  scores: Record<string, number>;
  final_score: number;
  tier: Tier;
  rationale: string | null;
  status: CandidateStatus;
  updated_at: string;
}

export interface DiscoveryRunDetail extends DiscoveryRunSummary {
  candidates: DiscoveryCandidate[];
}

export interface DiscoveryRunListResponse {
  runs: DiscoveryRunSummary[];
}

export interface DiscoveryCandidateUpdateInput {
  name?: string;
  industry?: string;
  scores?: Record<string, number>;
  rationale?: string | null;
  status?: CandidateStatus;
  tier?: Tier;
}

export interface DiscoveryRecomputeInput {
  weights?: Record<string, number>;
  product?: string;
}

export interface DiscoveryRecomputeResponse {
  run_id: string;
  candidates: DiscoveryCandidate[];
  weights_applied: Record<string, number>;
  tier_distribution: Record<string, number>;
}

export interface DiscoveryPromoteResponse {
  candidate_id: number;
  target_id: number;
  candidate_status: CandidateStatus;
}
