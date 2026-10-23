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
   workspace must be verified in their docs before building.)
4. **A voice that cannot move** (Studio or a clone on our plan): decided after Ashutosh replies to
   the §27 email.
5. **What the client sees during the move:** not yet answered.
6. **Payment refunded or disputed:** no automatic reversal; alert an operator, who decides.
7. **The 4th paying client and the workspace cap:** decided after Ashutosh replies.
8. **Fixed without asking** (clear bugs): a restated transfer that reaches ₹100 counts as a first
   payment, and an operator-converted invoiced account is stamped as paid.
