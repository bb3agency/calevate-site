# Runbook — Campaign is not dialling

Symptom: a client reports their campaign launched but nobody is being called; or the
`connected` count on the campaign screen has stopped moving.

The dispatch tick (`dispatch_campaign_tick` in `apps/workers/campaign_dispatch.py`) runs
every 30 seconds (cron `second={0, 30}` in `apps/workers/settings.py`). Work the checks
below IN ORDER — they go from "all tenants halted" to "this one contact blocked", which
is also cheapest-first.

Ground rules before any SQL: production access goes through the audited admin path —
distinct role, always-audited queries (SECURITY-COMPLIANCE.md §"Admin access path").
Read-only SELECTs only. Never select `phone_e164` or transcript text into a ticket or
terminal you'll paste from (hard rule 6) — every query below returns ids and counts.

## 1. Big red switch (halts ALL tenants)

The tick checks this once, up front, and returns `"halted_by_big_red_switch"` without
touching a single campaign (`apps/workers/campaign_dispatch.py`).

1. Ask the API (never shed — `/v1/ops` is in `ALWAYS_ALLOWED_PREFIXES`,
   `apps/api/core/loadshed.py`): `GET /v1/ops/platform` with an admin-realm principal
   holding `ops:manage` (`apps/api/ops/routes.py`). Response:
   `{"load_shed_mode": "...", "outbound_halted": true|false, "halt_reason": "..."|null}`.
2. Or read the durable truth directly — one row, id 1:

   ```sql
   SELECT load_shed_mode, outbound_halted, halt_reason, changed_by, changed_at
   FROM platform_state WHERE id = 1;
   ```

3. `outbound_halted = true` → someone pulled the switch. **`halt_reason` says why**, in
   the words of whoever pulled it; it is required to halt and cleared on release, so a
   non-null value here is always about the halt in force right now. Read it before
   considering un-halting — the question is whether that condition still holds.
   `audit_log` supplies the rest: `ops.halt_outbound` names WHO and WHEN. (It does not
   carry the reason text: `audit_log` has no summary column, and `write_audit`'s summary
   goes to the log stream keyed by entry id — which is exactly why the reason now lives
   on the row.) Un-halt is:

   ```
   POST /v1/ops/platform
   X-Confirm-Action: release_outbound
   {"outbound_halted": false, "reason": "engine recovered, dialling resumed"}
   ```

   **The confirmation header names the transition, and only that transition**
   (`platform_confirmation`, `apps/api/ops/routes.py`): `halt_outbound` to pull the
   switch, `release_outbound` to lift it, `set_load_shed:<mode>` to move the load-shed
   mode, and the two joined with `+` (halt half first) for a request that does both —
   e.g. `release_outbound+set_load_shed:normal`. The older `set_platform_state` header
   authorises nothing now, in either direction; if you send it you get 403
   `step_up_required` whose `remediation` prints the exact header to repeat with. Never
   flip the row with SQL: that skips the cache invalidation in `set_platform_status`,
   the audit entry, and the reason.
4. Note the read path is memo (5s) → Redis (`calevate:platform_state`) → Postgres
   (`apps/api/core/loadshed.py`). Worst-case staleness after an un-halt is seconds, not
   minutes — if dialling doesn't resume within two ticks, keep going down this list.

## 2. Read the tick's own verdict

Each tick returns one string (ARQ job result / worker logs). Match it:

| Return string | Meaning | Go to |
|---|---|---|
| `halted_by_big_red_switch` | Platform halt | step 1 |
| `no_outbound_pool` | Reserve ≥ total lines; pool is zero. Also fires alert `WORKER_STALL` / `outbound_pool_empty` | step 3 |
| `pool_saturated active=N` | Pool exists but N active calls consume it all | step 3 |
| `no_running_campaigns` | No campaign in status `running` had slots > 0 | steps 4–5 |
| `dialled=X blocked=Y exhausted=Z` | Tick is working; the problem is per-campaign or per-contact | steps 6–8 |

All strings from `dispatch_campaign_tick` in `apps/workers/campaign_dispatch.py`.

## 3. Platform pool exhaustion

Pool math (`apps/workers/campaign_dispatch.py`): `PLATFORM_LINES_TOTAL = 10`, reserve =
`max(MIN_INBOUND_RESERVE=4, 10 × inbound_reserve_ratio)` (ratio defaults to 0.3 in
`packages/shared/src/calevate_shared/config.py`) → outbound pool = 6 lines shared across
ALL tenants. Active = `calls` rows with `direction = 'outbound'`, status in
`queued / ringing / in_progress` (`ACTIVE_STATUSES`), `updated_at` within the last hour
(`ACTIVE_CALL_HORIZON` — older rows are presumed stranded and NOT counted).

Per tenant (tenant-scoped session; run for each suspect tenant):

```sql
SELECT status, count(*)
FROM calls
WHERE direction = 'outbound'
  AND status IN ('queued', 'ringing', 'in_progress')
  AND updated_at > now() - interval '1 hour'
GROUP BY status;
```

- Counts that look too high vs. real traffic = stranded rows from lost engine events.
  The reconciliation poller (`reconcile_executions`, every 10 minutes per
  `apps/workers/settings.py`) is the corrector — check it is running and green
  (metric `reconciliation_repairs`, `apps/api/core/alerting.py`) rather than fixing
  rows by hand.
- `no_outbound_pool` (pool ≤ 0) means config, not traffic: someone changed
  `inbound_reserve_ratio` or `PLATFORM_LINES_TOTAL`. Fix the config, not the data.

## 4. Per-tenant ceiling

The tick computes, per tenant: `tenant_budget = concurrency_ceiling − active`, then
`slots = min(campaign.concurrency, tenant_budget)`; only `slots > 0` campaigns join the
dial list (`apps/workers/campaign_dispatch.py`). Ceiling comes from
`plans.concurrency_ceiling`, `COALESCE(..., 10)`:

```sql
SELECT c.id, c.status, c.concurrency, COALESCE(p.concurrency_ceiling, 10) AS ceiling
FROM campaigns c
LEFT JOIN plans p ON p.tenant_id = c.tenant_id
WHERE c.status = 'running';
```

A tenant whose active-call count (step 3) ≥ ceiling gets zero slots every tick — that is
the design working (one client must not starve another's inbound), not a bug.

## 5. Campaign status

Only `status = 'running'` campaigns are dispatched. Lifecycle
(`apps/api/campaigns/service.py`, `apps/api/campaigns/routes.py`):
`draft` / `scheduled` → `running` (launch) → `paused` (pause; resume goes back to
`running`) → `completed` (auto, when nothing is left `pending` or `dialing`).

```sql
SELECT id, status, launched_at, concurrency, updated_at
FROM campaigns WHERE id = :campaign_id;
```

- Still `draft`? Launch never succeeded — `launch_campaign` raises
  `campaign_launch_blocked` listing named blockers (`launch_blockers` in
  `apps/api/campaigns/service.py`): `status`, `agent_not_live`, `disclosure_missing`,
  `dlt_template_missing`, `dlt_template_not_approved`, `dlt_template_mismatch`,
  `number_missing`, `number_series_mismatch`, `no_contacts`. The client sees these on
  the launch button; fix the named item (e.g. `set_template_status` recording the
  registrar's approval is an audited admin action). That list is the CAMPAIGN's own
  paperwork; `launch_blockers` also carries the tenant-level refusals — `kyc_missing` /
  `kyc_not_verified`, `first_campaign_review_pending` / `_rejected` (step 6),
  `spend_cap` and `no_credits` — which are properties of the ACCOUNT and are worked in
  `calls-stopped.md`. `GET /v1/campaigns/{id}/launch-check` returns all of them by name,
  exhaustively, rather than one at a time.
- `paused`? Someone paused it. Resume is the client's button (CAS `paused → running`) —
  and note it is a bare CAS with no gate, which is why step 6 exists.
- `completed` with contacts uncalled? Check for `dnc_blocked`/`failed` rows in step 7 —
  completion only requires zero `pending` + `dialing`.

## 6. The standing gate — a `running` campaign refused on every tick

This is the step people skip, and it is the one that explains a campaign that says
`running`, shows no progress, and produces a tick line where **everything is zero**.

Before claiming a single contact, the tick asks `dispatch_blockers`
(`apps/api/campaigns/service.py`) once per campaign inside the claiming transaction. If
anything comes back it records `record_compliance_block(rule=...)` per rule, logs
`campaign_dispatch_blocked`, and returns `{"dialled": 0, "blocked": 0, "exhausted": 0}` —
so `blocked=` in step 2's string stays **0** even though the campaign was blocked. The
only signals are:

- the WARNING log line `campaign_dispatch_blocked`, carrying `campaign_id` and a
  comma-separated `rules` list (ids and rule names only — never a number, never client
  wording); and
- the `compliance_blocks` metric, labelled by rule.

If a client's campaign is `running` and quiet and the tick reports zeros, look for that
log line **before** looking at contacts.

The rules it carries are the standing subset of the launch check — the paperwork a
registrar can withdraw while a campaign runs — **plus the first-campaign hold**, which is
the only tenant-level rule in it:

| rule | What it means | Who clears it |
|---|---|---|
| `first_campaign_review_pending` | No human at Calevate has released this self-serve account for campaign calling yet (BRD §245's R-11 control) | ops only |
| `first_campaign_review_rejected` | A reviewer looked and refused; the client is shown the reviewer's own note | ops, after the client fixes what the note names |

**Why it is asked here and not only at launch.** `resume` moves a campaign from `paused`
back to `running` with a bare CAS and no gate, and a release is **withdrawable** — a list
turns out to be bought, complaints arrive. A campaign that kept dialling to the end of its
list after we revoked the account's clearance is the exact failure this gate exists to
prevent, so the answer can change mid-campaign and the tick asks every time.

**Two properties that decide who you can unblock:** it is a property of the ACCOUNT, not
of a campaign (launching another or deleting the reviewed one changes nothing), and it
covers `self_serve` and `trial` only (`SELF_SERVE_TIERS`) — a managed client is never held
by it. It is deliberately NOT in `check_dispatch`, so the "call this lead" button and the
instant-lead callback still work for a held account; that residual is stated in
`apps/api/compliance/first_campaign.py`, and widening the gate is not how it closes.

**Find every held account at once**, which is the discovery step this runbook used to
lack:

```
GET /v1/admin/compliance/holds        # admin realm, org:read
→ [{"tenant_id": "...", "slug": "...", "plan_tier": "trial",
    "signed_up_at": "...", "holds": ["first_campaign_review_pending"]}]
```

`apps/api/admin/holds_routes.py` — oldest signup first, read-only, no audit row (every
decision taken from it writes its own). The release is
`POST /v1/admin/tenants/{tenant_id}/first-campaign-review` with a `decision` and a
required `note`, admin realm, `admin:tenants`, audited as
`first_campaign_review.decided`. `calls-stopped.md` §4 has the full procedure, the
client-facing view (`GET /v1/compliance/first-campaign-review`) and what the note must
contain; do not duplicate it here.

## 7. Contact states

Contact statuses (`apps/api/campaigns/service.py`, `apps/workers/campaign_dispatch.py`):
`pending` → `dialing` (CAS claim, attempts+1) → `connected` (call completed) /
back to `pending` with `next_attempt_at` (no-answer/busy/failed, retry ladder) /
`failed` (ladder exhausted) / `dnc_blocked` (terminal — launch scrub or per-dial DNC hit).

```sql
SELECT status, count(*),
       count(*) FILTER (WHERE next_attempt_at > now()) AS waiting_on_backoff
FROM campaign_contacts
WHERE campaign_id = :campaign_id
GROUP BY status;
```

Example (ids and counts only — never select `phone_e164`):

```
   status    | count | waiting_on_backoff
-------------+-------+--------------------
 pending     |   140 |                140
 dialing     |     3 |                  0
 connected   |    41 |                  0
 dnc_blocked |    16 |                  0
```

Interpretation:

- All `pending` with `waiting_on_backoff` = count → nothing is DUE. The claim query
  only takes `pending` rows with `next_attempt_at IS NULL OR next_attempt_at <= now()`.
  Backoff comes from the retry ladder (`retry_policy`, default
  `{"max_attempts": 3, "backoff_minutes": [30, 120]}` —
  `DEFAULT_RETRY_POLICY` in `apps/api/campaigns/service.py`) or from a non-terminal
  gate block (+30 minutes, step 8). Wait it out.
- Rows stuck in `dialing` → the reaper (`_reap_stuck_dialing`,
  `apps/workers/campaign_dispatch.py`) runs at the start of every per-campaign dispatch
  and returns any `dialing` row with `last_attempt_at` older than 30 minutes to
  `pending` (with a further 30-minute `next_attempt_at`). A `dialing` row younger than
  30 minutes is normal: it stays `dialing` until the post-call pipeline calls
  `resolve_campaign_contact` with the call outcome — `completed` → `connected`,
  anything else (no_answer, busy, failed) → the retry ladder, exhausting into `failed`.
  `dialing` rows older than 30 minutes that the reaper is NOT clearing means the tick
  isn't reaching this campaign at all — go back to steps 2–4.
- Rows resolved by call:

  ```sql
  SELECT cc.id, cc.status, cc.attempts, cc.last_call_id, ca.status AS call_status
  FROM campaign_contacts cc
  LEFT JOIN calls ca ON ca.id = cc.last_call_id
  WHERE cc.campaign_id = :campaign_id AND cc.status = 'dialing'
  ORDER BY cc.last_attempt_at
  LIMIT 20;
  ```

## 8. Per-dial compliance gate

Every claimed contact passes `check_dispatch` (`apps/api/compliance/service.py`) at dial
time — the launch scrub was UX, this is the law (hard rule 5). A blocked dial increments
the tick's `blocked=` count and the `compliance_blocks` metric (labelled by rule). The
real rule names:

| rule | Effect on the contact |
|---|---|
| `big_red_switch` | back to step 1 |
| `agent_missing` | non-terminal: `pending`, `next_attempt_at` +30 min, attempt refunded |
| `disclosure_missing` | non-terminal (but fix is on the agent — it may not dial at all) |
| `agent_not_live` | non-terminal — agent must be published |
| `agent_inbound_only` | non-terminal — wrong agent wired to the campaign |
| `spend_cap` | non-terminal — tenant hit their monthly cap (`spend_state.capped`) |
| `no_credits` | non-terminal — self_serve/trial wallet empty (D-34) |
| `calling_hours` | non-terminal — outside 09:00–21:00 IST (`DEFAULT_WINDOW`) |
| `dnc` | TERMINAL: contact set to `dnc_blocked` |

Only `dnc` is terminal in the dispatcher; every other block returns the contact to
`pending` with `next_attempt_at = now() + 30 minutes` and the attempt decremented
(`apps/workers/campaign_dispatch.py`). So "campaign blocked on spend cap" looks like
step 7's all-waiting-on-backoff picture, repeating every 30 minutes — check
`spend_state`, credits, and the clock before suspecting the dispatcher.

DNC membership check (existence only — do not select the number):

```sql
SELECT count(*) FROM campaign_contacts
WHERE campaign_id = :campaign_id AND status = 'dnc_blocked';
```

## What NOT to do

- **Never `UPDATE campaign_contacts` by hand to force dials** — not to `pending`, not
  clearing `next_attempt_at`, not un-blocking `dnc_blocked`. The states are the CAS
  contract between dispatcher, reaper and post-call pipeline; hand edits double-dial or
  dial DNC'd numbers (a TRAI violation, not an incident metric).
- **Never release an account by writing `first_campaign_reviews` directly.** The row is
  the state; the *decision* is the `audit_log` entry the route writes, plus the note
  saying what was read. A hand-written INSERT produces an account released by nobody,
  for no recorded reason — which is the finding, not the fix.
- **Never touch the compliance gate.** No bypass exists by design
  (`apps/api/compliance/service.py` — "no bypass flag, not even for testing") and one
  must not be introduced during an incident. If the gate blocks, the block is the fix
  working.
- Never flip `platform_state` or campaign `status` with raw SQL — use the audited
  endpoints/buttons so the CAS and audit trail hold.
- Never select `phone_e164`, transcript text, or extraction payloads while
  investigating (hard rule 6).
