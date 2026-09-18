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
