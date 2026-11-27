# Runbook — free-trial test calls (D-697)

**For:** an operator setting up free-trial calling, or one who got `trial_line_lend_failed` or
`trial_number_recorded_to_client`, or a trial client who says "test calls are not available",
"another test call is in progress" or "my trial has ended". Applies to `ENGINE=thinnest` only;
on any other engine the Trial panel says test calls are not available.

Vendor paths are under `thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/`.
Design: `docs/THINNEST-INTEGRATION.md` §3c.

## What a trial account can do

Every new account starts on a trial, signed up or invited (console **Free trial days /
minutes for a new account**, defaults 7 and 15, D-853); setting a trial from the client's
Credits page replaces it, counted from that moment. An account on a trial it has not paid
for builds agents and places outbound test calls to an Indian number it types, from ONE
shared Calevate number, from any agent it has got ready (Get it ready), including one that
only answers calls: that agent's own greeting opens the call. It cannot answer calls, run
campaigns, buy or record a number, verify its business or call its leads. Its first top-up of
at least the minimum (₹100 today, `billing/payment_routes.MIN_TOPUP_INR`) ends the trial at
once, makes the account paid, and queues its own voice workspace; then KYC, a number, and live
calls, as for any paid client (`engine-workspace-provisioning.md`).

Each test call still meets: the no-cold-calls pledge (accepted once, on Verify your business),
the daily cap (`trial_daily_call_cap`, default 10), the per-call limit
(`trial_call_max_seconds`, default 180 s), the trial's days and free minutes, the do-not-call
list, calling hours 9:00-21:00 IST, consent, the agent's AI disclosure and truthful answers,
and the big red switch.

## Switch phone test calls on: the checklist

What the owner sees while this is not done: step 4 of Meet your agent ("Hear it"), the
dashboard's test-call box and a campaign's or line's Test call box all say "Phone test calls
are not switched on yet: the line they ring from is not set up on our side", with **Type to it
instead** (the agent's Training tab). Rule `trial_calling_not_ready`, from
`agents/trial_calls.trial_calling_ready()`: false while `trial_caller_number` is empty.

Production read 18 Nov 2026 (decision D-1020): `platform_settings.trial_caller_number` is null.
The number used before had been given to a client (founder, 4 Nov 2026), so it can no longer be the shared
one (a recorded number is refused, `engine_number_is_platform_line`).

1. **Have a number in OUR developer workspace that no client has recorded.** Ops console →
   Platform configuration → Calling limits and pacing → Free trials → **Shared trial number**.
   The picker lists exactly those numbers, read live from the voice platform. If it is empty,
   a number must be bought in ThinnestAI's console in the **developer** workspace (not a
   client's customer workspace: a trial account has none until its first payment, D-697, and
   the shared line is ours, not a client resource, so D-693's "never the developer workspace
   for a client resource" does not apply to it). It must be one our key can lend: a brought
   number needs its carrier keys saved. Buying is a founder decision with a monthly cost;
   this runbook does not buy one.
2. **Pick it**, type a reason, **Save change**. Re-checked against the same list on save.
3. **Set up its line**: the panel **When someone rings this number back** → **Set it up now**
   (`POST /v1/ops/trial-number/line`, step-up). Pass = the panel shows the line ready.
4. **Smoke test** as in step 4 of the section below. Pass = your phone rings, the call ends at
   **Longest trial test call**, and the client's Calls shows it.
5. **Ring the number back** from your own phone. Pass = the "only places test calls" message,
   and no agent answers.
6. Optional, founder's call: **Longest trial test call** (`trial_call_max_seconds`, live, no
   deploy). The code default is 180 s (D-904: "trials keep 180 s"). A guided walk-through of a
   real business ran 4-5 minutes (founder, 28 Nov 2026), so 300 s lets one finish. A longer
   limit holds the one shared line longer for every trial account (each call holds it up to
   the limit plus 3 minutes) and spends a 15-minute trial in three calls instead of five.

Paying accounts with a number of their own do not need any of this (D-1020): their tests ring
from their own number. They meet the shared line only when their workspace has no free agent
slot for the test, or before they have a number.

### Talking to the agent in the browser

Not built. ThinnestAI's only documented browser call is the call button inside its website
chat widget: an agent with `voice.surfaces` including `web` and `answersCalls` on, embedded by
`<script src="https://thinnest.ai/widget.js" data-key="pk_…">` (`thinnest-findings/mirror/
snapshots/2026-11-26/pages/channels/website.md:9-23`, `channels/voice.md:1343-1368`,
`api-reference/agents/update-agent.md:1372-1394`; the key is the agent's `webKey`, `get-agent.md:766-771`). The key
"authorises nothing" and is public by design (`website.md:27-29`), and there is no API that
starts a web call for one person (`openapi.json` lists no such path). So a web call would
reach the agent without our dial gate, the trial's minutes and daily cap, the own-number tick
or any per-call limit, from anyone who copies the key; it would run in ThinnestAI's iframe on
their origin (`website.md:10`), and `call.completed` carries no `reference` or `metadata` for
it (`api-reference/webhooks.md:354`), so it could not be tied to the owner who started it.
What would change this is a vendor feature: a server-minted, single-use web-call session for
one agent with `maxCallSeconds` and our `reference`. It is a question for ThinnestAI, not code.

## Set up the shared trial number (gate T-22)

The founder bought the number in ThinnestAI, in OUR developer workspace (9 Oct 2026). Never
write the number itself into a ticket, a commit or a log; the console shows it to you.

1. **Record it as platform-held.** Do nothing on any client's page: a number held in our
   developer workspace and recorded against no client IS platform-held. Do not use a client's
   **Record this number**; recording it against a client is refused
   (`engine_number_is_platform_line`) once it is the trial number, and before that it would
   make it that client's.
2. **Select it.** Platform configuration → Calling limits and pacing → Free trials → the
   **Shared trial number** setting. Its picker lists, live from the voice platform
   (`GET /phone-numbers` in the developer workspace), only the numbers held there and recorded
   against no client. Pick one, type a reason and press **Save change**. The write is re-checked against the same list
   (`ops/trial_number.assert_trial_number_selectable`), so a typed number the platform does
   not hold is refused (`trial_number_not_platform_held`). The cap
   (`trial_daily_call_cap`) and the per-call limit (`trial_call_max_seconds`) sit beside it.
3. **What answers it: the trial line agent, which answers nobody (D-742).** The number's line
   is the developer-workspace agent "Calevate shared trial number (no answer)", Answer calls
   off, which plays the "only places test calls" message. Each test call sends
   `PATCH /phone-numbers/{number}` with that agent as `agent` and `callingAgent: <the trial
   agent>`, then gives the trial agent the `phone` surface (`PATCH /agents/{id}`
   `voice.surfaces: ["phone"]`), because ThinnestAI places a call only from an agent that
   "answers the phone". A lent agent "calls out on it without answering it"
   (`update-phone-number` `callingAgent`), so no client agent ever answers the number.
4. **Smoke test.** A new test account is already on its trial (or set one on its Credits
   page). As that client's owner: accept the no-cold-calls promise on Verify your
   business, make an agent and press **Get it ready**, then the dashboard's **Your free trial**
   panel → pick the agent, type your own mobile → **Make a test call**. An operator can run
   the same path without the client's login: the client's Credits page in the admin console
   → **Trial period** → pick the agent, type your own mobile → **Make a test call** →
   **Ring the phone**. The button sends:

   ```
   POST /v1/admin/tenants/{tenant_id}/trial/test-call
   Idempotency-Key: <fresh uuid>
   {"agent_id": "<agent uuid>", "number": "<your own mobile>"}
   ```

   (`admin:tenants`). Pass = your phone rings from the shared number, the call ends at the
   per-call limit (gate T-24), and a call row marked as a trial call shows under the
   client's Calls with its transcript.

## A client says…

- **"Phone test calls are not switched on yet: the line they ring from is not set up on our
  side."** (Before 28 Nov 2026: "Test calls are not available yet. Please try again later.")
  The shared number is not set, or the engine is not ThinnestAI. Run the checklist above.
- **"Another test call is in progress. Try again in a minute."** One test call runs at a time
  across ALL trial accounts, because they share one number. The line frees when that call
  ends, or at the latest the per-call limit plus three minutes after it was placed. Nothing to
  do unless it persists past that; then look for a trial call row stuck `queued` (its end was
  never delivered) — it ages out by itself.
- **"Test calls are not available right now."** The platform did not lend the number; see
  `trial_line_lend_failed` below.
- **"We couldn't place this test call ... a problem on our side."** The voice platform refused
  the dial for our own set-up (`engine_dial_setup_refused` paged); see the `calling_not_set_up`
  section below.
- **"You have placed today's 10 test calls."** The daily cap. Raise `trial_daily_call_cap` only
  if the founder agrees.
- **"Your free trial has ended."** The days or the free minutes ran out, or it was stopped.
  Extend by starting a new trial, or the client adds credit.
- **"Get this agent ready first"** (`agent_not_ready`). The agent is a draft. The owner
  presses **Get it ready** on its page; no Taking calls switch is needed for a test call.
- **"Answering calls starts after your first top-up and business check."** Shown beside an
  answer-only agent's locked Taking calls switch on a trial. Expected: it answers calls once
  the account pays and verifies; until then it can be tried in the chat or by a test call.

## `trial_line_lend_failed`

ThinnestAI refused `PATCH /phone-numbers/{number}` (the trial line agent as `agent`, the trial
agent as `callingAgent`), or did not give the trial agent the `phone` surface afterwards. Check
the number is in the developer workspace and our key can lend it (a brought number needs its
carrier keys saved, `update-phone-number.md:7`), and that the agent is published with voice on
(`:403-405`). The call was closed `failed`; the client may retry.

## Test calls refused: "no agent answers the phone" (`calling_not_set_up`)

Incident 15 Oct 2026. Every test call failed with `engine_dial_setup_refused` (`409
calling_not_set_up`, "No agent in this workspace answers the phone"), and the client saw
"We couldn't place this test call". Cause: since F1 (12 Oct) an agent with no number of its
own is published with `voice.surfaces: []`, and every trial agent is such an agent, so no agent
in the developer workspace counted as answering the phone. The fix gives the borrowing agent
`phone` at each lend, and the settings sweep no longer strips it.

After the fix is deployed:

1. **Smoke test.** Run step 4 above (the admin `trial/test-call` route is enough). Pass = your
   phone rings from the shared number. Nothing needs republishing for trial agents: the lend
   sets `phone` on every call.
2. **Ring the shared number back** from your own phone. Pass = you hear the "only places test
   calls" message and nothing answers. If it rings into a client's agent, stop trial calls
   (clear **Shared trial number**) and run `POST /v1/ops/trial-number/line`.
3. **A paying client's outbound-only agent** has the same problem and the same fix: it now
   publishes with `phone` because its number is lent to it. If one is live, republish it once
   (its agent page, **Publish**), then place one call from it.
4. If step 1 fails with `trial_line_lend_failed` naming `phone_number_required`, ThinnestAI
   does not count a lent number as one the agent can "call from". Stop and send the question
   in `docs/vendor/thinnest-replies-2026-10-12.md` §13.

## `trial_number_recorded_to_client`

The shared number is recorded against a client. The number sweep skips it (it would re-point
the number under a live test call). Release that client's record, or set another shared number.

## What not to do

- Do not record the shared number against a client, or answer it with an agent: an inbound
  caller would reach whatever was last set.
- Do not create a ThinnestAI workspace for a trial account by hand to "unlock" it; the first
  payment does that. The admin **Create workspace now** button stays as an override for an
  account that paid by a route this system does not see.
