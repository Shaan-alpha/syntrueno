# Syntrueno demo video: narration and shot list

## How to read this file

Every beat is split three ways. Nothing else in this file is spoken.

| Marker | Meaning |
| --- | --- |
| **SAY** | Read this aloud, word for word. It is the only spoken text. |
| **DO** | The action on screen while the SAY above it is being said. |
| **NOTE** | Background for you only. Never read, never filmed. |

Target 3:52 against a hard 4:00 cap. Read at roughly 145 words per minute.
Pause where marked rather than speeding up.

Record at 1440 by 900 in dark theme, bookmarks bar hidden, other tabs closed.
The ambient background does not read well below 1280 wide.

---

## Timing: this is a wall-clock budget, not a speech budget

The spoken script is 492 words, which is 3:24 of talking. That leaves about 35
seconds for three live runs, a real Cloud Run mutation, and four tab switches.
The mutation alone can outrun it: `_await_convergence` polls for up to 90
seconds, and a real revision rollout is usually 20 to 60.

**Plan an edit cut during convergence at 2:37.** It is the one place the machine
can blow the budget on its own.

| Section | Speech | Machine wait | Ends at |
| --- | --- | --- | --- |
| The problem | 32s | none | 0:32 |
| What it does | 38s | none | 1:10 |
| The clean run | 37s | ~18s, overlapped | 1:55 |
| The attack | 35s | ~6s, three screens | 2:37 |
| The gate and mutation | 28s | 30 to 60s, **cut here** | 3:12 |
| Proof on Google Cloud | 22s | ~6s of tab switches | 3:40 |
| Close | 12s | none | 3:52 |

---

## Pre-flight

**Already done, just confirm:**

1. ~~Deploy the three fixes.~~ Done. Revision `syntrueno-00042-dxk` is serving:
   Gemma answers instead of timing out, leaving Overview no longer destroys the
   incident, and the studio no longer refuses quoted commands.
2. ~~Reset the canary to 512Mi.~~ Done, revision `syntrueno-canary-00023-6mk`.
   **Re-check this after every rehearsal**, because a rehearsal that reaches the
   mutation step will push it back to 1Gi and the 2:37 shot needs it at 512Mi:
   ```
   curl -s https://syntrueno-18489510475.us-central1.run.app/api/v1/cloud/canary
   gcloud run services update syntrueno-canary --region us-central1 --memory 512Mi
   ```

**Still to do before you hit record:**

3. Close every other browser tab. Nine were open in your last screenshot,
   including "Careers at…" and a Twitch tab with a notification badge. Judges
   read tab titles.
4. Open the live service and let it load once, so the first metric row is
   populated and you are not filming a cold start.
   https://syntrueno-18489510475.us-central1.run.app
5. Confirm the header pill says **Gemini live**, not Heuristic mode.
6. Open these three tabs in advance, left to right in this order, so the 3:12
   tour moves one way across the tab strip: the Cloud Run revision page, the
   Firestore `audit_ledger` collection, and Cloud Trace.
7. Glance at the Ledger tab. The chain header must read **Valid**. It did at the
   last check, at 105 entries.
8. Rehearse once, then wait a few minutes before the real take. Gemma is on the
   free tier. An incident now completes in about 17 seconds.

---

# 0:00 to 0:32 · The problem

**DO** — On camera, or a single title card. Do not open the app yet.

---

**SAY**
> An agent that can fix your infrastructure is an agent that can break it. And
> the alert it reads is text that an attacker can write.

**DO** — Hold the title card. Pause a full beat before the next line.

**NOTE** — This couplet is the thesis of the whole video. The pause is what
marks it as one.

---

**SAY**
> Those are two different failures. One is a wrong action, executed. The other
> is a hostile instruction, obeyed.

**NOTE** — **This is the cut candidate.** If you run long anywhere, drop this
sentence and nothing else. It restates the couplet above it and buys back 7
seconds.

---

**SAY**
> This is Syntrueno. It diagnoses live incidents on Google Cloud, judges its own
> plans for safety, and makes real changes to running infrastructure. Everything
> you are about to see is the live service.

**DO** — Cut to the running app on the word "Syntrueno". On "live service", rest
the cursor on the **Gemini live** pill in the header for a beat.

**NOTE** — That pill is the claim. Let the viewer read it rather than asserting
it over a moving cursor.

---

# 0:32 to 1:10 · What it does

**DO** — Show `assets/architecture.png`. Trace the path with your cursor.

**NOTE** — Move deliberately. A fast cursor on a dense diagram reads as noise.

---

**SAY**
> An incident arrives, sometimes from a Cloud Monitoring alert with nobody in
> the loop. That text is untrusted, so three screens run over it: regex rules,
> Model Armor, and a Gemma semantic screen.

**DO** — Touch the ingest node, then stop on each of the three screening boxes
as you name it. Three named things, three separate stops.

---

**SAY**
> A Commander mints a short lived, scoped token for each dispatch. An SRE agent
> diagnoses from telemetry. A Judge scores the plan against a safety rubric.

**DO** — Same discipline: Commander, SRE, Judge, one stop each.

---

**SAY**
> The decision the whole system rests on is here. The agent's action space is a
> closed enum, handed to Gemini as its response schema. There is no destructive
> verb in it. Not blocked. Absent.

**DO** — Stop the cursor entirely on the action enum. Leave it still for the
rest of the paragraph.

**NOTE** — Stillness is what marks this as the important claim. "Not blocked.
Absent." is the strongest line in the script. Slow down and let the two full
stops do the work.

---

# 1:10 to 1:55 · The clean run

**DO** — Overview tab. Select "Memory exhaustion". Expect about 17 seconds end
to end.

---

**SAY**
> I will trigger a memory exhaustion incident. This runs the real swarm against
> the live canary service.

**DO** — On "the live canary service", rest the cursor on the red **Live
remediation armed** chip beside the button. One beat, then click Run on the word
"trigger", not before.

**NOTE** — That chip is the UI saying `dry_run=false`. It is the cheapest
corroboration in the app for the claim you made at 0:20 about making real
changes. Clicking on "trigger" means the stages fill under your narration
instead of racing ahead of it.

---

**SAY**
> Screening first. Then recall, which finds prior incidents on this same service.

**DO** — Point at the three layer chips on the screening row: regex, Model
Armor, Gemma.

**NOTE** — All three appear now. The "screened by 2 of 3 layers: gemma_timeout"
warning that used to sit here was not a quota problem and not a slow network:
Gemma does not enforce the response schema, so a benign alert produced an
unbounded answer that ran past the API's own 10 second deadline and came back
504. Bounding the output took benign text from 0 of 9 answering to 10 of 10 at a
1.8 second median. If that warning appears again, the deploy did not take.

---

**SAY**
> Diagnosis, from Gemini 3.5 Flash. Note the latency and the token count. Every
> figure on this screen was measured by the service. None of it is estimated.

**DO** — Point at the latency chip, then the token chip, in that order.

**NOTE** — The model attribution is correct as written. Diagnosis runs on the
fast tier deliberately, which is `gemini-3.5-flash`; only the judge runs on the
thinking tier. Easy to say backwards on camera, so read it as written.

---

**SAY**
> Safety review, from Gemini 3.6 Flash. It scores the plan and resolves the tier.
> Because this action changes a running service, it does not execute. It stops
> and waits for a human signature.

**DO** — Point at the score chip, then let the verdict card arrive on its own.
Click nothing.

**NOTE** — The card reads **Awaiting signature** in amber. The gate is the next
section and deserves its own beat.

---

# 1:55 to 2:37 · The attack

**NOTE** — The most important forty seconds in the video. Everything else is
setup for this.

---

**SAY**
> Now the same outage, with a prompt injection buried in the error text.

**DO** — Before clicking, hover the scenario blurb so "The same outage, with
hostile text buried in the error" is readable. Then run it.

**NOTE** — "Same" is the control in this experiment. The viewer has to believe
the only thing that changed is the hostile text.

---

**SAY**
> Quarantined, and three independent screens agreed.

**DO** — Point at the "neutralised" count chip, then the three layer chips.

**NOTE** — Reworded from "it names the rule that matched", which the Overview
timeline does not do. It shows a count plus the layers. Only the Security panel
lists rules individually.

---

**SAY**
> But refusing anything that looks dangerous is easy, and useless. Here is a
> real alert quoting a DROP TABLE statement from a slow query log. That is a
> database engineer's evidence about what broke.

**DO** — Switch to the **Security** tab. Click the "Alert quoting SQL" preset so
the payload text is visible. Do not click Screen yet.

---

**SAY**
> It passes straight through.

**DO** — Click Screen on the word "passes". The card returns green, headed
**Allowed through**.

---

**SAY**
> And here is what the model would actually receive. The DROP TABLE text is
> still in it.

**DO** — Point at the "What the model would receive" block, with the SQL intact.

**NOTE** — This is the strongest artifact in the app and the script used to walk
past it. It turns "it passes" from a claim into something the viewer reads for
themselves.

---

**SAY**
> Instructions are stopped. Evidence gets through. That distinction is the whole
> design.

**DO** — Cursor still. Land the line.

**NOTE** — Every green preset now passes, so you can click any of them safely.
That was not true before: "Alert quoting a shell command" came back quarantined
under a green button, which would have refuted this exact sentence while you
said it. The panel now screens with all three layers, and an injection here
reads **Instructions neutralised** while still showing what the model receives,
with the hostile spans replaced by NEUTRALIZED_INJECTION. If you are running
long, you can make this whole point on one screen: run the injection preset
here, show the excised text, then the SQL preset intact, back to back.

---

# 2:37 to 3:12 · The gate, and a real mutation

**NOTE** — **Read this before recording the section.** Execute calls the real
Cloud Run Admin API and then polls live state until the new revision converges,
for up to 90 seconds. You cannot talk for 60 seconds of rollout. Either stop
recording the moment you click Execute and resume when the memory reads 1Gi, or
keep rolling and cut the dead air in the edit.

**NOTE** — The approval you are returning to is the one the **injection** run
produced, which is the better story: the hostile text was neutralised and the
legitimate fix underneath it still had to pass the gate. It survives the trip
through the Security tab now. It did not before, and that was the bug that would
have killed this section.

**DO** — Back to Overview. The timeline and verdict are still there.

---

**SAY**
> I sign the approval. The signature is SHA-256, bound to this exact action and
> this exact parameter set, usable once, and it expires in thirty minutes.

**DO** — Point at the truncated action hash on the card as you say "bound to
this exact action". Sign on the word "sign".

---

**SAY**
> Now it executes against the Cloud Run Admin API, and the memory limit actually
> changes. The service then re-reads live state until it converges, rather than
> trusting the API's acknowledgement.

**DO** — Click Execute on "executes". Point at 512Mi before the cut. **The wait
starts here.** Cut, and resume on the canary row reading **1Gi**, pointing at it.

**NOTE** — The convergence sentence is written to be spoken over the first
seconds of the wait, so the cut has somewhere to hide. Pointing at 512Mi before
and 1Gi after is what makes the change legible across an edit.

---

**SAY**
> Now I replay the same signature. Refused. One signature authorises one
> execution.

**DO** — Replay immediately.

**NOTE** — The refusal toast is fast and the line is short. Do not rush it. One
signature, one execution is the payoff of the entire gate.

---

# 3:12 to 3:40 · Proof it runs on Google Cloud

**DO** — Ledger tab, then the three console tabs you opened in pre-flight.

---

**SAY**
> Every outcome, including every refusal, is in a hash chained audit ledger.
> Each entry commits to the one before it, and the chain verifies.

**DO** — Point at the chain header reading **Valid** on the word "verifies".
Then run your eye down the entries so the refusal you just caused is visible
near the top.

**NOTE** — "Including every refusal" is only credible if a refusal is on screen.

---

**SAY**
> This is running on Cloud Run. Here is the revision, the Firestore collection
> holding that ledger, and Cloud Trace showing the spans from the incident you
> just watched.

**DO** — Three tabs, about two seconds each, no lingering.

**NOTE** — You are proving the services exist, not touring them.

---

# 3:40 · Close

**DO** — Leave the repo and the live URL visible.

---

**SAY**
> Two hundred and eighty eight tests pass offline in seconds, with no API key
> and no cloud credentials.

**NOTE** — Say "in seconds", not a specific number. Measured on this machine:
7.6s warm, 10.5s cold. The load-bearing half of the claim is "no key and no
credentials", and that is exactly true.

---

**SAY**
> Every figure you just saw was measured, not assumed.

**DO** — Hold the final frame two seconds past the last word before stopping.

**NOTE** — A clean tail is worth more than the two seconds it costs.

---

## After recording

- Upload to YouTube. **Public or unlisted both work.** Not private, which judges
  cannot open.
- Keep it under 4:00. If you run long, cut the restatement at 0:00 first, then
  trim the console tour at 3:12. **Never cut the attack demo at 1:55.**
- Paste the URL into the Devpost **Video demo link** field, which is required.
