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
