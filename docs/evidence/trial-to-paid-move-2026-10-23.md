# Moving a trial client's agents into their own workspace at first payment — 23 October 2026

**Founder's ask (23 Oct 2026):** when a client pays and buys credit, its free-trial agents move to
the client's own ThinnestAI workspace, with every trial characteristic gone and the production
characteristics of a real agent in place.

## 1. What happens today (main, read from the code; file:line in the conversation's code map)

- **The first payment** (`billing/first_payment.on_payment_credited`, ≥ ₹100, once): converts the
  trial, clears its erasure date, resets the counters, writes the audit row
  `account.first_payment`, queues the client's customer workspace
  (`provision_engine_workspace`), and queues a tenant live-apply.
- **Every trial restriction keys on `restricting_trial`**, so they all lift the moment the payment
  commits: trial refusals, test-call caps, the dashboard trial panel, the trial switch and banner.
- **Workspace provisioning** is an outbox job with find-before-create, restore, 409 recovery,
  `plan_limit` / `failed` states, retries and a daily sweep. On activation it queues the business
  details, line sync, retention and the DNC push. **It does not touch agents**, and it does not
  install the Studio or own-model keys.
- **Agents move only when published.** `publish_agent` sees the developer-workspace ref, creates the
  agent in the client workspace, re-attaches knowledge, the webhook, in-call actions and numbers,
  then `retire_moved_engine_agent` deletes the old one after commit, waiting out a live call.
  Variants have the same path.

## 2. What is missing or broken for an automatic move

1. **No trigger when the workspace becomes active.** Agents stay in the developer workspace until
   someone publishes them. Meanwhile they hold our scarce developer-workspace agent slots
   (rememory 4360ad72), keep `callbacks_offered=False`, and the client workspace has no keys.
2. **The conversion's live-apply races provisioning.** If it runs first it fails permanently, and
   it only walks `live` agents, so ready (`paused`) trial agents are never moved.
3. **A paid client loses test calls.** After payment a test call is refused (`NOT_ON_TRIAL_RULE`),
   and the client has no number of its own until it passes KYC and buys one.
4. **Voices that will not exist in the client workspace.** Studio-band voices and shared clones
   are listed only on Pro and above, so on our pay-as-you-go plan the move fails with
   `shared_clone_not_listed` or a Studio-key error.
5. **Plan limits.** PAYG allows 3 customer workspaces (the 4th paying client lands in
   `plan_limit`), and the agent allowance (2 on PAYG; per workspace or per account UNKNOWN) can
   refuse the create step of a move.
6. **Payment paths that never count as a first payment:** a restatement up to ≥ ₹100 (the docstring
   claims a hook that does not exist) and invoiced or managed accounts (an operator converts the
   trial, but `first_paid_at` stays NULL).
7. **Numbers bought before the move** are bound across workspaces until the agent is republished.

## 3. Research

- **Trial-to-paid:** vendors either keep the tenant and change its plan, or move it to a new
  tenant. The move is the risky path and is designed for up front, with an irreversible switch and
  a confirmation step (Microsoft tenant-lifecycle guidance; Palo Alto and Acronis trial-to-production
  docs; read 23 Oct 2026).
- **The move pattern:** a saga where each step is idempotent under one move id, an outbox so no
  step is lost, compensation that does nothing when the forward step never ran, and an operator
  alarm when compensation keeps failing. Both workspaces may briefly hold the agent, so reads must
  tolerate that (vendor and engineering blogs; REPORTED).
- **ThinnestAI:** a phone number can be moved between workspaces
  (`POST /phone-numbers/{n}/move`, `api-reference/customers.md:185-200`). No agent move is
  documented, so an agent is recreated in the new workspace and the old one deleted. That is
  D-693's existing path.

## 4. Questions for the founder

Asked in the conversation of 23 Oct 2026; answers to be recorded here.

The founder's answers, 23 Oct 2026 (built as **D-859**):

1. **Move automatically:** yes. All of a paying client's agents move in the background as soon as
   its own workspace is active, with no action from the client. A draft has nothing at ThinnestAI
   and is created in the client's workspace when first got ready.
2. **State kept:** yes. A ready agent stays ready. Answering calls still needs the business check
   and the client's own number; calling out still needs the business check and the no-cold-calls
   promise.
3. **Test calls after paying.** Test calls are made from the client's moved agents, never from a
   trial agent; the trial agent is moved, or deleted from the developer workspace. Caller ID:
   - the client's own number once it has one;
   - until then, our shared number.

   (Whether ThinnestAI lets a developer-workspace number place a call for an agent in a customer
   workspace must be verified in their docs before building. It does not (§5); the founder then
   chose option A (§6).)
4. **A voice that cannot move** (Studio or a clone on our plan): decided after Ashutosh replies to
   the §27 email. He turned Studio and cloning on for our pay-as-you-go account (§7 below).
5. **What the client sees during the move:** an interactive guide like D-855's first run: moving
   your agents (real progress), verify your business, get your number, switch it on (founder,
   23 Oct 2026, later the same day).
6. **Payment refunded or disputed:** no automatic reversal; alert an operator, who decides.
7. **The 4th paying client and the workspace cap:** decided after Ashutosh replies. He raised the
   cap to 100 (§7 below).
8. **Fixed without asking** (clear bugs): a restated transfer that reaches ₹100 counts as a first
   payment, and an operator-converted invoiced account is stamped as paid.

## 5. Verified before building item 3 (hash-pinned mirror 2026-10-19)

The shared trial number **cannot** place a call for an agent in a customer workspace, so it
rings through a developer-workspace copy of the agent instead (§6):

- A call runs in the workspace the request names; `agent` must answer the phone **in this
  workspace** (`api-reference/calls/place-call.md:617-629`, `agent_not_found`), and a `from`
  that is not one of the agent's numbers is refused (`:544-549`).
- `PATCH /phone-numbers/{number}` (where `callingAgent` lends a number) answers 404 when "This
  workspace holds no such number, or no such agent" (`phone-numbers/update-phone-number.md:514`),
  so a developer-workspace number cannot be lent to a customer-workspace agent.
- The one way across, `POST /phone-numbers/{number}/move`, takes the number out of every agent and
  calling pool, lands it answered by nobody, and moves an Indian number only to a workspace whose
  business details are approved (`phone-numbers/move-phone-number.md:9,598-618`). It would take the
  shared number from every trial account.

## 6. Founder option A for test calls before a number (23 Oct 2026), as built

Because the shared number cannot reach an agent in the client workspace, the trial copy stays:

- **The move keeps the developer-workspace copy** of an agent that has no number
  (`agent_test_copies`, its route left active so its calls report back). An agent with a number
  has its copy retired after the commit, as before.
- **A paid test call before the agent has its own number rides the shared trial line** exactly
  as a trial call does (the platform-wide trial line lock, `lend_trial_line`, the per-call
  limit), through the agent's developer-workspace engine agent: the agent itself if it has not
  moved yet, else its copy. Once the agent holds its own number in its workspace the call rings
  from that number instead.
- **The copy is never stale:** before each such call the agent's current config is republished
  onto it through `publish_agent(onto_test_copy=True)` (the same publish path), and it is made
  again if the vendor no longer holds it. Knowledge documents converge on the agent's own
  engine agent only, so the copy keeps those it held when it moved (a known limit).
- **Retirement:** the hourly sweep retires every copy once the client owns a number in its
  workspace, and any copy unused for `paid_test_copy_idle_days` (console, default 14); the next
  test call makes another.
- Billed at normal rates and marked `calls.paid_test_call` (and `trial_call` on the trial line);
  every dial gate, the daily cap and the per-call cap apply.

## 7. ThinnestAI's answer (§28 of `docs/vendor/thinnest-replies-2026-10-12.md`, 23 Oct 2026)

VENDOR-STATED: agents are counted **per workspace**: our developer workspace 100, each customer
workspace 2 on pay as you go, raised per workspace on request. The customer-workspace cap is 100;
the Studio band and cloning are on for our pay-as-you-go account. So a client's third agent is
held (`engine_agent_allowance_used`, `agent_move_held`) until its workspace is raised, and gap 5
above no longer applies to the developer workspace once the raise is live.

Built as D-859 (`docs/ROADMAP.md` §6); runbook `runbooks/agent-workspace-move.md`.
