# Outpero: number supply, identity verification and calling policy — 20 September 2026

**EVIDENCE CLASS: FOUNDER-OBSERVED, FIRST-HAND, 20 September 2026.** Everything in §§1–5 was
seen by the founder in Outpero's own product and on their own published pages — purchase and
verification screens captured as screenshots, a trial account provisioned, and one inbound
demo call received and its caller ID read off the handset. No third party reported any of it
and nothing here is inferred from marketing copy.

**WHAT THIS FILE IS NOT.** These are observations of a competitor's PRODUCT. Nothing here is
a legal conclusion about Outpero, about their carrier arrangements, or about whether any
call described was lawful — we have not seen their registrations, their DLT chain or their
contracts, and a screen is not a licence. §6 draws conclusions about **our own** design only,
and marks the regulatory premises it leans on with their own class.

Prior teardowns of the same product: `outpero-teardown-aug2026.md` (authenticated
walkthrough, 10 Aug 2026) and `outpero-research-log.md` (its raw notes). This file is the
number-supply and calling-policy half, which those did not cover.

---

## 1. They sell Indian MOBILE numbers, from a contiguous block, instantly

- Price: **₹649 per month** per number.
- The numbers offered came from a **contiguous block**: `+91 94293 97618`, `97620`, `97621`,
  and `97628` through `97637`.
- Purchase is **instant, from a prepaid credit balance** — no ticket, no waiting on an
  operator, no carrier form in the flow.

These are ordinary 10-digit mobile numbers. They are not 140-series and not 160-series.

## 2. The purchased number is registered to the CLIENT, and their screen says so

Their purchase screen states that verification *"makes you (not us) the registered owner"*.

The verification itself, as shown:

- **PAN first, then Aadhaar via DigiLocker.**
- Required on the **first purchase only**, and **reused** for every later number.
- **Immutable** once completed.

So the client — not Outpero — is presented as the subscriber of record for numbers bought
through the platform, and the platform holds one verified identity per account rather than
one per number.

## 3. Trial accounts are given a number from Outpero's OWN pool

A trial account provisioned to the founder was handed a number beginning `807383…` from the
competitor's pool rather than one purchased in the client's name. So the platform runs two
supply modes side by side: their number for a trial, the client's number after purchase.

## 4. The demo call came from an ordinary mobile number

A product demo call placed to the founder arrived from **8087678987** — an ordinary mobile
number, **not a 140-series header**.

Two observed facts about that call, kept separate from any conclusion:

- It was a call **marketing their product to a prospect**, i.e. promotional commercial
  communication in substance.
- The **sender was Outpero themselves**, not a client of theirs. Whatever a client's
  obligations are on the platform, this call was the platform's own outbound marketing.

## 5. Their published calling policy, in their own terms

| Topic | What their page says |
|---|---|
| List sourcing | Consent-only lists; **no scraping** |
| Bulk campaign hours | **09:00–21:00** |
| Instant callback hours | **06:00–22:00** |
| Do-not-call | Automatic do-not-call **on request** |
| Do-not-call, instant path | Their own page states the DNC list **"is not yet applied to Instant lead calls"** |
| Do-not-call, bulk path | **Opt-in** on bulk campaigns |
| Liability | Placed on the client — *"Outpero is the phone, not the business"* |

The last three rows are the load-bearing ones and they are the competitor's own words, not a
characterisation: suppression is opt-in where it is applied at all, and on the instant path
it is not applied.

---

## 6. What this means for US

### 6.1 The client-as-subscriber model is now EVIDENCED, not inferred

`number-supply-model-a.md` and D-474 (Model B holds no carrier account at all) both turn on
whether an SMB-facing voice platform can put the numbers in the CLIENT's name. §2 is a
working competitor doing exactly that, with their own screen naming the client as registered
owner and a PAN-then-Aadhaar/DigiLocker flow as the mechanism. That moves the question from
"is this arrangement available to a platform of our size" to "which of the two models we
want", which is a commercial choice rather than an open unknown.

It does **not** tell us which entity holds the carrier relationship behind the screen, what
authorisation they operate under, or what their DLT registrations look like. Those remain
unknown and are precisely the questions `Settings.number_resale_authorization` gates.

### 6.2 Their 06:00–22:00 instant window is NOT a precedent to copy

Our platform window is **09:00–21:00 IST** (`apps/api/compliance/service.DEFAULT_WINDOW`,
half-open at the top since D-311). Outpero's instant-callback window runs three hours earlier
and one hour later, so **06:00–09:00 and 21:00–22:00 both fall inside the band our own rule
treats as forbidden** for commercial communication.

**The regulatory premise here is REPORTED, and it is recorded as such elsewhere in this tree**
— TCCCPR's prohibition on commercial communication between 2100 and 0900 hours is cited in
`compliance/service.py` and D-311, while
`number-series-inbound-vs-outbound-2026-09-13.md` §4 records that one independent search
failed to confirm a current nationwide window in the instruments it retrieved, and warns
against writing the 9-to-9 figure into compliance documentation without the operative
direction. `trai.gov.in` is egress-blocked from this container.

That caveat cuts one way only. A window that is too narrow costs us dialling hours; a window
that is too wide is a violation with a timestamp on it. A competitor dialling outside ours is
therefore not evidence that ours is wrong, and **"Outpero does it" may not be quoted as a
ground for widening.** If the window is ever widened it will be on the operative direction,
read.

### 6.3 Their DNC gap sits on their highest-volume path

Instant lead calls are the volume path in a speed-to-lead product — every form submission
produces one, and they are the calls a recipient is least expecting. A suppression list that
is **opt-in on bulk and not applied at all to instant** is therefore absent from the traffic
most likely to generate complaints.

Enforcement in this market is complaint-triggered and counted per sender: five unique
complainants in ten days obliges the access provider to suspend the sender's outgoing service
(recorded at `number-series-inbound-vs-outbound-2026-09-13.md` §3.4, same REPORTED class; our
own `campaigns/complaint_spike.py` uses the same five as a ceiling). Combined with §2 — the
numbers are registered to the CLIENT — the exposure created by that gap lands on the client's
telecom resources, not the platform's, which is also what §5's liability clause says out loud.

**For us this is a confirmation, not a lesson.** Hard rule 5 already puts DNC on every dial
path: `ingest/service.py` runs `check_dispatch` before the instant call and leaves the lead
in `new` with the blocking rule recorded, and `callbacks/service.py` re-checks at fire time
rather than at booking. The competitor's page is evidence that this is the corner a product
under speed-to-lead pressure actually cuts, and that the cut is invisible from the outside
until a complaint arrives.

### 6.4 Two things §4 does not license us to conclude

Their demo call came from an ordinary mobile rather than a registered voice header, and our
own reading of TRAI direction RG-25/(18)/2023-QoS of 18 Jun 2024
(`primary-legal-findings-2026-09-20.md` §1) is that a sender may not make promotional, service
or transactional voice calls from any other 10-digit number. **We do not know what
registrations Outpero holds**, and one observed caller ID is not a compliance finding about a
company. What it IS: a data point that this is normal practice in our market, which is the
reason `SERIES_FOR_CLASSIFICATION` refuses `standard` rather than merely warning about it —
the competitive pressure to allow it is real and arrives as "everyone does this".
