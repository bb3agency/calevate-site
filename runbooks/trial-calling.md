# Runbook — free-trial test calls (D-697)

**For:** an operator setting up free-trial calling, or one who got `trial_line_lend_failed` or
`trial_number_recorded_to_client`, or a trial client who says "test calls are not available",
"another test call is in progress" or "my trial has ended". Applies to `ENGINE=thinnest` only;
on any other engine the Trial panel says test calls are not available.

Vendor paths are under `thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/`.
Design: `docs/THINNEST-INTEGRATION.md` §3c.

## What a trial account can do

An account on a trial it has not paid for builds agents and places outbound test calls to an
Indian number it types, from ONE shared Calevate number. It cannot answer calls, run
campaigns, buy or record a number, verify its business or call its leads. Its first top-up of
at least the minimum (₹100 today, `billing/payment_routes.MIN_TOPUP_INR`) ends the trial at
once, makes the account paid, and queues its own voice workspace; then KYC, a number, and live
calls, as for any paid client (`engine-workspace-provisioning.md`).

Each test call still meets: the no-cold-calls pledge (accepted once, on Verify your business),
the daily cap (`trial_daily_call_cap`, default 10), the per-call limit
(`trial_call_max_seconds`, default 180 s), the trial's days and free minutes, the do-not-call
list, calling hours 9:00-21:00 IST, consent, the agent's AI disclosure and truthful answers,
and the big red switch.

## Set up the shared trial number (gate T-22)

The founder bought the number in ThinnestAI, in OUR developer workspace (9 Oct 2026). Never
write the number itself into a ticket, a commit or a log; the console shows it to you.

1. **Record it as platform-held.** Do nothing on any client's page: a number held in our
   developer workspace and recorded against no client IS platform-held. Do not use a client's
   **Record this number**; recording it against a client is refused
   (`engine_number_is_trial_number`) once it is the trial number, and before that it would
   make it that client's.
2. **Select it.** Ops console → Calling limits → **Shared trial number** panel. It lists, live
   from the voice platform (`GET /phone-numbers` in the developer workspace), only the numbers
   held there and recorded against no client. Type a reason and press **Use for trial
   calls**. The write is re-checked against the same list
   (`ops/trial_number.assert_trial_number_selectable`), so a typed number the platform does
   not hold is refused (`trial_number_not_platform_held`). The cap
   (`trial_daily_call_cap`) and the per-call limit (`trial_call_max_seconds`) sit beside it.
3. **What answers it: nothing.** Each test call sends `PATCH /phone-numbers/{number}` with
   `agent: null` and `callingAgent: <the trial agent>`
   (`phone-numbers/update-phone-number.md:451-470`), so no agent of any client, trial or
   paid, answers it, and a trial agent is only ever lent it to call out. Until the first test
   call, whatever answered it before still does (the panel says "an agent answers it now");
   clear it in the ThinnestAI console if that matters. What a caller hears on a number nothing
   answers is not documented; ring it once and record what you hear here (gate T-22).
4. **Smoke test.** Admin → the test client's Credits page → start a trial (days and free
   minutes). As that client's owner: accept the no-cold-calls promise on Verify your
   business, publish an agent that places calls, then the dashboard's **Your free trial**
   panel → pick the agent, type your own mobile → **Make a test call**. An operator can run
   the same path without the client's login:

   ```
   POST /v1/admin/tenants/{tenant_id}/trial/test-call
   Idempotency-Key: <fresh uuid>
   {"agent_id": "<agent uuid>", "number": "<your own mobile>"}
   ```

   (`admin:tenants`). Pass = your phone rings from the shared number, the call ends at the
   per-call limit (gate T-24), and a call row marked as a trial call shows under the
   client's Calls with its transcript.

## A client says…

- **"Test calls are not available yet."** The shared number is not set, or the engine is not
  ThinnestAI. Do step 3.
- **"Another test call is in progress. Try again in a minute."** One test call runs at a time
  across ALL trial accounts, because they share one number. The line frees when that call
  ends, or at the latest the per-call limit plus three minutes after it was placed. Nothing to
  do unless it persists past that; then look for a trial call row stuck `queued` (its end was
  never delivered) — it ages out by itself.
- **"Test calls are not available right now."** The platform did not lend the number; see
  `trial_line_lend_failed` below.
- **"You have placed today's 10 test calls."** The daily cap. Raise `trial_daily_call_cap` only
  if the founder agrees.
- **"Your free trial has ended."** The days or the free minutes ran out, or it was stopped.
  Extend by starting a new trial, or the client adds credit.

## `trial_line_lend_failed`

ThinnestAI refused `PATCH /phone-numbers/{number}` with `agent: null` and `callingAgent`. Check
the number is in the developer workspace and our key can lend it (a brought number needs its
carrier keys saved, `update-phone-number.md:7`), and that the agent is published with voice on
(`:403-405`). The call was closed `failed`; the client may retry.

## `trial_number_recorded_to_client`

The shared number is recorded against a client. The number sweep skips it (it would re-point
the number under a live test call). Release that client's record, or set another shared number.

## What not to do

- Do not record the shared number against a client, or answer it with an agent: an inbound
  caller would reach whatever was last set.
- Do not create a ThinnestAI workspace for a trial account by hand to "unlock" it; the first
  payment does that. The admin **Create workspace now** button stays as an override for an
  account that paid by a route this system does not see.
