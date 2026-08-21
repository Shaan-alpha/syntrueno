# Syntrueno — Live System Design

**Date:** 2026-08-22
**Status:** Awaiting review
**Scope:** Option C — full build (foundation + ThorForja + multimodal + BigQuery)
**Deadline:** Submit 2026-08-30. Video 08-29. **7 build days: Aug 22–28.**

---

## 1. Problem

The repository presents a Track 3 "Fortified Enterprise Fleet" submission whose
claims are not backed by its code. An audit on 2026-08-22 (commit `b96310c`)
found 24 defects. Two are disqualifying:

1. **No Gemini call exists anywhere.** `google-genai` is declared in
   `requirements.txt` and never imported. Every agent is an `if/elif` returning
   literals. This fails mandatory eligibility requirements 1 and 2.
2. **The D17 approval gate is bypassable by an unauthenticated caller** — proven
   live against production by forging an approval for `delete_production_database`.

This design replaces the stub layer with a genuinely live system: real Gemini
reasoning, real Google Cloud reads, real guarded mutations, real persistence,
and honest self-reporting when any of it degrades.

## 2. Verified environment

Everything below was confirmed by execution on 2026-08-22, not assumed.

| Fact | Value |
|---|---|
| GCP project | `composed-maxim-498517-f0` (number `18489510475`) |
| Billing | Enabled |
| Cloud Run service | `syntrueno` @ `us-central1` — live |
| Firestore | `(default)`, `FIRESTORE_NATIVE`, `us-central1` — **created this session** |
| Already enabled | `modelarmor`, `aiplatform`, `pubsub`, `bigquery`, `storage`, `run` |
| Enabled this session | `firestore` |
| `google-genai` | 2.19.0 in venv |

### 2.1 Model availability — this is a correction to every existing doc

`gemini-2.5-flash` returns **404: "no longer available to new users."** The docs,
`config.py`, and the submission package all target a model line this key cannot reach.

| Model | Thinking | Latency | Status |
|---|---|---|---|
| `gemini-3.1-flash-lite` | off | 8.5s | **FAST tier** |
| `gemini-3.6-flash` | 572 tok | 25.4s | **REASONING tier** |
| `gemini-3.6-flash` | forced off | — | `400` — thinking cannot be disabled |
| `gemini-3.5-flash` / `3.7-flash` | on | 32–37s | too slow |
| `gemini-pro-latest`, `3.1-pro-preview` | — | — | `429` quota exhausted on free tier |

Free tier is **intermittently unavailable** — `503 high demand` and `429` were both
observed within minutes. Retry with backoff is mandatory, not defensive polish.

### 2.2 Proof the real judge is better than the stub

Given a pool-exhaustion incident and the remediation the SRE stub proposes
(`max_connections` 100→200, `pool_timeout` 10s→30s), the real judge returned:

```
score = 3.5    is_approved = False    requires_human_signoff = True
critique: "Increasing max_connections from 100 to 200 without evaluating Cloud SQL
instance memory/CPU headroom risks database OOM or resource starvation.
Additionally, tripling pool_timeout to 30s when 504s are already occurring will
cause request pileups, thread starvation..."
```

The hardcoded stub returns **9.4 and approves**. The real judge catches a genuinely
dangerous fix. This becomes a demo beat: *the swarm rejects its own bad plan.*

## 3. Architecture

Eight modules, each with one purpose and an independently testable boundary.

| Module | Purpose | Depends on |
|---|---|---|
| `app/llm/gemini.py` | Sole Gemini entry point. Model routing, structured output, retry/backoff, timeout, degradation signalling | `google-genai` |
| `app/agents/sre.py` | Reads real telemetry, Gemini diagnoses root cause, proposes action | `llm`, `cloud.monitoring`, `cloud.runadmin` |
| `app/agents/judge.py` | Gemini scores the action against a safety rubric | `llm` |
| `app/agents/finops.py` | Real BigQuery billing analysis | `llm`, `cloud.bigquery` |
| `app/agents/commander.py` | Orchestrates, mints/verifies A2A tokens, writes audit | all agents, `security`, `storage` |
| `app/cloud/*` | `monitoring.py`, `runadmin.py`, `bigquery.py` — the only modules that touch GCP | google-cloud SDKs |
| `app/security/*` | `modelarmor.py` (real API + regex), `token_auth.py` (**enforced**), `human_gate.py` (server-side store) | `storage` |
| `app/storage/*` | Firestore-backed ledger, memory, approvals, trajectories — each with in-memory fallback | `google-cloud-firestore` |
| `app/compiler/*` | ThorForja: records real executions, compiles real dispatch, measures real timings | `storage` |

**Rule:** only `app/cloud/*` may call Google Cloud. Only `app/llm/*` may call Gemini.
Agents depend on interfaces, so every agent is testable offline.

## 4. Data flow

```
Cloud Monitoring alert policy ──► Pub/Sub topic ──► POST /api/v1/webhooks/gcp-alert ─┐
UI "Trigger Incident" button ────────────────────────────────────────────────────────┤
                                                                                      ▼
                                                              Model Armor (real API + regex)
                                                                                      ▼
                                                          Commander ── mints A2A token ──►│
                                                                                          ▼
                              SRE Agent: reads REAL metrics → Gemini 3.6-flash diagnoses
                                                                                          ▼
                                              Judge Agent: Gemini 3.6-flash scores 0–10
                                                                                          ▼
                        Tier 1 auto  │  Tier 2 consensus  │  Tier 3 → D17 human gate
                                                                                          ▼
                                    Cloud Run Admin API — GUARDED mutation on canary
                                                                                          ▼
                                    Re-read live metrics → VERIFY the fix actually worked
                                                                                          ▼
                          Firestore audit chain  +  ThorForja records the real trajectory
```

Both entry points converge on one `handle_incident()` function. The button is not a
separate path — it is a replay of the webhook payload, so demo and production are
the same code.

## 5. Safety guardrails on real remediation

Enforced in `app/cloud/runadmin.py` before any mutating call. Violations raise, never warn.

- **Service allowlist** — `syntrueno-canary` only. A dedicated throwaway service.
- **Project pin** — `composed-maxim-498517-f0`. The other three projects are
  unreachable by construction.
- **Verb allowlist** — `min-instances`, `max-instances`, `memory`, `cpu`,
  `concurrency`, deploy-new-revision. **No delete verb exists in the module.**
- **Approval binding** — a mutation requires a Firestore approval document with
  `status == APPROVED` whose `action_hash` matches the action being executed.
  This is the F-02 fix doing real work rather than being decorative.
- **Dry-run default** — `REMEDIATION_DRY_RUN` defaults to `true`, so tests and local
  runs plan the mutation and log it without executing. It is set to `false` only on
  the deployed demo service. In dry-run the audit entry records
  `status: DRY_RUN` — never `SUCCESS`.

### 5.1 Tier semantics

The three tiers in `ExecutionTier` currently exist as labels with no behaviour.
They become concrete:

| Tier | Condition | Behaviour |
|---|---|---|
| 1 — Autonomous | Read-only or non-mutating action | Executes immediately, no gate |
| 2 — Consensus | Judge `score >= 8.5` **and** `hallucination_detected == false` **and** the action's verb is in the allowlist | Executes automatically, audit records both agents' outputs |
| 3 — Human gate | Judge `requires_human_signoff`, **or** score `< 8.5`, **or** the action changes production capacity | Blocks. Writes a pending Firestore approval. Executes only after a signature whose `action_hash` matches |

Any action the judge scores below 5.0 is refused outright and never offered for
signature.

## 6. Degradation policy

Every fallback sets a visible flag. The system never pretends.

| Failure | Behaviour | Response field |
|---|---|---|
| Gemini 429/503 after retries | Heuristic diagnosis | `degraded: true`, `degraded_reason: "llm_unavailable"` |
| Firestore unreachable | In-memory store | `degraded: true`, `persistence: "memory"` |
| Model Armor API error | Regex-only screening | `armor_mode: "regex_fallback"` |
| Mutation fails | Audit entry `status: FAILED` | never a silent success |

This directly answers audit finding F-05 (fabricated metrics). **All latency and
token figures are measured with `perf_counter` and real `usage_metadata`.** The
`max(duration, 12.4)` floors are deleted.

## 7. Firestore schema

| Collection | Document | Purpose |
|---|---|---|
| `audit_ledger` | `{event_id}` | Hash-chained entries. `prev_hash`, `chain_hash` |
| `approvals` | `{approval_id}` | **Server-side** pending/approved records |
| `memory_bank` | `org_profile`, `incidents/{id}` | Cross-session memory that is actually written |
| `trajectories` | `{trajectory_id}` | Real executed tool sequences with measured timings |
| `compiled_skills` | `{skeleton_sig}` | ThorForja manifests with real execution counts |

The existing hash-chain logic in `audit_ledger.py` is correct and is preserved —
only the storage backend changes.

## 8. API changes

| Route | Change |
|---|---|
| `/healthz` | → `/api/v1/health`. Google Frontend intercepts `/healthz` before it reaches the container (F-08) |
| `/api/v1/webhooks/gcp-alert` | **New.** Pub/Sub push endpoint |
| `/api/v1/swarm/incident/stream` | **New.** SSE progress stream — required because real latency is ~35s |
| `/api/v1/governance/approvals/sign` | Accepts `{approval_id, signature}` only. Never a client-supplied action |
| `/.well-known/agent-card.json` | Reshaped to real A2A schema: `protocolVersion`, `capabilities`, `defaultInputModes/OutputModes`, skill `id`/`tags`, camelCase |
| CORS | Origin allowlist from env, not `*` |

## 9. Frontend changes

The `setTimeout` choreography must go. Real incidents take ~35s, so the UI
subscribes to the SSE stream and renders genuine agent progress.

- Health probe → `${apiBase}/api/v1/health` (fixes hardcoded `localhost`, F-08)
- Fix the five field-name mismatches (F-09)
- `runAutoHealingDemo` gets a real failure path — currently it freezes the UI (F-10)
- Wire the four unused endpoints: registry, audit ledger, compiled skills, replay
- Keynote replay toggle as recording insurance — justified by the observed 503/429

## 10. Testing

- Offline suite stays green with **no credentials** (`SIMULATION_MODE=true`)
- Live tests marked `@pytest.mark.live`, skipped without a key
- **New adversarial cases:**
  - A legitimate alert quoting `DROP TABLE` in a log excerpt **must pass** (F-06)
  - An injected instruction **must block**
  - A mutation against a non-allowlisted service **must raise**
  - A mutation without a matching approval **must raise**

## 11. Day plan — each day ends deployable

| Day | Date | Ships | End state |
|---|---|---|---|
| 1 | Aug 22 | `llm/gemini.py`; SRE + Judge real; F-02, F-03, F-06, F-12 | **Eligible + secure** |
| 2 | Aug 23 | Firestore for ledger, memory, approvals, trajectories (F-04) | **State is real** |
| 3 | Aug 24 | Canary service, real metric reads, guarded mutation + verification | **Action over chat is real** |
| 4 | Aug 25 | Pub/Sub spine, webhook, real Model Armor API | **Autonomous** |
| 5 | Aug 26 | Real ThorForja; SSE stream; frontend F-08/09/10/15 | **Differentiator real, demo safe** |
| 6 | Aug 27 | Multimodal vision + BigQuery FinOps | **Option C complete** |
| 7 | Aug 28 | Repo polish F-16, docs reconciled, license, diagram, naming sweep | **Submission-ready** |

**Cut order under time pressure:** multimodal → BigQuery → ThorForja depth.
**Days 1–4 are never cut.** If Day 6 is at risk, Day 5's demo-safety work takes
priority over Day 6's features.

## 12. Documentation reconciliation (Day 7)

The docs currently contradict the code and each other. To fix:

- One project name. `Syntrueno` in code, docs, and deploy script. `SentinelCommander`,
  `SentinelMesh`, `NexusFleet`, and `Compyle` are removed.
- One savings figure, derived from real BigQuery output — not `$650`/`$400`/`$440`.
- Real test count and real measured runtime.
- Model references updated from `2.5` to the verified `3.x` line everywhere.
- `deploy.sh` targets the repo root and the `syntrueno` service (F-14).
- Add `LICENSE` (Apache-2.0), repo description, page `<title>`, `docs/architecture.png`.
- **`docs/12_COMPETITIVE_LANDSCAPE` is excluded from all external material** — it
  names real competitor repositories and lists their "fatal weaknesses."

## 13. Open risks

| Risk | Mitigation |
|---|---|
| Free-tier `429`/`503` during the recorded demo | Retry, heuristic fallback, keynote replay toggle |
| ~35s real latency reads as slow on video | SSE progress stream; edit with cuts; pre-warm the container |
| Cloud Run service account lacks `run.admin` on canary | Grant on Day 3; verify with a dry-run first |
| Pub/Sub push auth to a public Cloud Run URL | OIDC token verification on the webhook |
| Day 6 features squeeze the video | Documented cut order; Day 5 leaves a shippable system |

## 14. Success criteria

1. `pytest` green offline with no credentials.
2. A judge can `curl` the live agent card and get spec-conformant JSON.
3. Triggering the canary alert produces, with no human input up to the D17 gate:
   a real diagnosis, a real score, a real approval record, a real mutation, and a
   real verification — all visible in the Firestore audit chain.
4. Every number shown in the UI is measured, not hardcoded.
5. No claim in the README or Devpost text is unsupported by code.
