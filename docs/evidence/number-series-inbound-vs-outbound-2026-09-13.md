# What number a clinic may lawfully use: inbound answers, outbound does not

**Date:** 13 September 2026
**Question asked:** may a non-BFSI SMB — a private clinic — use an ordinary landline for
commercial service calls, as a carrier's help page says, or is that prohibited as TRAI's
regulation and our own `SECURITY-COMPLIANCE.md` imply?
**Answer:** the contradiction was not the one we thought. The regulation is clear and the
carrier page is the outlier — **but the regulation prohibits something for which it has not
yet provided the permitted alternative.** A private clinic cannot today lawfully place an
appointment-reminder call from ANY number.

And separately, the question we had never asked turns out to have the best answer in the
brief: **inbound is not regulated as commercial communication at all.**

## 0. Evidence class

Produced by the founder's research agent against TRAI, DoT and PIB primary instruments, and
relayed. `trai.gov.in`, `dot.gov.in` and `pib.gov.in` are all egress-blocked from this
container (re-measured 13 Sep 2026: connect failed on each), so **nobody in this repository
opened these documents.**

Class in this tree: **REPORTED — research-agent reading of named primary regulatory
instruments, founder-relayed, 13 Sep 2026.** Stronger than the vendor-page research in
`orchestrator-commercial-and-carrier-2026-09-13.md`, because the cited sources are the
regulator's own text with clause numbers rather than an operator's help page — but still
below a reading this repo performed, and **it may not reach a client-facing compliance claim
without a lawyer or a re-read.**

Cited throughout: TCCCPR 2018 (19 Jul 2018) and the **Second Amendment Regulations, 2025**
(notified 12 Feb 2025), DoT's allocation page of 23 Dec 2024, and TRAI/PIB's 1601 Phase-I
direction of 10 Aug 2026.

## 1. INBOUND IS NOT COMMERCIAL COMMUNICATION — the finding that unblocks the product

TCCCPR's operative categories are drafted as calls **"made by a Sender to"** a recipient:
amended Regulation 2(bh) for a Service Voice Call, 2(bt) for a Transactional Voice Call, and
Regulation 22(1)(i)(A) speaks of resources "for the purpose of **making** service and
transactional calls".

**No provision in TCCCPR, its amendments, TRAI directions or the DoT numbering documents
examined classifies a business ANSWERING a subscriber-initiated call as commercial
communication, or requires the answering number to belong to a commercial series.**

Consequences, and they are large:

- **The inbound receptionist — the whole first vertical — ships on the clinic's ordinary
  published business number.** No 140, no 160, no special series.
- **No Sender / Principal Entity registration is triggered by answering calls.** The ₹5,900
  DLT PE registration D-420 records is an OUTBOUND cost, not an onboarding cost.
- Carrier KYC still applies (the per-tenant Plivo compliance application in
  `orchestrator-commercial-and-carrier-2026-09-13.md` §5.2 is unaffected — that is the
  carrier's rule, not TRAI's).

⚠ **One boundary is explicitly NOT addressed by the regulation**: an inbound agent that
volunteers an unrequested offer. The promotional definition is content-based and says
promotional content mixed into a commercial call makes the whole call promotional, but it
does not say how that applies when the RECIPIENT originated the call. Until that is settled,
**the inbound agent must stay responsive to what the caller asked** and must not be used as a
marketing surface. That is a prompt-composition rule and it belongs in `PROMPT-GUIDE.md`
beside the existing service/promo fencing.

## 2. OUTBOUND: the prohibition is real, and so is the gap

### 2.1 What the regulation requires

Amended **Regulation 3(1)**: every commercial communication must use "registered headers or
the number resources allotted to the Senders from **special series** assigned for the purpose
of commercial communication."

Amended **Regulation 22(1)(i)(A)**: "it shall be the **sole responsibility of the Sender** to
ensure that only registered Headers or the number resources allotted to such Sender from the
special series assigned for the purpose of making service and transactional calls, are used
by it for making such calls and **no promotional content shall be mixed in it**."

**An ordinary geographic landline (`022`, `080`) or 10-digit mobile is not a special series.**
No exception for ordinary business numbers appears in either regulation.

Critically: **being outside the UCC definition does not exempt a call from the number rule.**
A service call to an existing customer needs no consent and is not UCC — and still may not be
placed from an ordinary number. Two different questions, and the repo must not conflate them:

```
not UCC  ≠  exempt from the special-series requirement
```

### 2.2 And no special series exists for us

| Series | Purpose | Who may hold it |
|---|---|---|
| `140` | promotional / telemarketing | no sector restriction found |
| `1600` | service + transactional | government, and RBI/SEBI/PFRDA/IRDAI-regulated financial entities (DoT, 23 Dec 2024) |
| `1601` | service + transactional, sectors beyond BFSI/government | **Phase I only: utilities and logistics/courier** (TRAI/PIB, 10 Aug 2026) |

**Healthcare is in neither.** A clinic is not an RBI/SEBI-regulated financial entity, and is
not a utility or a courier.

So the position for a private clinic placing an appointment reminder is:

- prohibited from using its ordinary number (Reg 3(1), 22(1)(i)(A)), **and**
- not eligible for any service series that currently exists.

> ⚠ **CORRECTED LATER THE SAME DAY. THE SENTENCE THAT STOOD HERE IS WITHDRAWN.** It read:
> *"This is a regulatory gap, not a mistake in our reading. It is the single most important
> constraint on this product and it is nobody's bug to fix"* — and §5 drew from it that a clinic
> *"cannot ship lawfully today"*. A second, deeper pass by the same research agent located the
> migration directions the first pass missed, and they change the finding from a **prohibition**
> to a **transition gap**. The two bullets above survive as a reading of the regulation's text;
> what was wrong was treating that text as self-executing for every sector from the day it
> commenced. See §2.6.

### 2.6 IT IS A TRANSITION GAP — how TRAI actually operates the rule

The amended regulation states the special-series requirement broadly. **TRAI then operationalises
it sector by sector, through dated directions naming who must migrate and by when.** That is the
mechanism the first pass missed, and three instruments show it:

| Instrument | What it did |
|---|---|
| TRAI Direction, **19 Nov 2025** | `1600` migration deadlines for named RBI-, SEBI- and PFRDA-regulated categories. TRAI records that **most regulated entities were still using ordinary 10-digit numbers even after `1600` was allocated** — and answered that with dates, not with a finding that they were already in breach. |
| TRAI Direction, **16 Dec 2025** | IRDAI-regulated entities, deadline **15 Feb 2026**, after which they may not place service or transactional calls from outside `1600` *"even with the explicit or inferred consent of customers."* |
| DoT Order **16-2/2023-AS-III/TRAI/N115** (30 Jun 2026) + TRAI Direction (10 Aug 2026) | Created `1601` for non-BFSI, then opened Phase I to utilities and logistics/courier only, with further sectors *"notified separately … from time to time."* |

**The tell is that TRAI had to name the entities and set the dates.** Had the regulation alone
barred every ordinary-number commercial call from commencement, none of those directions would
have been needed.

For private healthcare: **no migration deadline has been published, and no express transitional
authorisation has been published either.** Both UNKNOWN — not found. So the adopted position is:

> Clinic service calls from ordinary carrier-issued numbers occupy a **regulatory transition
> gap** — neither clearly authorised nor clearly subject to an operative clinic-specific
> migration deadline.

#### 2.6.1 The DoT order exists, and `1601` numbers ARE ten-digit

The 30 June 2026 order the first pass could not find is cited above, and one detail bears
directly on the founder's model: **`1601ABCXXX` is itself a ten-digit number.** So "the clinic
buys a proper 10-digit number" is ambiguous, and the ambiguity is the entire question:

| "Proper 10-digit number" means | Lawful for outbound clinic service calls? |
|---|---|
| An allotted `1601ABCXXX` number | **Yes** — that is the designated class. Blocked only by healthcare not yet being in a phase. |
| An ordinary `022`/`080` DID registered on a DLT portal | **Not automatically.** Sender registration (Reg 3(2)) and special-series allotment (Reg 3(1)) are two separate requirements; satisfying one does not satisfy the other. |

⚠ **DLT registration does not convert an ordinary number into a special-series resource**, and an
ordinary 10-digit mobile is the practice TRAI's own Press Release 11/2025 §4(c) describes the
amendment as restricting. Neither may be written down anywhere as our compliance basis.

#### 2.6.2 Outpero is not evidence, in either direction

That Outpero appears to use ordinary 10-digit numbers is **not established from their public
material**: the research could not determine which carrier originates their calls, which series a
recipient actually sees, whether the customer or Outpero is the registered Principal Entity, or
under what instrument healthcare customers use that number. The `+91 98765…` numbers on their
site sit in an inbound display, not a proven outbound caller ID — and their own site calls
conversational inbound answering *"coming soon"*.

**Even if confirmed, vendor behaviour is not regulatory authority.** A competitor's calls
connecting proves the carrier permits the traffic, not that the traffic is lawful. `docs/TRD.md`
§10 already refuses this exact class of reasoning about this exact company.

### 2.3 D-420 is CONFIRMED and its reasoning strengthened

D-420 recorded that 160-series needs an RBI/SEBI certificate "which a clinic, a salon or a
coaching centre cannot produce", and concluded **our SMB clients are 140-series only, i.e.
every campaign is promotional**.

That conclusion stands, and the ground underneath it is now firmer than D-420 knew: it is not
merely that the certificate is unobtainable, it is that **the eligibility lists for both
service series exclude healthcare outright**, and the 2026 expansion everyone hoped would open
it named utilities and couriers instead.

**The earlier hope — recorded on 12 Sep, that the 30 June 2026 DoT order might unlock 160 for
clinics — is withdrawn.** The agent could not locate that order at all; the authoritative
instrument is TRAI's 10 Aug 2026 direction, and its Phase I does not include us.

### 2.4 The carrier page is the outlier

Plivo's number-purchase page says landline `022`/`080` may be used by non-BFSI businesses for
service and transactional calls. **An operator help page cannot displace Regulations 3 and
22.** Either Plivo relies on a transition direction, a Code of Practice clause or a sector
exemption none of this research located — or the page is wrong.

**Do not build on it.** If we ever place a service call from a geographic DID, we want the
carrier's written statement of the regulatory authority for it, filed in `docs/evidence/`.

## 2.5 THE FOUNDER'S MODEL, AND THE ONE CLAUSE IT TURNS ON

The intended commercial model, stated by the founder 13 Sep 2026:

> the client (clinic) buys a proper 10-digit number and registers it for DLT, hands it over to
> us digitally, and we use it on their behalf to make calls.

**Two of its three parts are exactly what the regulation requires**, and that is worth saying
before the doubt:

- **The number is the CLIENT's, not ours.** Amended Regulation 22(1)(d) requires the number
  resource to be allocated to, and authenticated as belonging to, the Sender in whose name it
  was issued. A pool of Calevate-owned numbers dialling for many clinics would be the wrong
  shape; one number per client, in the client's name, is the right one.
- **The clinic is the Sender / Principal Entity.** The communication supplies the clinic's
  services, so the clinic registers, and Calevate operates inside the delivery chain. Also
  correct, and it matches Plivo's own reseller rule (a separate compliance application per
  customer, `orchestrator-commercial-and-carrier-2026-09-13.md` §5.2).

**The third part is the open question, and it is narrower and sharper than "is Plivo right".**

Regulation 3(1) permits a commercial communication to use:

> "**registered headers** OR the number resources allotted to the Senders from **special
> series** assigned for the purpose of commercial communication"

Two branches, joined by *or*. §2.1 above reads only the second branch, which is why it
concluded the ordinary number is prohibited. **If the first branch is available to voice
calls, a DLT-registered 10-digit number is lawful and the gap in §2.2 does not exist.**

So everything turns on:

> **Is a DLT-registered 10-digit number a "registered header" for a VOICE call?**

What the research found, and it cuts both ways:

- Against: *"TCCCPR does not define a 'voice header' equivalent to an alphanumeric SMS
  header. For voice calls, the operative identity is the allotted special-series number
  resource."* On that reading the header branch is an SMS concept and voice has only the
  series branch.
- For: this repo already records header registration in the VOICE context — `docs/
  LEGAL-SURFACE.md:1284` describes 140-series via Vobiz and 160-series via Plivo each with
  *"PE/TM IDs, URN, header and template registration"*, and D-420 records ₹5,900 PE
  registration on the TATA DLT portal with a director-signed LOA. Somebody is registering
  voice headers, or our own documentation is using the word loosely.
- And it would explain the outlier: **Plivo's page may be relying on exactly this branch** when
  it says non-BFSI businesses may make service calls from `022`/`080`.

**This is now the question to put to the carrier and the regulator**, in place of the vaguer
one in §6.2. It is answerable, it is narrow, and the whole outbound service-call product line
depends on it:

> Under amended Regulation 3(1), may a private clinic make a service voice call from a
> DLT-registered 10-digit number under the "registered headers" branch — or does the voice leg
> admit only the special-series branch of that clause?

Until it is answered, §7's prohibitions stand: **do not build, price or promise outbound
service calls on the assumption that the header branch is available.** The inbound product
(§1) is unaffected either way, and that is what makes it safe to ship first.

One consequence to note whichever way it lands: if Calevate originates calls on the client's
number, Calevate is operating in the telemarketer chain, and *which* registered role we hold —
Telemarketer with Aggregator Function, or none — is §6.5, still unclassified.

## 3. Four more things that bite our design

### 3.1 "Transactional" is far narrower than an appointment reminder

Amended Regulation 2(bt): a transactional call is made **"in response to Customer initiated
transaction within thirty minutes of the transaction"** — OTPs, confirmations, refunds.

An appointment reminder sent the day before is **not transactional**. It is a *service* call
under 2(bh)(i), which is the category with no available number series. Nothing in our
vocabulary or our gate should let those two words be used interchangeably.

### 3.2 Promotional contamination is total

Promotional content mixed with any other commercial content makes **the entire call
promotional** (Reg 2(av) as replaced). A reminder that ends with "and we now offer teeth
whitening" is a promotional call, on a promotional number, subject to preference and consent.

`PROMPT-GUIDE.md` §4 already fences service agents against promotional content. This raises
that from good practice to the thing that decides which number the call was allowed to use.

### 3.3 An obligation we do not implement: advance autodialer notice

Amended **Regulation 4**: "Every Sender shall notify the Originating Access Provider, **in
advance**, about the use of Auto Dialer or Robo-Calls as well as the intended objective of
such calls **in writing**."

An automated outbound campaign is at minimum an autodialer. **There is no such notification
anywhere in this product**, and it is a per-Sender, written, pre-campaign step. Whether it is
per sender, per campaign, per number or per objective is **not stated** — that is a question
for the access provider.

### 3.4 Enforcement is harsher and faster than our docs record

| | |
|---|---|
| Complaint window | **7 days** from receipt (later = a report, not a complaint) |
| Enforcement threshold | **5 unique recipients in the preceding 10 days** — and it applies expressly to *promotional calls misusing service/transactional number resources* |
| First violation | outgoing barred **15 days**, across **all** the sender's telecom resources — PRI/SIP trunks, SIMs, including resources not used for the UCC |
| Repeat | **1 year** disconnection, blacklisting, no new resources, devices blocked across all access providers |
| Restoration | **₹5,000 per telecom resource**, capped ₹5 lakh — **and each DID on a PRI or SIP trunk counts separately** |
| Propagation | suspension/blacklist spreads through DLT; other providers must stop traffic within **24 hours** |

`SECURITY-COMPLIANCE.md` §1 records "15-day outgoing suspension (first), 1-year disconnection
+ blacklist (repeat)" — correct. What it does not record is that the bar hits **every**
resource the sender holds, and that per-DID restoration pricing makes a SIP trunk expensive
to un-bar. For a platform dialling on behalf of many clients, one client's violation pattern
is the thing to model.

## 4. ⚠ A constant in live code this research puts in question

`apps/api/compliance/service.py` enforces a platform calling window of **09:00–21:00 IST**
(`DEFAULT_WINDOW`, `within_calling_hours`), and its docstring sources the rule to TCCCPR's
prohibition on commercial communication "between 2100 hours and 0900 hours", carried from
TCCCPR 2010 reg. 12 and stated as unchanged by the Second Amendment.

**The research could not find a single current nationwide calling window in the instruments it
retrieved**, and warns specifically that the widely-repeated 9am–9pm figure should not be
written into compliance documentation without the operative direction and its exact scope.

These are **not necessarily in conflict** — our code cites the principal regulation, the
research examined the amendment and what it could retrieve. But the honest position is:

> **The 09:00–21:00 window is REPORTED with a plausible citation that nobody in this session
> re-read, and one independent search failed to confirm it.**

It is not being changed on that basis — a window that is too narrow is safe, and D-311 already
fixed the boundary semantics correctly. But it should stop being a silent constant: it wants
the clause text quoted at the constant, and a gate that says a human read TCCCPR 2018's
calling-hours clause and filed it, exactly as gate 20 does for the Azure region.

## 5. What this means for the roadmap

**Ships now, unblocked:**

- The inbound receptionist, on an ordinary business number, with no PE registration and no
  special series. This is the first vertical's core product and the regulation does not reach
  it.

**Ships only on a carrier's written authority — the transition gap (§2.6):**

- Outbound appointment reminders, confirmations, reschedules — the whole service-call class.
  ⚠ This heading read **"Cannot ship lawfully today"** until the §2.6 correction. That was too
  categorical: healthcare has no published migration deadline AND no published transitional
  authorisation, so the class is unresolved rather than barred. What it needs before it ships is
  the carrier's written statement of the authority it relies on — §6.2, whose wording is now
  specific enough to send.

**Ships with work:**

- Outbound promotional campaigns on `140`, with Sender/PE registration, a registered
  telemarketer route, preference or explicit consent checks, and the Regulation 4 autodialer
  notice we have not built.

The product consequence is that **inbound and outbound are now separated by a regulatory line,
not merely a feature line**, and the inbound half is the half that is legal today.

## 6. Open, and who can close it

1. **Which special series may a private clinic use for service calls?** If the answer is
   none, is healthcare scheduled for a later 1601 phase, and when? → TRAI / DoT.
2. **What authority does the carrier rely on** for non-BFSI service calls from `022`/`080`?
   → Plivo or Exotel, in writing. Send exactly this:

   > "Please identify the TRAI regulation, TRAI direction, DoT order or operative Code-of-
   > Practice clause under which a non-BFSI private medical clinic may make service voice calls
   > from its DLT-registered ordinary geographic DID instead of a `1601`-series number."

   A sufficient answer looks like this, and anything vaguer is not an answer:

   > "Until healthcare entities are notified for migration to the 1601 series, this carrier
   > permits a duly verified private medical clinic to originate non-promotional service calls
   > from the clinic's allotted ordinary business number, subject to PE/DLT registration,
   > consent/customer-relationship requirements, DNC controls, autodialer notification and the
   > carrier's applicable Code of Practice."

   That does not erase the ambiguity. It does give us a named party who asserted the authority,
   which is materially stronger than inferring it from a competitor's calls connecting.
3. **Is interactive generative speech a "Robo-Call"?** Undefined in every instrument
   examined. → TRAI.
4. **Must a voice script be a registered content template?** The Schedule I template controls
   are drafted for messages — "sample message", characters, variables, Message Headers — and
   no voice-script matching protocol was found. → TRAI / access provider.
5. **Is Calevate a Sender, a Telemarketer with Aggregator Function, or an unregulated software
   processor** when Plivo originates the call? Not classified anywhere. → access provider.
6. **May one entity hold both Sender and TM registration?** No prohibition found; no
   permission either. → access provider.
7. **The operative calling-hours clause and its scope.** → §4 above.
8. **Does an inbound agent volunteering an offer become a promotional call?** → TRAI.

Every one of these is EXTERNAL in the sense CLAUDE.md's tempo section means: it needs a
regulator, a carrier or a lawyer, and none of it is coded around.

## 7. What must not be written anywhere until those close

- That a clinic may make service calls from a geographic number **as a settled matter** — and
  equally, that it may not. Both overstate. The position is §2.6's transition gap, and the only
  thing that moves it is a carrier's written authority or a TRAI phase notification.
- That DLT registration of an ordinary DID satisfies the special-series requirement. It does not
  — they are separate clauses (Reg 3(2) vs 3(1)).
- That healthcare is eligible for 1600 or 1601.
- That a 9am–9pm window is the regulator's stated rule (say: our platform window).
- That inbound answering requires DLT registration — it does not, and saying so would add
  friction and cost to onboarding for no legal reason.
- That another vendor's practice makes ours lawful (§2.6.2).

### 7.1 The sentence our own policy may safely use

Until the carrier answers, client-facing copy describes the mechanism rather than claiming
compliance:

> "Calls are originated using a carrier-issued number registered to the customer and operated
> under the carrier's applicable DLT, KYC and commercial-calling requirements. Number-series
> eligibility is subject to the current TRAI/DoT phased implementation and the originating
> carrier's written authorization."

**Never** "unconditionally compliant with TCCCPR". That is the claim this whole document exists
to stop us from making.
