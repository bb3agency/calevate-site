# Backend open items from the 12 Oct 2026 audit

The backend audit lane of 12 Oct 2026 (commit `90c047fd`) fixed 15 defects and left these
five unfixed. Each needs a founder decision, a vendor answer or a migration. **Founder,
12 Oct 2026: document them and wait.** Nothing below has been changed in code.

| # | Item | Waiting on |
|---|------|------------|
| 1 | Late deliveries refused after an agent's route is switched off | Founder decision (design) |
| 2 | A late-billed minute uses the agent's current rate key | Founder decision + a migration |
| 3 | A forwarding test can claim a real caller | Founder decision (design) |
| 4 | A full refund drains the oldest credit lot | Founder decision |
| 5 | Razorpay `closed` releases a dispute hold | Razorpay answer |

## 1. Late deliveries refused after an agent's route is switched off

**Where.** An agent's `engine_agent_routes` row goes `active = false` when an experiment
concludes (`apps/api/agents/experiments.py`, the `UPDATE engine_agent_routes SET active =
false` in the conclude path) and when a moved agent is retired
(`apps/workers/engine_workspaces.retire_moved_engine_agent`). Signed deliveries and in-call
actions are authenticated against active routes only (`apps/voice-runtime/signed_intake.py`,
`apps/api/worker/engine_actions.py`, both `... AND active`).

**Effect.** A `call.analysed` or an in-call action that arrives after the route is switched
off, for a call that started before it, is refused as unauthenticated. That call's results
are not filed and its minutes are not metered.

**Options.** (a) A grace window: an inactive route still authenticates deliveries for calls
that started before it went inactive, for a bounded time. (b) Keep refusing, and recover
the call from the vendor's call list by the poller. Either one changes the D-189
withdrawn-route rule, so it is a decision, not a fix.

## 2. A late-billed minute uses the agent's current rate key

**Where.** `apps/api/billing/engine_minutes.py`, the minute cost for a ThinnestAI call. It
reads `engine_agent_routes.engine_rate_key` through a join on the agent
(`ORDER BY r.active DESC, r.updated_at DESC LIMIT 1`), not a key recorded on the call.

**Effect.** If the agent moves between Clear and Studio (or another rate key) between the
dial and the billing of that call, the call is costed at the new key. The trial Studio
minute cap reads the same way, so a trial's Studio minutes can be over- or under-counted
across a voice change.

**Fix when decided.** Stamp the rate key on `calls` at dial time (new column, reversible
migration with a backfill from the current route) and read it from there. Needs a
`pg_dump` before deploy.

## 3. A forwarding test can claim a real caller

**Where.** `apps/api/forwarding/testing.claim_inbound_call`. During an open forwarding test
(`_OPEN_TEST_SQL`, by time), an inbound call whose caller is the business's own number or
hidden is marked as the test's arrival (`calls.forwarding_test_id`), its minutes become
ours, and it files no lead.

**Effect.** A real customer who rings a forwarded line during the test window with their
number hidden is taken for the test. Their lead is not filed.

**Options.** Match the test's own leg more tightly: the placed leg's call id or exact start
time, instead of "any matching arrival while a test is open".

## 4. A full refund drains the oldest credit lot

**Where.** `apps/api/billing/service.py`, the credit removal for a refund (`lot_of_entry`,
then `if lot is not None and amount_inr < lot.credits_total`). A partial refund restates
the refunded purchase's own lot. A refund of the WHOLE purchase does not satisfy `<` and
falls through to `credit_lots.consume`, which takes credit from the oldest lots first.

**Effect.** After a full refund, the refunded lot can keep its credit while an older lot,
at different frozen rates, is emptied. The rupee total is right; the rates the remaining
credit is used at can be wrong.

**Fix when decided.** Treat `amount_inr == lot.credits_total` like a partial refund (restate
the purchase's own lot to zero). Founder to confirm that this is the intended rule.

## 5. Razorpay `closed` releases a dispute hold

**Where.** `apps/api/billing/disputes.py` releases the hold on both `won` and `closed`. The
module states the reason: Razorpay closes a fraud dispute after we explain the payment or
refund it, and a refund records its own debit through `refund.processed`.

**Effect.** If `closed` can also mean the money went to the customer without a
`refund.processed` event, we would release credit we no longer hold.

**UNKNOWN.** What `closed` means in every case is not verified from Razorpay's docs. To ask
Razorpay: can a dispute end `closed` with the amount deducted from our balance and no
refund event?

## Also left as they are (decided 12 Oct 2026)

- The admin call-handling defaults for a client have no step-up code. The client can set
  the same values itself and no money moves (ROADMAP D-761).
- Smaller worker gaps the lane noted:
  - the remetering sweep restarts from the oldest demand on every tick;
  - the Studio and engine-workspace sweeps catch only `ProblemError`;
  - the translation backfill stalls after 40 failed retries for one tenant, and can meter
    a model call twice after a database error;
  - charge reconciliation may never match outbound calls if the usage-log id differs from
    our `out_…` id. Checking this needs one real usage row.
  - Display totals: `credit_totals` is not reduced by refunds, and the wallet runway counts
    dispute holds as spend.
