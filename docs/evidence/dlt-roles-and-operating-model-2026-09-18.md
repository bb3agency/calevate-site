<!-- EVIDENCE CLASS: DERIVED. This file reasons FROM two documents landed 17 Sep 2026 —
     `telephony-regulatory-brief-2026-09-17.md` (28 primary sources: DoT licence text, TRAI
     regulations, three operators' DLT portals, three CPaaS providers' terms) and
     `carrier-pricing-concurrency-2026-09-17.md` (authenticated provider consoles). Every
     claim below either cites one of those or is marked as a READING of a definition.

     ⚠ IT IS NOT LEGAL ADVICE AND SETTLES NOTHING. `docs/legal/LEGAL-OPS-PLAYBOOK.md` §20
     routes these questions to a telecom lawyer, and the brief's PART 4 holds eight of them.
     A ninth is added here, and it is the one that would cost real money to get wrong. -->

# DLT roles, the three operating models, and where the Telemarketer ID is NOT

## Why this file exists

Two questions came up on 17-18 Sep 2026 that this repository could not answer from its own
documents: *can we sell numbers to clients?* and *what registrations do we need?* Both were
answered against licence and regulation text for the first time. The answers change what
`docs/FLOWS.md` §10 describes, and one of them reverses something stated in this
conversation and repeated with more confidence than the evidence carried.

## 1. The three models, and which have a documented path

| | Who is the CPaaS's customer | Who is subscriber / PE | Status |
| --- | --- | --- | --- |
| **A** — Calevate buys numbers, sells them on | **Calevate** | Calevate | **CLOSED** for this entity |
| **BYON** — client's number from carrier X, trunked into our account at CPaaS Y | Calevate | ambiguous | **NO DOCUMENTED PATH**, technical or legal |
| **B** — client holds their own CPaaS account; we hold delegated API credentials | **the client** | the client | **DOCUMENTED** (brief Route 1a) |

### Model A is closed by licence text, not by caution

`UL-VNO Licence Agreement` Annexure-I item 53 defines "Licensee" as **"a registered Indian
Company"**. Calevate is a sole proprietorship. `LEGAL-OPS-PLAYBOOK` §9.1 and §19 reached the
same conclusion before the licence text was read; the brief supplies the text it lacked.

The three CPaaS routes do not open a side door:

* **Exotel** — absolute domestic resale ban, **no consent mechanism at all** (ToS cl.2).
  They can sell numbers because **they hold their own pan-India UL-VNO**. That is a licence,
  not a business model.
* **Vobiz** — resale banned without prior written consent; "Partner with us" is a contact
  form with no published terms.
* **Plivo** — *"Plivo owns the telephone number(s) assigned to you"*; Plivo is customer of
  record (Additional Service Terms §1.1-1.2, §3.2).

⚠ **PLIVO'S "RESELLER" CHECKBOX IS NOT AUTHORISATION, AND IT IS THE EASIEST THING HERE TO
MISREAD.** Their India compliance application does offer "Direct Brand" vs "Reseller" with a
separate application per customer — that is real and documented. It is Plivo's own KYC flow.
It is **not** Plivo granting standing under their licence, and it is not DoT recognising
anything. The brief: *"'authorised reseller' … was not found defined or obtainable as a
formal status in any primary text."*

### BYON — the variant that has no path

Client buys a number from any carrier and we terminate it on our trunk:

* **Vobiz blocks it outright** — *"You cannot port a number from another provider … There is
  no number transfer/porting flow"*; the trunk's Assign Number endpoint takes only numbers
  already in your Vobiz inventory.
* **Plivo** claims it via "SIP forwarding or your own RespOrg" — RespOrg is a US/FCC concept
  with no Indian equivalent, and native porting is documented as US/Canada only.
* **Exotel** is silent, which is not consent.

And legally: **no lawful mechanism was found for presenting a client's own validly-assigned
number as caller ID from third-party infrastructure** — not in the MNP Regulations, not in
Airtel's Consumers Charter, not in any CPaaS terms. The MNP LoA is an instrument for
*changing operators*, not for delegation; and porting into a CPaaS makes the CPaaS the
subscriber of record, so the number stops being the client's in any meaningful sense.

Next to which sits **Telecommunications Act 2023 s.42(3)(c)**, criminalising unauthorised
CLI tampering — cognizable and non-bailable. Every source found concerns *spoofing*. Whether
*authorised delegation of a real number* falls outside s.42 **is addressed nowhere**.

### Model B is what the playbook always meant

`LEGAL-OPS-PLAYBOOK` §9.1, verbatim: *"Client's entity is on the CAF / carrier KYC · Client
is PE on DLT · You are TM · Bolna uses **their** API credentials · You are **not** the DoT
subscriber of their DID."*

⚠ **THE FOURTH BULLET IS THE ONE THAT WAS LOST IN CONVERSATION.** Model B was always the
client holding their own CPaaS account with us given delegated API access. It was never
"client hands us a number". Those were treated as the same thing for part of a day, and the
BYON findings were reported as though they had killed Model B. They had not.

Vobiz's sub-accounts gate on **per-sub-account KYC** (`kyc_calls_blocked: true` until
verified) — the closest thing the research found to a provider explicitly accommodating
multi-tenant use of this shape. Worth asking all three about by name.

## 2. KYC and DLT are different regimes

Plivo's Additional Service Terms state the split in their own contract: Plivo is customer of
record and *"carries DoT/TRAI licensing burden"*, while *"customer carries DLT PE
obligation"*.

| | What it is | With whom | Cost / time |
| --- | --- | --- | --- |
| CPaaS KYC | proof you are a real business, so they will rent you a number | the CPaaS | Plivo: one document (GST/CoI/Udyam), ~5 min. Exotel: entity-specific tables, 1-3 (up to 5) business days. Vobiz: Individual (Aadhaar+PAN) or Company track, ~2 min automated |
| DLT PE registration | registering as a sender of commercial communication | an operator's DLT portal | ₹5,000 + 18% GST = **₹5,900**, 3-7 working days |

**₹5,900 = ₹5,000 + 18% GST.** Both figures seen in this tree are the same figure; the
relationship was never recorded. `docs/LEGAL-SURFACE.md:1284` carries ₹5,900 as if it were
distinct.

**The ₹50,000 TM-DF security deposit is CURRENT**, confirmed identical across Airtel, Vi and
Tata — not the stale 2021 Tata artefact it was previously flagged as. Registration fees are
non-refundable; **refunds apply to security deposits only** (VILPOWER registration page, read
by the founder 18 Sep 2026). PE validity 1 year, TM-AF/DF validity 5 years.

## 3. The roles, and the question nobody can answer

**PE and TM are two ends of one relationship, not alternatives.**

* **Sender** (TCCCPR Reg 2(bf)) — whoever owns the number/header, asserts the CLI, causes
  the communication, authorises it, **or benefits from the promoted goods/services**. For a
  call selling the client's services, that is the client.
* **Telemarketer** (Reg 2(bp)) — anyone *"engaged in the activity of transmission or
  delivery of commercial communication or scrubbing or aggregation"*.

**A PE must register itself.** TRAI: *"all PEs have to initiate all the related registration
request by themselves"* — a telemarketer cannot register on a client's behalf. A Calevate TM
ID is therefore never a substitute for a client's own PE registration; the documented
linkage is a **Letter of Authorisation** signed by the PE's authorised signatory naming the
TM and its Key Account Manager.

### ⚠ 3a. WHERE DOES THE TM ID ATTACH ON A VOICE CALL? NOBODY KNOWS.

**This section corrects a claim made confidently in conversation on 18 Sep 2026 and not
supported by anything in the brief.** The claim was that a registered TM gives clients *"a
registered telemarketer they can lawfully delegate delivery to — without one, a PE has no
registered route."* That was inferred from how SMS works and stated as though established.

What the brief actually records, in its own NOT FOUND list:

> *"A voice-specific 'header'/content-template registration process analogous to the SMS
> header/template system — Tata's FAQ describes headers/templates only in terms of 'actual
> SMS'; no equivalent voice-specific process was found."*

The documented DLT machinery — headers, templates, scrubbing against a registered sender —
is **SMS machinery**. For voice the roles, the fees and the LoA instrument are documented;
**the mechanism by which a TM ID attaches to an outbound voice call is not.**

**A READING, MARKED AS SUCH AND NOT A FINDING:** TM-DF is defined by *"direct connectivity
with telecom service provider(s)"*. In every model above, the party with that connectivity
is the **CPaaS** — Exotel holds its own UL-VNO; Plivo carries the DoT/TRAI licensing burden
by its own terms. If the CPaaS is the delivery telemarketer, a software platform with no
telecom connectivity may not appear in the DLT chain at all, in the way a CRM does not.
That is a reading of published definitions. It is not a finding, and it must not be acted on
as one.

**CONSEQUENCE, AND IT IS THE PRACTICAL POINT OF THIS FILE: do not pay ₹5,900 for a TM
registration until someone can name where the ID is used.** The fee is non-refundable and
the category choice carries a ₹50,000 difference. Both are decided by questions below that
no public source answers.

### 3b. Where Calevate might be a PE in its own right

If Calevate makes its own outbound sales calls — marketing Calevate to prospects — then for
*those* calls Calevate benefits from the promoted service and is the Sender under Reg 2(bf)'s
"benefits from" limb. That is a separate registration on our own entity, distinct from any TM
role for client traffic. **READING of the definition's plain words; confirm with the lawyer.**

## 4. What this changes in this repository

* `docs/FLOWS.md` §10 states *"All numbers are virtual DIDs (Exotel / Vobiz / Plivo,
  connected to the engine)"* and fixes the carrier by series (**140 → Vobiz, 160 → Plivo**).
  Both describe a Bolna-era model where the ENGINE provisioned numbers. D-592 removed Bolna.
* `docs/LEGAL-SURFACE.md:1284` carries ₹5,900 without recording that it is ₹5,000 + GST, and
  the ₹50,000 deposit as a 2021 figure needing re-verification. It is current.
* `LEGAL-OPS-PLAYBOOK` §9/§19 are CONFIRMED by licence text, not superseded. Model A remains
  refused, now for a cited reason rather than a prudential one.

## 5. Questions for the telecom lawyer, in the order that saves the most money

The brief's PART 4 holds eight. These are the three that gate spending, plus one new:

1. **Do transactional/service calls to consenting customers require PE/TM registration
   ITSELF, or only exemption from UCC enforcement?** (brief Q6.) TCCCPR Reg 2(bw) excludes
   them from the *definition* of UCC, but the registration mandate is framed around
   "Commercial Communication" generally and no carve-out from registration was found. **And
   does an inbound-only agent require any DLT registration at all?** If the answer is no,
   most of what follows never arises.
2. **NEW — In a voice call placed through a licensed CPaaS on behalf of a registered PE, at
   what point does a Telemarketer ID attach, and which party asserts it? If the CPaaS holds
   the direct TSP connectivity, is the CPaaS the TM-DF — and does a software platform with
   no telecom connectivity appear in the DLT chain at all?** This decides whether the
   ₹5,900 is spent and whether the ₹50,000 deposit applies.
3. **Is a software-only intermediary a Telemarketer under TCCCPR at all — and if so, TM-AF,
   TM-DF or TM-VCF?** (brief Q2.) On the published definitions Calevate has no direct TSP
   connectivity, which points to TM-AF and away from the deposit. The brief states plainly
   that no text applies this framework to a software-only intermediary.
4. **If we incorporate, does ticking a CPaaS's "Reseller" compliance option give us standing
   under their UL-VNO, or do we need our own authorisation regardless?** (brief Q1/Q7.)
   This decides whether Model A is ever available.

---

# Addendum, 18 Sep 2026: the mechanism, found — and §3a's reading reversed

**EVIDENCE CLASS: RELAYED, WITH A PROVENANCE PROBLEM STATED UP FRONT.** A research agent
with browser control answered the question §3a opened, and the founder relayed the summary.
It cites TCCCPR 2018 and its 2025 amendment, TRAI's 4 May 2024 direction, DoT's 1600-series
allocation page, VILPOWER's `Telemarketer_140_series.pdf`, Plivo's 140-series provisioning
docs, Vobiz's DID-provisioning best practices and Exotel's operator-registration page.

⚠ **SEVERAL CITATIONS IN THE SUMMARY DO NOT MATCH THEIR CLAIMS** — the Plivo quotation is
footnoted to a VILPOWER PDF, the Exotel RTM ID to a Plivo docs page, and the Vobiz claim to
a dot.gov page. The findings may be sound and the links merely transposed, but under hard
rule 11 a claim whose citation does not support it may not be re-stated as fact. **Every
finding below is REPORTED until the underlying report is opened and the quotation is matched
to its source.** The one that most needs it is finding 2, because it decides who the
Telemarketer is.

## 1. The RTM ID is never asserted on a call

**NOT DOCUMENTED as a per-call attachment**, in TCCCPR 2018, the 2025 amendment, the 4 May
2024 direction, the 2026 draft amendment, or any public operator material: the 19-digit
Registered Telemarketer ID is **not** carried in SIP or SS7 signalling, **not** displayed as
caller ID, **not** written to a prescribed voice CDR field, and **not** supplied per call.

What it is, is a **control-plane identifier**: it authenticates the telemarketer on DLT,
supports PE–TM mapping, and is used **when registering or allocating the Voice Header**. The
thing asserted on the live call is the **Header CLI — the 140/160 DID itself**. Vobiz states
it directly: *"the header is the DID number itself — the identity presented on outbound
calls."*

**So §3a's question has a concrete answer: a client never uses our TM ID.** The TM ID is what
allows a 140 number to be allocated and mapped to their PE. No 140 number, no role for it.

## 2. ⚠ §3a's READING WAS WRONG: the CPaaS is NOT the Telemarketer

§3a recorded, marked as a reading rather than a finding, that the CPaaS — holding the direct
TSP connectivity that defines TM-DF — was probably the Telemarketer, and that a software
platform might not appear in the DLT chain at all. **Plivo's own documentation says the
opposite**: *"Plivo is neither the PE nor the TM."* It identifies the TM as **"the entity
placing the call"** — which holds the DLT TM ID, signs Plivo's declaration, and registers the
Voice Header. And explicitly: *"a technology provider placing promotional calls for a PE is
treated as the TM."*

**That is us, on the promotional leg.** The reading is withdrawn. It was marked as a reading
and it was still wrong, which is the argument for marking them.

Where the other two stand: **Exotel publishes RTM ID `1002641844184516305`**, so Exotel holds
a telemarketer registration — but its page is SMS-oriented and does not establish that Exotel
is TM-DF or TM-VCF for every voice customer or call. **Vobiz** says provisioning proceeds
through *"your Telemarketer (TM) ID"* without identifying whose legal entity owns it.

⚠ **AND THIS CANNOT BE EXTENDED PAST 140.** The conclusion rests on Plivo's documented
140-series workflow. **No equivalent published workflow was found for ordinary-DID service
calls**, which is where this product actually sits.

## 3. The transactional/service exemption does NOT exempt registration

Brief Q6, answered, and answered against us. This file's §5 named it the question that could
remove most of the compliance surface. It does not.

**Amended Regulation 3(2) prohibits an unregistered Sender from making "any commercial
communication."** The transactional/service exclusion protects properly-classified
communications from the ordinary UCC *definition*; it does not carve them out of the
registration mandate. **Regulation 2(bw) closes the loop: commercial communication from an
unregistered Sender is TREATED AS UCC.**

**Consequence: a client calling their own consenting customers for service purposes still
needs PE registration.** The ₹5,900 is theirs to pay, per client, and it is not avoidable by
classifying the calls as service.

## 4. Purely inbound has no identified registration mandate

TCCCPR's operative language concerns a Sender who **makes, sends, causes or authorises** an
outbound commercial communication. Nothing was found requiring registration because a
business ANSWERS a consumer-originated call.

⚠ **A TEXTUAL CONCLUSION, NOT AN EXPRESS EXEMPTION** — no provision says "inbound is exempt",
and any callback, follow-up or other outbound communication is assessed separately. But for
an inbound-only AI receptionist this is a real answer, and it is the cleanest product shape
in this whole file.

## 5. A voice header process EXISTS — for 140, and only for 140

Seven steps, from VILPOWER's and Tata's implementations:

1. PE and TM establish an approved mapping (VIL: **mandatory before a TM can allocate 140
   Voice Headers**)
2. A 140 number is allocated to the TM
3. The TM registers that number as a **Voice Header / Header CLI** for the PE
4. The PE accepts or approves it
5. The operator approves it
6. On Tata's implementation the PE also registers a **Voice Template, including the sample
   spoken transcript**
7. The approved 140 CLI is presented on calls

⚠ **STEP 6 IS NEW TO THIS REPOSITORY AND HAS A PRODUCT CONSEQUENCE.** A Voice Template
carrying a sample spoken transcript is a registered, approved script. An AI agent that
composes its words at runtime does not obviously produce one. Nothing here says how a
generative agent satisfies a template requirement — and nothing here says it does not.

**BSNL's chain manual** says the selected TM-DF is treated as the final entity submitting
traffic to the telecom DLT network, and mentions a hash in a TLV parameter whose technical
process is *"shared separately with TM-DFs"* — not public, not stated to be voice-specific,
and not stated to contain the RTM ID.

## 6. The undocumented middle, which is where we live

Putting §3 and §5 together:

* **Registration is required** for commercial communication, including service calls (§3).
* **A documented header/template mechanism exists only for 140** (§5).
* **No equivalent workflow was found for ordinary DIDs.**

So a client calling their own consenting customers from an ordinary business number is
**required to register and has no published mechanism for the header half**. That is not a
permission and not a prohibition — it is a gap, and it sits exactly under this product.

TRAI's own 4 May 2024 direction is consistent with a regime still being built: it
acknowledged that **voice DLT had not been implemented**, that **140 operations were
occurring outside DLT**, and that real-time consent recording and scrubbing were therefore
not happening. It ordered Access Providers to implement DLT-based 140 voice and migrate
telemarketers — **without publishing SIP fields, CDR fields, API schemas or any RTM-ID
carriage mechanism**. As of 18 Sep 2026 the **Third Amendment remains a CLOSED CONSULTATION,
not a notified regulation.**

## 7. What this does to the ₹5,900 and the ₹50,000

**A TM registration is needed only if we place promotional calls on 140-series for client
PEs** (§1, §2). For an inbound receptionist plus service calls on ordinary DIDs, nothing
found puts a TM ID in the path.

The category question (TM-AF vs TM-DF, and the ₹50,000 deposit) stays open and is now
sharper rather than closer: Plivo says it is not the TM, while BSNL describes TM-DF as the
final entity submitting traffic to the DLT network — and the entity actually submitting is
the CPaaS. Those two do not obviously sit together.

## 8. Revised question list

**ANSWERED:** brief Q6 — transactional/service does NOT exempt registration (§3). §3a's "is
the CPaaS the TM" — no, per Plivo (§2), on the 140 leg only.

**STILL OPEN, in the order that spends money:**

1. **Does an ordinary-DID service call have a header/template obligation at all, and if so
   what is the mechanism?** §6's gap. This is now the highest-value open question: it governs
   the product's main path and no public source describes it.
2. **How does a generative AI agent satisfy a Voice Template requirement** that expects a
   sample spoken transcript (§5 step 6)?
3. **If we are the TM on the promotional leg, are we TM-AF or TM-DF** — and does the
   ₹50,000 deposit apply when the entity physically submitting traffic is the CPaaS?
4. **Confirm the Plivo sentence from a Plivo page.** The summary's citation points elsewhere
   (see this addendum's header). It is the sentence that makes us the Telemarketer.

---

# Addendum 2, 18 Sep 2026: the competitor's caller ID, and a correction to "unenforced"

## The observation

The founder placed a call through a competitor (Outpero) and read the caller ID off the
handset: **`+918765267389` — an ordinary 10-digit Indian mobile number.** Not 140. Not 160.

**EVIDENCE CLASS: DIRECT OBSERVATION**, by the founder, 18 Sep 2026. The strongest single
data point in this whole line of research, because it is a fact about what actually happens
on a live Indian call rather than about what a document says.

## What it establishes, and what it does not

**Establishes:** that competitor's outbound is **not in the 140 chain at all** — no Voice
Header, no PE–TM mapping, no Voice Template. Which is why no client of theirs pays ₹5,900:
the apparatus §5 of this file describes is simply not in their path.

It therefore also **disposes of the hypothesis** that they operate as the Principal Entity
for their clients. There is no PE registration to speak of on an ordinary mobile DID, because
there is no Header CLI to register.

**Does NOT establish:** whose name that number is in. A follow-up test would settle it — if
the SAME number appears for every client it is the platform's own; if it varies per client,
each client's number is being presented, which loops back to the caller-ID question §1 of
addendum 1 found unanswerable from primary sources.

## Why the whole market does this, and it is in our own BRD

`docs/BRD.md:326` already carried the commercial reason and nobody had connected it to the
compliance question:

> *"140-series promotional answer rates run 8–20% industry-wide (vs 45–65% on 160-series /
> recognized numbers)"*

**A compliant 140 promotional call is answered roughly one time in eight.** Recipients can
block 140 by sector under DND — TRAI's 10 July 2026 clarification says so explicitly — and
they do. So the mandate produces a trap: comply and the product barely functions; use an
ordinary number and it functions but sits outside the mandate.

That is not a loophole somebody discovered. It is the predictable outcome of a mandate whose
preventive machinery TRAI itself reported as unbuilt.

## ⚠ CORRECTION: "the enforcement machinery isn't built" WAS TOO LOOSE, AND IN THE DANGEROUS DIRECTION

Stated in conversation on 18 Sep 2026: *"a mandate whose enforcement machinery TRAI itself
says isn't built."* What TRAI's 4 May 2024 direction actually said is narrower — that **DLT
for voice** was unimplemented, so **real-time consent recording and scrubbing** were not
happening. That is the PREVENTIVE half.

**The PUNITIVE half is running at scale.** From the same brief, source 17 (DoT/TRAI UCC
enforcement statistics, 2025):

* **731,120 UTM notices** issued in 2025
* **1,84,482 disconnections** in 2025
* **₹153.8 crore** held in financial disincentives on TSPs

So the accurate statement is: **nothing stops the call going out, and the consequence arrives
afterwards, by complaint.** That is a worse risk shape than "unenforced", not a better one —
there is no gate to bounce off, only a bill that arrives later.

And the shape of the consequence matters here more than the volume. **TCCCPR Reg 25(6)
disconnects "all telecom resources of the sender" and blacklists that sender for up to two
years.** Whether "the sender" resolves to one client or to the account carrying every
client's traffic is **lawyer question 5 in the brief and is unresolved** — which is the
contagion risk this file's §7 already flagged, now with a number attached to how often
disconnection actually happens.

## The classification question that may make all of this moot

Before any decision about whether to follow the 140 mandate, there is a prior question nobody
has answered: **is this product's outbound PROMOTIONAL at all?**

The described use case is a client calling **their own existing, consenting customers** about
**that customer's own bookings, orders and appointments**. TCCCPR distinguishes promotional
from transactional and service communication, and the 140 mandate is aimed at the
promotional class.

**If these calls are service/transactional, the 140 mandate is not aimed at them and there is
no rule being worked around.** That is a correct classification, not a workaround — and it is
a far better place to stand than a decision to operate outside a mandate.

It is unresolved here and it is the single highest-value question left:

> **Are calls made by a business to its own existing, consenting customers about those
> customers' own bookings, orders or appointments PROMOTIONAL under TCCCPR — requiring
> 140-series — or TRANSACTIONAL/SERVICE? And separately: what is the practical exposure,
> for the client and for the platform, of the market's evident practice of promotional
> calling from ordinary DIDs?**

## What this does NOT change in the code

`apps/api/compliance/service.py` requires, for a DLT-governed dispatch, an entity chain and
**the agent's own DLT-registered bound number, never a shared pool** (`agent_outbound_number_blocker`).

**That gate is not relaxed by anything in this addendum.** Changing it is a decision with a
name on it and belongs in `docs/ROADMAP.md` with its reasoning, not in a quietly edited
check. `dlt_governed=False` already exists as a per-call-path selector for a genuinely
different regime (WhatsApp, §11 of the playbook); using it to route around the voice regime
would be the "satisfying the words while defeating the purpose" defect hard rule 12 names.
