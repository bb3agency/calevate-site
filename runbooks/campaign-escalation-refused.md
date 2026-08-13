# Runbook — the campaign follow-up message never goes out

Symptom: a client asks why the WhatsApp follow-up promised for contacts who never
answered has not been sent; or the alert `campaign_escalation_rejected` /
`campaign_escalation_exhausted` fires; or the lead timeline shows a follow-up row with
`delivered: false`.

`escalate_campaign_contact` (`apps/workers/whatsapp.py`) is queued through the outbox the
moment a contact's dial ladder is spent, once per contact, and it **records every
non-delivery on the lead timeline whatever the reason.** So the answer is always visible
— the job never fails silently. What this runbook does is tell you which refusal you
have, and whether it is one a human is supposed to close.

The first question is not "why did it fail" but **"is this a refusal that pages, or one
that deliberately does not?"** The code draws that line itself
(`_is_operational`, `_OPERATIONAL_REFUSALS`) and this runbook is organised around it.

Ground rules: audited admin path for any production SQL (SECURITY-COMPLIANCE.md
§"Admin access path"); read-only; ids, statuses and reason codes only. The escalation's
recipient is a consumer, so their number must not reach a ticket, a log or a screenshot
(hard rule 6) — the payload rows below carry `contact_id` and `reason`, never a number,
by design.

---

## 1. Read the refusal off the lead timeline

One row per (lead, contact), updated in place as the retry ladder walks
(`_record_escalation_attempt`). Everything you need is in the jsonb.

```sql
SELECT le.lead_id,
       le.payload ->> 'campaign_id' AS campaign_id,
       le.payload ->> 'contact_id'  AS contact_id,
       le.payload ->> 'delivered'   AS delivered,
       le.payload ->> 'status'      AS send_status,
       le.payload ->> 'reason'      AS reason,
       le.payload ->> 'attempts'    AS attempts,
       le.updated_at
FROM lead_events le
WHERE le.type = 'notification'
  AND le.payload ->> 'channel' = 'whatsapp'
  AND le.payload ->> 'kind'    = 'campaign_escalation'
ORDER BY le.updated_at DESC
LIMIT 50;
```

`kind = 'campaign_escalation'` is not optional in that predicate. The hot-lead WhatsApp
alert writes `channel = 'whatsapp'` on the same lead with no `kind`, and without the
discriminator a delivered hot-lead alert and an un-sent follow-up answer for each other.

`send_status` is one of `delivered`, `transport_failed`, `rejected` (`SendStatus`).
`reason` is an authored code — never vendor prose, deliberately, because a provider
error string is untrusted text that may quote the payload we just sent it.

The job's own return string says the same thing: `sent`, `duplicate`, `not_exhausted`,
`contact_missing`, `no_lead`, `rejected <reason>`, `exhausted after N`.

## 2. The refusals that DO page a human

`_OPERATIONAL_REFUSALS` — a reason starting with any of `no_provider_configured`,
`provider_not_implemented`, `template_`, `dev_sink_`. These fire
`alert("WORKER_TERMINAL", "campaign_escalation_rejected")` with the tenant and contact
ids, because only a person can close them and **every exhausted contact keeps going
un-followed-up until they do.**

| reason | What it means | Fix |
|---|---|---|
| `no_provider_configured` | `whatsapp_enabled` is on but `WHATSAPP_PROVIDER` is unset, outside `local` | Either finish the BSP decision and set the provider, or turn `WHATSAPP_ENABLED` off — a channel that is on and cannot send is the worst of the three states |
| `provider_not_implemented:<name>` | `WHATSAPP_PROVIDER` names something with no adapter behind it | The name in the reason is OUR config, not vendor text. There is exactly one implemented value (`console`, and only when `APP_ENV=local`). Setting `WHATSAPP_PROVIDER=gupshup` today fails loudly **on purpose** |
| `dev_sink_refused_outside_local` | `WHATSAPP_PROVIDER=console` on staging or prod | Config error, and the dangerous kind: the console sink reports DELIVERED forever. Clear the setting |
| `template_*` | The provider rejected the template | No BSP adapter exists yet, so nothing in the tree can currently produce this. When one lands, this is the branch that means the approved template drifted from `TEMPLATE_MISSED_CALL` (`calevate_missed_call_follow_up_v1`) |

`exhausted after N` is the other pageable outcome
(`alert("WORKER_DELIVERY", "campaign_escalation_exhausted")`): the transport was reached,
kept failing, and the ladder (`WORKER_MAX_TRIES` = 3, deferring 15s then 45s) ran out.
That is a provider or network problem, not a policy one.

Two more that page and are neither: `campaign_escalation_unrecordable` (return `no_lead`)
means a contact exhausted with no lead to record the follow-up against — reachable only
when every dial was refused by the ENGINE, so no call row was ever written and the
post-call pipeline never upserted a lead. Investigate the dials, not the messaging.

## 3. The refusals that deliberately do NOT page

These are logged at INFO as `campaign_escalation_refused` with `contact_id` and `reason`,
counted, recorded on the timeline, and **never alerted** — paging once per exhausted
contact for the system working as designed trains everyone to ignore the alert.

| reason | Meaning |
|---|---|
| `whatsapp_disabled` | `WHATSAPP_ENABLED=false` — the channel is off until a human finishes the switch-on checklist (WABA, business verification, an approved template, a chosen BSP) |
| `recipient_not_opted_in` | No current messaging consent for this person. §4 |
| `blocked_dnc` | The number is suppressed. Correct, and the whole point: a person who asked not to be contacted and then did not answer the phone is the last person a follow-up may reach |
| `blocked_calling_hours` | Outside 09:00–21:00 IST |
| `blocked_big_red_switch` | Platform-wide outbound halt |
| `blocked_spend_cap` / `blocked_no_credits` / `blocked_agent_*` | The dispatch gate's other rules |

Every `blocked_*` reason is `check_dispatch`'s own rule name with a prefix
(`_send_escalation`). A WhatsApp follow-up is outbound commercial contact with a
subscriber, so it passes the identical gate a dial passes — the live DNC read above all.
There is no messaging-shaped copy of those rules and no flag that skips them, and none
may be added.

**`whatsapp_disabled` is the answer to give a client today.** The feature ships off
(`whatsapp_enabled` defaults to False) and nothing in this repository chooses a WhatsApp
Business Solution Provider — ROADMAP §6 carries no D-entry for one. Tell the client the
follow-up channel is not live yet rather than opening an investigation.

## 4. `recipient_not_opted_in` — check which state the tree is in before you answer

This is the refusal that has meant two different things, and the reply to a client is
different in each. **Establish which state you are in first; do not answer from memory.**

```sh
# Does the ledger permit a messaging consent row at all?
grep -n "CONSENT_PURPOSES" apps/api/compliance/models.py
ls alembic/versions/ | grep c2f7a91b4e63
# Is there a surface that can capture one?
ls apps/api/compliance/consent.py apps/api/compliance/consent_routes.py 2>/dev/null
```

```sql
-- And has the database this deployment runs against actually applied it?
SELECT version_num FROM alembic_version;
SELECT conname FROM pg_constraint WHERE conname = 'ck_consent_ledger_messaging_names_its_source';
```

**State A — the purpose does not exist on this database.** The
`ck_consent_ledger_purpose_enum` CHECK permits only `recording`, `callback`, `marketing`.
The consent read still runs and still returns nothing (a CHECK constrains INSERTs, not
SELECTs), so **every contact of every tenant records `recipient_not_opted_in`** and no
follow-up has ever been sent or can be. Any attempt to capture one fails at the database.
That was the shipped state by design — a live read against the table the consent belongs
in rather than a hardcoded `False`, so the day the migration lands the feature starts
working without a code change. In this state the correct answer to "why did nobody get the
follow-up" is *the feature is not finished*, not *your customers declined*. If you see
this on a deployment while the working tree is at State B, the database is simply behind
head: run the migration.

**State B — the purpose exists and can be captured.** Migration `c2f7a91b4e63` widens
the CHECK to include `messaging`, adds `consent_ledger.consent_source` with a five-member
enum, and adds three more CHECKs that make an unevidenced grant unrepresentable.
`apps/api/compliance/consent.py` reads and writes it and
`POST /v1/compliance/messaging-consent` (`leads:dispatch`, audited) is how a row gets
there. In this state `recipient_not_opted_in` means what it says: **this specific person
has never affirmatively opted in to being messaged by this business, or their opt-in has
lapsed.** It is the default of the world, not a defect, and there was no backfill — by
design. Consent to be CALLED is not consent to be MESSAGED (DPDP §6 purpose limitation;
Meta requires an opt-in that names the business and states the person is opting in to
receive messages).

**As of this runbook's writing the tree is in State B**: the migration is head
(`c2f7a91b4e63`, revises `b1d5c8e73f04`), `CONSENT_PURPOSES` carries `messaging`, both
`apps/api/compliance/consent.py` and its route exist, and the worker asks the same
`read_messaging_consent` the client-facing surface does — one implementation of "may we
message this person", so the console and the follow-up cannot disagree. Re-run the checks
above rather than trusting this paragraph; it is the line here with the shortest shelf
life.

In State B, the diagnosis per contact is:

```
POST /v1/compliance/messaging-consent/lookup   (leads:read)
{"phone": "<the number the CLIENT already holds>"}
→ {"status": "none"|"granted"|"declined"|"withdrawn",
   "source": ..., "captured_at": ..., "expires_at": ..., "messageable": false}
```

POST, not GET, because the identifier IS the personal data — a number in a query string
lands in every access log between here and the client. The response never echoes it back.
Hold the number in a shell variable or let the client run this from their own console;
it must not reach the ticket, and nothing in the reply needs it to. Where you have to
name the subject in writing, use the hashed `subject_ref` the export and erasure paths
already share (`apps/api/compliance/export.py`). Read `messageable`, not `status`: an opt-in is current only if it is
`granted` AND inside `MESSAGING_CONSENT_VALIDITY_DAYS` (365), so
`status: "granted", messageable: false` means a lapsed opt-in and the remediation is to
re-ask, not to investigate.

What the client may do about it: capture opt-ins going forward, on a call
(`inbound_call_verbal`, which must name the `call_id`), on their own web or paper form,
or from an inbound WhatsApp message. What they may **not** do: have their staff record an
opt-in on a customer's behalf. `staff_recorded_request` is CHECK-barred from
`status = 'granted'` and the service refuses it with `consent_source_cannot_grant`.
Consent must be evidenced; a refusal must never be obstructed. That asymmetry is the
feature, and it must not be argued away for a client in a hurry.

## 5. Is anything even reaching the job?

If the timeline query in §1 returns nothing at all for a campaign whose contacts are
`failed`, the escalation was never enqueued.

```sql
-- One outbox row per contact, forever. The outbox is never deleted from, which is
-- what makes it the durable answer to "did a previous run already promise this?"
SELECT status, count(*)
FROM outbox_messages
WHERE job = 'escalate_campaign_contact'
GROUP BY status;
```

- **No rows** — `_record_failure` in `apps/workers/campaign_dispatch.py` never ran, which
  means no contact has actually exhausted its ladder. Check `campaign_contacts.status`:
  a contact is only escalated on the transition to `failed`.
- **`pending` piling up** — the outbox dispatcher or the workers are down. That is
  `webhook-delivery-failures.md` §3, same mechanism.
- **`failed`** — the outbox DLQ. Replay from the console (`/admin/ops` → "Dead-lettered
  outbox messages") or, if it is down, through `POST /v1/ops/outbox/replay` — never by
  hand.

One contact can reach "exhausted" more than once — `_reap_stuck_dialing` returns a
stranded contact to `pending` with its attempt count intact and no ceiling. The outbox
row is what stops that becoming a second message about one enquiry, which is exactly the
behaviour that gets a WABA reported. Do not delete an outbox row to "retry" a follow-up.

## What NOT to do

- **Never patch a refusal into a send.** There is no bypass on `check_dispatch` and none
  may be added for messaging; `blocked_dnc` on a follow-up is the live DNC read doing the
  one job it exists for.
- **Never record a messaging consent on a consumer's behalf** to unblock a client's
  campaign. The database refuses it, the service refuses it, and the reason both do is
  that a staff-asserted grant is "implied consent" wearing a different name.
- **Never UPDATE or DELETE a `consent_ledger` row** (hard rule 4). A withdrawal is a new
  row with `status = 'withdrawn'`; a correction is another row. The read takes the latest
  per (tenant, phone, purpose), so appending is how every change is made.
- **Never flip `delivered` on a `lead_events` row by hand** to close a ticket. That row is
  the client's answer to "was I told?", and a follow-up that never landed has to stay
  visible as one.
- **Never paste the recipient's number** into the ticket, the alert or the reply
  (hard rule 6). Every query here is keyed by `contact_id` and `lead_id` precisely so you
  do not have to.
