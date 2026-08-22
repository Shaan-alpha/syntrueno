/**
 * The incident track.
 *
 * Renders the five stages up front as a dimmed skeleton and fills them in as
 * the server reports them. Showing the whole track immediately tells the user
 * what is going to happen; filling it in tells them where it has got to. The
 * previous version grew the list on a timer, which meant the shape of the work
 * was invisible until it was already over.
 */

import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Clock,
  FileLock2,
  History,
  Scale,
  Shield,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { Card, Chip, LiveProgress, StatusDot } from '../ui/primitives';
import { STAGE_AGENT, STAGE_LABELS, type Stage } from '../../lib/useIncident';
import type { StageName } from '../../lib/types';

const ICONS: Record<StageName, LucideIcon> = {
  armor: Shield,
  recall: History,
  diagnose: Brain,
  judge: Scale,
  gate: FileLock2,
  record: CheckCircle2,
};

function formatDuration(ms?: number): string | null {
  if (ms === undefined || ms === null) return null;
  if (ms < 1000) return `${ms < 10 ? ms.toFixed(2) : Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function StageRow({ stage, startedAt }: { stage: Stage; startedAt: number | null }) {
  const Icon = ICONS[stage.name];
  const duration = formatDuration(stage.durationMs);

  const dotState =
    stage.state === 'active' ? 'active'
      : stage.state === 'done' ? 'done'
      : stage.state === 'degraded' ? 'warn'
      : stage.state === 'failed' ? 'error'
      : 'idle';

  return (
    <li className={`stage stage--${stage.state}`}>
      <div className="stage__rail">
        <span className="stage__icon">
          <Icon size={15} strokeWidth={2.2} />
        </span>
      </div>

      <div className="stage__body">
        <div className="stage__head">
          <span className="stage__name">{STAGE_LABELS[stage.name]}</span>
          <span className="stage__agent">{STAGE_AGENT[stage.name]}</span>
          <StatusDot state={dotState} label={`${STAGE_LABELS[stage.name]} ${stage.state}`} />

          <span className="stage__meta">
            {stage.state === 'active' && startedAt !== null && <LiveProgress since={startedAt} />}
            {duration && stage.state !== 'active' && (
              <span className="stage__duration">
                <Clock size={11} /> {duration}
              </span>
            )}
          </span>
        </div>

        {stage.detail && stage.state !== 'active' && (
          <p className="stage__detail">{stage.detail}</p>
        )}

        {(stage.model || stage.tokens || stage.score !== undefined || stage.confidence !== undefined) &&
          stage.state !== 'active' && (
            <div className="stage__chips">
              {stage.model && <Chip tone="info">{stage.model}</Chip>}
              {stage.tokens !== undefined && stage.tokens > 0 && (
                <Chip>{stage.tokens.toLocaleString()} tokens</Chip>
              )}
              {stage.confidence !== undefined && (
                <Chip tone={stage.confidence >= 0.8 ? 'good' : 'warn'}>
                  {Math.round(stage.confidence * 100)}% confidence
                </Chip>
              )}
              {stage.score !== undefined && (
                <Chip tone={stage.score >= 8 ? 'good' : stage.score >= 5 ? 'warn' : 'bad'}>
                  {stage.score.toFixed(1)} / 10
                </Chip>
              )}
              {stage.tool && <Chip tone="info">{stage.tool}</Chip>}
              {stage.threats && stage.threats.length > 0 && (
                <Chip tone="bad">{stage.threats.length} neutralised</Chip>
              )}
            </div>
          )}

        {stage.state === 'degraded' && stage.degradedReason && (
          <p className="stage__degraded">
            <AlertTriangle size={12} /> Ran without the model — {stage.degradedReason}
          </p>
        )}

        {stage.state === 'failed' && (
          <p className="stage__failed">
            <XCircle size={12} /> This stage did not complete.
          </p>
        )}
      </div>
    </li>
  );
}

export function IncidentTimeline({
  stages,
  startedAt,
  running,
  error,
}: {
  stages: Stage[];
  startedAt: number | null;
  running: boolean;
  error: string | null;
}) {
  const finished = stages.filter((s) => s.state === 'done' || s.state === 'degraded').length;

  return (
    <Card
      title="Incident timeline"
      subtitle={
        running
          ? 'Streaming from the swarm as each stage completes'
          : finished > 0
            ? `${finished} of ${stages.length} stages completed`
            : 'Trigger an incident to watch the swarm work'
      }
    >
      {error && (
        <div className="banner banner--error" role="alert">
          <XCircle size={15} />
          <div>
            <strong>The incident stream failed.</strong>
            <span>{error}</span>
          </div>
        </div>
      )}

      <ol className="stages" aria-live="polite" aria-busy={running}>
        {stages.map((stage) => (
          <StageRow key={stage.name} stage={stage} startedAt={startedAt} />
        ))}
      </ol>
    </Card>
  );
}
