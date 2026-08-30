/**
 * The read-mostly panels: agent registry, audit ledger, FinOps, compiler.
 *
 * All four call endpoints the previous console never touched — the data was
 * being served and thrown away while the tabs rendered static markup.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  BadgeCheck,
  DollarSign,
  Hammer,
  Link2,
  Loader2,
  RefreshCw,
  ScrollText,
  ShieldCheck,
} from 'lucide-react';
import { Button, Card, Chip, EmptyState, Metric, Skeleton } from '../ui/primitives';
import { useToast } from '../ui/Toast';
import { api, API_BASE, ApiError } from '../../lib/api';
import type { AgentCard, CompiledSkill, FinOpsAudit, LedgerEntry } from '../../lib/types';

/** Load-once-on-mount with loading and error states, so no panel can render a
 *  confident empty list while a request is still in flight or has failed. */
function useResource<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await load());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [load]);

  useEffect(() => {
    // set-state-in-effect fires on refresh()'s opening setLoading(true).
    // On this path it is a no-op: `loading` initialises to true, React bails
    // out of a set to the identical value, and no extra render happens. The
    // call is not removable either -- it is what puts the Refresh button into
    // its busy state on every subsequent manual refresh.
    // oxlint-disable-next-line react/set-state-in-effect
    void refresh();
  }, [refresh]);

  return { data, error, loading, refresh };
}

/* ============================================================== registry */

export function RegistryPanel() {
  const { data, error, loading, refresh } = useResource<AgentCard[]>(useCallback(() => api.agents(), []));

  return (
    <div className="panel">
      <Card
        title="Agent registry"
        subtitle="Discovered over the A2A protocol"
        action={<Button variant="ghost" busy={loading} icon={<RefreshCw size={14} />} onClick={refresh}>Refresh</Button>}
      >
        <a className="linkout" href={`${API_BASE}/.well-known/agent-card.json`} target="_blank" rel="noreferrer">
          <Link2 size={13} /> /.well-known/agent-card.json
        </a>

        {loading && <Skeleton lines={4} />}
        {error && <p className="muted-note">{error}</p>}

        {data && (
          <ul className="cards-list">
            {data.map((agent) => (
              <li key={agent.name} className="mini">
                <div className="mini__head">
                  <BadgeCheck size={15} />
                  <strong>{agent.name}</strong>
                  <Chip tone="info">{agent.role}</Chip>
                  <span className="mini__ver">v{agent.version}</span>
                </div>
                <p className="mini__desc">{agent.description}</p>
                <div className="stage__chips">
                  {agent.skills.map((s) => (
                    <Chip key={s.name} tone={s.is_compiled_skill ? 'good' : 'neutral'}>
                      {s.name}
                    </Chip>
                  ))}
                </div>
                {agent.security_schemes.map((scheme) => (
                  <span key={scheme} className="mini__scheme">
                    <ShieldCheck size={11} /> {scheme}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/* ================================================================ ledger */

export function LedgerPanel() {
  const { data, error, loading, refresh } = useResource(useCallback(() => api.ledger(), []));

  return (
    <div className="panel">
      <Card
        title="Audit ledger"
        subtitle="Every entry commits to the one before it"
        action={<Button variant="ghost" busy={loading} icon={<RefreshCw size={14} />} onClick={refresh}>Refresh</Button>}
      >
        {loading && <Skeleton lines={5} />}
        {error && <p className="muted-note">{error}</p>}

        {data && (
          <>
            <div className="verdict__facts">
              <Metric label="Entries" value={data.ledger_entries.length} />
              <Metric
                label="Chain"
                value={data.is_chain_valid ? 'Valid' : 'Broken'}
                tone={data.is_chain_valid ? 'good' : 'bad'}
                hint="Replays every link and recomputes each hash"
              />
            </div>

            {data.ledger_entries.length === 0 ? (
              <EmptyState
                icon={<ScrollText size={26} />}
                title="Ledger is empty"
                body="Run an incident and the audit trail starts here."
              />
            ) : (
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>#</th><th>Agent</th><th>Action</th><th>Status</th><th>ms</th><th>Chain</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.ledger_entries].reverse().map((e: LedgerEntry) => (
                      <tr key={e.chain_hash ?? e.event_id}>
                        <td className="num">{e.sequence ?? '—'}</td>
                        <td>{e.agent_name}</td>
                        <td className="mono">{e.action_name}</td>
                        <td>
                          <Chip tone={e.status.includes('FAIL') || e.status === 'REFUSED' ? 'bad' : 'good'}>
                            {e.status.replace(/_/g, ' ').toLowerCase()}
                          </Chip>
                        </td>
                        <td className="num">{Math.round(e.duration_ms)}</td>
                        <td className="mono dim">{e.chain_hash?.slice(0, 12)}…</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

/* =============================================================== finops */

export function FinOpsPanel() {
  const { data, error, loading, refresh } = useResource<FinOpsAudit>(useCallback(() => api.finops(), []));

  const priced = data?.total_monthly_savings_usd ?? 0;

  return (
    <div className="panel">
      <Card
        title="Cloud spend"
        subtitle="Configured limits measured against recorded usage"
        action={<Button variant="ghost" busy={loading} icon={<RefreshCw size={14} />} onClick={refresh}>Rescan</Button>}
      >
        {loading && <Skeleton lines={4} />}
        {error && <p className="muted-note">{error}</p>}

        {data && (
          <>
            <div className="verdict__facts">
              <Metric
                label="Recoverable monthly"
                value={priced > 0 ? `$${priced.toLocaleString()}` : '—'}
                tone={priced > 0 ? 'good' : 'muted'}
                hint={priced > 0 ? undefined : 'Nothing priced — see notes below'}
              />
              <Metric label="Findings" value={data.waste_detected_count} />
              <Metric
                label="Services examined"
                value={data.measurement.services_examined}
                hint={`${data.measurement.window_days}-day window`}
              />
            </div>

            {data.waste_details.length === 0 ? (
              <EmptyState
                icon={<DollarSign size={26} />}
                title={data.measurement.cloud_run_available ? 'Nothing over-provisioned' : 'Nothing measured'}
                body={
                  data.measurement.cloud_run_available
                    ? 'Every service examined sits within its limits, allowing for headroom.'
                    : 'Cloud Run is unreachable from here, so there is nothing to audit. No figures are shown rather than estimated ones.'
                }
              />
            ) : (
              <ul className="cards-list">
                {data.waste_details.map((w) => (
                  <li key={w.resource_id} className="mini">
                    <div className="mini__head">
                      <DollarSign size={15} />
                      <strong className="mono">{w.resource_id}</strong>
                      {w.monthly_cost_usd !== null ? (
                        <Chip tone="warn">${w.monthly_cost_usd}/mo</Chip>
                      ) : (
                        <Chip tone="neutral">unpriced</Chip>
                      )}
                    </div>
                    <p className="mini__desc">
                      {w.configured_memory_mib}Mi configured · peaked at{' '}
                      {w.observed_peak_memory_mib}Mi across {w.samples} samples
                    </p>
                    <p className="mini__fix">{w.remediation}</p>
                    {w.cost_note && <p className="muted-note">{w.cost_note}</p>}
                  </li>
                ))}
              </ul>
            )}

            {data.measurement.services_unmeasured.length > 0 && (
              <p className="muted-note">
                No usage recorded for {data.measurement.services_unmeasured.join(', ')} — reported
                as unmeasured rather than as idle, since nothing was observed either way.
              </p>
            )}
            <p className="muted-note">{data.measurement.billing_export.note}</p>
          </>
        )}
      </Card>
    </div>
  );
}

/* ============================================================= compiler */

export function CompilerPanel() {
  const toast = useToast();
  const [skills, setSkills] = useState<CompiledSkill[] | null>(null);
  const [trajectories, setTrajectories] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const t = await api.trajectories();
      setTrajectories(t.length);
    } catch {
      setTrajectories(null);
    }
  }, []);

  useEffect(() => {
    // load() only ever sets state after `await api.trajectories()`, so nothing
    // here runs synchronously during the effect. The rule cannot see past the
    // await and flags the call itself.
    // oxlint-disable-next-line react/set-state-in-effect
    void load();
  }, [load]);

  const mine = async () => {
    setBusy(true);
    try {
      const result = await api.mineSkills();
      setSkills(result.all_compiled_skills);
      void load();
      if (result.newly_compiled_count > 0) {
        toast.success(`${result.newly_compiled_count} skill(s) compiled`);
      } else {
        toast.info('Nothing to compile', 'A trajectory must recur before it becomes a skill.');
      }
    } catch (e) {
      toast.error('Mining failed', e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <Card
        title="ThorForja"
        subtitle="Recurring tool sequences become deterministic skills"
        action={
          <Button variant="primary" busy={busy} onClick={mine} icon={<Hammer size={15} />}>
            Mine trajectories
          </Button>
        }
      >
        <div className="verdict__facts">
          <Metric
            label="Recorded trajectories"
            value={trajectories ?? '—'}
            hint="Tool sequences the swarm actually executed"
          />
          <Metric label="Compiled skills" value={skills?.length ?? '—'} />
        </div>

        <p className="muted-note">
          A sequence must recur across <em>separate incidents</em> before it compiles. The
          same incident seen twice is one observation, not a pattern — and a compiled skill
          only skips the diagnosis call, never the safety review or the human gate.
        </p>

        {skills === null ? (
          <EmptyState
            icon={<Loader2 size={26} />}
            title="Not mined yet"
            body="Run a couple of incidents first, then mine for repeated sequences."
          />
        ) : skills.length === 0 ? (
          <EmptyState
            icon={<Hammer size={26} />}
            title="No recurring sequence yet"
            body="Run two separate incidents of the same shape and it becomes eligible."
          />
        ) : (
          <ul className="cards-list">
            {skills.map((s) => (
              <li key={s.skill_id} className="mini">
                <div className="mini__head">
                  <Hammer size={15} />
                  <strong className="mono">{s.skill_id}</strong>
                  <Chip tone={s.verified_by_judge ? 'good' : 'warn'}>
                    {s.verified_by_judge ? 'judge-verified' : 'unverified'}
                  </Chip>
                </div>
                <p className="mini__desc mono">{s.skeleton_signature.replace(/->/g, ' → ')}</p>
                <div className="stage__chips">
                  <Chip>{s.distinct_incidents} incident(s)</Chip>
                  <Chip>{s.total_executions} dispatch(es)</Chip>
                  {s.mean_diagnosis_tokens > 0 && (
                    <Chip tone="good">~{s.mean_diagnosis_tokens} tokens/call saved</Chip>
                  )}
                  {s.input_slots.map((slot) => (
                    <Chip key={slot} tone="info">{slot}</Chip>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
