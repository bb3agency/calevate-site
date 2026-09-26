# Runbook — restating calls metered under a wrong cost unit

Symptom: `usage_events` rows whose engine-reported cost was converted to rupees under a
premise that turned out to be wrong — the vendor figure was in major units and we divided it
as if it were minor units (100x), or the reverse. The admin margin panel reads a margin too
good (or too bad) to be true, and every figure is internally consistent with every other one.

**This stops nothing.** No call failed and no client is billed off this figure — a client's
invoice is priced off MINUTES at their own plan rate (`prepaid_billed_inr`,
`usage_summary`), never off what the engine charged us. What is wrong is OUR recorded cost,
which is what `margin_for_tenant` and every spend cap are computed from.

⚠ **The alarm that used to page for this, `engine_cost_implausible`, was raised by the rented
engine's adapter and went with it (D-639).** The rows that adapter wrote are history and
still carry `meta.source_currency`, `meta.source_amount` and `meta.fx_rate`, which is what
the restatement below reads. The tooling is engine-neutral.

## 1. Confirm the premise before touching anything

Read the row, and compare the vendor's own figure for the same execution (their dashboard
or their invoice for the day) against `vendor_figure`:

```sql
SELECT unit_type, qty, unit_cost_paid,
       meta->>'source_currency'  AS currency,
       meta->>'currency_stated'  AS stated,
       meta->>'source_amount'    AS vendor_figure,
       meta->>'fx_rate'          AS fx
FROM usage_events WHERE tenant_id = :tid AND call_id = :cid ORDER BY unit_type;
```

If that comparison cannot be made right now, **stop here.** Nothing below may be run on a
suspicion; the ledger is wrong in a knowable, repairable way and it stays repairable.

## 2. Restate history

Say the observation is that the account is billed in **rupees**, not paise — rows were
metered at a divisor of 100 and should have been 1.

1. **Dry-run first**, so you know the size of what you are about to change:

   ```
   uv run python -m scripts.correct_cost_unit --currency INR --from 100 --to 1
   ```

   It writes nothing. The report is per tenant, per call, ids and rupees only — paste it
   into the incident ticket. Add `--tenant <uuid>` to rehearse on one client first.

2. **Apply**, with the same arguments plus `--apply`:

   ```
   uv run python -m scripts.correct_cost_unit --currency INR --from 100 --to 1 --apply
   ```

   It appends ONE compensating entry per affected call (hard rule 4 — `usage_events` is
   INSERT-only and a database trigger enforces it; the mis-metered rows stay, because they
   are the evidence of what we believed when we metered them). It is idempotent on a
   reference derived from `(currency, from, to)`, so a re-run corrects nothing twice. Its
   own correction rows carry `corrected_source_currency` rather than `source_currency`, so
   a second run cannot read them back as more mis-metered cost.

3. **Confirm.** Re-read the margin panel for the affected month, and re-run the dry run: it
   should report no calls at all.

If the answer went the other way (`--from 1 --to 100`), everything above is the same with
the arguments swapped; the deltas are negative and the report says so.

## 3. What NOT to do

* **Do not UPDATE `usage_events`.** The trigger will refuse, and it is right to: the wrong
  rows are the evidence that we read the vendor wrong.
* **Do not touch the client's invoice.** Only our cost moved. Restating a client-facing
  figure here would invent an error the client never experienced.
