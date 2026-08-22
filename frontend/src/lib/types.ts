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
  estimated_cost_delta_usd: number;
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
}

/** Note the exact field names — these are the ones that were previously wrong. */
export interface FinOpsAudit {
  waste_detected_count: number;
  total_monthly_savings_usd: number;
  waste_details: Array<{
    resource_id: string;
    resource_type: string;
    status: string;
    monthly_cost_usd: number;
    remediation: string;
  }>;
  suggested_action: RemediationAction;
  duration_ms: number;
}

export interface CompiledSkill {
  skill_id: string;
  skeleton_signature: string;
  tool_sequence: string[];
  input_slots: string[];
  safety_preconditions: string[];
  verified_by_judge: boolean;
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
