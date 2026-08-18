# Runbook — "You called someone who asked you not to"

Symptom: a consumer complains they were called after opting out; a client forwards a
complaint; or a TRAI/DLT escalation arrives naming a number and a date.

This is the runbook where the answer is a **timeline**, not a fix. The first job is to
establish what the system knew and when — because the difference between "the
suppression was recorded and we dialled anyway" (a defect, and a serious one) and "the
suppression was never recorded" (a process gap at the client) decides everything that
follows.

Ground rules before any SQL: production access goes through the audited admin path —
distinct role, always-audited queries (SECURITY-COMPLIANCE.md §"Admin access path").
Read-only SELECTs. **The complainant's number is the one piece of data this whole
investigation is about, so it is the one thing that must not end up pasted into a
ticket, a Slack thread or a terminal you screenshot** (hard rule 6). Hold it in a shell
variable, select ids and timestamps, and quote the last two digits if you must refer to
it in writing.

```sh
# Set once, in a shell whose history you will not paste. E.164, as we store it.
PHONE='+919876500000'
```

## 1. Is the number suppressed NOW?

```sql
SELECT id, tenant_id, scope, source, added_at
FROM dnc_list
WHERE phone_e164 = :phone;
```

- **A row with `scope = 'global'`** (`tenant_id IS NULL`) — suppressed PLATFORM-WIDE.
  Every tenant is blocked; no tenant can add or remove one. It is written only by
  operations, through `POST /v1/ops/dnc/global` (§6 below), and it means "Calevate does
  not dial this number for anybody" — a regulator/TSP instruction naming the number, or
  our own permanent refusal. It is **not** the national customer preference register:
  that is a per-campaign scrub run on an access provider's DLT platform, recorded in
  `preference_scrub_runs` (SEC-COMP §3), and a number it blocked shows up as a
  `dnc_blocked` campaign contact, not as a row here.
- **A row with `scope = 'tenant'`** — that tenant only. `source` is the answer to "who
  put it there": `call_optout` (the caller asked during a call), `customer_request`
  (they told the client, who added it), `manual` (someone typed it in), `regulator`.

`call_optout` rows are written by the system, not by a person (D-56): either the agent's
in-call tool fired, or the post-call transcript pass matched the caller's words. Both
leave the SAME evidence, and it is the thing to quote in a reply —

```sql
SELECT captured_at, call_id, evidence
FROM consent_ledger
WHERE tenant_id = :tenant_id AND phone_e164 = :phone
  AND purpose = 'marketing' AND status = 'withdrawn'
ORDER BY captured_at DESC;
```

`evidence->>'detected_by'` is `in_call_tool` or `post_call_transcript`,
`evidence->>'rule'` names the phrase rule that matched, and `evidence->>'matched'` is the
caller's own words. The row is append-only (hard rule 4), so it cannot have been edited
after the fact — which is the point of quoting it.
- **No row** — the number is not suppressed. Skip to §4; this is a "never recorded"
  case, not a "recorded and ignored" case.

`added_at` is the time that matters for the rest of this runbook. Everything below asks:
did a dial happen *after* it?

## 2. Did we call after the suppression was recorded?

The gate (`check_dispatch` in `apps/api/compliance/service.py`) reads `dnc_list` **live
on every dispatch** — there is no cache to be stale, which is why hard rule 5 says
additions propagate before the next tick. So a dial after `added_at` is a real defect,
not a timing artefact.

```sql
SELECT c.id, c.direction, c.status, c.started_at, c.ended_at, c.agent_id
FROM calls c
WHERE c.tenant_id = :tenant_id
  AND (c.to_e164 = :phone OR c.from_e164 = :phone)
ORDER BY c.started_at DESC
LIMIT 20;
```

Compare `started_at` against `added_at` from §1.

- **All dials BEFORE `added_at`** → the system behaved correctly. The complaint is about
  calls that predate the opt-out. Go to §3 to confirm nothing is queued, then answer
  with the timeline.
- **Any dial AFTER `added_at`** → **stop and escalate.** This is a hard-rule-5 breach.
  Pull the campaign or lead source that produced it (§3), pause it, and page the
  engineer on call. Do not "just remove the campaign" — preserve the state that shows
  how it happened.
- **`direction = 'inbound'`** → they called US. An inbound call to a suppressed number
  is not a violation; the DNC list governs outbound dialling.

## 3. Stop anything still queued for that number

A suppression blocks the *next* dispatch decision, so nothing already-decided should be
in flight — but confirm rather than assume, and confirm before you reply to anyone.

```sql
-- Campaign contacts still pending or mid-dial for this number
SELECT cc.id, cc.campaign_id, cc.status, cc.attempts, cc.next_attempt_at
FROM campaign_contacts cc
WHERE cc.phone_e164 = :phone
  AND cc.status IN ('pending', 'dialing');
```

Any row here will still pass through the per-dial gate before a call is placed, so a
suppressed number is refused at the moment of dialling even while the row sits pending.
That is by design (defence in depth) — but if the client wants the contact gone from the
campaign entirely, that is a product action through the console, not a DELETE here.

If a **campaign** is implicated, pause it from the console
(`POST /v1/campaigns/{id}/pause`) rather than editing rows. If **every** tenant needs to
stop while you investigate, that is the big red switch — see `campaign-stall.md` §1 for
the audited path.

## 4. Record the suppression, if it is not already recorded

If §1 found no row, the number must be suppressed now, before any reply goes out.

The client does this themselves in the console (Do-not-call → add numbers), which is the
right path: it is their list, their `leads:dispatch` authority, and it produces an audit
row naming who added it. Use `source = customer_request` for "the consumer told the
business", `regulator` for a complaint arriving through a regulator.

```
POST /v1/dnc
{"numbers": ["<the number>"], "source": "customer_request"}
```

The response is counts only — `added` / `already_suppressed` / `malformed` — deliberately,
so the endpoint never echoes a suppression list back into a log or a screenshot. `added:
0, already_suppressed: 1` means it was already covered (possibly by a global entry).

Verify without printing the list:

```
POST /v1/dnc/check
{"phone": "<the number>"}
→ {"valid": true, "suppressed": true, "scope": "tenant"}
```

`scope: "global"` in that response means it was *already* nationally suppressed, which
changes the story in §5 — a call after that is a breach regardless of what the tenant
did.

## 5. Reconstruct the timeline for the reply

Everything that touched the suppression is in `audit_log` (INSERT-only, hash-chained):

```sql
SELECT at, action, actor_type, actor_id, object_id
FROM audit_log
WHERE tenant_id = :tenant_id
  AND action IN ('dnc.added', 'dnc.removed', 'campaign.launched',
                 'compliance.call_optout_recorded')
ORDER BY at DESC
LIMIT 50;
```

`dnc.added` rows carry counts and the source in the log stream (keyed by entry id), never
the number — so this query is safe to run and safe to quote from.

**`dnc.removed` is the row to look for hardest.** A removal is only possible for
`source = 'manual'` entries — the API refuses to delete anything recording a consumer's
opt-out (`dnc_consumer_optout`) and refuses global entries (`dnc_global_entry`). So a
`dnc.removed` followed by a dial means someone deleted a hand-added suppression and then
called. That is a legitimate action with a legitimate audit trail, and it is exactly what
a regulator will ask about. `object_id` is the entry id; `actor_id` is who.

The reply should state, in this order: when the suppression was recorded, by whom, what
calls exist before it, and that no call exists after it. If a call DOES exist after it,
say so — the audit chain makes the truth discoverable anyway, and a wrong answer given
early is the thing that turns a complaint into a penalty.

## 6. Suppressing a number for EVERY client

Use this when the instruction is not one client's — a regulator, a TSP or the DLT
registrar names a number, or we decide this platform will never call it again. It is an
ops action: no client can create or remove a global entry, and a client who tries is
refused by name (`dnc_global_entry`).

**Console: Operations → Global do-not-call (`/admin/ops/dnc`).** Paste the numbers, pick
the source, write the reason, type SUPPRESS. The screen shows the whole list masked, and
lifting one takes its own typed confirmation naming that row. Use it rather than the
requests below: it sends the confirmation headers for you, states the blast radius before
the click, and is the same audited path.

The requests are the fallback for a console that will not load, and nothing else:

```
POST /v1/ops/dnc/global
X-Confirm-Action: suppress_number_platform_wide
{"numbers": ["<the number>"], "source": "regulator",
 "reason": "TRAI escalation <ticket>"}
```

`source` is `regulator` (an instruction from outside) or `platform_block` (our own
decision). The `reason` is not a column — it travels into the audit log stream, and it
is what answers "on whose instruction" a year later, so write the ticket reference.
The response is counts only.

Lifting one is the mirror, and it needs its own confirmation — a different verb from the
suppression, and **carrying the id of the row being released**, so that neither a header
captured for a suppression nor one captured for a different row can lift this one. Retype
the suffix for every entry; a curl re-run with a new `{entry_id}` and the old header is
refused:

```
DELETE /v1/ops/dnc/global/{entry_id}
X-Confirm-Action: release_number_platform_wide:{entry_id}
```

`GET /v1/ops/dnc/global` lists them, masked. Both writes land an `audit_log` entry
(`ops.dnc_global_added` / `ops.dnc_global_removed`) naming the operator, never the
number.

**Lifting one is the direction to be slow about.** It re-permits dialling somebody who
asked not to be dialled, for every client, from the next dispatch tick — and the audit
log will show that we chose to. Do it only when the instruction behind the entry has been
withdrawn, and say so in the ticket.

## 7. If the suppression was recorded and we dialled anyway

Treat as an incident.

1. Pause the implicated campaign; if more than one tenant is affected, halt outbound
   globally (`campaign-stall.md` §1).
2. Capture, before anything is changed: the `dnc_list` row, the `calls` rows, the
   `campaign_contacts` row, and the `audit_log` slice from §5.
3. The gate reads live, so the failure is NOT "a stale cache". The candidates are: a
   dial path that does not call `check_dispatch` at all, a normalization mismatch (the
   list holds `+919876500000` and the dial used `9876500000` — compare the exact strings,
   they must both be E.164 per `normalize_phone`), or a suppression added under a
   different tenant than the one that dialled.
4. Whichever it is, the fix ships with a test that fails on the old code. Hard rule 5
   permits no bypass — including a temporary one to unblock a client.

## 8. Recording a national DND (NCPR) scrub of a campaign's list

Symptom: a client's PROMOTIONAL campaign is refused at launch or mid-dispatch with
`national_dnd_scrub_missing`, `national_dnd_scrub_expired` or
`national_dnd_scrub_incomplete`. This is the one procedure in this file that has **no
console screen and deliberately will not get one** — see the decision log — because the
work happens on somebody else's platform and only the last step is ours.

**Before anything: is this even possible today?** Running a scrub needs a login to an
access provider's DLT platform, which comes with the Registered Telemarketer registration
Calevate is still obtaining (R-01, `platform_state.tm_registration_status`). Until that is
`active`, EVERY tenant's campaign is already refused with `tm_registration_missing` and
there is nothing true to record here. Check the ops console first; if the platform is not
a live registered telemarketer, this runbook is not the answer to the client's problem
and recording a scrub anyway would be evidence of something that did not happen.

1. **Get the list.** The numbers to submit are the campaign's pending contacts. Read-only,
   through the audited admin path, and the output is a file you do not paste anywhere:

   ```sql
   SELECT phone_e164 FROM campaign_contacts
   WHERE campaign_id = :campaign_id AND status = 'pending';
   ```

2. **Submit it to the access provider's scrub facility** and keep what comes back: a
   reference number, a report of COUNTS (never the numbers), the blocked list, and the
   timestamp of the run. The verdict is valid until **23:59:59 IST of the day it was
   produced** — a scrub run this morning does not cover tomorrow's dialling, which is why
   the gate is on the dispatch tick as well as on launch.

3. **Record it against the campaign it covers.** `admin:tenants`, step-up confirmed, and
   the confirmation is bound to the campaign id so a header captured for one campaign
   cannot green-light another:

   ```
   POST /v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub
   X-Confirm-Action: record_preference_scrub:{campaign_id}
   {"provider": "airtel", "scrub_ref": "<the reference>",
    "scrubbed_at": "2026-08-15T11:30:00+05:30",
    "blocked_numbers": ["<numbers the register suppressed>"]}
   ```

   - `blocked_numbers` is the list the register **suppressed** — the ones to take OUT.
     The portal hands back two files and pasting the survivors here would suppress
     everybody the scrub cleared. Up to 5,000 per recording.
   - `scrubbed_at` must carry an offset. The window ends at a specific IST midnight and a
     bare local string leaves the server guessing which one — a whole day of dialling.
   - There is no `submitted_count` field: how many contacts were pending is read from the
     campaign rather than typed, so it cannot be mistyped.
   - Re-sending the same `(campaign, provider, scrub_ref)` is idempotent, so a retry after
     a timeout is safe.

4. **Check the answer, not the HTTP status.** The response carries `is_current`, which is
   the same predicate the launch gate reads. `recorded: false` with `is_current: true`
   means this run was already recorded. `is_current: false` means the run you recorded is
   a legitimate historical record that does not satisfy the gate — usually a run whose day
   has ended — and the campaign is still refused.

**What is NOT this.** A number the register blocked shows up as a `dnc_blocked` campaign
contact, not as a `dnc_list` row: NCPR preference is category-scoped and per list, so
loading it into `dnc_list` would refuse lawful transactional traffic to the same person.
§6 above is the different thing — an absolute platform-wide suppression naming one number.

## 9. `campaign_complaint_spike` — a campaign is generating opt-outs

You were paged with `campaign_complaint_spike`, and **the campaign is already paused.**
It stopped itself: five or more of its connected calls in the last 24 hours ended in an
opt-out, and that was at least 10% of them (`apps/api/campaigns/complaint_spike.py`
argues all three numbers). This is FLOWS §5's mid-campaign safety doing what it exists
for; nothing further is dialling on that campaign.

**Read the counts as a leading indicator, not as complaints.** What was measured is
people who told the agent to stop — every one of them is a `consent_ledger` withdrawal and
a `dnc_list` row, and all of them are already suppressed. A TRAI complaint is filed with an
access provider and arrives, if it ever does, days later as a letter. The reason five is
the trigger is that **five unique complaints inside ten days obliges the TSP to suspend the
client's outgoing service** (TCCCPR Second Amendment, in force 12 February 2025). Anyone who
files is in the population we just counted. This is the last cheap moment.

### 9.1 Confirm what was measured

```sql
SET LOCAL app.tenant_id = '<tenant-uuid>';
SELECT count(*) AS connected,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM consent_ledger cl
         WHERE cl.call_id = c.id AND cl.status = 'withdrawn' AND cl.purpose = 'marketing'
       )) AS optouts
FROM calls c
WHERE c.campaign_id = '<campaign-uuid>' AND c.status = 'completed'
  AND coalesce(c.started_at, c.created_at) >= now() - interval '24 hours';
```

Then read WHY people opted out. `consent_ledger.evidence` carries the detector, the rule
and the matched words — that is the fastest way to tell "the list is wrong" from "the
script is wrong":

- **Everyone says they never signed up** → the list. Ask the client for the consent
  artefact behind `campaigns.consent_source`; §6 of this file is where a number gets a
  platform-wide suppression if a regulator is already involved.
- **People know the client but object to the call** → the script, the hour, or the
  frequency. Check `campaigns.calling_hours` and the retry policy.

### 9.2 Decide with the client, then act

The pause is ours; resuming is theirs to ask for and yours to allow. Three outcomes:

1. **The list is bad.** Cancel the campaign. Do not resume it — the remaining contacts are
   from the same list. A new campaign against a scrubbed list is a new `campaign_id` with
   no history, which is the honest way to start again.
2. **The script or the hour is bad.** Fix it, then resume. **Resuming while the 24-hour
   window still holds the spike will re-pause the campaign on the next tick**, and that is
   deliberate: nothing about the campaign changed in the ten minutes after somebody pressed
   resume. Wait the window out, or cancel and relaunch.
3. **It is a false alarm** — a tiny campaign where five people out of thirty genuinely had
   nothing to do with each other. Rare, and still worth one look at the list before
   resuming.

### 9.3 What NOT to do

- **Do not unblock the numbers.** Every opt-out counted here is already suppressed and
  every suppression is a person's instruction. Removing one to "clean up the metric" is
  the one action in this file that is unlawful.
- **Do not raise the threshold to stop the alarm.** It is derived from the number that
  suspends the client's service; moving it moves the alarm past the event it exists to
  precede.
- **Do not resume and watch.** The next tick re-evaluates, so "watching" means dialling.
