# Deep dive: money, metering and billing, re-attacked (D-250 – D-256)

A second full pass over the money surface, ~140 commits after
`docs/evidence/deepdive-money.md`. That wave's five findings are not re-reported and were
re-checked as still fixed: `_ist_month` has one spelling, the `spend_state` accumulator
refuses to go backwards, the margin panel prices the prepaid motion, `priced_overage` is
the one month-pricing rule, and the SQL billing month converts with `AT TIME ZONE`.

Every item is marked **PROVEN** (reproduced by running code against this tree and a
Postgres 16) or **REASONED** (derived from reading, not reproduced). Sub-surfaces that
were attacked and found sound are listed under CLEARED — a negative result from a real
attempt is evidence.

**Base.** `7c5de50` (merge of PR #19). Migrations applied to a private
`calevate_money2` database; **no migration was added by this wave**, so there is no head
to linearise.

**One overlap to know at merge time.** The shared checkout at `/home/user/calevate-site`
carries an UNCOMMITTED rewrite of the billing-month predicate — `plans.ist_month_window`,
`service._IST_MONTH_WINDOW`, `_month_bounds`, and their use in `rung_seconds`,
`usage_summary`'s call count and `ai_quota._USAGE_SQL`. That work is a sibling's and is
not in this branch's base. Nothing here touches those lines: `rung_seconds` is called by
`month_increment` but its predicate is untouched, and the three files that differ
(`plans.py`, `service.py`, `ai_quota.py`) are edited only in regions the sibling does not.

---

## 1. The charge, re-derived by hand, every intermediate checked

The exercise the last wave called the highest-value one, redone on the current code with a
fixture built to make each rule do real work. `tests/hand_derived_charge_test.py` is the
executable half — it asserts the VALUES below rather than the invariants, so a change that
keeps the system self-consistent and moves what a client owes has somewhere to fail.

**The account.** Managed tenant. Plan: monthly fee ₹4,999.00, included 100 min, overage
₹8.5000/min premium and ₹3.2500/min value, setup fee ₹15,000.00. Four calls, none of whose
durations divides by 60, one of them on an agent with no configured voice:

| call | configured voice | duration | engine charged us |
|---|---|---|---|
| 1 | premium (`bulbul:v3`) | 3847 s | ₹77.19 |
| 2 | value (`bulbul:v2`)   | 2913 s | ₹58.26 |
| 3 | premium               |  611 s | ₹12.22 |
| 4 | none                  |  137 s |  ₹2.74 |

### Hop 1 — seconds onto the ledger

`_meter` writes `telephony_s` at `qty = duration_s` and stamps `meta.tts_tier` from the
agent's configured voice. Call 4 has no voice, so `billable_tier(None)` returns
`("value", "unproven")` — SURFACES §2b: a call we cannot prove got the premium voice is
never charged the premium rate. Per-rung seconds:

    premium  3847 + 611 = 4458 s
    value    2913 + 137 = 3050 s
    total                 7508 s

### Hop 2 — seconds to minutes, divided once and allocated

`rung_minutes` divides per bucket in Python (not in SQL — `SUM(a)/60 + SUM(b)/60` and
`SUM(a+b)/60` are two roundings of one number and Postgres picks the scale), then
`allocate_paise` distributes:

    exact    premium 74.300000   value 50.833333
    total    to_paise(7508 / 60) = to_paise(125.133333) = 125.13
    floors   74.30 + 50.83 = 125.13   ->  owed = 0 paise, nothing redistributed

**Published minutes 125.13.** The three buckets add to it exactly (`tier_usage` reports
premium 74.30, value 50.83, unattributed 0.00).

### Hop 3 — the allowance, spent on the DEARER rung first

₹8.50 > ₹3.25, so premium is dearer. It holds 74.30 min and the allowance is 100, so the
whole premium rung is covered and 25.70 min of allowance is left for value.

    overage        125.13 - 100 = 25.13 min
    premium over   max(0, 74.30 - 74.30) = 0.00 min
    value over     25.13 - 0.00 = 25.13 min     (= 50.83 - 25.70, the same number)

### Hop 4 — each rung priced, quantized once

    premium   0.00 x 8.5000 =  0.0000  -> ₹0.00
    value    25.13 x 3.2500 = 81.6725  -> ₹81.67   (ROUND_HALF_UP, `billing.rates.ROUNDING`)
    total                                  ₹81.67   (the SUM of the rungs, not a re-quantization)

### Hop 5 — the live counter, built from four increments that telescope

Each call is charged the difference it makes to the month's overage bill. Measured after
each `_meter`, and every figure is the hand-derived one:

| after call | month minutes | month overage | increment | `spend_state.billed_inr` |
|---|---|---|---|---|
| 1 |  64.12 | under the allowance | +₹0.00  | ₹0.00 |
| 2 | 112.67 | 12.67 × 3.25 = 41.1775 → ₹41.18 | +₹41.18 | ₹41.18 |
| 3 | 122.85 | 22.85 × 3.25 = 74.2625 → ₹74.26 | +₹33.08 | ₹74.26 |
| 4 | 125.13 | 25.13 × 3.25 = 81.6725 → ₹81.67 | +₹7.41  | ₹81.67 |

`spend_state.minutes_used` ends at **125.1300** — equal to the published 125.13, which it
was NOT before this wave (see F-4). `spend_state.spend_used` ends at ₹150.4100, the sum of
the four engine charges; that is OUR cost and is a different fact, correctly kept apart.

### Hop 6 — the invoice

    Monthly plan fee                          1 × ₹4,999.00   = ₹4,999.00
    One-time onboarding & setup               1 × ₹15,000.00  = ₹15,000.00
    Extra calling minutes, value voice   25.13 × ₹3.25        = ₹81.67
    (no premium line — a rung with no minutes prints nothing)
    ------------------------------------------------------------------
    subtotal                                                   ₹20,080.67

Every line multiplies out. The subtotal is the sum of the printed lines and nothing else.

### Hop 7 — GST

    18% of 20,080.67 = 3,614.5206  ->  ₹3,614.52
    total = 20,080.67 + 3,614.52   =   ₹23,695.19

Split across the heads for an intra-State supply (Rule 46(l)-(m)):

    CGST  20,080.67 × 0.09 = 1,807.2603 -> ₹1,807.26
    SGST  3,614.52 - 1,807.26           =  ₹1,807.26   (the second absorbs the remainder)
    heads sum to ₹3,614.52 exactly = the published `gst_inr`

Every deployment today reports `document_type: "proforma"` and one unclassified `GST`
head, because no `GST_SUPPLIER_*` value is configured.

**No step disagreed with the hand arithmetic** — after the fixes below. Three of the seven
hops were wrong before them: hop 5's minute counter (F-4), hop 5's rate when the call
belongs to a closed month (F-1), and hop 7's tax total having two homes (F-5).

---

## FIXED

### F-1 — The meter priced a late-settling call by TODAY's plan, where its own month's panel and invoice priced it by that month's — **PROVEN** (D-250)

`_meter` resolved `plan_in_effect_sql(..., at=NOW_SQL)` and then priced the call into
`month = ist_billing_month(snapshot.ended_at)`. Those are two different months whenever a
call settles after the roll, which is a routine path rather than an exotic one: `engine.py`
records that the vendor may take minutes to price a call, the reconciliation poller's
listing window straddles midnight IST on the 1st, and the ARQ retry ladder can cross it.

`billing/plans.py::month_pricing_instant` is this repository's one answer to "which plan
prices this month" — now while it is open, the month's LAST instant once it is closed —
and `usage_summary` and `billing/charges.py` both already used it. The meter did not.

Measured, one ten-minute call ending on the last day of a month whose ₹2/min terms were
superseded by ₹20/min on the 1st:

```
spend_state         ('2026-07', minutes 10.0000, billed_inr 200.0000)
usage_summary(2026-07)   overage_rate_inr 2.00   overage_cost_inr 20.00
```

**₹200.00 on the counter against ₹20.00 on the panel and the invoice**, for one call.

**Fix.** `month` is resolved above the plan read and the read binds
`month_pricing_instant(month)`. The CEILING is deliberately still resolved at `now()`
inside the upsert's `caps` CTE, and that split is the point rather than an inconsistency: a
RATE is a term of the month being priced, a CAP is a question about whether this tenant may
dial right now. `tests/late_call_prices_at_its_own_month_test.py` reproduces it and pins
the other direction too — terms dated to start later THIS month must not price a call made
today, which is the defect `billing/plans.py` exists for.

**Blast radius, stated honestly.** The wrongly-priced figure lands on a `spend_state` row
stamped with a closed month, and `read_spend_counters` reports zeros for a stale month, so
no client surface published it and no cap was enforced against it. What it was is a second
pricing rule living in the tree — the exact defect class the previous wave's F-4 removed —
one call away from being read, and the ₹200-vs-₹20 measurement is what it was worth.

### F-2 — A vendor-reported NEGATIVE call duration aborted metering entirely, and every retry hit the same wall — **PROVEN** (D-251)

`ExecutionSnapshot.duration_s` is `int | None` with no floor, and both adapters build it
as `int(duration) if isinstance(duration, int | float) else None`
(`engine/bolna.py:1072`, `engine/cartesia.py:752`). A `-1` "unknown" sentinel — a common
vendor idiom — or a duration derived from two clocks that disagree therefore reaches the
money path unfiltered and is multiplied through everything.

Taking seconds AWAY makes `month_increment`'s `after < before`, i.e. a NEGATIVE
contribution to `spend_state.billed_inr`. That is the one input to that counter which is
not monotone (adding minutes can only raise a month's overage, whichever rung they land
on), which is why `ck_spend_state_billed_inr_nonnegative` had never been reachable.

And a healthy accumulated total does not save it. Measured against this pg16 rather than
recalled — PostgreSQL evaluates a CHECK against the row an `INSERT ... ON CONFLICT DO
UPDATE` **proposes**, before the conflict is arbitrated:

```sql
CREATE TEMP TABLE t(k int primary key, v numeric NOT NULL CHECK (v >= 0));
INSERT INTO t VALUES (1, 100);
INSERT INTO t VALUES (1, -5) ON CONFLICT (k) DO UPDATE SET v = t.v + EXCLUDED.v;
ERROR:  new row for relation "t" violates check constraint "t_v_check"
DETAIL:  Failing row contains (1, -5).
```

End to end, on a tenant with ₹120.96 already accrued for the month:

```
_meter(..., duration_s=-1)
  -> psycopg.errors.CheckViolation: new row for relation "spend_state" violates
     check constraint "ck_spend_state_billed_inr_nonnegative"
```

The abort takes the whole metering transaction: no usage rows, no wallet debit, no
counters — and every ARQ retry reproduces it, so the call never settles on its own.

**Fix.** `pipeline._billable_seconds` clamps a negative duration to zero and fires
`call_duration_negative` (`WORKER_TERMINAL`, ids plus the value, which is the one fact that
tells a sentinel apart from a clock-skew subtraction). Clamping rather than refusing keeps
P1.2's rule: `_unit_price` holds a leg whole at `qty <= 0`, so our supplier cost still
lands and the client is billed for no minutes, while a call with NO usage artefact is one
the reconciliation poller classifies `settled` and never revisits.
`tests/negative_duration_test.py`, three cases including that the usage panel still
renders — `allocate_paise` refuses a breakdown whose parts cannot add to its total, so a
negative bucket is a 500 on the panel and not merely a wrong number on it.

### F-3 — An operator TIGHTENING a client's ceiling did not arm the gate — **PROVEN** (D-252)

`plans.hard_cap_min` / `hard_cap_spend` are written by exactly one function,
`billing/terms.py::record_terms`, and they are half of the ceiling `over_cap_sql` enforces
(`LEAST(hard, client)`). The only thing that can stop a dial is `spend_state.capped`.
`record_terms` wrote the ceiling and left the flag alone.

`caps.apply_client_caps` had this right for the CLIENT's own stop button and states the
argument in as many words — *"a cap accepted whose gate is not armed is a cap that does
nothing until the next call meters, and for an outbound-only tenant the next call is
exactly what the cap was supposed to stop"*. The ADMIN half, the one an operator reaches
for during an incident, did not do it.

Measured: ₹480 of the client's own money already billed for the month, operator writes
`hard_cap_spend = ₹100`.

```
before   capped=False   check_dispatch -> allowed=True
after    capped=False   check_dispatch -> allowed=True        <- the ceiling bound nothing
```

**Fix.** `record_terms` takes `lock_tenant_spend_state` before the `plans` read its write
depends on (the same check-then-write hole a balance read outside `lock_tenant_credits`
is, with the post-call meter as the concurrent writer), and calls the shared
`recompute_capped` in the same transaction as the insert. Three writers of the flag, one
definition of over-cap. `TermsWriteResult.capped_now` reports it and the
`plan.terms_recorded` audit row carries it, because an operator who tightens a ceiling
mid-incident needs to be told it bit rather than infer it from an empty call list. The
recompute sits AFTER the `_same_terms` early return, so re-posting identical terms stays a
true no-op. `tests/admin_cap_arms_the_gate_test.py`, four cases including the expensive
direction: a first ceiling a tenant is nowhere near must NOT stop them.

After:

```
after    capped=True    check_dispatch -> allowed=False, rule='spend_cap'
```

### F-4 — Two spellings of "minutes used this month": the ceiling was judged against one and the client was shown the other — **PROVEN** (D-253)

* `spend_state.minutes_used` accumulated the meter's own `duration_s / 60`, one call at a
  time, at the column's NUMERIC(14,4) scale. `over_cap_sql` compares it against `cap_min`,
  so it is the number that decides whether a dial happens.
* `usage_summary.minutes_used` is the month's total SECONDS divided once and allocated to
  paise. It is the number on the client's panel, and `minutes_left` derives from it.

Measured on the §1 fixture (3847 / 2913 / 611 / 137 seconds):

```
spend_state.minutes_used   125.1333    <- the ceiling was judged against this
usage_summary              125.13      <- and the client was shown this
```

The drift is the sum of the per-call rounding errors and only grows within a month, so a
busy tenant's two figures land either side of an integer ceiling: the panel promises
minutes the gate has already refused, or the reverse.

**Fix.** The meter no longer computes a minute figure of its own.
`billing.service.overage_increment_inr` becomes `month_increment` and returns a
`MonthIncrement` carrying BOTH differences — minutes and rupees — from the ONE
`rung_seconds` read it already did; `pipeline._billed_for_this_call` becomes
`_counter_increment` and feeds the minute half into the counter on every tier. Because
`rung_minutes` guarantees its parts sum to `to_paise(total_seconds / 60)`, the increments
telescope to precisely the published figure, and every increment is a two-decimal value
the column stores without rounding at all. After: `spend_state.minutes_used` is `125.1300`.

The cost is one grouped aggregate over the month's `usage_events` on the PREPAID path that
was not there before, under a lock the caller already holds.

**What deliberately did NOT move: the prepaid wallet debit.** It stays
`prepaid_billed_inr(this call's own minutes)`. Pricing a call off the month's running
remainder would charge two identical 137-second calls differently on a ledger a client
reads per entry, which is a worse defect than the one being fixed.
`spend_state.billed_inr` for a prepaid tenant is therefore still exactly the sum of the
wallet debits — measured, ₹89.0000 against ₹89.0000 on the ten-call fixture in F-6.

`tests/counter_minutes_match_the_panel_test.py`, both motions.

### F-5 — The invoice stated a tax total its own tax lines were not required to add up to — **PROVEN** (D-255)

`build_invoice` computed `gst = to_paise(subtotal * GST_RATE_PCT / Decimal("100"))` and
then called `split_tax`, which opens with the same expression, character for character.
`split_tax`'s docstring promises that *"the two halves summing to the printed GST total is
the property a hand-checker actually tests"* — and that promise was two identical spellings
agreeing rather than one number being published once.

**Fix.** The heads are computed first and `gst_inr` is their sum. Rule 46(l)-(m) requires
the heads to be stated separately and a recipient credits them to different ledgers, so the
heads are what the document asserts and the total is a convenience over them. The next
rounding decision on this line — F-7 — would otherwise have had to be made in two places or
the document stops adding up.
`tests/invoice_tax_total_is_the_heads_test.py` makes the two differ (a wrapped `split_tax`
with one paisa moved onto the second head) and pins that the document follows the heads.

---

## FOUND, NOT FIXED

### F-6 — The prepaid wallet and the prepaid panel price a month by two arithmetics — **PROVEN**, founder decision (D-254)

Ten calls of 7 / 7 / 7 / 13 / 41 / 59 / 101 / 137 / 211 / 307 seconds at ₹6.00/min, in a
closed month:

```
wallet debited (sum of `usage` entries)   ₹89.0000
spend_state.billed_inr                    ₹89.0000   <- equals the wallet by construction
usage_summary spend_used_inr (closed)     ₹88.98     <- 14.83 min × ₹6.00
```

The two answer different questions and cannot both be satisfied. The wallet is debited per
call at scale 4 because a call is charged for its own length, which is the only rule a
client can be shown per ledger entry. The panel multiplies out against the `minutes_used`
printed beside it, which is the arithmetic a client actually performs — and feeding it the
exact seconds instead would close the gap against the wallet and open it against the
panel, because ₹89.00 is not `14.83 × ₹6.00`, and a figure a client cannot multiply out is
the defect `billing/invoice.py` spent a whole slice removing.

The gap is bounded by half a paisa of minutes times the rate — under ₹0.05 at any rate this
product would quote — and is systematic rather than random.

**What closes it:** the founder decision `deepdive-money.md` N-2 already names — what a
prepaid statement IS (a receipt for top-ups received, a statement of consumption, or both).
If the WALLET is the statement, `calling_revenue_inr`'s prepaid branch reads the ledger and
the re-derivation disappears; if the PANEL is, the wallet's per-call rule is what moves.
The measurement now lives on that function so the next reader inherits the evidence.

### F-7 — GST is stated in PAISE and CGST s.170 rounds tax to the nearest RUPEE — **REASONED**, external blocker (D-256)

**REPORTED, NOT READ** (`billing/payments.py`'s three-rung evidence ladder;
cbic-gst.gov.in is refused by this environment's egress proxy, so no first-party read was
made). Several independent secondaries quote s.170 identically — *the amount of tax,
interest, penalty, fine or any other sum payable, and the amount of refund or any other sum
due, shall be rounded off to the nearest rupee*, fifty paise or more rounding up — and they
agree it is applied per INVOICE and per HEAD (CGST, SGST/UTGST, IGST each) rather than on a
consolidated total.

On §1's document that is the difference between:

```
stated today   gst_inr 3614.52   CGST 1807.26 + SGST 1807.26
under s.170    gst_inr 3614.00   CGST 1807.00 + SGST 1807.00, plus a ROUND OFF line of
                                 -0.52 so subtotal + tax + round_off = total still adds
                                 up in a client's hand
```

**Not implemented, deliberately.** It moves money on every invoice the platform would ever
issue, and no secondary settles first-party whether s.170 binds the DOCUMENT or the RETURN,
nor whether the taxable value rounds along with the tax. Guessing a compliance rule is not
recoverable. Nothing is out of compliance today: `supplier.is_registered` is false in every
deployment and the document says `proforma` — exactly the posture Rule 46(b)'s
serial-number gap already sits in, one comment block above.

**What closes it:** the GST registration (ROADMAP M0) plus a first-party read or an
accountant's confirmation of the per-invoice, per-head reading. Recorded beside
`GST_RATE_PCT`, which is the one home of the rate.

---

## CLEARED (attacked, found sound)

* **Float contamination, the whole surface.** No `float`, no `round()`, no `/` producing
  one, anywhere money flows: `apps/api/billing/**`, the metering path in
  `apps/workers/pipeline.py`, `apps/workers/billing.py` and `packages/shared`. The only
  `round()` calls in the metering file are on a span attribute and a log duration. Every
  money column is `NUMERIC` (`MONEY = Numeric(12, 4)`, `usage_events.qty` and
  `spend_state.minutes_used` `NUMERIC(14, 4)`), every read out of one goes through
  `Decimal(str(...))`, and the four request models that carry money each have a
  `mode="before"` validator refusing a JSON float. **Money leaves the API as digit
  STRINGS** — `routes._stringify` recurses through `line_items`, `tax_components` and
  `usage`, and `InvoiceLineItemOut.qty` is `str` for the stated reason that a consumer must
  never get a bare JSON number on one line and a string on the next. Nothing in the
  OpenAPI money surface is typed `number`.
* **Append-only ledgers (hard rule 4).** `check_ledger_immutability` green: 8 ledgers,
  triggers verified `ENABLE ALWAYS` and raising on UPDATE, DELETE **and** TRUNCATE, no
  mutating statements in app code. A direct grep for `UPDATE`/`DELETE FROM` against each of
  the eight table names across `apps/`, `scripts/` and `packages/` returns nothing.
  `platform_ai_spend` is UPDATEd and is correctly NOT in the list — it is a counter whose
  every rupee is re-derivable from the `usage_events` rows that produced it, and it says so.
* **`credit_ledger.reason = 'refund'` has no unique index, and that is deliberate, not a
  gap.** Migration `f9c2b41a8e57` argues it: `refund` has no writer in `apps/` at all,
  every refund row would carry a NULL `ref`, and the obvious future shape — several partial
  refunds against one payment — legitimately shares a reference. A grep confirms no writer
  exists today.
* **Idempotency of everything that charges.** The Razorpay receiver (`lock_tenant_credits`
  first, then `find_topup` on the permanent `payment_id`, then one `record_entry`, with a
  409 rather than a silent absorb when one payment id arrives at two amounts); the manual
  UTR route (same lock-first order, and it answers on the reference's TOTAL so a restated
  payment does not read as a conflicting one); `adjustment_ref` and `restatement_ref`
  (content-addressed, so a second click derives one key); `issue_setup_fee`
  (unconditional `INSERT ... ON CONFLICT DO NOTHING` on `(tenant_id, kind, ref)`, no
  read-then-write anywhere on the path, and the nightly job is explicit that its probe is a
  cost filter and not a guard); `purchase_ai_overage` (lock, then replay, then the ONE
  reason ladder, then the debit); `record_ai_assist_usage` (idempotent in the index on a
  server-minted `ref`, with the platform counter bumped only for rows that landed);
  `_meter` (`lock_call_writes` + a pre-check + `ux_usage_events_tenant_call_unit` behind
  it) and `charge_for_call` (dedupe read under `credit:{tenant}`). A second delivery of
  each is a no-op or a 409, never a second charge.
* **Concurrency on money.** Every read-then-write over a balance, a counter or a ceiling
  runs under an advisory xact lock taken BEFORE the read: `credit:{tenant}` for the wallet
  (and `find_entry_by_ref` takes it itself, so a future caller cannot reach the read from
  outside the critical section), `spend_state:{tenant}` for the counters and the flag, and
  `call:{call}` for metering. The two are never taken in opposite orders — the meter takes
  `credit:` then `spend_state:` and nothing takes `spend_state:` before `credit:` — and
  D-252 added `record_terms` to the second on the same side. The `spend_state` upsert
  computes `capped` in the same statement that accumulates the totals, from the totals it
  is storing, so two calls finishing at once cannot both see a pre-cap total.
* **Boundaries.** A call spanning midnight IST or a month end lands wholly in the month its
  `ended_at` falls in, on every surface, because `occurred_at` is `ended_at` on every usage
  row and the counter's month derives from the same instant. A call from a CLOSED month
  leaves the open month's counters alone (`_accumulate`'s three-way rule) and its money is
  still on `usage_events`, which is what every panel and invoice read. A ZERO-duration call
  keeps its leg costs whole on the row and contributes nothing to any reader that
  multiplies by `qty` — a measured, documented gap that both `_unit_price` and `_spend_used`
  now describe the same way. A plan changing mid-month prices the whole month by the row in
  effect at `month_pricing_instant` (no proration, argued at length in `plans.py`), and a
  re-rendered closed month cannot be re-priced.
* **A tenant's `plan_tier` cannot change, so no closed month can be re-priced by a motion
  switch.** `organizations.plan_tier` is written in exactly one place —
  `admin/service.create_organization` — and by no UPDATE anywhere. That matters because
  `calling_revenue_inr` and `_spend_used` branch on the CURRENT tier for a whole period: if
  a tier switch is ever added it must carry a valid-time window the way `plans` does, or a
  closed month's statement will change the day it is used.
* **A tenant suspended mid-month.** `compliance.account_stopped_blocker` refuses the dial;
  metering of calls already made is unaffected, which is correct — the calls happened.
* **The setup fee.** Landed in the tenant's own IST onboarding month, frozen in the row,
  quoted by the plan in effect at that month's pricing instant, issued by a daily job whose
  schedule cannot pick the month, and once-per-tenant by a unique index rather than by a
  reader's `if`. Re-verified end to end in §1.
* **`allocate_paise` on the meter's path.** `sum(floors) <= floor(sum(exact)) <=
  to_paise(sum(exact))` still bounds `owed` into `[0, len(parts)]` for non-negative
  buckets, and F-2's clamp is what keeps the buckets non-negative — measured, a negative
  bucket does reach it and does raise.
* **`split_tax`'s remainder.** The second head absorbs `total - first`, so the heads sum to
  the published tax exactly at every subtotal including odd-paise ones; re-checked at
  ₹20,080.67 and on a fixture whose monthly fee ends in an odd paisa.
* **Rounding direction, stated and consistent.** One mode in the tree
  (`billing.rates.ROUNDING = ROUND_HALF_UP`, passed explicitly at every `quantize` and
  scanned for by `tests/money_rounding_mode_test.py`), two quanta with distinct jobs
  (`MONEY_Q` = the NUMERIC(12,4) storage scale for a unit price, `PAISE` = the display
  scale for a rupee amount a human reads), and `ROUND_FLOOR` appears only as the first half
  of `allocate_paise`'s largest-remainder split, whose output is exact. The half-paisa goes
  UP, and the invoice and the counter agree about it because they are the same function.
* **The AI-assist meter and the platform brake.** The `ref` namespace is server-minted and
  validated (a browser-supplied key would be an off switch for metering), both rows and the
  counter commit in the caller's transaction, and the month is read back out of the row the
  database stamped rather than taken from the API process's clock.
* **`margin_for_tenant`.** Cost has one definition (the rungs summed, which is the
  ungrouped total), revenue routes through `calling_revenue_inr` for both motions, and
  `margin_pct` is `None` rather than 0 when there is no revenue.

---

## Gates

`ruff check` · `ruff format --check` · `mypy apps packages` (230 files) ·
`check_ledger_immutability` · `check_rls_coverage` · `check_docs_drift` ·
`check_wiring` · `check_raw_sql` — all green.

Targeted suites: the 16 new cases plus 742 existing tests matching
`billing|money|credit|cap|invoice|usage|meter|quota|pipeline|terms|margin|tier|spend|plan`.

**Sabotage-verified.** Each fix was reverted in turn and its test re-run:

| fix | reverted to | result |
|---|---|---|
| F-1 pricing instant | bind `now()` | `late_call_prices_at_its_own_month_test` 1 failed / 1 passed |
| F-2 duration clamp | return the raw duration | `negative_duration_test` 3 failed |
| F-3 gate re-arm | `capped = None` | `admin_cap_arms_the_gate_test` 2 failed / 2 passed |
| F-4 minute increment | pass `duration_s / 60` | `counter_minutes_match_the_panel_test` 3 failed / 1 passed |
| F-5 tax total | re-derive `gst` from the subtotal | `invoice_tax_total_is_the_heads_test` 1 failed / 2 passed |

The cases that stayed green under sabotage are the ones asserting the OTHER direction
(an open month must still price at now; a ceiling a tenant is inside must not cap; a
re-post must stay a no-op; the heads must sum to the total) — they are companions, not
reproductions, and they are what stops each fix from being a blanket rule.
