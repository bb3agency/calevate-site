# Runbook — "Our calls have stopped"

Symptom: a client says the phone has gone quiet. That sentence now covers at least nine
different conditions, three of which the client caused themselves and one of which is
about Calevate rather than about them. This runbook is the ordered way to tell them
apart.

Two things decide most of it before you run anything.

**Which direction?** Every check below is about OUTBOUND. The compliance gate is
outbound-only by design (`check_dispatch` — "inbound calls never reach this function"),
and load-shedding does not touch `apps/voice-runtime` at all, which is the service the
engine calls on an inbound ring. So *"nobody is answering our number"* is an engine or
telephony problem and belongs in the engine-outage procedure (OPERATIONS §7), not here.
*"our campaign has stopped"* or *"the call-back button does nothing"* is this runbook.

**Campaign, or every outbound path?** The call-this-lead button, the instant-lead
callback and the campaign dispatcher all pass the same gate, so a cause that blocks one
blocks all three. Causes 6–8 below are campaign-only. If the client's callbacks work and
only the campaign is quiet, start at step 4.

Ground rules: production access goes through the audited admin path — distinct role,
always-audited queries (SECURITY-COMPLIANCE.md §"Admin access path"). Read-only SELECTs.
Every query below returns ids, counts and flags; never select `phone_e164`, transcript
text or extraction payloads into a ticket or a terminal you will paste from
(hard rule 6).

---

## The nine causes, and who can clear each

| # | Cause | Where it lives | Cleared by |
|---|---|---|---|
| 1 | Big red switch | `platform_state.outbound_halted` | ops only, audited |
| 2 | Load-shed mode | `platform_state.load_shed_mode` | ops only, audited |
| 3 | Calevate's TM registration | `platform_state.tm_registration_status` | ops only — blocks EVERY tenant's campaign |
| 4 | Admin spend cap | `plans.hard_cap_min` / `hard_cap_spend` | ops only (SQL on the audited path, then the recompute in step 2) |
| 5 | The client's OWN spend cap | `plans.client_cap_min` / `client_cap_spend` | **client, immediately** |
| 6 | The cap flag itself | `spend_state.capped` | ops (`POST /v1/ops/tenants/{id}/spend-cap/recompute`) or the client — see step 2 |
| 7 | Prepaid wallet empty | `credit_ledger` balance, self-serve/trial only | client (top-up) or ops |
| 8 | The client's PE registration / TM link | `dlt_registrations` | ops record it; the registrar decides it |
| 9 | Consent provenance, template, number, DNC | `campaigns.consent_source`, `dlt_templates`, `phone_numbers`, `dnc_list` | mixed — see step 4 |

Work them in the order below, which is cheapest-and-most-likely first, not in the order
of the table.

---

## 1. One request answers causes 1, 2 and 3

`GET /v1/ops/platform`, admin realm, `ops:manage` (`apps/api/ops/routes.py`). It is
never load-shed — `/v1/ops` is in `ALWAYS_ALLOWED_PREFIXES` — so it answers even when
the platform is in maintenance mode.

```
GET /v1/ops/platform
→ {"load_shed_mode": "normal",
   "outbound_halted": false,
   "tm_registration": {"status": "active", "tm_id": "...", "registered_at": "...",
                       "verified_at": "...", "is_live": true}}
```

Read all three fields, not just the first.

- **`outbound_halted: true`** — the big red switch. Nobody dials, no tenant, no path.
  The dispatch tick returns `halted_by_big_red_switch` and touches nothing. Go to
  `campaign-stall.md` §1 for the audited un-halt; do not flip the row with SQL.
- **`load_shed_mode` not `normal`** — this is subtler than it looks and is the one
  people get wrong. Load-shedding is an **HTTP** control (`LoadShedMiddleware`,
  `apps/api/core/middleware.py`). `reduced`, `emergency` and `maintenance` all shed
  non-GET requests, and `maintenance` sheds reads too, so the client gets 503
  `service_load_shed` when they press Launch or Call. But the ARQ dispatch tick is not
  an HTTP request: **a campaign that is already `running` keeps dialling in every
  load-shed mode.** So "the launch button 503s but calls are still going out" is
  load-shed, and "no calls at all" is not.
- **`tm_registration.is_live: false`** — Calevate's own DLT telemarketer registration is
  not active. This blocks **every tenant's campaign at once**, however complete the
  client's own paperwork is. It is `is_live`, computed server-side, not `status` read by
  eye — the console must not decide for itself whether `submitted` is good enough
  (`_tm_out`, `apps/api/ops/routes.py`). This is a legal fact, not an operational one:
  it is not "cleared", it is re-obtained from the registrar and then recorded with
  `POST /v1/ops/platform/tm-registration` (step-up confirmed, audited).

If this step is clean, the platform is not the reason.

## 2. One request answers causes 4, 5 and 6

The client can run this themselves and should be asked to, because it is the fastest
way to find out whether they did it to themselves: `GET /v1/billing/caps`,
`billing:read` (`apps/api/billing/cap_routes.py`). `billing:read` is an owner
permission, not staff's (SEC-COMP §5), so it is the owner who has to look.

```
GET /v1/billing/caps
→ {"month": "2026-08",
   "plan_cap_minutes": 5000,  "plan_cap_spend_inr": "40000.00",
   "client_cap_minutes": null, "client_cap_spend_inr": "5000.00",
   "effective_cap_minutes": 5000, "effective_cap_spend_inr": "5000.00",
   "minutes_used": "812.0000", "spend_used_inr": "5002.40",
   "capped": true}
```

Three ceilings are reported because they are three different facts. `plan_*` is the
ceiling ops agreed and the client cannot move. `client_*` is the client's own, which
they can set as low as they like including zero. `effective_*` is
`LEAST(plan, client)` — the one the gate enforces — and a NULL on either side means "no
constraint from that side", never zero (`billing/caps.py`).

- **`client_cap_spend_inr` (or `client_cap_minutes`) is the smaller one** — the client
  capped themselves. This is self-serve in both directions and takes effect immediately:
  `PUT /v1/billing/caps` (`org:manage`) with a higher value, or `null` to fall back on
  the plan's ceiling. The write recomputes `spend_state.capped` in the same transaction,
  so the next dial is allowed rather than the dial after the next call happens to meter.
  A value **above** the plan's ceiling is refused by name, `client_cap_exceeds_plan_cap`
  — refused, not silently clamped.
- **`plan_cap_*` is the smaller one** — this is ours. There is no route that writes
  `hard_cap_min` / `hard_cap_spend`; raising a plan ceiling is a hand-written UPDATE on
  the audited admin path against the tenant's **newest** `plans` row (`plans` is
  effective-dated and every reader in the codebase takes `ORDER BY created_at DESC LIMIT 1`).
  **That UPDATE is half the job** — finish it with the recompute below, or the client
  stays stopped on a ceiling they are no longer over.
- **`capped: true`** — outbound is refused right now with rule `spend_cap`. Inbound is
  unaffected.

**The trap in this step, and the button that clears it.** `spend_capped()` reads the
`spend_state.capped` boolean, not the ceilings (`apps/api/compliance/service.py`). So
**raising the admin ceiling in SQL does not by itself clear the flag** — it is a derived
column, a capped outbound-only tenant meters nothing, and nothing recomputes it as a
side effect of the UPDATE. If you raise `hard_cap_*` and walk away, the client is still
stopped.

Three things recompute it, and one of them is not "wait":

1. **ops**, immediately, on the audited path:

   ```
   POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute
   X-Confirm-Action: recompute_spend_cap:{tenant_id}
   → {"tenant_id": "...", "month": "2026-08",
      "capped_before": true, "capped": false,
      "minutes_used": "812.00", "spend_used_inr": "5002.40",
      "effective_cap_minutes": 5000, "effective_cap_spend_inr": "8000.00"}
   ```

   `ops:manage`, admin realm, step-up confirmed and audited as `ops.recompute_spend_cap`
   (`apps/api/ops/routes.py`). The confirmation header carries the TENANT ID — one
   captured for another client will not work here, by design. Like everything under
   `/v1/ops` it is never load-shed, so it answers in `maintenance` too.

   **Run it AFTER raising the ceiling, not instead of.** It re-derives the flag from the
   counters already in the row against the ceiling now in force; it does not un-cap. If
   the response comes back `"capped": true`, compare `minutes_used` / `spend_used_inr`
   against the two `effective_cap_*` fields in that same response — the ceiling is still
   the smaller number and the tenant is correctly capped. Note `effective_cap_*` is
   `LEAST(plan, client)`, so a client cap below the one you just raised will keep them
   stopped and only they can move it (route 2 below);
2. **the client** issues `PUT /v1/billing/caps` — any valid body, including one that
   changes nothing. `apply_client_caps` runs the same recompute in the same transaction.
   This is the only route that clears a CLIENT-set cap: `PUT` needs `org:manage`, which
   is in `MUTATING_PERMISSIONS`, so an impersonating admin (D-22) cannot do it for them
   from a client screen;
3. the billing month rolls over. `spend_capped` compares `spend_state.month` against
   `current_billing_month()` (IST), so a flag belonging to a closed month is not a cap —
   which is also why the ops recompute reports `capped: false` and writes nothing for a
   tenant whose row still carries a closed month.

Do **not** UPDATE `spend_state.capped` by hand to unstick it. It is a derived counter
column with three writers sharing one expression (`over_cap_sql` — the meter, the
client's cap route and the ops recompute); a writer that sets the flag directly is how
the meter and the gate start disagreeing.

## 3. Cause 7 — the prepaid wallet

Only bites `self_serve` and `trial` tenants (`organizations.plan_tier`). A managed
client is invoiced against a retainer and is never blocked on credit — that is
`credits_exhausted()` returning False before it looks at any balance
(`apps/api/compliance/service.py`).

The client sees it on their usage panel: `GET /v1/usage` (`billing:read`,
`apps/api/crm/routes.py`) → `credit_balance_inr`
(null for a managed tenant, deliberately — showing them a ₹0 wallet invites a ticket
about a concept that does not apply to them). The gate's refusal rule is `no_credits`.

Remediation is a top-up, and what you can honestly promise depends on whether this
deployment takes online payments at all — see `topup-payments.md` before telling a
client "just pay online".

## 4. Causes 8 and 9 — one request, per campaign

`GET /v1/campaigns/{id}/launch-check`, `leads:read`
(`apps/api/campaigns/routes.py`). The client sees this on their own launch button; it
returns every reason by name, exhaustively rather than one at a time.

```
GET /v1/campaigns/{campaign_id}/launch-check
→ {"ready": false, "blockers": [{"rule": "pe_registration_not_active", "reason": "..."}]}
```

The rule names, from `launch_blockers` (`apps/api/campaigns/service.py`):

| rule | What it means | Who clears it |
|---|---|---|
| `status` | Campaign is not `draft`/`scheduled` | n/a — it already launched |
| `tm_registration_missing` | OUR TM registration (step 1) | ops |
| `pe_registration_missing` | This business has no DLT PE row at all | client files with the registrar; ops records it |
| `pe_registration_not_active` | Filed, not active | the registrar |
| `tm_link_not_active` | The PE has not authorised Calevate as its telemarketer | client, at the registrar — a **different desk** from the line above |
| `consent_provenance_missing` | Nobody has declared where this list came from | client: `POST /v1/campaigns/{id}/consent-provenance` (`leads:dispatch`, audited, **draft campaigns only**) |
| `consent_source_refused` | The declared source is `purchased_list` — the only member of `REFUSED_CONSENT_SOURCES` | not clearable by re-declaring: the list itself is the problem |
| `agent_not_live` / `agent_missing` / `agent_inbound_only` / `disclosure_missing` | The agent may not place calls | client publishes / fixes the agent |
| `spend_cap` / `no_credits` | Steps 2 and 3 | see above |
| `dlt_template_missing` / `_not_approved` / `_mismatch` | The registered voice template | registrar; recording approval is an audited admin action |
| `number_missing` / `number_series_mismatch` / `number_not_registered` | The calling header | ops + TSP |
| `no_contacts` | Nothing pending | client |
| `all_contacts_dnc` | Every number on the list has opted out | not clearable — that is the answer |

The client can read this page themselves. `GET /v1/compliance/dlt-registration`
(`org:read`) shows them what the registrar currently holds for their entity, including
`tm_link_status` and `is_active` computed the same way the gate computes it — absence is
`recorded: false` and a 200, not a 404.

## 5. The campaign is already `running` and quiet

`launch-check` is a launch-time question. A campaign that launched a week ago and has
gone quiet is a different query, because **the registrar can withdraw any of the step-4
facts while a campaign runs** and `resume` is a bare CAS with no gate.

The dispatcher asks the standing subset every tick, once per campaign, inside the
claiming transaction (`dispatch_blockers`, `apps/workers/campaign_dispatch.py`). It
carries the DLT entity, PE, TM-link, consent-provenance, template and number rules —
the same rule names as step 4.

**This refusal is invisible in the tick's return string.** A campaign blocked here
contributes `{"dialled": 0, "blocked": 0, "exhausted": 0}`, so the tick reports
`dialled=0 blocked=0 exhausted=0` and nothing looks wrong. The signal is:

- the WARNING log line `campaign_dispatch_blocked`, carrying `campaign_id` and a comma-
  separated `rules` list (ids and rule names only — never a number, never client
  wording); and
- the `compliance_blocks` metric, labelled by rule (`record_compliance_block`).

If a client's campaign says `running`, shows no progress, and the tick reports zeros
across the board, look for that log line before looking anywhere else.

Two more per-campaign reasons a running campaign sits still, both of them the design
working:

- **The campaign's own calling window.** `campaign_window_open` skips a campaign outside
  its narrowed window entirely — no attempts burned, no refund. A window may only narrow
  the platform's 09:00–21:00 IST, never widen it (`_validated_window`).
- **Everything is waiting on backoff.** See `campaign-stall.md` §6; that runbook owns
  the dispatcher's own failure modes (pool exhaustion, per-tenant ceiling, stuck
  `dialing` rows) and this one should not duplicate them.

## 6. Cause 9's last member — a DNC hit

Per-contact, terminal, and by design. `check_dispatch` reads `dnc_list` LIVE on every
dispatch (hard rule 5), and a hit sets the contact to `dnc_blocked`, which is the only
terminal rule in the dispatcher.

Existence and counts only — do not select the number:

```sql
SELECT status, count(*)
FROM campaign_contacts
WHERE campaign_id = :campaign_id
GROUP BY status;
```

A campaign whose contacts are largely `dnc_blocked` is not broken. If the client
believes a specific number should not be suppressed, that is `dnc-complaint.md`, and the
answer is a timeline, not a removal.

## 7. Answering the client

State it in this order: whether the block is ours or theirs, which named rule is in
force, whether it affects inbound (almost never — the gate is outbound-only), and
whether they can clear it themselves.

The four they can clear without us: their own spend cap (`PUT /v1/billing/caps`), a
prepaid top-up, consent provenance on the campaign, and publishing the agent. Everything
else is either ops, the registrar or a TSP — and in the registrar's case, saying so early
is better than a "we're looking into it" that turns into a week.

## What NOT to do

- **Never UPDATE `spend_state.capped`, `platform_state` or a campaign's `status` by
  hand.** Each has an audited write path and a cache to invalidate; the SQL skips both.
  For `spend_state` specifically the flag is derived — the correct lever is the cap, and
  the recompute rides with it: move the ceiling, then run
  `POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute` (step 2). There is a route for
  this now, so there is no longer any reason to reach for the UPDATE.
- **Never introduce a bypass**, not for a demo, not for one tenant, not for an hour.
  There is no bypass flag on the compliance gate by design (`compliance/service.py` —
  "no bypass flag, not even for testing"), and a TM registration that is not live means
  we would be dialling as an unregistered telemarketer.
- **Never treat `tm_registration_status` as a per-tenant fact.** It is one row, id 1, and
  moving it moves every client at once.
- **Never quote a client's minutes or spend from the `plans` row alone.** A tenant that
  has changed plan has several rows; every reader takes the newest. A join on
  `tenant_id` alone multiplies them.
- **Never select `phone_e164` or transcript text while investigating** (hard rule 6). If
  you need to refer to one subject in writing, use the hashed `subject_ref` the export
  and erasure paths already share.
