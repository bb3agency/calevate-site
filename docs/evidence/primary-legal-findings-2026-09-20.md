# Primary-source legal findings, 20 September 2026

**EVIDENCE CLASS: PRIMARY-REGULATORY, FOUNDER-RELAYED.** Every host below is egress-blocked
from the build container (`trai.gov.in`, `dot.gov.in`, `indiacode.nic.in`, `egazette.gov.in`,
`meity.gov.in`, `www.airtel.in`, `www.tatatelebusiness.com`, `www.vilpower.in` — measured
20 Sep 2026). The founder ran three research passes against the official texts and relayed
them with verbatim quotations, section numbers and URLs. Quotations below are that relay.

This file exists because three questions this repository had been carrying as UNKNOWN are
now answered from operative text, and one of them found a live defect in our own code.

---

## 1. Outbound commercial voice calls may not use an ordinary DID

**This is the finding that changed code.** TRAI direction RG-25/(18)/2023-QoS (E-10291),
18 June 2024:

> "Senders shall not use any other 10-digit fixed line/ mobile number for making
> Promotional/ Service/ Transactional voice calls to their customers, either directly or
> through their employees or channel partners, DSAs, BPO partner, in-house or outsourced
> Call Centre, etc."

and:

> "Senders … shall ensure that they register their Voice Headers (i.e. indicators in 140 and
> 160 series) with any of the Telecom Service Providers (TSPs) and send the commercial
> communications through voice to the customers using such registered Voice Headers only."

**What we had**: `campaigns/service.SERIES_FOR_CLASSIFICATION` allowed `("160", "standard")`
for both `service` and `transactional`, so a campaign could launch dialling from an ordinary
DID. That is the number class the direction forbids by name.

**What it is now**: `("160",)` for both, `("140",)` for promotional, and
`tests/outbound_voice_header_series_test.py` states the rule as a subset so a fourth
classification is covered the day it is added.

**INBOUND IS UNAFFECTED AND THAT IS NOT A LOOPHOLE.** The direction binds a *sender making*
a call. A receptionist answering one the customer placed is not one, and
`SERIES_FOR_CLASSIFICATION` is consulted only on the campaign launch path. No official
source located says an inbound call on an ordinary DID needs a header.

**The series ladder moved and our prefix check already survives it.** TRAI has since
operationalised **1601** for service and transactional voice calls by entities outside BFSI
and government (direction dated 10 Aug 2026), and a phase-wise **1600** series for
RBI/SEBI/PFRDA-regulated entities (Sep 2026). `agents/models._REGULATED_PREFIXES` matches on
`startswith`, so a 1600- or 1601-series number recorded as `160` validates with no change.

## 2. There is no Voice Template obligation — OPERATIONS §2 gate 58 closes

The gate asked whether a 140-series promotional voice call carries a registered-script
obligation. **It does not, on every official source that could be read.**

* VILPOWER's own enterprise manual for 140-series promotional calls gives the path
  `Headers -> Voice Headers` and asks for a request name, mapped telemarketer, count,
  validity, circle and optional remarks. **No content, transcript, utterance, purpose
  declaration, character limit, variable placeholder or template id appears in the flow.**
* The content-template flow is a *separate* menu (`Content template -> + Add`) and is SMS
  throughout: the vendor's own form says **"actual SMS"**, the manual says "All new SMS
  templates", and the fields are an approved SMS header and a Template Message.
* TRAI's own 18 Jun 2024 circular heads the provision **"Registration of Content
  Templates"** and says "Senders are required to get **message** Content Templates also
  registered". It defines 140/160 Voice Headers separately and never calls anything a Voice
  Template.
* **No reviewed source says delivered call content is compared to anything.** The only
  scrubbing mechanism documented anywhere is titled "How will SMS Scrubbing take place".

**So the generative-agent problem the gate was opened for does not arise**: there is no
registered script for an LLM's output to diverge from. What is regulated for voice is the
NUMBER — PE/TM registration, header allocation, and dialling only from the allocated header.

**Absence of a matching statement is not proof no backend analytics exist**, and no live
form was submitted (doing so without an activated PE/TM mapping would itself create a
compliance record). A retest belongs after the VILPOWER registration activates.

## 3. The Rs 2 crore figure is real, and §3(7) is not what this repo assumed

Telecommunications Act 2023, **section 42(1)** (e-Gazette copy hosted by DoT eServices,
Gazette page 15) — the figure is in the section, **not in a Schedule**:

> "42. (1) Whoever provides telecommunication services or establishes telecommunication
> network without authorisation under sub-section (1) of section 3, or causes damage to
> critical telecommunication infrastructure shall be punishable with imprisonment for a term
> which may extend to three years, or with fine which may extend up to two crore rupees, or
> with both."

**The Third Schedule entry is a different offence and must not be quoted for this one.**
Third Schedule entry 2 penalises *use* of an unauthorised service "knowing or having reason
to believe" it is unauthorised, civil penalty up to ten lakh rupees. That one would reach a
CLIENT of an unauthorised provider, which is its own reason not to become one.

**Section 3(7) is a biometric-identification duty, not an impersonation provision:**

> "(7) Any authorised entity which provides such telecommunication services as may be
> notified by the Central Government, shall identify the person to whom it provides
> telecommunication services through use of any verifiable biometric based identification as
> may be prescribed."

It binds an *authorised entity* and only for services the Central Government later notifies.
Impersonation is §29(a); fraud in obtaining identifiers is §42(3)(e). Any reading of §3(7)
as the reseller-identification rule is wrong.

**The SaaS question itself remains open on the text, and the founder's research says so
plainly**: §3(1) requires authorisation to "provide telecommunication services", §2(t)
defines that as "any service for telecommunication", the Act does not define "provide", and
it creates no safe harbour for reselling licensed carriage. The characterisation turns on
whose name holds the account and the numbers, who controls origination and billing, and how
the service is presented — which is precisely why **Model B (D-474) holds no carrier account
at all**, and why `Settings.number_resale_authorization` gates every Model A path.

On UL-VNO: the located licence text permits a licensee to "appoint or employ franchisee,
agents, distributors and employees" while forbidding sublicensing — so an agent acts FOR the
VNO and does not hold delegated licence rights. "Authorised downstream reseller under the
VNO's licence" is too strong.

## 4. DPDP §12 does not excuse an erasure we cannot match — it simply does not address it

Read from the Act (Act 22 of 2023) and the DPDP Rules 2025 (G.S.R. 846(E), notified
13 Nov 2025).

**§12(3)**:

> "A Data Principal shall make a request in such manner as may be prescribed to the Data
> Fiduciary for erasure of her personal data, and upon receipt of such a request, the Data
> Fiduciary shall erase her personal data unless retention of the same is necessary for the
> specified purpose or for compliance with any law for the time being in force."

**There is NO equivalent of GDPR Article 11.** Nothing in the Act or the Rules says a
Fiduciary need not acquire further information to identify a principal, or may refuse a
request it cannot match. **So the defensive reading — "we could not identify them, so the
duty did not attach" — has no textual support.** Whether the duty reaches unmatchable data
is *not addressed* either way; the honest position is the one the certificate now takes,
which is to disclose the residue rather than claim completeness.

Two more provisions that bear on retention design:

* **§2(t)**: "'personal data' means any data about an individual who is identifiable by or
  in relation to such data". Whether a call we cannot attribute is still personal data turns
  on identifiability — but the text does not say how or when identifiability is lost.
* **Rule 8(3)** sets a **minimum one-year retention** of personal data, associated traffic
  data and processing logs for Seventh Schedule purposes. Any proposal to delete
  unattributable calls early meets this floor first.

**§§7-17 and Rules 5-16 are notified but NOT YET IN FORCE** — commencement G.S.R. 843(E)
places them eighteen months from Gazette publication. Our erasure obligation today is
contractual, not statutory. That is a reason the design must be right before the duty
arrives, not a reason to relax it.

## 5. Cross-reference: the thirty-minute transactional window is NOT of this file's class

A campaign classification gate landed on 20 Sep 2026 against the amended definition of a
transactional voice call — **"in response to Customer initiated transaction within thirty
minutes of the transaction"**, non-promotional with it (amended TCCCPR Regulation 2(bt)).
It is recorded here so the next reader does not mistake it for one of the readings above.

**Its class is REPORTED, one rung below the rest of this file.** The wording comes from
`number-series-inbound-vs-outbound-2026-09-13.md` §3.1 — a research agent's reading of the
Second Amendment Regulations 2025, founder-relayed on 13 Sep 2026 — not from a founder
reading of the operative text on 20 Sep. Nobody in this repository has opened the gazette
PDF; `trai.gov.in` is egress-blocked from this container. It may not reach a client-facing
compliance CLAIM without a re-read, and the gate below is careful to be a refusal rather
than a claim.

**What it changed.** `campaigns/service.DIALABLE_CAMPAIGN_CLASSIFICATIONS` is
`{promotional, service}`: a campaign filed as `transactional` is refused by
`classification_not_campaignable`, at launch and again on every dispatch tick, and the
refusal tells the client to file it as `service` (a non-promotional message to their own
customers) or `promotional` (anything that offers or markets), and that a genuinely
time-boxed call is placed by the instant-callback path instead. The reason it is a refusal
and not a validation is that the thirty minutes are measured from EACH RECIPIENT's own
action: a list dialled over hours or days cannot hold the property for its contacts, so the
classification was false by construction rather than merely unchecked.

**What it does NOT close, stated because the opposite is the natural assumption.** Every
gate in `campaigns/service.py` treats `service` and `transactional` identically — the same
160 series, the same absence from `preference_scrub.PREFERENCE_SCRUBBED_CLASSIFICATIONS`,
the same membership of `ATTESTABLE_CLASSIFICATIONS`. So this removes no escape that
`service` does not equally offer. What stands between a promotional list and the lighter
obligations of either label is `dlt_template_mismatch`: a registrar-approved DLT template of
the campaign's own class. Guard: `tests/transactional_campaign_classification_test.py`.

**Neither instant path was widened.** `ingest/service.py` (form submission → dial in
seconds) and `callbacks/service.py` (a callback the caller asked for mid-call) carry no
classification at all, so neither claims a lighter obligation and neither was touched.
