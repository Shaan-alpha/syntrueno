/**
 * The judge's verdict and the authorisation gate that follows from it.
 *
 * These are one card because they are one decision: the score is *why* a
 * signature is being asked for, and separating them invites signing without
 * reading. The critique is shown in full rather than truncated — it is the most
 * substantive thing the system produces.
 */

import { useState } from 'react';
import { AlertTriangle, CheckCircle2, FileLock2, ShieldCheck, XCircle } from 'lucide-react';
import { Button, Card, Chip, CountUp, EmptyState, Metric } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { api, ApiError } from '../../lib/api';
import type { RemediationResult, TriageResult } from '../../lib/types';

const ENGINEER = 'shaan@syntrueno.dev';

export function VerdictCard({
  result,
  onExecuted,
}: {
  result: TriageResult | null;
  onExecuted?: (outcome: RemediationResult) => void;
}) {
  const toast = useToast();
  const [signing, setSigning] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [signed, setSigned] = useState(false);
  const [outcome, setOutcome] = useState<RemediationResult | null>(null);

  if (!result) {
    return (
      <Card title="Verdict">
        <EmptyState
          icon={<ShieldCheck size={26} />}
          title="No verdict yet"
          body="The judge scores every plan against a safety rubric before anything is allowed to run."
        />
      </Card>
    );
  }

  const verdict = result.judge_evaluation;
  const approval = result.approval_record;
  const action = result.proposed_action;
  const tone = verdict.score >= 8 ? 'good' : verdict.score >= 5 ? 'warn' : 'bad';

  const sign = async () => {
    if (!approval) return;
    setSigning(true);
    try {
      await api.sign(approval.approval_id, ENGINEER);
      setSigned(true);
      toast.success('Authorisation signed', `Bound to ${action.tool_name}`);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      toast.error('Could not sign', msg);
    } finally {
      setSigning(false);
    }
  };

  const execute = async () => {
    if (!approval) return;
    setExecuting(true);
    try {
      const res = await api.execute(approval.approval_id);
      setOutcome(res);
      onExecuted?.(res);

      if (res.status === 'APPLIED') {
        toast.success('Remediation applied', res.verification_detail ?? 'Verified against live state');
      } else if (res.status === 'REFUSED') {
        toast.error('Refused by a guard', res.reason);
      } else if (res.status === 'DRY_RUN') {
        toast.info('Dry run', 'The plan was not executed; dry-run mode is on.');
      } else {
        toast.error(res.status, res.reason ?? res.verification_detail);
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      toast.error('Execution failed', msg);
    } finally {
      setExecuting(false);
    }
  };

  return (
    <Card
      title="Verdict"
      subtitle={verdict.degraded ? 'Scored by offline heuristics' : 'Scored by the judge model'}
      accent={tone === 'good' ? 'green' : tone === 'warn' ? 'yellow' : 'red'}
    >
      <div className="verdict">
        <div className={`verdict__score verdict__score--${tone}`}>
          <span className="verdict__number">
            <CountUp to={verdict.score} />
          </span>
          <span className="verdict__of">/ 10</span>
        </div>

        <div className="verdict__facts">
          <Metric label="Decision" value={verdict.is_approved ? 'Approved' : 'Rejected'} tone={verdict.is_approved ? 'good' : 'bad'} />
          <Metric label="Tier" value={result.resolved_tier.replace(/^TIER_\d_/, '').replace(/_/g, ' ').toLowerCase()} />
          <Metric label="Total" value={(result.total_duration_ms / 1000).toFixed(1)} unit="s" />
        </div>
      </div>

      <p className="verdict__critique">{verdict.critique}</p>

      {verdict.hallucination_detected && (
        <div className="banner banner--warn">
          <AlertTriangle size={15} />
          <span>The judge flagged ungrounded claims in this plan.</span>
        </div>
      )}

      <div className="plan">
        <div className="plan__head">
          <span className="plan__tool">{action.tool_name}</span>
          <Chip tone="info">{String(action.parameters.service_id ?? '')}</Chip>
        </div>
        <dl className="plan__params">
          {Object.entries(action.parameters)
            .filter(([k]) => k !== 'service_id')
            .map(([k, v]) => (
              <div key={k}>
                <dt>{k.replace(/_/g, ' ')}</dt>
                <dd>{String(v)}</dd>
              </div>
            ))}
        </dl>
        {action.code_diff && <pre className="plan__diff">{action.code_diff}</pre>}
      </div>

      {approval ? (
        <div className="gate">
          <div className="gate__head">
            <FileLock2 size={15} />
            <div>
              <strong>Authorisation required</strong>
              <span className="gate__hash">
                signature binds to {approval.action_hash.slice(0, 24)}…
              </span>
            </div>
          </div>

          {outcome ? (
            <div className={`banner banner--${outcome.status === 'APPLIED' ? 'good' : 'error'}`}>
              {outcome.status === 'APPLIED' ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
              <div>
                <strong>{outcome.status.replace(/_/g, ' ')}</strong>
                <span>
                  {outcome.verification_detail ?? outcome.reason}
                  {outcome.before?.memory && outcome.after?.memory && (
                    <> — {outcome.before.memory} → {outcome.after.memory}</>
                  )}
                </span>
              </div>
            </div>
          ) : (
            <div className="gate__actions">
              {!signed ? (
                <>
                  <Button variant="primary" busy={signing} onClick={sign} icon={<ShieldCheck size={15} />}>
                    Sign authorisation
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={async () => {
                      try {
                        await api.reject(approval.approval_id, ENGINEER);
                        toast.info('Rejected', 'No change will be made.');
                      } catch (e) {
                        toast.error('Could not reject', e instanceof ApiError ? e.message : String(e));
                      }
                    }}
                  >
                    Reject
                  </Button>
                </>
              ) : (
                <Button variant="primary" busy={executing} onClick={execute} icon={<CheckCircle2 size={15} />}>
                  Execute remediation
                </Button>
              )}
            </div>
          )}
        </div>
      ) : (
        <p className="gate__none">
          {result.execution_status === 'NO_ACTION_REQUIRED'
            ? 'The swarm concluded no change was warranted.'
            : 'Cleared for autonomous execution at this tier — no signature required.'}
        </p>
      )}
    </Card>
  );
}
