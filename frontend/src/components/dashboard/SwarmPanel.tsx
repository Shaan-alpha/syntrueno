/**
 * The four agents and what each is doing right now.
 *
 * Agent state is derived from the stage stream rather than held separately, so
 * the panel cannot drift out of sync with the timeline beside it.
 */

import { Activity, DollarSign, Scale, Zap, type LucideIcon } from 'lucide-react';
import { Card, StatusDot } from '../ui/primitives';
import type { Stage } from '../../lib/useIncident';
import type { StageName } from '../../lib/types';

interface AgentDef {
  id: string;
  name: string;
  role: string;
  icon: LucideIcon;
  /** The stage whose state this agent reflects. */
  stage?: StageName;
  accent: string;
}

const AGENTS: AgentDef[] = [
  { id: 'commander', name: 'Commander', role: 'Routes work, mints capability tokens', icon: Zap, stage: 'gate', accent: 'blue' },
  { id: 'sre', name: 'SRE Agent', role: 'Diagnoses from live telemetry', icon: Activity, stage: 'diagnose', accent: 'green' },
  { id: 'judge', name: 'Judge Agent', role: 'Scores every plan before it runs', icon: Scale, stage: 'judge', accent: 'purple' },
  { id: 'finops', name: 'FinOps Agent', role: 'Finds waste, enforces scale-to-zero', icon: DollarSign, stage: undefined, accent: 'yellow' },
];

export function SwarmPanel({ stages, running }: { stages: Stage[]; running: boolean }) {
  const byStage = new Map(stages.map((s) => [s.name, s]));

  return (
    <Card title="Swarm" subtitle={running ? 'Working' : 'Standing by'}>
      <ul className="agents">
        {AGENTS.map((agent) => {
          const stage = agent.stage ? byStage.get(agent.stage) : undefined;
          const state =
            stage?.state === 'active' ? 'active'
              : stage?.state === 'done' ? 'done'
              : stage?.state === 'degraded' ? 'warn'
              : stage?.state === 'failed' ? 'error'
              : 'idle';

          const Icon = agent.icon;
          return (
            <li key={agent.id} className={`agent agent--${state}`}>
              <span className={`agent__icon agent__icon--${agent.accent}`}>
                <Icon size={16} strokeWidth={2.2} />
              </span>
              <span className="agent__text">
                <span className="agent__name">{agent.name}</span>
                <span className="agent__role">
                  {stage?.state === 'active'
                    ? 'Working…'
                    : stage?.state === 'degraded'
                      ? 'Ran without the model'
                      : agent.role}
                </span>
              </span>
              <StatusDot state={state} label={`${agent.name} ${state}`} />
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
