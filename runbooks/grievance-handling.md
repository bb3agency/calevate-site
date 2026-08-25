# Runbook — handling a grievance / data-principal request

Symptom: someone has complained, or exercised a right, through the grievance channel —
a client, a caller whose data a client processes, or a member of the public. The
published documents (`/legal/grievance`, `/legal/privacy` §14) promise a named person and
fixed clocks; this runbook is the procedure behind that promise.

**Why a runbook and not a `grievances` table.** For a sole proprietor operating one
mailbox, the correct control is a written procedure plus a dated record, not a database
feature — the same "one operator, mailbox is sufficient" reading the playbook takes
(`docs/legal/LEGAL-OPS-PLAYBOOK.md` §13, §16-A4; LEGAL-SURFACE DP-8/S-2). A `grievances`
table with a ticket store and an SLA clock is unwarranted infrastructure at this size and
would be a half-wired feature (a clock nobody watches). If volume ever makes a mailbox
untenable, that is when a table earns its migration — and this runbook says so rather than
implying the product already does it. Until then, **`/legal/grievance` §6 must not imply an
automated record system**; it describes this manual procedure.

## 0. The clocks, and what starts them

All run from when the request is **received** in the grievance mailbox.

| What | Deadline | Where it comes from |
|---|---|---|
| Acknowledge the complaint | **2 business days** | `/legal/grievance` §2; Consumer Protection (E-Commerce) Rules 2020, rule 4(6) (48h ack) |
| Resolve a grievance | **15–30 days** | `/legal/grievance` §2; SPDI Rule 5(9) (one month); DPDP Rules 2025 rule 14(3) (≤90 days, published timeline) |
| Answer a data-principal rights request (access / correction / erasure / withdrawal) | within the resolution window above; **erasure** runs the product path in §3 | DPDP §11–§13 |

If a request is both a grievance and a rights request, run both tracks; the shorter clock
governs the acknowledgement.

## 1. Who answers

The **Grievance Officer** named on `/legal/grievance` §1 (`{{GRIEVANCE_OFFICER_NAME}}`)
and the **data-protection contact** on `/legal/privacy` §14
(`{{DATA_PROTECTION_CONTACT_EMAIL}}`). For a sole proprietor these may be the same person
(the founder) — but the name must be **filled in and real**, not a placeholder, before any
`/legal/*` page is shown to a client, a regulator or a payment gateway (LEGAL-SURFACE S-2;
this is the cheapest unmet statutory obligation, `docs/legal/LAUNCH-CHECKLIST.md` A4). Rule
9 of the DPDP Rules also requires the contact be repeated **in every reply** — do it.

## 2. The procedure

1. **Log it, dated.** Record the request in the grievance log — a dated entry per request:
   received-at, from (masked: never store a caller's raw number in the log — hard rule 6;
   use the same `subject_ref` hash the erasure path uses if you need to correlate),
   category, and the clock it starts. A dated folder or an append-only notes file is
   sufficient; do **not** paste transcript text or phone numbers into it.
2. **Acknowledge within 2 business days**, from the Grievance Officer address, repeating
   the data-protection contact (Rule 9).
3. **Classify** — is it (a) a service complaint, (b) a data-principal rights request, or
   (c) a telecom/consent complaint (DND, a call they did not consent to)? Route:
   - (b) erasure → the product path, §3 below.
   - (b) access / correction / withdrawal → `apps/api/compliance/export.py` (access),
     the lead-edit path (correction of a lead), `apps/api/compliance/optout.py`
     (withdrawal); a transcript/recording is a record of an event and is not corrected
     (DP-6 — this is a founder+counsel decision recorded in ROADMAP, not a gap to code).
   - (c) → `runbooks/dnc-complaint.md`.
   - **The rights request is usually the CLIENT's to answer, not ours** — for caller data
     the client is the Data Fiduciary and we are their Processor (LEGAL-SURFACE §1). Our
     job is to give the client the mechanism and, where they ask us to act on their
     instruction, to act. Say so in the reply when the request should go to the client.
4. **Resolve within the window** and record the outcome in the same dated log.
5. **If it is also a breach**, stop and use `runbooks/data-breach-notification.md` — those
   clocks (some as short as CERT-In's 6 hours) start from awareness and override this.

## 3. Erasure (the one track that is a product feature)

`POST /v1/compliance/deletion-requests` → transactional outbox → the worker locates by
phone across calls, turns, extractions, leads, recordings, engine payloads and searches
the knowledge base, writes the proof JSON, and returns a certificate. See
`runbooks/processor-erasure.md` and `apps/api/compliance/deletion.py`. The certificate
enumerates its own limits (e.g. an under-floor recording deferred to its lawful
`erase_after`, and engine-side deletion reported as pending the vendor commitment). Attach
the certificate to the grievance-log entry.

## 4. What is still external

- A **person must be appointed** as Grievance Officer and data-protection contact, and the
  `{{GRIEVANCE_OFFICER_*}}` / `{{DATA_PROTECTION_CONTACT_*}}` tokens filled in
  (`apps/web/src/lib/legal/placeholders.ts`). Until then the published pages carry a
  placeholder, which is not a designation.
- The published **resolution timeline** on `/legal/grievance` §2 is a commitment; counsel
  should confirm 15–30 days sits within Rule 14(3)'s ≤90-day ceiling for your categories
  (it does, comfortably) before the review banner is lifted.
