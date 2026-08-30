# Syntrueno demo video: narration and shot list

## How to read this file

Every beat is split three ways. Nothing else in this file is spoken.

| Marker | Meaning |
| --- | --- |
| **SAY** | Read this aloud, word for word. It is the only spoken text. |
| **DO** | The action on screen while the SAY above it is being said. |
| **NOTE** | Background for you only. Never read, never filmed. |

**DO** lines name the browser tab by number: **Tab 1** is the app, **Tabs 2, 3
and 4** are the Google Cloud console. The numbers and their links are in
Pre-flight. A DO line without a number means stay on the tab you are already on.

Target 3:38 against a hard 4:00 cap, in one unedited take. Read at roughly 145 words per minute.
Pause where marked rather than speeding up.

Record at 1440 by 900 in dark theme, bookmarks bar hidden, other tabs closed.
The ambient background does not read well below 1280 wide.

---

## Timing: this is a wall-clock budget, not a speech budget

**Record this in one take, with no cuts.** The 30% Demo and Production
Readiness criterion asks, verbatim: "Does the video show an *unedited*, live
execution of the agent performing its task (via terminal logs, database updates,
or UI changes)?" A splice through the one real mutation is exactly what that
line penalises, and the mutation is the shot the whole video is built around.

That constraint is what decides the running order. `_await_convergence` polls
for up to 90 seconds and a real revision rollout is usually 30 to 60, which is
far too long to stand in silence and too long to cut without it showing. So the
Google Cloud proof moves *inside* the wait: you click Execute, walk the ledger
and the console while the revision rolls out, then come back to the canary row
now reading 1Gi. The dead air is filled with material that was already in the
script, and the rollout becomes the thing you are talking over rather than a gap.

The script is 514 words of required speech, 3:33 of talking, plus one optional
24-word spare line for a slow rollout. Counted from the SAY blocks in this file,
not estimated.

| Section | Speech | Machine wait | Ends at |
| --- | --- | --- | --- |
| The problem | 32s | none | 0:32 |
| What it does | 38s | none | 1:10 |
| The clean run | 37s | ~18s, overlapped by the speech | 1:47 |
| The attack | 36s | ~6s, three screens | 2:29 |
| The gate, sign and execute | 23s | rollout **starts**, you do not wait | 2:52 |
| Google Cloud proof | 25s | covers the rollout | 3:17 |
| Back to the canary, and the replay | 10s | rollout should be done | 3:27 |
| Close | 11s | none | 3:38 |

That lands at about 3:38 with roughly 22 seconds of headroom, and the spare line
spends 10 of it if the rollout is slow.

**If the rollout still is not finished after the spare line**, stay on Cloud
Trace and keep talking about what is on screen. Going slightly long is cheap;
the cap only means anything past 4:00 is not watched, and everything that scores
has already happened by 3:30. Cutting is the expensive option, not overrunning.

---

## Pre-flight

**Already done, just confirm:**

1. ~~Deploy the three fixes.~~ Done. Revision `syntrueno-00042-dxk` is serving:
   Gemma answers instead of timing out, leaving Overview no longer destroys the
   incident, and the studio no longer refuses quoted commands.
2. ~~Reset the canary to 512Mi.~~ Done, revision `syntrueno-canary-00023-6mk`.
   **Re-check this after every rehearsal**, because a rehearsal that reaches the
   mutation step will push it back to 1Gi, and the mutation shot needs 512Mi:
   ```
   curl -s https://syntrueno-18489510475.us-central1.run.app/api/v1/cloud/canary
   gcloud run services update syntrueno-canary --region us-central1 --memory 512Mi
   ```

**Still to do before you hit record:**

3. Close every other browser tab. Nine were open in your last screenshot,
   including "Careers at…" and a Twitch tab with a notification badge. Judges
   read tab titles.
4. Load Tab 1 once and let it settle, so the first metric row is populated and
   you are not filming a cold start.
5. On Tab 1, confirm the header pill says **Gemini live**, not Heuristic mode.
6. Open the four tabs below, left to right in that exact order. See the tab
   table under this list. The order matters: the 2:55 tour moves one way across
   the strip so you are never hunting for a tab while a Cloud Run revision is
   rolling out behind you.
7. On Tab 1, open the Ledger tab. The chain header must read **Valid**. It did
   at the last check, at 105 entries. Then go back to Overview so the recording
   starts where it should.
8. Rehearse once, then wait a few minutes before the real take. Gemma is on the
   free tier. An incident now completes in about 17 seconds.

### The four tabs, in left-to-right order

Open these and nothing else. Every **DO** line below names the tab by number.

**Tab 1 · The app.** Everything except the console tour happens here.
```
https://syntrueno-18489510475.us-central1.run.app
```

**Tab 2 · Cloud Run, the syntrueno service.** This is the tab that satisfies
"must demonstrate the backend is running on Google Cloud", so it is the one that
cannot be skipped.
```
https://console.cloud.google.com/run/detail/us-central1/syntrueno/revisions?project=composed-maxim-498517-f0
```

**Tab 3 · Firestore, the `audit_ledger` collection.** The chain you just showed
in the app, in the database that actually holds it.
```
https://console.cloud.google.com/firestore/databases/-default-/data/panel/audit_ledger?project=composed-maxim-498517-f0
```

**Tab 4 · Cloud Trace.** Spans are exported under service name `syntrueno`.
```
https://console.cloud.google.com/traces/explorer?project=composed-maxim-498517-f0
```

**NOTE** — Load all four once before recording and leave them loaded. A console
tab that spins up a loading skeleton on camera costs you three seconds each time,
and you have four of them back to back inside a Cloud Run rollout.

**NOTE** — Optional fifth tab if you want a stronger mutation proof:
`https://console.cloud.google.com/run/detail/us-central1/syntrueno-canary/revisions?project=composed-maxim-498517-f0`
is the canary's own revision list, where the mutation creates a new revision you
can watch appear. It is a better shot and it costs a tab switch and a refresh.
Only add it if a rehearsal shows you have the time.

---

# 0:00 to 0:32 · The problem

**DO** — *(no tab yet)* On camera, or a single title card. Do not show the
browser until the last line of this section.

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

**DO** — **Tab 1.** Cut to the running app on the word "Syntrueno". On "live
service", rest the cursor on the **Gemini live** pill in the header for a beat.

**NOTE** — That pill is the claim. Let the viewer read it rather than asserting
it over a moving cursor.

---

# 0:32 to 1:10 · What it does

**DO** — *(no tab)* Show `assets/architecture.png` full screen. Trace the path
with your cursor.

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

**DO** — **Tab 1**, Overview. Select "Memory exhaustion". Expect about 17
seconds end to end.

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

**DO** — **Tab 1**, Security tab. Click the "Alert quoting SQL" preset so the
payload text is visible. Do not click Screen yet.

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

# 2:37 to 2:55 · The gate, and a real mutation

**NOTE** — The approval you are returning to is the one the **injection** run
produced, which is the better story: the hostile text was neutralised and the
legitimate fix underneath it still had to pass the gate. It survives the trip
through the Security tab now. It did not before, and that was the bug that would
have killed this section.

**DO** — **Tab 1**, back to Overview. The timeline and verdict are still there.

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

**DO** — Point at the canary row reading **512Mi**, then click Execute on the
word "executes". **The rollout starts here and you do not wait for it.** Go
straight to the next section while it runs.

**NOTE** — This is the hinge of the whole recording. Do not stop, do not cut,
and do not stand watching a spinner. The convergence sentence is true and is
worth saying, and then you leave it running and go prove the Google Cloud
deployment, which takes about as long as the rollout does. You come back to a
finished mutation instead of filming a wait.

---

# 2:55 to 3:17 · Proof it runs on Google Cloud, while the revision rolls out

**DO** — **Tab 1** Ledger, then **Tabs 2, 3, 4** in that order. Left to right,
no backtracking.

**NOTE** — Same content as before, moved earlier on purpose. It is doing two
jobs now: it is the Google Cloud evidence the rules require, and it is what
covers the 30 to 60 seconds the Cloud Run rollout needs.

---

**SAY**
> While that rolls out, here is where all of this is running. Every outcome,
> including every refusal, is in a hash chained audit ledger. Each entry commits
> to the one before it, and the chain verifies.

**DO** — **Tab 1**, Ledger. Point at the chain header reading **Valid** on the
word "verifies". Then run your eye down the entries so the refusal you just
caused is visible near the top.

**NOTE** — "Including every refusal" is only credible if a refusal is on screen.
The opening clause is what makes the detour read as deliberate rather than as
stalling.

---

**SAY**
> This is Cloud Run. Here is the revision, the Firestore collection holding that
> ledger, and Cloud Trace showing the spans from the incident you just watched.

**DO** — **Tab 2** on "Cloud Run", **Tab 3** on "the Firestore collection",
**Tab 4** on "Cloud Trace". About two seconds each, no lingering.

**NOTE** — You are proving the services exist, not touring them.

---

**SAY** *(spare line, only if the rollout is not finished yet)*
> These spans are the same incident, stage by stage, with the model latencies
> the console reported. Nothing here is reconstructed after the fact.

**DO** — Stay on **Tab 4** and say this rather than cutting or going quiet.

**NOTE** — Written to buy about 9 seconds without padding. There are 16 seconds
of headroom before the cap, so use this before you ever consider an edit. If the
rollout is still not done after it, keep going on the trace detail. A slightly
long video that is unedited scores better on this rubric than a tight one with a
splice through the live execution.

---

# 3:17 to 3:32 · Back to the canary, and the replay

**DO** — Back to **Tab 1**, Overview. The canary row now reads **1Gi**. Point
at it.

---

**SAY**
> And there it is. The memory limit on the live service actually changed.

**DO** — Let the 1Gi sit on screen for a beat.

**NOTE** — You pointed at 512Mi before you clicked Execute. This is the other
half of that pair, and because there is no cut between them the change is
something the viewer watched happen rather than something they are told about.

---

**SAY**
> Now I replay the same signature. Refused. One signature authorises one
> execution.

**DO** — Replay immediately.

**NOTE** — The refusal toast is fast and the line is short. Do not rush it. One
signature, one execution is the payoff of the entire gate.

---

# 3:32 · Close

**DO** — **Tab 1**. Leave the repo and the live URL visible.

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
- **Do not edit it.** If a take goes wrong, record it again rather than
  trimming. The 30% criterion asks for unedited live execution, so a reshoot is
  cheaper than a splice. If you need to save time, drop the restatement at 0:00
  before the recording, not after it. **Never cut the attack demo at 1:55.**
- Paste the URL into the Devpost **Video demo link** field.

### What the rules require of the video

Checked against https://allthingsagentichackathon.devpost.com/rules. The video
is **mandatory**, not optional: the submission requirements say "Include a
demonstration video of your Project." All four required elements are in the
script above, in this order:

| Required | Where it lands |
| --- | --- |
| Short overview of the problem | 0:00 |
| Value proposition | 0:15 and 0:32 |
| Demo of the application in action | 1:10 through 3:27 |
| Backend demonstrably running on Google Cloud | 2:55 |

Plus: not longer than 4 minutes, or only the first 4 minutes are evaluated. Must
be in English or carry English subtitles.
