# Runbook — An agent is running something we did not publish

Symptom: the alert `engine_agent_drift_detected` (`WORKER_STALL`) fires, or the ops
console's **What the voice platform is running** panel shows a non-zero "Running
something else". Either way the claim is specific: for N live agents, the voice platform
was READ BACK and is holding a script, disclosure line or voice other than the one our
row says we published.

This is not a screen being stale. `sweep_engine_drift`
(`apps/workers/engine_reconciliation.py`, cron at :07 and :37) asks the vendor and
compares against the exact `AgentConfig` a publish would send. A `not_applied` verdict is
a PROVEN mismatch — "we could not read the answer" is counted separately, as
`undetermined`, and never raises this alarm.

**Why it matters more than a wrong screen.** The disclosure line is in the prompt. An
agent whose greeting was dropped or rewritten at the vendor is a client answering Indian
callers without the disclosure TRAI requires (hard rule 5), on our infrastructure, under
our telemarketer registration.

Ground rules: production access goes through the audited admin path (SECURITY-COMPLIANCE
§"Admin access path"). Read-only SELECTs. Never select a prompt body, a disclosure line
or a phone number into a ticket (hard rule 6) — every query below returns ids and
verdicts.

## 0. Do NOT start by re-publishing

Neither the sweep nor the console will re-publish, deliberately, and neither should you
as a first move. The two things that produce this state are:

* somebody edited the agent in the **vendor's own dashboard** — plausibly the correct
  emergency edit, made while our console was the thing that was down;
* a publish that **failed on our side after the vendor committed**, so our row rolled
  back to the previous script and the engine kept the new one.

In the first case re-publishing destroys someone's incident response. In the second it is
usually right. You cannot tell which from a count, which is why step 2 exists.

## 1. Find the agents

The verdicts live on the routing bridge, which is global and un-RLS'd
(`apps/api/db/registry.py` records why):

```sql
SELECT tenant_id, agent_id, engine_agent_ref, drift_state, drift_detected_at,
       drift_checked_at
FROM engine_agent_routes
WHERE active AND drift_state = 'not_applied'
ORDER BY drift_detected_at;
```

`drift_detected_at` is when the CURRENT run of divergence began, not when it was last
observed — it is set once and left alone until the agent reads back clean. Minutes old
beside a recent deploy is probably a publish that raced the sweep; days old is a vendor
dashboard edit nobody noticed.

## 2. Read what actually differs, per agent

`GET /v1/agents/{agent_id}/engine-state` (client realm, the tenant's own scope — an
admin uses D-22 view-as). It performs the same read on demand and returns the
operator-readable sentence plus the three per-property verdicts
(`prompt_applied`, `disclosure_applied`, `voice_applied`).

* `disclosure_applied: false` — **treat as an incident, not a config drift.** Hard rule 5
  is the one property here with a legal consequence. Consider pausing the agent before
  deciding anything else.
* `prompt_applied: false` alone — the script differs. Read the agent's own screen for what
  we believe is live, and the vendor dashboard for what they are holding, before choosing
  a direction.
* `voice_applied: false` alone — the cheapest case; a republish is almost always right.

## 3. Choose a direction, then act through the normal path

* **Our version is right** (the vendor edit was a mistake, or a publish was lost):
  republish from the agent's screen — "Apply to live". That path reads the agent back and
  REFUSES on a proven mismatch, so a republish that does not take will fail loudly rather
  than leaving you believing it worked.
* **The vendor's version is right** (someone made a deliberate emergency edit): bring OUR
  row up to it — edit the prompt/voice in the console and apply — so the next publish does
  not silently undo it. Do not leave the two disagreeing: the alarm will keep firing and
  will stop being read.

Either way the next sweep clears `drift_detected_at` on its own once the agent reads back
`applied`. There is nothing to acknowledge and nothing to reset by hand.

## 4. If the count is `undetermined` rather than `out_of_sync`

That is the voice platform not answering or not answering in a shape our adapter can read.
It does not alert, and it should not: it is a vendor availability signal, not a fleet of
drifted agents. Check `engine_unreachable` / `engine_rejected` in the API logs. A
persistent non-zero `undetermined` with no vendor outage means the adapter's read-back
shape has drifted from what the vendor now returns — that is our bug, and it is the same
class OPERATIONS §2 gate 2 exists to catch.

## 5. If "Oldest check" stops moving

The panel's `oldest_checked_at`. If it is `never`, or older than about an hour, the sweep
is not running and **every count on that panel is stale** — `out_of_sync: 0` then means
nothing at all. Check the worker (`arq` process, `apps.workers.settings.WorkerSettings`)
and the outbox dead-letter panel above it for `sweep_engine_drift` entries: the cron is
registered with `max_tries = WORKER_MAX_TRIES`, so a sweep that failed three times is in
the DLQ rather than silently absent.
