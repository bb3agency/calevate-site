# Runbook — the engine's charge does not look like a price: `engine_cost_implausible`

Symptom: a page whose detail reads *"one call metered at INR 0.0530 per minute over 142s,
outside the plausible band 0.10-100"*, and then names what the adapter believed — the
currency it read, whether the payload STATED that currency, and the fx rate it used. Or the
same disease with no page at all: the admin margin panel reads a margin too good to be
true, `tier_usage` says a minute of calling costs us a fraction of a rupee, and nobody can
find the mistake because every figure is internally consistent with every other one.

**This is a money alarm and it stops nothing.** No call failed, no job is queued, and no
client is billed off this figure — a client's invoice is priced off MINUTES at their own
plan rate (`prepaid_billed_inr`, `usage_summary`), never off what the engine charged us.
What is wrong is OUR recorded cost, which is what `margin_for_tenant` and every spend cap
are computed from. Read the whole page before changing anything: the repair is one constant
and one script, and doing them in the wrong order leaves a month split across two scales.

## 1. What the alarm is actually saying

Two premises sit between the vendor's number and the rupee in `usage_events`, and
**NEITHER HAS EVER BEEN OBSERVED AGAINST A LIVE ACCOUNT** (OPERATIONS §2 gate 7):

| Premise | Held as | Worth |
| --- | --- | --- |
| the UNIT — minor units (cents) or major units | `engine/bolna.py::_MINOR_UNITS_PER_MAJOR`, `USD: 100`, from the vendor's OpenAPI ("in cents") against their own prose ("Bolna cost in account currency") | 100x |
| the CURRENCY — which one the account is billed in | `_ASSUMED_CURRENCY` = USD, named in no first-party document at all | ~88x |

`_check_cost_plausibility` in the same file scores the derived ₹/min against
`_PLAUSIBLE_INR_PER_MIN_FLOOR`–`_PLAUSIBLE_INR_PER_MIN_CEILING` (₹0.10–₹100), which is
roughly 5x below and 15x above every price this product plausibly pays. Calls shorter than
`_PLAUSIBILITY_MIN_DURATION_S` (30 s) are not scored at all — their charge is a stub rather
than a price, and an alarm that fires on the commonest call shape gets muted.

A miss **too small** means we are under-recording our cost, the direction that flatters the
margin panel. **Too large** means the opposite and shows up as an impossible cost of goods
at the first month-end read.

## 2. Triage — three readings, in order

1. **How wide is the miss?** ~100x → the UNIT. ~85–90x → the CURRENCY (that is the USD/INR
   rate; compare against `usd_inr_rate`). Neither — 3x, say — is not this defect: check
   whether a vendor plan changed before touching any of the below.
2. **What does the row say it did?** The alert carries ids only (hard rule 6), so go to the
   ledger for the rest:

   ```sql
   SELECT unit_type, qty, unit_cost_paid,
          meta->>'source_currency'  AS currency,
          meta->>'currency_stated'  AS stated,
          meta->>'source_amount'    AS vendor_figure,
          meta->>'fx_rate'          AS fx
   FROM usage_events WHERE tenant_id = :tid AND call_id = :cid ORDER BY unit_type;
   ```

   `stated = false` means the currency is OUR assumption and not theirs — which is also
   gate 7's second criterion, answered from the ledger. `vendor_figure` is the vendor's own
   number already divided by the divisor that priced the row; the divisor itself is not on
   the row and does not need to be, because it is a function of `currency` and the table
   above (one entry, `USD: 100`). A row from before that table existed was priced by the
   same 100.
3. **What does the VENDOR say the same execution cost?** This is the only independent
   check, and it is the gate-7 observation: open the execution on their dashboard, or their
   invoice for that day, and put their figure beside `vendor_figure`. Two orders of
   magnitude apart is impossible to misread.

If step 3 cannot be done right now, **stop here.** Nothing below may be run on a suspicion.
The ledger is wrong in a knowable, repairable way and it stays repairable.

## 3. The fix, in the order that keeps a month coherent

Say the observation is that the account is billed in **rupees**, not paise — i.e. the
divisor for `INR` should be 1, and rows were metered at 100.

1. **Dry-run the restatement first**, so you know the size of what you are about to change
   and so the ledger has not moved under you:

   ```
   uv run python -m scripts.correct_cost_unit --currency INR --from 100 --to 1
   ```

   It writes nothing. The report is per tenant, per call, ids and rupees only — paste it
   into the incident ticket. Add `--tenant <uuid>` to rehearse on one client first; the
   default walks every tenant, which is the mode that matches the defect (one adapter
   prices the whole fleet).

2. **Change what is metered NEXT.** Add the currency's line to `_MINOR_UNITS_PER_MAJOR` in
   `apps/api/engine/bolna.py` and deploy. This is a code change and not a config row, on
   purpose: `_ASSUMED_CURRENCY` and `_CONVERTIBLE_CURRENCIES` are module constants for the
   same reason, and a settings field for one of the three would be a second way to state
   one class of assumption. Until the deploy lands, calls keep metering at the old divisor
   — or, for a currency with no entry at all, keep refusing (see §4) — and that is fine,
   because step 3 can be re-run.

3. **Restate history**, with the same arguments plus `--apply`:

   ```
   uv run python -m scripts.correct_cost_unit --currency INR --from 100 --to 1 --apply
   ```

   It appends ONE compensating entry per affected call (hard rule 4 — `usage_events` is
   INSERT-only and a database trigger enforces it; the mis-metered rows stay, because they
   are the evidence of what we believed when we metered them). It is idempotent on a
   reference derived from `(currency, from, to)`, so re-running after a crash — or after
   the deploy in step 2 caught a few more calls — corrects nothing twice. Its own
   correction rows carry `corrected_source_currency` rather than `source_currency`, so a
   second run cannot read them back as more mis-metered cost.

4. **Confirm.** Re-read the margin panel for the affected month, and re-run the dry run: it
   should report no calls at all.

If the answer went the other way (`--from 1 --to 100`), everything above is the same with
the arguments swapped; the deltas are negative and the report says so.

## 4. If the CURRENCY is what is wrong

The adapter REFUSES rather than converts when a payload states a currency whose unit it has
no evidence for, so the usual symptom of a currency surprise is not this alarm at all: it is
`call_billable_without_cost` (from `pipeline._meter`) plus `engine_cost_unit_unknown` in the
adapter's log, on every call. Nothing is metered for that account until the table gains its
entry — that cost is deliberate, and §3 is still the repair: observe, add the line, deploy,
restate whatever was metered before. If the account turns out to be billed in a currency we
hold no FX rate for at all, the adapter refuses earlier and differently
(`engine_cost_currency_unsupported`, `_CONVERTIBLE_CURRENCIES`), and that needs a rate
before anything can meter — a code change plus a config row, not a runbook step.

## 5. What NOT to do

* **Do not UPDATE `usage_events`.** The trigger will refuse, and it is right to: the wrong
  rows are the evidence that we read the vendor wrong, and a ledger somebody can tidy is not
  evidence of anything.
* **Do not widen the band to silence the page.** It is derived from the BRD's unit economics
  and is already ~5x below and ~15x above every price this product pays. A band that admits
  a 100x error admits the only error it exists to catch.
* **Do not "fix" the divisor on a hunch.** `_MINOR_UNITS_PER_MAJOR` holds the vendor's own
  documented reading until somebody makes the observation. Changing it on inference is
  exactly how the ledger acquired a premise nobody had checked in the first place.
* **Do not touch the client's invoice.** Only our cost moved. Restating a client-facing
  figure here would invent an error the client never experienced.
