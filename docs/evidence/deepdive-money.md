# Deep dive: money, metering and billing, end to end (D-186)

A second hunt over the money surface, deliberately aimed AWAY from the core a prior pass
already cleared (`docs/evidence/audit-correctness.md`, `audit-reliability.md`): no float
near currency, one rounding quantum with an explicit mode, `allocate_paise`'s
largest-remainder split, the credit lock before every dedupe read, `clock_timestamp()` on
the ledger insert, `correct_tts_tier`'s paired ledgers, `_meter`'s lock-plus-unique-index,
`_billed_for_this_call`'s order-independent increment, the eleven advisory-lock sites.
None of those is re-reported here.

Every item is marked **PROVEN** (reproduced by running code against this tree and this
database) or **REASONED** (derived from reading, not reproduced).

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
records why. `tests/one_billing_month_spelling_test.py` is an AST scan over `apps/`,
`packages/shared/src/` and `scripts/` asserting that exactly ONE module
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

### F-3 — The admin margin panel priced the entire self-serve motion as a pure loss — **PROVEN**

`billing.margin_for_tenant` computed `revenue = monthly_fee_inr + overage_cost_inr`.
That is the whole bill for a MANAGED tenant — it is literally the invoice's subtotal —
and it is ZERO for a prepaid one: D-34's other motion has no `plans` row at all, no
monthly fee, no included allowance and no `overage_rate`. Every minute is charged at
`self_serve_inr_per_min` and taken out of the wallet by `charge_for_call`.

Measured, one self-serve minute at the ₹1.90 supplier cost
(`tests/margin_prepaid_revenue_test.py`):

```
credit_ledger  -6.0000   (the wallet was debited the list price)
margin panel   revenue_inr = 0.00, margin_inr = -<cost>, margin_pct = None
```

`margin_pct` is `None` because that branch reads `revenue > 0`, so the number gate G2
turns on reported "nothing billed yet" for a client who had been billed.

This is P1.1's shape one layer up: the panel was still deriving what a client owes from
two plan columns a prepaid client does not have, four lines from a branch that already
knew better — `_spend_used`'s closed-month prepaid figure has priced these minutes at the
list rate since P1.3.

**Fix.** New `calling_revenue_inr(plan_tier, minutes, overage_cost_inr)` is the one home
of "this period's calling, priced to the client"; `_spend_used`'s prepaid branch (which
was right) moved into it, `usage_summary` calls it, and the margin panel reads it. It
deliberately does NOT route through `prepaid_billed_inr`, which quantizes at the
NUMERIC(12,4) storage scale for a ledger row: a period total is quantized once by its
reader at the paise scale, and pre-rounding would round the same amount twice.

Two smaller "one way per problem" defects fell out of the same reading and are fixed with
it: `usage_summary` was spelling the prepaid tier set BOTH ways four lines apart (the
literal `("self_serve", "trial")` for the runway framing, the `PREPAID_TIERS` constant for
`spend_used_inr` — the constant's own docstring warns that exactly this is "a wallet that
stops draining"), and it read `organizations.plan_tier` with a hand-rolled `SELECT` while
`ai_quota.py` describes `plan_tier_of` as "the one reader … the same one `usage_summary`
and `charge_for_call` use". Both now go through the constant and the function.

### F-4 — The live spend counter priced a month by a different rule than the invoice — **PROVEN**

Two functions priced the same month and they used different rules:

* `usage_summary` (whose numbers `build_invoice` prints as its lines) spends the included
  allowance on the **dearer** rung first — `split_overage` argues why: the allocation
  decides the bill, and consuming the expensive minutes first leaves the cheap ones to be
  charged for, which is the client's favour;
* `_billed_for_this_call` (the counter the CAP is enforced against, and the one
  `usage_summary` republishes as `spend_used_inr` while the month is open) spent the
  allowance in **arrival order** and priced each call's marginal minutes at that call's
  own rung.

They agree whenever a plan quotes ONE rate — `sum of (over(before+m) - over(before)) x rate`
is `max(0, total - included) x rate` — which is every plan in the database today, because
`plans.overage_rate_value` is an open founder decision and is NULL everywhere. They
diverge the moment a second is quoted. Measured
(`tests/two_rung_counter_agrees_test.py`), on a plan with `included_min=100`,
`overage_rate=8`, `overage_rate_value=2`, 60 value minutes then 150 premium:

```
invoice / panel  overage_cost_inr = 520.00   (50 premium @8 + 60 value @2)
spend_state      billed_inr       = 880.00   (110 premium-rate minutes, allowance by arrival)
```

`tests/money_walk_test.py` already states the invariant this breaks in as many words —
"the figure a client reads as 'used so far' and the number they are invoiced must now
AGREE" — and proves it only on a one-rate fixture, where the two arithmetics cannot
differ. What the divergence costs lands on two surfaces at once: `/c/<slug>/usage` prints
"Extra usage total" (month-level) in one card and "Used so far … ₹X" (the counter) in the
card below it — two rupee figures for one month on one screen; and the client's own spend
cap is compared against the LARGER, so their stop button stops their outbound calling
before their bill justifies it.

**Fix.** `billing.service.priced_overage` is the one month-pricing rule (`usage_summary`
and `build_invoice` already shared its parts — `split_overage` and `overage_rungs` — but
nothing owned the composition). `overage_increment_inr` charges a call the DIFFERENCE it
makes to that, computed from the per-rung SECONDS the ledger holds.

Two properties made the difference-of-two-totals shape the right one rather than a
formula, and both are recorded in the code:

* **the increments telescope.** Each call's `before` is the previous call's `after` — both
  are `priced_overage` over the same raw-seconds state — so the running total is exactly
  the month's own overage cost, however many calls meter and in whatever order.
* **a rung's delta can legitimately be NEGATIVE and still be right overall.** Adding
  premium minutes moves the allowance onto the premium rung, which INCREASES the value
  rung's overage. Only the month total is a meaningful quantity; pricing the rungs' deltas
  separately would have had to drop or clamp the negative one.

It reads SECONDS rather than the quantized minutes because `allocate_paise` distributes a
remainder across the whole set and is not linear in any one bucket, so subtracting from
minutes would not reproduce the state the previous call priced against.

`client_billed_inr` loses its managed branch and becomes `prepaid_billed_inr`; the two
arguments it carried for that branch ("an unpriced managed tenant accrues nothing, and a
list price is deliberately not substituted for one") move to `priced_overage` with the
branch, and their unit tests moved with them.

**Cost, stated:** one extra grouped aggregate over the month's `usage_events` per metered
call, under a lock `_meter` already holds.

### F-5 — The SQL billing month depended on the session's `TimeZone` setting — **PROVEN**

`billing.service._IST_MONTH` — interpolated into every query that buckets
`usage_events` by month, including `ai_quota`'s two — was
`to_char(occurred_at + interval '5 hours 30 minutes', 'YYYY-MM')`. `to_char` on a
`timestamptz` renders the instant in the SESSION's `TimeZone`, so shifting first and
formatting second is the IST month only while that setting is UTC. It is UTC on this
database and nothing in `apps/` sets it — which is exactly why it is worth fixing: a
money expression whose correctness is held by an environment variable fails silently when
the variable moves, and a `PGTZ` in a deploy unit or a managed-Postgres default is not an
exotic event.

Measured against this pg16, one instant (23:00 IST on 31 August — an AUGUST call), three
session zones:

```
TimeZone=UTC               + interval -> 2026-08    AT TIME ZONE -> 2026-08
TimeZone=Asia/Kolkata      + interval -> 2026-09    AT TIME ZONE -> 2026-08
TimeZone=America/New_York  + interval -> 2026-08    AT TIME ZONE -> 2026-08
```

**Fix.** `to_char(occurred_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM')`. The conversion
produces a `timestamp` whose fields ARE the IST wall clock, so `to_char` has nothing left
to interpret and the session cannot change the answer. The named zone rather than a
literal `+05:30` for the same reason the Python side documents its fixed offset: India has
no DST today, and if that ever changed the zone would follow it and a hardcoded offset
would not. `tests/billing_month_ordering_test.py::
test_the_sql_billing_month_is_the_same_under_any_session_timezone` drives the expression
itself under three `SET LOCAL TimeZone` values (LOCAL, so the change dies with the
transaction and no sibling suite sharing this database sees it).

---

## FOUND, NOT FIXED

### N-1 — The client usage card's "Total so far" is neither the usage subtotal nor the invoice total — **REASONED**

`apps/web/src/app/c/[slug]/usage/page.tsx` computes
`addRupees(monthly_fee_inr, overage_cost_inr)` and labels it "Total so far" under a card
titled "This month". Two things the invoice for that month contains are missing:

* **one-time charges.** `billing/charges.py::issue_setup_fee` writes the onboarding fee
  into the tenant's own IST onboarding month, and `build_invoice` prints it as a line, so
  in exactly one month of a client's life the two documents differ by the setup fee;
* **GST.** `total_inr = subtotal + 18%`, so the invoice total is 1.18x this figure in
  every month.

It is not fixed because what the row should show is a product decision about that card,
not a refactor: including the setup fee but not GST would still not reconcile with the
invoice, and including GST would make a usage panel a tax document. Publishing the
one-time charges would also need a new field on `GET /v1/usage`, a regenerated OpenAPI
snapshot and a frontend change — worth doing once somebody has decided which of the two
numbers the card is for. **What closes it:** a founder decision on whether that card's
total is the pre-tax usage subtotal or the month's bill. The invoice itself is one click
away on the adjacent screen (`/c/<slug>/invoice`), which is why this is a mismatch and
not a missing number.

### N-2 — A PREPAID tenant's invoice shows no line for the minutes their wallet paid for — **REASONED**

`build_invoice` derives every line from `plans` (monthly fee, overage rungs) plus
`one_time_charges`. A `self_serve`/`trial` tenant has no `plans` row, so their invoice —
reachable from both realms, `GET /v1/billing/invoice` and the admin route — renders with
no usage line and a ₹0.00 subtotal, while their wallet has been debited
`self_serve_inr_per_min` per minute all month and `usage_summary` reports that spend on
their usage panel.

Not fixed because it is not a bug with one correct answer: what a prepaid statement IS —
a receipt for top-ups received, a statement of consumption, or both — and **where GST
attaches on a prepaid credit** (at the top-up or at consumption) are commercial and tax
questions, not engineering ones. Inventing lines for it would put a shape on a client's
tax document that nobody has agreed to. **What closes it:** the same GST registration
Rule 46(b) is already waiting on (ROADMAP M0, `supplier.is_registered` false in every
deployment), plus a founder decision on the prepaid statement's shape.

---

## CLEARED (looked at, found sound)

* **The invoice's arithmetic, re-derived by hand end to end.** Managed plan, 150 premium
  and 60 value minutes against a 100-minute allowance at ₹8/₹4: `_tier_totals` allocates
  (150.00, 60.00, 0.00) summing exactly to 210.00; `split_overage` covers the dearer rung
  and returns (50.00, 60.00) summing exactly to the 110.00 overage; `overage_rungs` prices
  400.00 + 240.00; the invoice's subtotal is the sum of the printed lines and each line
  multiplies out. GST 18% on 5640.00 is 1015.20 and the total is 6655.20. No step
  disagreed.
* **`allocate_paise`'s preconditions are unreachable from `_tier_totals`.** `sum(floors)
  <= floor(sum(exact)) <= to_paise(sum(exact))` bounds `owed` below at 0, and
  `sum(exact) - sum(floors) < 0.01 x len(parts)` bounds it above at `len(parts)`, so the
  `ValueError` cannot fire on that path. The subtraction is exact (both operands are
  multiples of 0.01), so `int()` cannot truncate a near-integer.
* **`gst.split_tax`'s remainder.** The second head absorbs `total - first`, so CGST+SGST
  sums to the published `gst_inr` exactly at every subtotal, including odd-paise ones.
* **Which month a call belongs to when it spans a boundary.** `occurred_at` is
  `ended_at` on every usage row and the counter's month derives from the same instant, so
  a call that starts in one month and ends in the next lands wholly in the end month, on
  every surface.
* **Retro-active plan changes.** `month_pricing_instant`'s three cases (closed month
  prices at its last instant, current at now, future at its first) plus
  `CommercialTermsIn._window_is_a_window`'s refusal of any `effective_from`/`effective_to`
  in a closed month mean a re-rendered statement cannot be re-priced.
* **`CommercialTermsIn` bounds.** Every money field is `Decimal | None` with `ge=0`, a
  ceiling, `max_digits`/`decimal_places` matching its column, and a `mode="before"`
  validator refusing a JSON float. No negative rate, no invented default.
* **Two concurrent invoice generations.** `build_invoice` writes nothing (D-64) and
  `issue_setup_fee` is `INSERT … ON CONFLICT DO NOTHING` on `(tenant_id, kind, ref)`, so
  regeneration and a race both read back the one row.
* **The setup fee's month.** Derived from `organizations.created_at` through
  `ist_billing_month` and frozen in the row, not re-derived per render.
* **The AI-assist meter (D-137).** `_INSERT_USAGE` stamps `occurred_at` with the
  DATABASE's `now()` and returns `_IST_MONTH` of the row it wrote, so the platform brake
  counter and the `usage_events` rows cannot land in different months across NTP skew —
  the same two-clock hazard F-1 is about, already closed there.
* **The Sarvam fallback on a dashboard assist writes no `usage_events` row and that is
  correct**, not a silent margin loss: `AssistResult.usage` is `None` because the fallback
  is Sarvam, which D-36 prices at zero per token, and `crm/schemas.py` publishes the fact
  as a disclosed field rather than hiding it.
* **`number_rental` has no writer**, and that is not the D-181 shape: numbers are recorded
  by an operator (`agents.service.provision_number` INSERTs a row an admin typed), not
  purchased through an API, so the rental is arranged and paid out of band. There is no
  per-call vendor consumption going unmetered.
* **FX.** `bolna._to_inr` stringifies before `Decimal`, refuses a currency it has no rate
  for rather than converting at the USD rate, and stamps `fx_rate` and `currency_stated`
  on every row so the assumption is falsifiable from the ledger.
* **`_unit_price` at `qty == 0`.** The gap is real, bounded, measured and already
  documented in both directions (`pipeline._unit_price` and `_spend_used` now agree about
  it); nothing new found.
