# Runbook — a personal data breach, and the notifications it starts

Symptom: personal data has been, or may have been, exposed to somebody who should not
have it. A leaked credential in a repository or a log; an object-storage prefix served
publicly; a database restored to the wrong host; a query result mailed to the wrong
client; a vendor telling us they were breached; a tenant seeing another tenant's rows.

**This is a runbook where the deliverable is a set of NOTICES with statutory deadlines on
them, and the deadlines start the moment somebody becomes aware — not when the
investigation finishes.** The contain-and-fix work is the other runbooks' (see
`calls-stopped.md` for the platform-wide levers and `database-restore.md` for a restore).
This one exists because `/legal/dpa` §7 promises every client a notification within **48
hours**, and until D-179 there was no template, no Board route and no procedure behind
that promise — a clock in a contract with nothing on the other side of it.

## 0. The three clocks, and what starts them

All three run from **AWARENESS** — the moment any Calevate person knows there has been a
breach of personal data. Not from the exposure, not from the ticket, not from the fix.

| Who | When | Whose duty | Where it comes from |
|---|---|---|---|
| The affected **client** | within **48 hours** | ours, contractual | `/legal/dpa` §7 |
| Each affected **Data Principal** | **without delay** | the **client's** for caller data; **ours** for client-account data | DPDP Rules 2025, Rule 7(1) |
| The **Data Protection Board** — first intimation | **without delay** | same split | Rule 7(2) |
| The **Board** — detailed report | within **72 hours** of awareness | same split | Rule 7(2) |

**The role split decides who sends what, and getting it backwards wastes the window.**
Calevate is the **Processor** for callers' personal data.
The client business is the **Data Fiduciary** for it (LEGAL-SURFACE §1).
So for anything touching calls, transcripts, recordings,
leads or campaign contacts, the Rule 7 duties are the CLIENT'S and ours is to tell them
fast enough and fully enough that they can discharge theirs. For client-ACCOUNT data —
`users`, `organizations.intake`, `kyc_records`, billing — Calevate is the Fiduciary and
the Board and data-principal duties are ours directly.

There is **no severity threshold and no minimum number of affected people** in Rule 7.
"Only one record" and "no evidence of access" are facts to state in the notice, not
reasons to skip it.

Sources and their retrieval dates are in `docs/LEGAL-SURFACE.md` §9; the rule's content
requirements are restated in `apps/api/compliance/breach.py`, which is where they are
enforced. **The gazette text is not reachable from our environment and counsel has not
reviewed any of this** — see §7.

## 1. First fifteen minutes

1. **Write down the awareness time**, in UTC with an offset, before anything else. Every
   deadline below is computed from it, and reconstructing it from Slack scrollback two
   days later is how a 72-hour report becomes a 78-hour one.
2. **Open an incident reference** (`CAL-BREACH-YYYYMMDD-n`). One string the client can
   quote back.
3. **Contain**, if containment is still possible: rotate the credential, remove the public
   grant, stop the job. The big red switch (`POST /v1/ops/outbound/halt`) stops outbound
   dialling and is the right lever if the exposure is being made worse by calls going out.
4. **Do not delete anything.** `audit_log` is a hash chain and `usage_events`,
   `consent_ledger` and the other append-only ledgers cannot be edited (hard rule 4) —
   that is the forensic record, and it is also what proves the scope you are about to
   state. Object-storage keys, `webhook_deliveries` rows and the admin access log are the
   rest of it.
5. **Tell the incident lead.** One person owns the notifications from here; see §4.

## 2. Establish the scope — WHOSE data, WHICH categories, HOW MANY

The notice needs categories and counts, and it needs them to be defensible rather than
precise. Approximate honestly ("approximately 4,000 call records across 3 tenants");
never round a number you have not counted, and never guess a category.

Read-only SELECTs through the audited admin path (SECURITY-COMPLIANCE §"Admin access
path"). **No phone number, transcript line or extraction payload goes into the ticket, the
notice, or a terminal you screenshot** (hard rule 6) — ids, categories and counts only.
`apps/api/compliance/breach.py` refuses to render a notice containing anything shaped like
a phone number, which is a backstop and not a substitute for not pasting one.

The inventory to walk is `docs/LEGAL-SURFACE.md` §2 — it lists every store of personal
data in the platform and where each one lives. The four that are outside Postgres, and are
therefore the ones most easily missed in a scope assessment:

- **recordings** — object storage, `recordings/…`;
- **delivered CRM bodies** (D-23) — `webhook-bodies/{tenant}/{lead|call}-{id}/…`;
- **archived raw engine payloads** (D-126) — `engine-payloads/{tenant}/{call}/…`, which
  carry the caller's number AND the transcript;
- **knowledge-base content** — the client's own uploads, which can name their staff.

If the exposure is a database one, `apps/api/db/registry.py` names every tenant-scoped
table; if it is an object-storage one, the four prefixes above are the whole of it.

## 3. Write the facts down once

Everything the three notices need is one JSON file, and the file is the artifact: it goes
on the ticket, it is re-rendered when the facts firm up for the 72-hour report, and it is
what answers "what did we tell people?" a year later.

```json
{
  "reference": "CAL-BREACH-20260817-1",
  "aware_at": "2026-08-17T04:12:00+05:30",
  "nature": "A storage credential committed to a private repository was used to list one object-storage prefix from an address outside our infrastructure.",
  "extent": "Call recordings and archived call payloads for approximately 1,200 calls belonging to 2 client accounts. Each payload carries the caller's number and a transcript of the call.",
  "timing": "The credential was valid from 2026-08-02. The single unauthorised listing is at 2026-08-16 22:41 IST. No further access is recorded.",
  "consequences": "Someone outside Calevate may hold a list of object keys and, for objects they then fetched, the audio and transcript of those calls. That would disclose the caller's number and what they said on the call.",
  "mitigation": "The credential was revoked at 04:31 IST. The bucket's public-access block was verified. All access from the address is enumerated in the storage access log and is attached.",
  "safety_measures": "Nothing is required of you. If anyone contacts you claiming to be from this business and quotes a recent call, do not act on it and tell them.",
  "cause_findings": "A credential was committed by us on 2026-08-02 and not detected by the secret scan. No third party is implicated so far.",
  "remedial_measures": "Pre-commit secret scanning is now blocking, the credential set is rotated on a schedule, and object-store credentials are issued per host with the prefix scoped.",
  "contact": "Sri J, Data Protection Contact, security@calevate.tech",
  "unknowns": "Whether objects were FETCHED as well as listed is not yet established from the vendor's access log. We expect an answer within 24 hours and will follow up either way."
}
```

`unknowns` is a required part of an honest first notice, not an admission of failure: the
clock runs from awareness, so the first notice goes out before forensics finish. Leave it
empty only when the investigation is genuinely closed.

Then render:

```sh
uv run python -m scripts.breach_notice incident.json                 # all three
uv run python -m scripts.breach_notice incident.json --which client  # just one
```

The renderer **refuses** a notice with a required Rule 7 element missing, and names every
missing element at once. It sends nothing.

## 4. Who signs off

The **incident lead** owns the notifications and is the person named in the `contact`
field. The **founder** signs off every outgoing notice before it is sent — all three
kinds, without exception, including the first partial one. There is no delegation and no
"send it and tell him after": a breach notification is a statement to a regulator about
our own conduct.

If the founder cannot be reached within **six hours** of awareness, the incident lead
sends the CLIENT notification anyway with what is established, marks it clearly as a first
notification, and records that the sign-off was unreachable. The 48-hour promise is not
conditional on somebody answering their phone, and a late notice is a worse breach of it
than an incomplete one.

## 5. Send

- **Client notification** (within 48 hours): from the incident mailbox, to the client's
  `organizations.billing_email` **and** every `org:manage` holder on the account — one
  address is a single point of failure during an incident. Attach nothing containing
  personal data.
- **Data principals**: for caller data this is the CLIENT'S to send. Offer them the
  rendered `principal` draft — they are writing against a clock too, and a draft they can
  edit is worth more than a reminder that it is their job. For client-account data we send
  it ourselves, to the address on the account.
- **The Board**: the first intimation goes without delay and the detailed report within 72
  hours. **The Board's reporting channel is not recorded here on purpose**: the Board's
  own intake — a portal, an address, a form — is not something to look up for the first
  time during an incident, and this file will not carry a guess. See §7: establishing it
  and writing it into this section is one of the two things this runbook still needs from
  outside the repository, and it is cheap.
- Record on the ticket: what was sent, to whom, at what time. Section 7 of the Board
  report requires a summary of the intimations given to Data Principals, and that is the
  only place the count exists.

## 6. Afterwards

- Attach the rendered notices and the incident file to the ticket.
- If the breach reached caller data, the affected clients may receive erasure requests as
  a result — `POST /v1/compliance/deletion-requests` is their surface, and
  `apps/api/compliance/deletion.py`'s register is what the certificate will say.
- Add the remedial measure to `docs/OPERATIONS.md` §2 if it is a gate, or to the
  pre-launch checklist if it is a condition.
- Re-render the client notification with the completed facts and send it as a final
  update, even where nothing material changed. A client who was told "we do not yet know"
  and never heard again learned the wrong thing about us.

## 7. What this runbook does NOT have, and who closes it

Stated here rather than discovered mid-incident:

1. **The Data Protection Board's reporting channel.** Nobody has established it. It needs
   one person to look it up from the Board's own notification and write it into §5. It is
   not blocked on anything.
2. **Counsel's review.** Neither the notice wording here nor the rule summary in
   `apps/api/compliance/breach.py` has been reviewed by an advocate qualified in India,
   and the rule's operative text could not be fetched from this environment (the same
   caveat `docs/LEGAL-SURFACE.md` §9 records for every citation in it). The elements are
   drawn from concurring secondary sources, retrieved 17 August 2026. Counsel should
   check the wording — the mechanism does not change either way.

Neither of those is a reason to delay a notification. A notice sent on time with wording
counsel would improve beats a perfect one sent on day four.
