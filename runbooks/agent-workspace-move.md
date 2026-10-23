# Runbook — a paying client's agents moving into its own workspace (D-859)

**For:** an operator who got `agent_move_held`, `agent_move_failed`,
`engine_agent_allowance_used` or `paid_account_payment_reversed`, or a client whose go-live
guide says "We're finishing this for you". Applies to `ENGINE=thinnest` only.

Design: `docs/THINNEST-INTEGRATION.md` §3c ("After the first payment"); code `apps/api/go_live/moves.py`,
`apps/workers/agent_moves.py`. Evidence: `docs/evidence/trial-to-paid-move-2026-10-23.md`.

## What happens by itself

1. The first payment (top-up, a bank transfer credited or restated to at least the minimum
   top-up, or an operator converting an invoiced account's trial) stamps the account paid,
   ends its trial and owes it its own customer workspace (`runbooks/engine-workspace-
   provisioning.md`).
2. The workspace becoming **active** queues one `move_agents_to_workspace` job.
3. The job republishes every live or ready agent (and running script-test arm) still in our
   developer workspace, one at a time, with "not taking calls": a ready agent stays ready, a
   live one stays live, nothing is switched on. The publish recreates the agent in the client's
   workspace, re-attaches its knowledge, webhook, in-call actions and numbers, and the old
   copy is deleted after the commit (`retire_moved_engine_agent`, which waits out a live call).
4. Each agent's outcome is a row in `agent_workspace_moves` (`moved`, `waiting`, `held`,
   `failed`). The owner's guide reads it.
5. Every hour `sweep_agent_moves` queues the job again for any active client workspace whose
   tenant still has an agent left behind.

Drafts have nothing at the voice platform and are created in the client's workspace when first
got ready. Archived agents are not republished.

## Reading the state

```
sudo -u postgres psql -d calevate -c "SELECT agent_id, workspace_id, status, reason_code, attempts, alarmed_code, last_attempt_at, moved_at FROM agent_workspace_moves WHERE tenant_id = '<tenant uuid>' ORDER BY created_at;"
```

`postgres` is a superuser, so the table's FORCEd row-level security does not hide the rows.
Ids and codes only; no client data.

## `agent_move_held`

The agent keeps answering and placing calls from the developer workspace. Read `reason_code`:

| Code | What it is | What to do |
| --- | --- | --- |
| `engine_agent_allowance_used` | The plan's agent allowance is used up (ThinnestAI 409, "Pay as you go includes 2 agents"). | Delete agents nobody uses in the ThinnestAI console (archived ones, old test agents), or upgrade the plan. Whether the allowance counts per workspace or per account is UNKNOWN (asked of ThinnestAI, §27). The next hourly sweep moves it. |
| `shared_clone_not_listed`, `studio_*`, `own_model_*` | The agent's voice (a Studio-band voice or one of our clones) is not offered in the client's workspace on our plan, or our key could not be switched on there. | **Do not change the client's voice.** What happens to such an agent is a founder decision waiting on ThinnestAI's reply (D-859, decision 4). Note the tenant and agent in the founder thread. |
| `agreements_not_accepted`, `agent_language_not_offered`, `engine_prompt_too_long`, other refusals about the account or the agent | The client has to act (accept the current agreements, shorten the script, choose an offered language). | Tell the client what to do; the sweep moves the agent within the hour after they do. |

The alarm is raised once per agent per cause; a retry meeting the same cause does not page
again.

## `agent_move_failed`

Every retry of the job met an error we did not expect. Find the `agent_move_not_done` log line
for the agent (it carries the code), fix the cause, and let the hourly sweep retry. Nothing is
lost meanwhile: the agent works from the developer workspace.

## `engine_agent_allowance_used`

Raised wherever ThinnestAI refuses to create an agent for the allowance: a trial agent being got
ready (the client reads "We could not set up another agent just now") or a move. Free slots in
the ThinnestAI console or upgrade the plan; the client can then press Get it ready again.

## `paid_account_payment_reversed` — payment reversed

A refund was recorded, or a dispute opened, against a payment of an account that has paid.
**Nothing is reversed automatically** (founder, 23 Oct 2026): its agents stay in its own
workspace and it stays paid. A dispute also pauses its outbound calling until resolved
(`runbooks/topup-payments.md` §7). Decide with the founder whether the account should stay
paid; there is no tool that un-pays an account, deliberately.

## Test calls after payment

A paid account's test calls (dashboard and "Hear it") ring from the client's **own number**: a
call runs in one ThinnestAI workspace, and our shared trial number cannot be lent to an agent in
a client's workspace (`snapshots/2026-10-19/pages/api-reference/phone-numbers/update-phone-number.md:514`,
`calls/place-call.md:544-549,617-629`). Until the client has a number and a live agent on it,
the panel says so. They are billed at normal rates and capped by `trial_daily_call_cap` and
`trial_call_max_seconds` (Ops console).
