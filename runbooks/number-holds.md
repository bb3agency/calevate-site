# Runbook — held phone numbers (D-860)

Symptoms this runbook answers: a client asks why its number stopped answering, or when it will
be given up; a closed client's workspace stays `offboarding`; the alarms
`number_hold_unsettled` and `number_hold_notice_undelivered` (`runbooks/alarm-index.md`).

## What a hold is

A client is **stopped** when its account is closed, or its prepaid wallet has been below zero
for `number_hold_after_negative_days` (Ops console → Billing → Payments; default 7, proposed and
not confirmed by the founder). A wallet below zero during an active trial stops nothing.

Every number we rent in a stopped client's own ThinnestAI workspace is then **held**
(`phone_number_holds`, one open row per number):

- nobody answers it and nobody calls out on it: it is detached at ThinnestAI, which leaves it
  rented and charged to us (`thinnest-findings/mirror/snapshots/2026-10-19/pages/channels/
  phone-numbers.md:787-791`);
- the daily renewal job charges the client nothing for it;
- it is released with `?confirm=release` at `release_at`, for good: the number goes back to
  the pool, anybody may rent it next, and the month is not refunded
  (`…/api-reference/phone-numbers/release-phone-number.md:7,461-464`).

A number lent to a client from our developer workspace is never held; it stays an operator's
to release.

**When `release_at` falls.** 24 hours before the earliest instant the number's next monthly
rent could be charged, and never more than 30 days after the hold began. ThinnestAI charges
rent "every month on the same day until you release the number" (`…/rent-phone-number.md:
449-451`) without saying in which zone or at what hour. So the day is read from the number's
`since` (when it was rented, `…/get-phone-number.md:702-707`) and from our own `created_at`,
each as a UTC date and as an IST date; the earliest renewal any of them gives is the one we
release before, the day clamped to a short month's last. `anchor_source` on the row says
whether `since` was read (`vendor`) or only our record was available (`recorded`). The day is
not known more exactly than that, and every doubt makes the release earlier, never later.

**The emails** go to the billing address and every active owner: when the hold starts, a
reminder three days before the release at 09:00 IST (only when the hold is at least five days
long), and when the number is released. A number is named by the agent it was on, never by its
digits; the digits are on the client's Phone numbers page.

**Undo.** A top-up that brings the wallet back to zero or more, or the account reopened
(DELETE `/v1/admin/tenants/{id}/closure`), ends the hold within seconds: the number answers
again on the agent in `phone_numbers.agent_id` (a hold never changes it) and the next rental
period is charged as usual.

## The jobs

- `settle_number_holds` (outbox, per tenant): queued by a closure, a reopening and a wallet
  crossing back to zero or more.
- `sweep_number_holds` (hourly, minute 23 IST): the same pass over every organization,
  erased ones included. This is where a wallet that has been below zero long enough is
  noticed, and where every reminder and release happens.
- `notify_number_hold` (outbox): one email per event for all of a tenant's numbers it concerns.

Every step is a compare-and-swap or idempotent at ThinnestAI, so running either job by hand is
safe.

## A closed client's workspace stays `offboarding`

Expected while a number there is held: `offboard_engine_workspace` answers
`waiting_for_holds=N` and keeps the agents and the customer, so a reopening gets each number
back on its agent (and ThinnestAI refuses to delete a customer that still rents a number).
The release of the last held number queues the offboarding again. If the holds are all ended
and the workspace is still `offboarding`, press **Offboard** on the client's admin page.

## `number_hold_unsettled`

Some held numbers could not be settled after the retries. Read the `number_hold_settle_failed`
log lines (number id and error type):

1. **The release date is not set** (`release_at` NULL): ThinnestAI's `GET /phone-numbers/{n}`
   failed. Check the platform's status and our key; the next hourly tick sets it.
2. **Not detached** (`detached_at` NULL): `engine_number_attachment_failed` names why.
3. **The release failed**: if `release_at` is in the past and the hold is still open, the
   renewal is close. Release the number from the client's admin Numbers page (or in the
   ThinnestAI console inside that customer), then run `settle_number_holds` for the tenant so
   the hold closes and the email goes.

To see a tenant's holds (in a tenant session, or with the owner role):

```
SELECT number_id, reason, held_at, release_at, anchor_source, detached_at, ended_at, end_reason
  FROM phone_number_holds WHERE tenant_id = '<tenant uuid>' ORDER BY held_at;
```

## Emails

`number_hold_notice_undelivered`: check the email transport (`EMAIL_PROVIDER`, the sender
domain), or the account has no billing address and no active owner. Tell the client another
way: the date is `release_at` (shown in IST on its Phone numbers page). Re-queueing is not
needed for later events; each is sent once when it happens.
