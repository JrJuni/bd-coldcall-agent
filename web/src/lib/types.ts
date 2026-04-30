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
}

export interface RagNamespaceListResponse {
  namespaces: RagNamespaceSummary[];
  default: string;
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
