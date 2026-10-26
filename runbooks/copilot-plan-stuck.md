# Runbook — a Pip plan is stuck

Symptom: a client approved a plan ("Change 240 leads", "Call 80 leads") and its card has
said "Working…" with the same numbers for a long time, or no "finished" notice reached the
bell; or `copilot_plans_resume_failed` fired.

How a plan runs (D-893, `apps/api/copilot/plans.py`): approving it writes a
`run_copilot_plan` message to the outbox in the same transaction. The worker
(`apps/workers/copilot_plans.py`) moves the plan to `running`, settles each frozen target
in its own transaction (a compare-and-set on `pending`, so a target is never run twice),
updates the counts after every batch of 25, and closes the plan with a result sentence. A
dialling plan does not dial: it makes a `pip` campaign and launches it, and the campaign
does the calling (`runbooks/campaign-stall.md` if those calls stop).

Every five minutes `resume_copilot_plans` re-queues a plan that is `approved` or `running`
with no progress for ten minutes. A stuck plan is therefore usually one of: the outbox is
not dispatching, the worker is down, or one target's work hangs.

Ground rules: read-only SELECTs only, ids and counts only (hard rule 6). Never print a
lead's name or number into a ticket.

## 1. What the plan says

```
sudo -u postgres psql -d calevate -c "SELECT id, tool, status, target_count, done_count, skipped_count, failed_count, approved_at, started_at, updated_at, campaign_id FROM copilot_plans WHERE id = '<plan uuid>';"
```

* `approved` and `started_at` empty: the run never started — go to 2.
* `running` and `updated_at` older than ten minutes: the worker stopped holding it — go to 3.
* `running` and `updated_at` recent: it is working; a large plan takes a while (each target
  is one transaction). Nothing to do.
* `done` with `campaign_id` set: the plan's part is finished; the calls are the campaign's.

## 2. The run was never picked up

```
sudo -u postgres psql -d calevate -c "SELECT status, attempt_count, created_at, published_at FROM outbox_messages WHERE job = 'run_copilot_plan' AND payload ->> 'plan_id' = '<plan uuid>' ORDER BY created_at;"
```

* No row: the approval rolled back; the plan cannot be `approved` without one. Re-read 1.
* `pending` for minutes: the outbox dispatcher is not running — see
  `runbooks/webhook-delivery-failures.md`, which describes `dispatch_outbox`.
* `published`: the worker got it. Check the worker's log for `copilot_plan_target_failed`
  or an exception naming the plan id.

## 3. The worker stopped part-way

Nothing to repair by hand. The resume sweep re-queues it within five minutes and the new
run continues from the first `pending` target; settled targets are not touched. If
`copilot_plans_resume_failed` is firing, the sweep itself cannot read the database — fix
the database or the worker pool first (the sweep calls no model).

Which targets are still waiting:

```
sudo -u postgres psql -d calevate -c "SELECT status, count(*) FROM copilot_plan_targets WHERE plan_id = '<plan uuid>' GROUP BY status;"
```

## 4. Stopping it

The client stops a plan from its card (Cancel), which is
`POST /v1/copilot/plans/{id}/cancel`: every target not yet reached is marked skipped ("Cancelled before it was
reached.") and the worker stops before its next batch. An operator does not cancel a
client's plan for them; if a plan must stop and the client cannot be reached, pause the
account's outbound through the usual controls (`runbooks/calls-stopped.md`) — a non-dialling
plan only changes the client's own records, each of which they can change back.
