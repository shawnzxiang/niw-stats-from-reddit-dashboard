export type KnownPair = [number | null, boolean];

export interface SlimRecord {
  id: string | null;
  title: string | null;
  permalink: string | null;
  flair: string | null;
  created_utc: number;
  outcome: string | null;
  degree: string | null;
  field: string | null;
  profession?: string | null;
  profession_raw?: string | null;
  law_firm: string | null;
  publications: KnownPair;
  patents?: KnownPair;
  citations: KnownPair;
  years_experience: KnownPair;
  processing_days: KnownPair;
  premium_processing: boolean | null;
  was_rfed: boolean | null;
  rfe_date: string | null;
  rfe_response_date: string | null;
  // Run provenance (model picker + composite voting). Optional: legacy fixtures omit them.
  run?: string | null;
  prompt_version?: string | null;
  schema_version?: string | null;
  classified_at?: number | null;
  selftext?: string | null;
  op_comments?: string | null;
  // Re-file detection (per-author, computed client-side via markRefiled).
  author?: string | null;
  refiled?: boolean | null;
  refiled_url?: string | null;
  refile_approval?: boolean | null;
}

export interface RunInfo {
  prompt_version?: string;
  schema_version?: string;
  run_key: string;
  backend: string;
  model: string | null;
  effort: string | null;
  label: string | null;
  ok: number;
  excluded: number;
  failed: number;
  posts: number;
  last_classified_at: number | null;
}

export interface VersionInfo {
  prompt_version: string;
  schema_version: string;
  version_key: string;
  runs: RunInfo[];
  post_count: number;
  candidate_count: number;
  classified_count: number;
  excluded_count: number;
  failed_count: number;
  active_processed_count: number;
  active_pending_count: number;
  is_partial: boolean;
  max_classified_at: number | null;
}

export interface Snapshot {
  data_version: string;
  generated_at: number;
  meta: Record<string, unknown>;
  records: SlimRecord[];
}

export interface Bucket {
  label: string;
  count: number;
  approved: number;
  denied: number;
}

export interface Distribution {
  metric: string;
  kind: "categorical" | "numeric" | "duration";
  buckets: Bucket[];
  unknown_count: number;
  n: number;
  total: number;
}

export interface ApprovalRate {
  approved: number;
  denied: number;
  total_decided: number;
  rate: number | null;
}

export interface GroupRow {
  label: string;
  approved: number;
  denied: number;
  n: number;
  rate: number | null;
}

export interface ApprovalByGroup {
  group: string;
  groups: GroupRow[];
}
