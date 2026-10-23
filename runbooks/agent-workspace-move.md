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
   workspace and re-attaches its knowledge, webhook, in-call actions and numbers. The old
   developer copy is deleted after the commit (`retire_moved_engine_agent`, which waits out a
   live call) when the agent has a number; without one it is kept as the agent's test copy
   (see "Test calls after payment").
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
| `engine_agent_allowance_used` | The client workspace's agent allowance is used up (ThinnestAI 409, "Pay as you go includes 2 agents"). The allowance is counted per workspace: 2 per customer workspace on pay as you go, 100 on our developer workspace (ThinnestAI, 23 Oct 2026, `docs/vendor/thinnest-replies-2026-10-12.md` §28.1). A client's third agent meets it. | Email ThinnestAI to raise that customer workspace's allowance (name the client's `org_…` id from its admin Numbers page). The next hourly sweep moves the agent. |
| `shared_clone_not_listed`, `studio_*`, `own_model_*` | The agent's voice (a Studio-band voice or one of our clones) is not offered in the client's workspace on our plan, or our key could not be switched on there. | **Do not change the client's voice.** ThinnestAI turned the Studio band and cloning on for our pay-as-you-go account on 23 Oct 2026 (`docs/vendor/thinnest-replies-2026-10-12.md` §28.1, VENDOR-STATED), so refresh the voice listing (`POST /v1/ops/voices/refresh`) and wait for the next hourly sweep. If it is still held, note the tenant and agent in the founder thread (D-859, decision 4). |
| `agreements_not_accepted`, `agent_language_not_offered`, `engine_prompt_too_long`, other refusals about the account or the agent | The client has to act (accept the current agreements, shorten the script, choose an offered language). | Tell the client what to do; the sweep moves the agent within the hour after they do. |

The alarm is raised once per agent per cause; a retry meeting the same cause does not page
again.

## `agent_move_failed`

Every retry of the job met an error we did not expect. Find the `agent_move_not_done` log line
for the agent (it carries the code), fix the cause, and let the hourly sweep retry. Nothing is
lost meanwhile: the agent works from the developer workspace.

## `engine_agent_allowance_used`

Raised wherever ThinnestAI refuses to create an agent for the allowance, which is counted per
workspace (§28.1 above): a trial agent or a test copy being made in our developer workspace (100)
or a client's agent in its own workspace (2 on pay as you go). The client reads "We could not set
up another agent just now". For a client workspace, ask ThinnestAI to raise it; for the developer
workspace, delete agents nobody uses (archived ones, old test agents) or ask for a raise.

## `paid_account_payment_reversed` — payment reversed

A refund was recorded, or a dispute opened, against a payment of an account that has paid.
**Nothing is reversed automatically** (founder, 23 Oct 2026): its agents stay in its own
workspace and it stays paid. A dispute also pauses its outbound calling until resolved
(`runbooks/topup-payments.md` §7). Decide with the founder whether the account should stay
paid; there is no tool that un-pays an account, deliberately.

## Test calls after payment

A paid account's test calls (dashboard and "Hear it") ring from the client's **own number** once
the agent holds one, and until then through the **shared trial line** (founder option A, 23 Oct
2026). A call runs in one ThinnestAI workspace and our shared trial number cannot be lent to an
agent in a client's workspace (`snapshots/2026-10-19/pages/api-reference/phone-numbers/update-phone-number.md:514`,
`calls/place-call.md:544-549,617-629`), so the trial-line call goes through the agent's **test
copy** in our developer workspace: the copy the move kept (`agent_test_copies`), republished from
the agent's current config before every such call, and made again if it is gone. They are
billed at normal rates and capped by `trial_daily_call_cap` and `trial_call_max_seconds` (Ops
console); on the trial line they share the one-call-at-a-time lock with free-trial calls.

The hourly sweep retires a client's test copies once it has a number of its own, and any copy
unused for **Days a paid account's test copy may sit unused** (`paid_test_copy_idle_days`,
default 14). Each copy holds one of the developer workspace's 100 agent slots. To see them:

```
sudo -u postgres psql -d calevate -c "SELECT agent_id, engine_agent_ref, last_used_at, created_at FROM agent_test_copies WHERE tenant_id = '<tenant uuid>';"
```

A copy carries the agent's config, script, voice, facts document, webhook and in-call actions.
Knowledge documents published after the move do not reach it (they are converged on the agent's
own engine agent only); a client testing new knowledge should do so once it has its own number.
