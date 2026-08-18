# Deep dive: money, metering and billing, end to end (D-186)

A second hunt over the money surface, deliberately aimed AWAY from the core a prior pass
already cleared (`docs/evidence/audit-correctness.md`, `audit-reliability.md`): no float
near currency, one rounding quantum with an explicit mode, `allocate_paise`'s
largest-remainder split, the credit lock before every dedupe read, `clock_timestamp()` on
the ledger insert, `correct_tts_tier`'s paired ledgers, `_meter`'s lock-plus-unique-index,
`_billed_for_this_call`'s order-independent increment, the eleven advisory-lock sites.
None of those is re-reported here.

Every item below is marked **PROVEN** (reproduced by running code against this tree and
this database) or **REASONED** (derived from reading, not reproduced).

---

## FIXED

### F-1 — The meter had a SECOND spelling of "which IST billing month is this", and it was wrong for any instant not expressed in UTC — **PROVEN**

`apps/workers/pipeline.py::_ist_month` was
`(moment + timedelta(hours=5, minutes=30)).strftime("%Y-%m")`. That is correct only when
`moment` is expressed in UTC, because `strftime` renders the value's own naive fields
rather than converting. Nothing guarantees UTC: both engine adapters parse `ended_at` with
`datetime.fromisoformat` and PRESERVE whatever offset the vendor sent
(`apps/api/engine/bolna.py::_parse_dt`, `apps/api/engine/cartesia.py::_parse_dt` — the
`replace(tzinfo=UTC)` in each covers NAIVE values only). Bolna is an Indian voice
platform, so `+05:30` on a timestamp is the likely case rather than the exotic one.

`apps/api/billing/plans.py::ist_billing_month` already existed, is exported, converts
correctly for any aware instant, and REFUSES a naive one instead of guessing. It was the
stated home of this shift ("callers that hold an instant in Python … come here rather than
adding their own offset") and the meter added its own anyway — the "one way per problem"
defect, on the axis that decides which month a spend cap counts a call into.

Measured, both halves:

```
vendor instant           2026-08-31 23:00:00+05:30  = 2026-08-31 17:30:00+00:00 UTC
pipeline._ist_month      2026-09        <- the counter's month
plans.ist_billing_month  2026-08
_IST_MONTH (SQL, pg16)   2026-08        <- the month every invoice and panel reads
naive instant            _ist_month -> "2026-09"; ist_billing_month -> ValueError
```

So a call at 23:00 IST on the last of the month was counted into the NEXT month's
`spend_state` while its own `usage_events` rows sat in the right one. The two never
reconcile: the closed month's ceiling was under-counted by those calls and the new month
opened with them already spent.

**Fix.** `_ist_month` deleted; `_meter` calls `ist_billing_month`. The removal comment
records why. `tests/one_billing_month_spelling_test.py` is an AST scan over
`apps/`, `packages/shared/src/` and `scripts/` asserting that exactly ONE module
(`apps/api/billing/plans.py`) turns an instant into a `%Y-%m` string — an equality
assertion, so a second spelling fails and so does deleting the first.

### F-2 — A call from a CLOSED month could WIPE the open month's spend counters and roll the cap back with them — **PROVEN**

`_SPEND_STATE_UPSERT`'s accumulator was

```sql
CASE WHEN spend_state.month = EXCLUDED.month
     THEN spend_state.<col> + EXCLUDED.<col>
     ELSE EXCLUDED.<col> END
```

with `month = EXCLUDED.month`. That is right when the incoming month is LATER and
destructive when it is EARLIER. A call that settles late — the reconciliation poller's
30-minute listing window straddling midnight IST on the 1st, an ARQ retry ladder crossing
it, a vendor that takes minutes to price a call (`engine.py` says so in as many words) —
arrives carrying the PREVIOUS month's stamp, fails the equality, takes the `ELSE` branch,
and REPLACES this month's `minutes_used`, `spend_used`, `billed_inr` and `capped` with its
own, stamping the row back to the closed month.

Reproduced against the real meter and the real row (`tests/billing_month_ordering_test.py
::test_a_late_call_from_a_closed_month_does_not_wipe_this_months_counters`):

```
call A  ended 2026-09-01 12:00Z, 10 min  -> spend_state(month=2026-09, minutes=10)
call B  ended 2026-08-31 12:00Z, 10 min  -> spend_state(month=2026-08, minutes=10)
                                              ^ September's ten minutes are gone
```

Blast radius past the counter: `compliance.spend_capped` treats a stale month as no cap at
all, so the tenant's outbound calling reopens for the rest of the month; and
`usage_summary`'s open-month `spend_used_inr` reads that same counter, so the client's own
panel reads ₹0.00 spent beside minutes correctly read from `usage_events`.

**Fix.** The three accumulator strings collapse into one `_accumulate(column)` (they
differed only by a column name — the shape a fourth column silently gets wrong) with a
three-way rule: same month accumulates, later month replaces, EARLIER month leaves the
counters alone. `month = GREATEST(spend_state.month, EXCLUDED.month)` so the stamp cannot
go backwards. The call's money is not lost — `usage_events` is the ledger and every
invoice and panel reads it; what a closed month's call may not do is move a ceiling for a
month it does not belong to, and `spend_state` holds exactly one month by construction
(PK `tenant_id`, no history), so there is no other honest answer available to it.

The 80%/breach alarm (D-183) had to follow: it derives "before" as `after - this call's
delta`, and a call that moved nothing has a delta of zero. `EXCLUDED` is **not**
referencable from a `RETURNING` clause — measured against this pg16, not recalled:

```
psycopg.errors.UndefinedTable: invalid reference to FROM-clause entry for table "excluded"
```

— so the statement now returns the row's `month` instead, and because `GREATEST` never
moves it backwards, `returned_month == :month` is exactly "this call's totals went in".
One rule, in the statement, read back from the statement; the caller does not re-derive
it. A skipped call gets an INFO line naming both months (ids and months only, hard rule 6)
because an operator looking at a cap that did not move needs to see that a call was
deliberately not counted into it — not an `alert()`, because around a month boundary this
is the expected outcome and an alarm that fires every rollover is a muted one.

Regression cover: `tests/billing_month_ordering_test.py` (three tests — the month
agreement, the wipe, and that the forward rollover still resets, which is the one thing
the fix must not cost). Both fixes verified to FAIL on the pre-fix tree by reverting
`apps/workers/pipeline.py` and re-running.

---

## FOUND, NOT FIXED HERE

(see the closing section of this file)

---

## CLEARED

(see the closing section of this file)
