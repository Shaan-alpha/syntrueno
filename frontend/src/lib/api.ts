/**
 * The only place the console talks to the backend.
 *
 * Every fetch used to be inline in a component with a `|| fallbackNumber` after
 * it, which meant a renamed field degraded silently into a fabricated value
 * rather than failing. Centralising the calls makes each response shape assert
 * itself once, and makes the mapping testable without a browser.
 */

import type {
  AgentCard,
  ApprovalRecord,
  ArmorScan,
  CanaryState,
  CompiledSkill,
  FinOpsAudit,
  LedgerEntry,
  RemediationResult,
  StreamEvent,
  SystemStatus,
  TriageResult,
} from './types';

const isLocal =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

export const API_BASE = isLocal ? 'http://127.0.0.1:8000' : '';

export class ApiError extends Error {
  readonly status?: number;
  readonly detail?: string;

  constructor(message: string, status?: number, detail?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    throw new ApiError(
      'Cannot reach the Syntrueno API. Is the backend running?',
      undefined,
      String(cause),
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* body was not JSON; the status text will do */
    }
    throw new ApiError(detail, response.status, detail);
  }
  return (await response.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });

export interface IncidentInput {
  incident_id: string;
  service_id: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  metric_name: string;
  error_message: string;
  telemetry_data?: Record<string, unknown>;
}

export const api = {
  health: () => request<{ status: string; llm_available: boolean; version: string }>('/api/v1/health'),
  status: () => request<SystemStatus>('/api/v1/status'),

  scanPrompt: (prompt: string) =>
    post<ArmorScan>('/api/v1/security/model-armor/scan', { prompt }),

  triage: (incident: IncidentInput) =>
    post<TriageResult>('/api/v1/swarm/incident/triage', incident),

  finops: () => request<FinOpsAudit>('/api/v1/swarm/finops/audit'),

  agents: () => request<{ agents: AgentCard[] }>('/a2a/v1/registry').then((r) => r.agents),

  approvals: () =>
    request<{ approvals: ApprovalRecord[] }>('/api/v1/governance/approvals').then((r) => r.approvals),

  sign: (approvalId: string, engineerId: string) =>
    post<{ status: string; approval_record: ApprovalRecord }>(
      '/api/v1/governance/approvals/sign',
      { approval_id: approvalId, engineer_id: engineerId },
    ).then((r) => r.approval_record),

  reject: (approvalId: string, engineerId: string) =>
    post<{ status: string; approval_record: ApprovalRecord }>(
      '/api/v1/governance/approvals/reject',
      { approval_id: approvalId, engineer_id: engineerId },
    ).then((r) => r.approval_record),

  execute: (approvalId: string) =>
    post<RemediationResult>('/api/v1/swarm/remediation/execute', { approval_id: approvalId }),

  canary: () => request<CanaryState>('/api/v1/cloud/canary'),

  ledger: () =>
    request<{ ledger_entries: LedgerEntry[]; is_chain_valid: boolean }>(
      '/api/v1/governance/audit-ledger',
    ),

  mineSkills: () =>
    post<{ newly_compiled_count: number; all_compiled_skills: CompiledSkill[] }>(
      '/api/v1/compiler/mine',
    ),

  trajectories: () =>
    request<{ trajectories: Array<{ skeleton_signature: string; duration_ms: number; recorded_at: string }> }>(
      '/api/v1/compiler/trajectories',
    ).then((r) => r.trajectories),
};

/**
 * Stream an incident, yielding each stage as the swarm completes it.
 *
 * `fetch` is used rather than `EventSource` because the endpoint is a POST —
 * `EventSource` only issues GETs.
 */
export async function streamIncident(
  incident: IncidentInput,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/swarm/incident/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(incident),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new ApiError(`Stream failed (${response.status})`, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Anything after the last
    // separator is a partial frame and stays in the buffer.
    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';

    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data: '));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as StreamEvent);
      } catch {
        /* a malformed frame should not tear down the whole stream */
      }
    }
  }
}
