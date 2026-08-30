/**
 * Incident stage machine.
 *
 * Two problems this solves.
 *
 * A real incident spends 15-25 seconds inside model calls. The previous
 * implementation filled that silence with a `setTimeout` sequence — the
 * "Sandbox tests passed 14/14" line appeared 1.6 seconds in regardless of what
 * the backend was doing. Stages here come from the server as they complete, so
 * every duration and model name on screen is one that actually happened.
 *
 * And the old flow had no failure path at all: on any error it returned with
 * `isSimulating` still true, freezing the trigger button for the rest of the
 * session. Here `running` is cleared in a `finally`, so there is no path out of
 * this hook that leaves the UI stuck.
 */

import { useCallback, useRef, useState } from 'react';
import { usePulse } from './usePulse';
import { streamIncident, type IncidentInput } from './api';
import type { StageEvent, StageName, StageState, StreamEvent, TriageResult } from './types';

export const STAGE_ORDER: StageName[] = ['armor', 'recall', 'diagnose', 'judge', 'gate', 'record'];

export const STAGE_LABELS: Record<StageName, string> = {
  armor: 'Screening',
  recall: 'Recall',
  diagnose: 'Diagnosis',
  judge: 'Safety review',
  gate: 'Authorisation',
  record: 'Audit',
};

export const STAGE_AGENT: Record<StageName, string> = {
  armor: 'Model Armor',
  recall: 'Memory Bank',
  diagnose: 'SRE Agent',
  judge: 'Judge Agent',
  gate: 'Commander',
  record: 'Audit Ledger',
};

export interface Stage {
  name: StageName;
  state: StageState;
  durationMs?: number;
  model?: string;
  tokens?: number;
  detail?: string;
  score?: number;
  confidence?: number;
  tool?: string;
  tier?: string;
  threats?: string[];
  /** Layers that returned a verdict on this stage. Absent means it did not run. */
  screenedBy?: string[];
  degradedReason?: string | null;
}

const blankStages = (): Stage[] =>
  STAGE_ORDER.map((name) => ({ name, state: 'pending' as StageState }));

export interface IncidentState {
  stages: Stage[];
  running: boolean;
  result: TriageResult | null;
  error: string | null;
  startedAt: number | null;
  activeStage: StageName | null;
}

export function useIncident() {
  const { setPulse, emitRipple } = usePulse();
  const [state, setState] = useState<IncidentState>({
    stages: blankStages(),
    running: false,
    result: null,
    error: null,
    startedAt: null,
    activeStage: null,
  });

  const abort = useRef<AbortController | null>(null);

  const applyStage = useCallback((event: StageEvent) => {
    // A finished stage sends one ring through the ambient field, so the
    // background is reporting the same events the timeline is listing.
    if (event.state !== 'active') emitRipple();

    setState((prev) => ({
      ...prev,
      activeStage: event.state === 'active' ? event.stage : prev.activeStage,
      stages: prev.stages.map((s) =>
        s.name !== event.stage
          ? s
          : {
              ...s,
              state: event.state,
              durationMs: event.duration_ms ?? s.durationMs,
              model: event.model ?? s.model,
              tokens: event.tokens ?? s.tokens,
              detail: event.detail ?? s.detail,
              score: event.score ?? s.score,
              confidence: event.confidence ?? s.confidence,
              tool: event.tool ?? s.tool,
              tier: event.tier ?? s.tier,
              threats: event.threats ?? s.threats,
              screenedBy: event.screened_by ?? s.screenedBy,
              degradedReason: event.degraded_reason ?? s.degradedReason,
            },
      ),
    }));
  }, [emitRipple]);

  const run = useCallback(
    async (incident: IncidentInput) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      setState({
        stages: blankStages(),
        running: true,
        result: null,
        error: null,
        startedAt: performance.now(),
        activeStage: null,
      });
      setPulse('thinking');

      try {
        await streamIncident(
          incident,
          (event: StreamEvent) => {
            if (event.type === 'stage') applyStage(event);
            else if (event.type === 'result') {
              setState((p) => ({ ...p, result: event.result }));
              // A refusal or a rejected plan reads differently from a clean
              // pass, and the field should say so without anyone reading text.
              const verdict = event.result.judge_evaluation;
              setPulse(verdict.is_approved ? 'settled' : 'refused');
            } else if (event.type === 'error') {
              setState((p) => ({ ...p, error: event.message }));
              setPulse('refused');
            }
          },
          controller.signal,
        );
      } catch (cause) {
        if (controller.signal.aborted) return;
        const message = cause instanceof Error ? cause.message : String(cause);
        setState((p) => ({
          ...p,
          error: message,
          // Whatever was mid-flight did not finish. Say so rather than leaving
          // a spinner turning forever.
          stages: p.stages.map((s) => (s.state === 'active' ? { ...s, state: 'failed' } : s)),
        }));
        setPulse('refused');
      } finally {
        // The one guarantee this hook makes: `running` always returns to false,
        // so the trigger control always comes back.
        setState((p) => ({ ...p, running: false, activeStage: null }));
      }
    },
    [applyStage, setPulse],
  );

  const reset = useCallback(() => {
    abort.current?.abort();
    setPulse('idle');
    setState({
      stages: blankStages(),
      running: false,
      result: null,
      error: null,
      startedAt: null,
      activeStage: null,
    });
  }, [setPulse]);

  return { ...state, run, reset };
}
