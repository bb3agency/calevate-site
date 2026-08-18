# Runbook — "Our calls have stopped"

Symptom: a client says the phone has gone quiet. That sentence now covers at least eleven
different conditions, three of which the client caused themselves, one of which is about
Calevate rather than about them, and two of which are Calevate waiting on itself — an
account held for a human decision nobody has made yet. This runbook is the ordered way to
tell them apart.

Two things decide most of it before you run anything.

**Which direction?** Every check below is about OUTBOUND. The compliance gate is
outbound-only by design (`check_dispatch` — "inbound calls never reach this function"),
and load-shedding does not touch `apps/voice-runtime` at all, which is the service the
engine calls on an inbound ring. So *"nobody is answering our number"* is an engine or
telephony problem and belongs in the engine-outage procedure (OPERATIONS §7), not here.
*"our campaign has stopped"* or *"the call-back button does nothing"* is this runbook.

**Campaign, or every outbound path?** The call-this-lead button, the instant-lead
callback and the campaign dispatcher all pass the same gate, so a cause that blocks one
blocks all three. Causes 8, 10 and 11 are campaign-only — 11 because the first-campaign
hold is asked by `launch_blockers` and `dispatch_blockers` and deliberately NOT by
`check_dispatch`, which is also the single-lead paths (`compliance/first_campaign.py`
states the residual that leaves). If the client's callbacks work and only the campaign is
quiet, start at cause 11 in step 4, then step 5.

Ground rules: production access goes through the audited admin path — distinct role,
always-audited queries (SECURITY-COMPLIANCE.md §"Admin access path"). Read-only SELECTs.
Every query below returns ids, counts and flags; never select `phone_e164`, transcript
text or extraction payloads into a ticket or a terminal you will paste from
(hard rule 6).

**Use the console first; the curl is the fallback.** Every step below that has an operator
control names the screen before it prints the request. Prefer the screen: it shows the
current state before you move it, states the blast radius before the click, and sends the
step-up header for you — three things a hand-assembled `curl` at 3am gets wrong in ways
that are only visible afterwards.

**The requests stay printed, because the console is not independent of what you are
fixing.** It is a browser talking to this same API, so an API that is down, unreachable
from the operator's network, or newly deployed and broken takes the console with it — and
these are precisely the steps you run when something is wrong with the API. (Load-shedding
is NOT one of those cases: `/v1/ops` and `/v1/admin` are in `ALWAYS_ALLOWED_PREFIXES`
(`apps/api/core/loadshed.py`), so the console keeps working in every load-shed mode
including `maintenance` — that is deliberate, so an operator cannot shed themselves out of
the switch that undoes it.) If the console is up, the curl below is the wrong tool; if it
is not, it is the only one.

---

## The eleven causes, and who can clear each

| # | Cause | Where it lives | Cleared by |
|---|---|---|---|
| 1 | Big red switch | `platform_state.outbound_halted` | ops only, audited |
| 2 | Load-shed mode | `platform_state.load_shed_mode` | ops only, audited |
| 3 | Calevate's TM registration | `platform_state.tm_registration_status` | ops only — blocks EVERY tenant's campaign |
| 4 | Admin spend cap | `plans.hard_cap_min` / `hard_cap_spend` | ops only (SQL on the audited path, then the recompute in step 2) |
| 5 | The client's OWN spend cap | `plans.client_cap_min` / `client_cap_spend` | **client, immediately** |
| 6 | The cap flag itself | `spend_state.capped` | ops (client screen → "Spend cap") or the client — see step 2 |
| 7 | Prepaid wallet empty | `credit_ledger` balance, self-serve/trial only | client (top-up) or ops |
| 8 | The client's PE registration / TM link | `dlt_registrations` | ops record it; the registrar decides it |
| 9 | Subscriber KYC not verified | `kyc_records.status`, self-serve/trial only | ops record it (`POST /v1/admin/tenants/{id}/kyc`); the client cannot self-verify |
| 10 | Consent provenance, template, number, DNC | `campaigns.consent_source`, `dlt_templates`, `phone_numbers`, `dnc_list` | mixed — see step 5 |
| 11 | First campaign not yet released by a human | `first_campaign_reviews`, self-serve/trial only | ops only (`POST /v1/admin/tenants/{id}/first-campaign-review`); the client cannot release itself |

Work them in the order below, which is cheapest-and-most-likely first, not in the order
of the table.

---

## 1. One request answers causes 1, 2 and 3

**Console: Operations — `/admin/ops`** (admin realm, `superadmin`; the nav entry is under
"Platform"). It renders all four fields below and carries the control for each of the
three causes: the big red switch, the load-shed mode, and our TM registration. If it says
*"We do not know whether outbound calling is halted"*, the read failed — believe that
sentence and do not treat it as "running".

The request it makes, for when the console is not available (see the ground rules):
`GET /v1/ops/platform`, admin realm, `ops:manage` (`apps/api/ops/routes.py`). It is
never load-shed — `/v1/ops` is in `ALWAYS_ALLOWED_PREFIXES` — so it answers even when
the platform is in maintenance mode.

```
GET /v1/ops/platform
→ {"load_shed_mode": "normal",
   "outbound_halted": false,
   "halt_reason": null,
   "tm_registration": {"status": "active", "tm_id": "...", "registered_at": "...",
                       "verified_at": "...", "is_live": true}}
```

Read all four fields, not just the first.

- **`outbound_halted: true`** — the big red switch. Nobody dials, no tenant, no path.
  The dispatch tick returns `halted_by_big_red_switch` and touches nothing. Release it on
  the **Operations** screen (type `RESUME` plus a reason, which is what the audit row and
  the row's own `halt_reason` will carry); `campaign-stall.md` §1 has the equivalent
  request for when the console is down. Do not flip the row with SQL either way.
- **`halt_reason`** — WHY it was halted, in the words of whoever halted it. It is
  required to halt, so it is null while `outbound_halted` is true only for a halt thrown
  before this field was wired (fall back to `audit_log` for those), and it is
  **cleared on release**, so it is never anything else while outbound is running: a
  reason beside a running platform would read as current and send you after last week's
  incident. Read it BEFORE deciding whether the condition still holds — that decision is
  the whole reason the field exists, and a halt lifted because nobody could find out why
  it was pulled is the failure this replaced. The permanent history of who halted, when
  and why is `audit_log` (`ops.halt_outbound` / `ops.release_outbound`).
- **`load_shed_mode` not `normal`** — this is subtler than it looks and is the one
  people get wrong. Load-shedding is an **HTTP** control (`LoadShedMiddleware`,
  `apps/api/core/middleware.py`). `reduced`, `emergency` and `maintenance` all shed
  non-GET requests, and `maintenance` sheds reads too, so the client gets 503
  `service_load_shed` when they press Launch or Call. But the ARQ dispatch tick is not
  an HTTP request: **a campaign that is already `running` keeps dialling in every
  load-shed mode.** So "the launch button 503s but calls are still going out" is
  load-shed, and "no calls at all" is not.

  Moving the mode is the **Load-shed mode** control on the Operations screen: pick the
  target, type it back in capitals, give a reason. The screen prints what the target mode
  sheds before you commit, and it will not submit the mode the platform is already in —
  a re-assert writes an audit row for a change nobody made. Note what that screen also
  says, because it is not obvious from the names: **`reduced` and `emergency` shed exactly
  the same set today** (both are in `_SHED_WRITES`, neither is in `_SHED_READS` —
  `apps/api/core/loadshed.py`), so choosing `emergency` expecting reads to stop buys
  nothing. Only `maintenance` sheds reads. By hand, if the console is down:

  ```
  POST /v1/ops/platform
  X-Confirm-Action: set_load_shed:normal
  {"load_shed_mode": "normal", "reason": "index build finished, restoring writes"}
  ```

  The header names the TARGET mode. `campaign-stall.md` §1 lists every form of it,
  including the `+`-joined string for a request that also moves the halt.
- **`tm_registration.is_live: false`** — Calevate's own DLT telemarketer registration is
  not active. This blocks **every tenant's campaign at once**, however complete the
  client's own paperwork is. It is `is_live`, computed server-side, not `status` read by
  eye — the console must not decide for itself whether `submitted` is good enough
  (`_tm_out`, `apps/api/ops/routes.py`). This is a legal fact, not an operational one:
  it is not "cleared", it is re-obtained from the registrar and then recorded — on the
  Operations screen's **Our telemarketer registration (DLT)** form, or by hand with
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
  the audited admin path against the tenant's **plan IN EFFECT** — which since D-46 is
  the row whose `[effective_from, effective_to)` window contains the instant, not simply
  the newest row (`plan_in_effect_sql`, `apps/api/billing/plans.py`). Match that predicate
  when you pick the row: a tenant with a price change staged for next month has more than
  one, and updating the wrong one moves a ceiling that is not binding today. If
  `GET /v1/billing/caps` reports all-NULL ceilings for a tenant that has plan rows, the
  window has closed with no successor — that is the `warn_no_plan_in_effect` case, and the
  fix is a successor row or clearing `effective_to`, not a cap edit.
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

1. **ops**, immediately, on the audited path.

   **Console: the client's own screen — `/admin/tenants/{tenant_id}` → "Spend cap"**
   (admin realm, `superadmin`: this is the one control on that page whose route lives
   under `/v1/ops`). It is on the CLIENT's screen rather than on Operations because the
   route names a tenant and binds its confirmation to that tenant's id — the panel puts
   the button beside this client's three ceilings and this month's counters, so "will the
   recompute help?" is answerable before you press it rather than from the response.

   Read the panel's flag, not the directory badge, when the two disagree: the badge reads
   `spend_state.capped` with no month test (`apps/api/admin/service.py`), while the panel
   and the compliance gate both apply one — a row left over from a closed month shows as
   capped on the directory and is not a cap. The panel says so when it happens.

   The request, for when the console is down:

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

## 4. Causes 9 and 11 — the two holds that wait on a human at Calevate

These two are different in kind from everything above. Nothing is broken, no ceiling was
hit, and the client cannot fix it however much they want to: **we have not done something
yet.** Both are R-11 mitigations, both apply to `self_serve` and `trial` only
(`SELF_SERVE_TIERS`, `apps/api/compliance/service.py`), and both are cleared by an
audited admin action and by nothing else.

**Ask the queue first — it answers "is a human the blocker?" for every account at once:**

```
GET /v1/admin/compliance/holds        # admin realm, org:read
→ [{"tenant_id": "...", "name": "...", "slug": "...", "plan_tier": "self_serve",
    "signed_up_at": "2026-08-01T09:12:44Z",
    "holds": ["kyc_missing", "first_campaign_review_pending"]}]
```

`apps/api/admin/holds_routes.py`. Oldest signup first, because that is the triage order.
`org:read` and not `admin:tenants` deliberately, so a read-only "view as client"
impersonation session (D-22) can still look; the realm is what separates admin from
client here, not the permission. It is read-only and writes no audit row — every
decision taken FROM it writes its own. An account held by both gates appears once with
both rules, and the strings are the same rule names the client's screen and
`/launch-check` use, so you and the client are naming one condition identically.

An empty list means no account is waiting on us. If the client is not on it, their
problem is one of the other nine causes — the queue is exhaustive for causes 9 and 11
and says nothing about the rest.

### Cause 9 — subscriber KYC

Only bites `self_serve` and `trial` tenants, the same scope as the wallet above and for
the same reason: the risk R-11 names is an ANONYMOUS signup, and a managed client is
contracted with a PE registration an access provider granted only after checking
PAN/GST/CIN. `kyc_blocker()` in `apps/api/compliance/service.py` is the one
implementation, shared by `check_dispatch` and the launch preview, so this reason reads
identically wherever it appears.

**Inbound is unaffected**, on every plan. Say that first when a client calls: they will
assume their receptionist is down and it is not.

```
GET /v1/compliance/kyc          # the tenant's own state; org:read, absence is a 200
```

| reason | What it means | Who clears it |
|---|---|---|
| `kyc_missing` | No `kyc_records` row at all | ops, after the client sends the entity documents |
| `kyc_not_verified` | A row exists in `submitted`, `rejected` or `expired` | ops — `rejected` carries the reason; `expired` needs re-verification |

Recording it is admin-realm and audited: `POST /v1/admin/tenants/{tenant_id}/kyc`
(`admin:tenants`). There is deliberately NO client-realm write — the client sends us
documents, we record what we checked. **Never accept an identity document**: the record
holds a public business-registry reference, and a CHECK refuses a 12-digit string so an
Aadhaar cannot be filed by accident.

Note the asymmetry, because it decides who you can unblock: DIALLING is gated for
self-serve and trial only, but BUYING a number is gated for every tier with no
`plan_tier` test at all — the DoT obligation attaches to the connection, and `plan_tier`
is admin-settable, so a legal control keyed on it would be one support ticket from being
switched off. A managed tenant therefore keeps dialling but cannot buy a new number.

### Cause 11 — the first campaign is held for review

BRD §245's last self-serve control: **the first campaign of every self-serve account is
read by a person before it dials** (`apps/api/compliance/first_campaign.py`). Two things
about it surprise people, and both are deliberate:

- **The hold is on the ACCOUNT, not on a campaign.** While an account is unreleased,
  *every* campaign it owns is refused, not only the first — so launching a second one, or
  deleting the first, changes nothing. Once released, no campaign is refused on this rule
  again.
- **Absence is the held state.** There is no "pending" row. A tenant with no
  `first_campaign_reviews` row has not been reviewed, which is where every new account
  starts, so a client who says "my account looks fine" is reading a screen that says
  exactly that.

It refuses in **two** places, which is why a client can hit it after a successful launch:
`launch_blockers` at the button, and `dispatch_blockers` on **every dispatch tick** — so
withdrawing a release stops a running campaign mid-list rather than letting it finish.
A campaign blocked this way is invisible in the tick's counters; see step 6.

The client's own view — ask them to read it, it is the fastest way to agree on facts:

```
GET /v1/compliance/first-campaign-review        # org:read, the client's own realm
→ {"held": true, "rule": "first_campaign_review_pending", "reason": "...",
   "status": null, "decision_note": null, "reviewed_campaign_id": null,
   "decided_at": null}
```

| rule | What it means | Who clears it |
|---|---|---|
| `first_campaign_review_pending` | No decision row: nobody at Calevate has looked yet | ops, after reading the list, the script and the disclosure line |
| `first_campaign_review_rejected` | A reviewer looked and refused; `decision_note` is their words, and the client is shown them | ops, after the client fixes what the note names |

Releasing (or refusing) it is admin-realm, audited as `first_campaign_review.decided`,
and names the tenant in the path:

```
POST /v1/admin/tenants/{tenant_id}/first-campaign-review     # admin:tenants
{"decision": "approved",
 "note": "read the 240-contact list, the script and the disclosure line; source is their own webform",
 "reviewed_campaign_id": "<the campaign you actually read>"}
```

`apps/api/compliance/first_campaign_routes.py`. The note is required and refused under
three characters (`first_campaign_review_note_required`) — a release nobody can account
for later is the audit finding this record exists to avoid. `reviewed_campaign_id` is
evidence, not mechanism: it is checked against the tenant's own campaigns and deleting it
later does not re-hold the account. The route upserts, so a release can be **withdrawn**
when complaints arrive and granted again; the history is `audit_log`, not this row.

Two things this hold does NOT do, so you do not send a client down the wrong path:

- **Inbound is unaffected**, like every gate in this runbook.
- **Single manual calls still go out.** The D-21 "call this lead" button and the
  instant-lead callback go through `check_dispatch`, which does not ask this question —
  they are one call to a lead who just raised their hand, not a campaign. A held account
  that says "but we called someone yesterday" is describing the design.

---

## 5. Causes 8 and 10 — one request, per campaign

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
| `first_campaign_review_pending` / `_rejected` | The account has not been released for campaign calling (step 4) | ops only |
| `spend_cap` / `no_credits` | Steps 2 and 3 | see above |
| `dlt_template_missing` / `_not_approved` / `_mismatch` | The registered voice template | registrar; recording approval is an audited admin action |
| `number_missing` / `number_series_mismatch` / `number_not_registered` | The calling header | ops + TSP |
| `no_contacts` | Nothing pending | client |
| `all_contacts_dnc` | Every number on the list has opted out | not clearable — that is the answer |

The client can read this page themselves. `GET /v1/compliance/dlt-registration`
(`org:read`) shows them what the registrar currently holds for their entity, including
`tm_link_status` and `is_active` computed the same way the gate computes it — absence is
`recorded: false` and a 200, not a 404.

## 6. The campaign is already `running` and quiet

`launch-check` is a launch-time question. A campaign that launched a week ago and has
gone quiet is a different query, because **the registrar can withdraw any of the step-4
facts while a campaign runs** and `resume` is a bare CAS with no gate.

The dispatcher asks the standing subset every tick, once per campaign, inside the
claiming transaction (`dispatch_blockers`, `apps/workers/campaign_dispatch.py`). It
carries the DLT entity, PE, TM-link, consent-provenance, template and number rules —
the same rule names as step 5 — **plus the first-campaign hold** (step 4, cause 11),
which is the one tenant-level rule in that list and the one that can appear on a
campaign that launched cleanly last week: a release we withdrew stops the campaign at
the next tick rather than letting it dial to the end of its list.

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
  the platform's 09:00–21:00 IST, never widen it (`_validated_window`). That check runs
  BEFORE the claim, once per tick; `campaign_dialable_now` asks the same question again
  per contact after the claim has committed, because the dial is a whole dial phase
  later, and a contact refused there does burn and refund an attempt
  (`campaign_window_closed` in `campaign-stall.md` §8).
- **Everything is waiting on backoff.** See `campaign-stall.md` §7; that runbook owns
  the dispatcher's own failure modes (pool exhaustion, per-tenant ceiling, stuck
  `dialing` rows) and this one should not duplicate them.

## 7. Cause 10's last member — a DNC hit

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

## 8. Answering the client

State it in this order: whether the block is ours or theirs, which named rule is in
force, whether it affects inbound (almost never — the gate is outbound-only), and
whether they can clear it themselves.

The four they can clear without us: their own spend cap (`PUT /v1/billing/caps`), a
prepaid top-up, consent provenance on the campaign, and publishing the agent. Everything
else is either ops, the registrar or a TSP — and in the registrar's case, saying so early
is better than a "we're looking into it" that turns into a week.

## 9. `engine_error_spike` — the twelfth cause, which is not ours

The eleven causes above are all OUR refusals: a switch, a cap, a registration, a hold. The
twelfth is the voice platform failing, and it looks different — nothing is refused, the
gate is green, and calls simply do not connect.

**What the alarm measured.** Ten or more engine requests failed inside five minutes,
counting both 5xx answers and requests that got no answer at all. The threshold is derived
from the retry ladder (`3 x WORKER_MAX_TRIES + 1`): below it, one unlucky call retrying
three times could set it off. `apps/api/engine/health.py` carries the argument.

### 9.1 Confirm and scope it

```sql
SELECT engine, bucket_start, server_errors, unreachable
FROM platform_engine_health
WHERE bucket_start >= now() - interval '2 hours'
ORDER BY bucket_start DESC;
```

Read the two columns apart — they are different incidents wearing one alarm:

- **`unreachable` high, `server_errors` ~0** — nothing is answering. DNS, egress, TLS, or
  the vendor being entirely down. Check egress from the host before blaming the vendor.
- **`server_errors` high** — the vendor's application is answering and failing. Their
  status page is the next stop; there is nothing to fix here.
- **Both, in a narrow band of minutes, then nothing** — a blip. The alarm fired because
  the retry ladders across several operations overlapped. No action beyond noting it.

### 9.2 What is and is not lost

- **Calls already placed are not lost.** The reconciliation poller is the guarantee of
  record (D-31): it re-reads executions every ten minutes and repairs what the webhooks
  missed. Expect `reconciliation_repairs{kind=missing_call}` to rise afterwards — that is
  the design working, not a second incident.
- **Dials attempted during the outage burned a contact attempt each.** They come back
  through the retry ladder; a campaign may exhaust contacts early if the outage is long.
- **Publishes failed.** An agent whose publish failed is NOT live. Re-publish and confirm
  from the agent's own screen after the engine recovers.
- **Nothing is dead-lettered by this.** Do not run an outbox replay; that is a different
  alarm (`outbox_dead_letter`) with a different remedy.

### 9.3 If it is sustained

Halt outbound with the big red switch rather than letting campaigns grind their contacts'
retry budgets against a dead vendor — every attempt spent now is one not available when the
platform comes back. Inbound is unaffected by the switch and by definition already broken
if the engine is down.

## What NOT to do

- **Never UPDATE `spend_state.capped`, `platform_state` or a campaign's `status` by
  hand.** Each has an audited write path and a cache to invalidate; the SQL skips both.
  For `spend_state` specifically the flag is derived — the correct lever is the cap, and
  the recompute rides with it: move the ceiling, then press **Recompute this client's
  spend cap** on `/admin/tenants/{tenant_id}` (step 2). There is a route and a screen for
  this now, so there is no longer any reason to reach for the UPDATE.
- **Never clear a hold with SQL.** Neither `kyc_records` nor `first_campaign_reviews` is
  a flag to flip: the value of both rows is that a named person recorded what they
  checked, and the audited routes write that record. An account released by an UPDATE is
  an account released by nobody.
- **Never introduce a bypass**, not for a demo, not for one tenant, not for an hour.
  There is no bypass flag on the compliance gate by design (`compliance/service.py` —
  "no bypass flag, not even for testing"), and a TM registration that is not live means
  we would be dialling as an unregistered telemarketer.
- **Never treat `tm_registration_status` as a per-tenant fact.** It is one row, id 1, and
  moving it moves every client at once.
- **Never quote a client's minutes or spend from the `plans` row alone.** A tenant that
  has changed plan has several rows, and every reader resolves the one whose effective
  window contains the instant being priced (D-46) — so a figure read off "the" plan row
  can be next month's price or last quarter's. A join on `tenant_id` alone multiplies them.
- **Never select `phone_e164` or transcript text while investigating** (hard rule 6). If
  you need to refer to one subject in writing, use the hashed `subject_ref` the export
  and erasure paths already share.
