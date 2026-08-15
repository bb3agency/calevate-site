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

Lifting one is the mirror, and it needs its own confirmation so a header captured for a
suppression cannot release one:

```
DELETE /v1/ops/dnc/global/{entry_id}
X-Confirm-Action: release_number_platform_wide
```

`GET /v1/ops/dnc/global` lists them, masked. Both writes land an `audit_log` entry
(`ops.dnc_global_added` / `ops.dnc_global_removed`) naming the operator, never the
number.

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
