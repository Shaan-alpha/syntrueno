/**
 * Response shapes mirroring the backend.
 *
 * These exist because five separate fields were being read under the wrong
 * name — `monthly_savings_usd` for `total_monthly_savings_usd`, and so on. Each
 * had a `||` fallback, so the UI rendered invented numbers while the network
 * panel showed a green 200. Naming the shapes once, here, makes that class of
 * bug a type error instead of a silent wrong answer.
 */

export type StageName = 'armor' | 'recall' | 'diagnose' | 'judge' | 'gate' | 'record';
export type StageState = 'pending' | 'active' | 'done' | 'degraded' | 'failed';

export interface StageEvent {
  type: 'stage';
  stage: StageName;
  state: Exclude<StageState, 'pending'>;
  duration_ms?: number;
  model?: string;
  tokens?: number;
  detail?: string;
  confidence?: number;
  tool?: string;
  score?: number;
  approved?: boolean;
  tier?: string;
  status?: string;
  approval_id?: string | null;
  chain_hash?: string;
  threats?: string[];
  redactions?: string[];
  screened_by?: string[];
  degraded_reason?: string | null;
}

export type StreamEvent =
  | { type: 'start'; incident_id: string; stages: StageName[] }
  | StageEvent
  | { type: 'result'; result: TriageResult }
  | { type: 'error'; message: string }
  | { type: 'done' };

export interface LlmTelemetry {
  model: string;
  tier: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  thought_tokens: number;
  total_tokens: number;
  attempts: number;
  degraded: boolean;
  degraded_reason: string | null;
  fallback_used: boolean;
  preferred_model: string;
}

export interface RemediationAction {
  action_id: string;
  tool_name: string;
  parameters: Record<string, unknown>;
  rationale: string;
  tier: string;
  code_diff: string | null;
  /** null when the price list was unreachable. "unknown" and "no change" are
   *  different claims, so the server sends null rather than 0.0 — and this said
   *  `number`, which would let `.toFixed()` typecheck and then throw at
   *  runtime on exactly the FinOps proposal that could not be priced. */
  estimated_cost_delta_usd: number | null;
}

export interface JudgeEvaluation {
  score: number;
  is_approved: boolean;
  critique: string;
  hallucination_detected: boolean;
  requires_human_signoff: boolean;
  degraded: boolean;
  degraded_reason: string | null;
  telemetry: Partial<LlmTelemetry>;
}

export interface ApprovalRecord {
  approval_id: string;
  incident_id: string;
  action_hash: string;
  requested_action: RemediationAction;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  signed_by: string | null;
  signed_at: string | null;
  consumed_at: string | null;
  expires_at: string | null;
}

export interface TriageResult {
  incident_id: string;
  execution_status: string;
  sre_diagnosis: string;
  sre_confidence: number | null;
  proposed_action: RemediationAction;
  judge_evaluation: JudgeEvaluation;
  resolved_tier: string;
  approval_record: ApprovalRecord | null;
  past_memory_context: unknown[];
  /** Which store answered recall. Memory Bank matches on meaning; Firestore
   *  on substring. A silent fallback would look identical without this. */
  past_memory_source?: 'memory_bank' | 'firestore';
  ledger_chain_hash: string;
  executed_tools: string[];
  degraded: boolean;
  degraded_reasons: string[];
  telemetry: { sre: Partial<LlmTelemetry>; judge: Partial<LlmTelemetry>; total_duration_ms: number };
  total_duration_ms: number;
}

export interface ArmorScan {
  is_safe: boolean;
  verdict: 'ALLOWED' | 'BLOCKED' | 'QUARANTINED';
  sanitized_prompt: string;
  detected_threats: string[];
  redacted_pii: string[];
  latency_ms: number;
  timestamp: string;
  /** Layers that actually returned a verdict — "regex", "model_armor", "gemma".
   *  A layer that timed out is absent, because it screened nothing. */
  screened_by: string[];
  /** Set when a configured layer could not be reached. A scan that could not
   *  run says so rather than reading as clean. */
  degraded_reason: string | null;
}

/** Note the exact field names — these are the ones that were previously wrong. */
export interface FinOpsFinding {
  resource_id: string;
  resource_type: string;
  configured_memory_mib: number;
  observed_peak_memory_mib: number;
  observed_peak_utilization: number;
  /** How many datapoints the peak rests on. A finding from 2 is weaker than one from 200. */
  samples: number;
  window_days: number;
  recommended_memory_mib: number;
  recoverable_memory_mib: number;
  min_instances: number;
  remediation: string;
  /** null when the price list was unreachable, or when scale-to-zero makes a
   *  monthly figure meaningless. A finding without a price is still true. */
  monthly_cost_usd: number | null;
  cost_note?: string;
}

export interface FinOpsAudit {
  waste_detected_count: number;
  total_monthly_savings_usd: number;
  waste_details: FinOpsFinding[];
  /** null when nothing was found — there is then nothing to propose. */
  suggested_action: RemediationAction | null;
  duration_ms: number;
  /** What was looked at and what could not be, so an empty result is readable. */
  measurement: {
    services_examined: number;
    services_unmeasured: string[];
    window_days: number;
    cloud_run_available: boolean;
    pricing: { memory_gib_second_usd: number | null };
    billing_export: { configured: boolean; note: string };
  };
  degraded?: boolean;
  degraded_reason?: string;
}

export interface CompiledSkill {
  skill_id: string;
  skeleton_signature: string;
  tool_sequence: string[];
  input_slots: string[];
  safety_preconditions: string[];
  /** True only when the Judge approved every trajectory in the cluster. */
  verified_by_judge: boolean;
  /** Rows mined. Two of these can be one incident recorded twice. */
  occurrences: number;
  /** Separate incidents. This is the number that makes it a pattern. */
  distinct_incidents: number;
  min_judge_score: number | null;
  /** Mean tokens of the diagnosis calls this skill replaces. 0 when unmeasured. */
  mean_diagnosis_tokens: number;
  total_executions: number;
  total_tokens_saved: number;
}

export interface AgentCard {
  name: string;
  role: string;
  version: string;
  description: string;
  endpoints: Record<string, string>;
  skills: Array<{ name: string; description: string; is_compiled_skill: boolean }>;
  security_schemes: string[];
}

export interface LedgerEntry {
  event_id: string;
  sequence?: number;
  session_id: string;
  agent_name: string;
  action_name: string;
  status: string;
  details: Record<string, unknown>;
  duration_ms: number;
  timestamp: string;
  chain_hash?: string;
  prev_hash?: string;
}

export interface SystemStatus {
  project: string;
  environment: string;
  registered_agents_count: number;
  compiled_skills_count: number;
  audit_ledger_size: number;
  pending_approvals: number;
  llm: { available: boolean; fast_model: string; reasoning_model: string; simulation_mode: boolean };
  remediation: { dry_run: boolean; allowlisted_service: string };
  persistence: {
    firestore: { enabled: boolean; connected: boolean; database: string };
    audit_ledger: { entries: number; persistent: boolean };
    memory_bank: { incidents_recorded: number; persistent: boolean };
    /** Reasoning-chain traces. `active` means the exporter was built;
     *  `flushes_failed` is the one that says whether spans are landing --
     *  the same distinction firestore draws between connected and healthy. */
    tracing: {
      enabled: boolean;
      active: boolean;
      exporter: string;
      error: string | null;
      flushes_ok: number;
      flushes_failed: number;
      last_flush_error: string | null;
    };
  };
}

export interface CanaryState {
  available: boolean;
  service?: string;
  revision?: string | null;
  memory?: string;
  cpu?: string;
  min_instances?: number;
  max_instances?: number;
  uri?: string;
  reason?: string;
}

export interface RemediationResult {
  status: 'APPLIED' | 'APPLIED_UNVERIFIED' | 'REFUSED' | 'FAILED' | 'DRY_RUN' | 'NO_INFRASTRUCTURE_CHANGE';
  verified?: boolean;
  verification_detail?: string;
  approval_consumed?: string | null;
  reason?: string;
  before?: CanaryState;
  after?: CanaryState;
  duration_ms: number;
}
