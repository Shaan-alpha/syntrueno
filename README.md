# Syntrueno

**Zero-trust autonomous cloud operations swarm on Google Cloud.**

Gemini-backed agents diagnose live incidents, propose remediations, judge their
own plans for safety, and — behind a cryptographic human gate — execute real
changes against real infrastructure, then verify the change actually took effect.

> Google Cloud "All Things Agentic" Hackathon 2026 · Track 3: The Fortified Enterprise Fleet

| | |
| :-- | :-- |
| **Live service** | https://syntrueno-18489510475.us-central1.run.app |
| **Agent card** | [`/.well-known/agent-card.json`](https://syntrueno-18489510475.us-central1.run.app/.well-known/agent-card.json) |
| **API docs** | [`/docs`](https://syntrueno-18489510475.us-central1.run.app/docs) |
| **Health** | [`/api/v1/health`](https://syntrueno-18489510475.us-central1.run.app/api/v1/health) |
| **Tests** | 113 passing offline in ~0.9s, no credentials required |

---

## See it work in 30 seconds

```bash
python scripts/run_demo.py --remote
```

Drives the live service and prints what actually came back. Add `--execute` to
sign the human gate and perform a real Cloud Run mutation.

Nothing in that output is scripted. Every latency and token count is measured by
the service, and when the swarm degrades or refuses, that is what prints.

---

## What it actually does

An incident arrives. What follows is real:

```
error message carries an injection attempt
      │
      ▼
Model Armor            neutralises the injection, keeps the evidence
      │
      ▼
Commander              mints a scoped A2A capability token per dispatch
      │
      ▼
SRE Agent              reads telemetry, Gemini diagnoses the root cause
                       chooses a tool from a closed enum
      │
      ▼
Judge Agent            Gemini scores the plan 0-10 against a safety rubric
      │
      ▼
tier resolution        Tier 1 auto · Tier 2 consensus · Tier 3 human gate
      │
      ▼
D17 gate               engineer signs; signature is hash-bound, single-use,
                       and expires
      │
      ▼
Cloud Run Admin        five guards, then the real mutation
      │
      ▼
verification           re-reads live state to prove the change took effect
      │
      ▼
Firestore              hash-chained audit entry + memory the next incident reads
```

A measured run against the live service:

```
injections neutralized  1
diagnosis               "memory usage is consistently hitting the 512Mi limit,
                         causing repeated OOMKilled and 7 restarts"
confidence              1.0
tool chosen             update_cloud_run_resources {memory: 1Gi, cpu: 1}
judge score             8.0 / 10  →  TIER_3_HUMAN_GATE
sre model               gemini-3.1-flash-lite   1,178 ms
judge model             gemini-3.6-flash        5,596 ms
canary before           memory=512Mi
canary after            memory=1Gi     status APPLIED, verified True
signature replay        409 refused
ledger                  12 entries, chain valid
```

---

## Security design

The interesting decisions are the ones that make a class of failure
**unrepresentable** rather than merely blocked.

**The agent's action space is a closed enum.** `RemediationTool` is handed to
Gemini as its response schema. There is no destructive verb in it, so a
successful prompt injection cannot produce one — the worst it can achieve is a
*wrong safe action*, which the Judge and the human gate still have to pass.
Filtering a bad tool call is a weaker guarantee than making it unrepresentable.

**No delete verb exists.** `app/cloud/runadmin.py` implements only capacity and
lifecycle changes. Deletion is not blocked; it is absent. A blocked path can be
reached by a bug — an absent one cannot. A test asserts no delete API call
appears anywhere in the module.

**Evidence is not instruction.** Inbound telemetry and outbound tool calls get
different rule sets. Real alerts quote SQL and shell commands — that is what an
incident *looks like* — so screening evidence for `DROP TABLE` and refusing the
alert breaks the product's primary use case. Destructive-verb screening happens
at the tool-invocation boundary, the only place such a verb could do harm.

**Signatures authorise one execution.** A signed approval is bound by SHA-256 to
one tool, one parameter set, one tier. It is spent on execution and expires
after 30 minutes. It cannot be replayed, and it cannot cover a different action.

**IAM enforces the allowlist independently.** The runtime service account holds
`run.admin` on the canary service *resource*, never project-wide. The code check
and the platform check would both have to fail.

**The system reports its own degradation.** Every fallback sets a visible flag.
Gemini unreachable → heuristic path plus `degraded: true` and a reason. Firestore
unreachable → in-memory plus a flag. A mutation that fails is audited as
`FAILED`, never as a silent success. Latencies come from `perf_counter` and token
counts from the model's own `usage_metadata`.

---

## Model routing

Verified by execution against this project's API key on 2026-08-22.
`gemini-2.5-*` returns **404 for new keys**, and the Pro tier returns 429 on the
free tier.

| Tier | Model | Measured | Used for |
| :-- | :-- | --: | :-- |
| Fast | `gemini-3.1-flash-lite` | ~1.2–2.1 s | diagnosis, extraction, triage |
| Reasoning | `gemini-3.6-flash` | ~5.6–21.6 s | safety judgement |

The free tier caps each thinking-capable Flash model at **20 requests per day**,
so pinning both agents to one model allows ten incidents a day in total. The
client walks an ordered chain instead — and because a 429 is usually a daily cap
that backoff will never clear, it advances to the next model immediately rather
than sleeping against a wall.

```
gemini-3.6-flash → gemini-3.7-flash → gemini-3.5-flash → gemini-3.1-flash-lite
      20/day    +       20/day     +      20/day      +       500/day
                                                    = ~560 reasoning calls/day
```

Diagnosis runs on the fast tier deliberately: it is closer to extraction than to
judgement, and reserving the scarce thinking budget for the Judge is where being
wrong actually costs something.

---

## Google Cloud stack

| Service | Use |
| :-- | :-- |
| **Cloud Run** | Hosts the API and the built frontend in one container, scale-to-zero |
| **Cloud Run Admin API** | The guarded remediation surface |
| **Firestore** | Hash-chained audit ledger, cross-session memory, approvals, trajectories |
| **Secret Manager** | Gemini key and A2A signing secret, mounted at runtime |
| **Gemini API** | `gemini-3.1-flash-lite` and `gemini-3.6-flash` via `google-genai` |
| **IAM** | Resource-scoped `run.admin` confining the swarm to one service |

---

## Run it locally

```bash
# 1. Configure
cp backend/.env.example backend/.env
#    add a free Gemini key from https://aistudio.google.com/apikey
#    generate a secret:  python -c "import secrets; print(secrets.token_urlsafe(48))"

# 2. Start both services
./dev.sh          # Linux / macOS
.\dev.bat         # Windows
```

- Frontend — http://localhost:5173
- API docs — http://localhost:8000/docs
- Agent card — http://localhost:8000/.well-known/agent-card.json

### Tests

```bash
cd backend && .venv/Scripts/pytest -q
```

**113 tests, ~0.9s, no API key and no cloud credentials needed.** The suite is
offline by construction: `conftest.py` forces every external dependency off
regardless of your local `.env`, and a guard test fails if writes ever get slow
enough to imply a network round trip.

### Deploy

```bash
./deploy.sh
```

Builds from the repo root so the frontend ships with the API, mounts secrets
from Secret Manager, and sets a 300s request timeout — real reasoning takes
longer than the 60s default allows.

---

## Repository layout

```
backend/app/
  llm/gemini.py          sole Gemini entry point — routing, chain fallback, telemetry
  agents/                sre · judge · finops · commander
  cloud/runadmin.py      the only code that can change infrastructure
  security/              model_armor · token_auth · human_gate
  storage/               firestore_backend · audit_ledger · memory_bank
  compiler/              ThorForja trajectory recording and compilation
backend/tests/           113 offline tests
frontend/src/            React 19 + TypeScript operations console
docs/specs/              system design
scripts/run_demo.py      end-to-end demo against a live deployment
```

Only `app/cloud/*` talks to Google Cloud, and only `app/llm/*` talks to Gemini.
Agents depend on those interfaces, which is what keeps every agent testable with
no network.

---

## Status

Built and verified live:

- [x] Gemini-backed diagnosis and safety judgement, with honest degradation
- [x] Firestore persistence — ledger head recovery verified across a cold start
- [x] Guarded Cloud Run remediation with post-change verification
- [x] Single-use, hash-bound, expiring approvals
- [x] Enforced A2A capability tokens on every agent dispatch
- [x] Secrets in Secret Manager, resource-scoped IAM

In progress:

- [ ] Cloud Monitoring alert → Pub/Sub → webhook, for fully event-driven triage
- [ ] `modelarmor.googleapis.com` in front of the regex layer
- [ ] ThorForja compiling genuinely recurring trajectories into dispatchable skills
- [ ] Streamed incident progress in the console, replacing staged timing
- [ ] Multimodal telemetry ingestion and BigQuery-backed FinOps

`docs/` also contains the strategy research this project was planned from. Those
documents predate the build and describe intent rather than current state; where
they disagree with this README, this README is what the code does.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
