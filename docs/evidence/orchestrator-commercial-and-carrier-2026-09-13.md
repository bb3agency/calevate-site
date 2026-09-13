# Pipecat vs LiveKit: the commercial and carrier half, and what it found in the carrier

**Date:** 13 September 2026
**Companion to:** `docs/evidence/orchestrator-livekit-vs-pipecat-2026-09-12.md`, which settled the
technical comparison from source and deliberately left every commercial question open (its §8).
This document closes what can be closed, and records three findings about the CARRIER leg that
matter more to this product than the orchestrator choice did.

## 0. Evidence class — read this before quoting anything below

**Nothing in §§1–6 was read by this repository.** Every host involved is egress-blocked from the
build container, re-measured 13 Sep 2026:

```
www.plivo.com  plivo.com  trai.gov.in  www.trai.gov.in
dot.gov.in     developer.exotel.com    status.daily.co     all 000 (connect failed)
docs.pipecat.ai  docs.livekit.io  livekit.io  www.daily.co  blocked (measured 12 Sep)
```

The findings were produced by the founder's research agent and relayed. That agent labels its own
claims VENDOR-DOCS; **this repository cannot promote them to that class**, because nobody here
opened the page. Their class in this tree is:

> **REPORTED — research-agent reading, founder-relayed, 12 Sep 2026.**

Under hard rule 11 that is below VENDOR-PUBLISHED and may **not** reach `unit_cost_paid`, a wire
value, a rate card, or any client-facing claim without being re-read from the primary source. It is
recorded here so the next reader inherits the evidence *and its weakness*, not the conclusion.

Where a claim is corroborated by something this tree already holds at a stronger class, that is
stated explicitly — §5.3 is the important case.

## 1. The two questions the decision hung on

`orchestrator-livekit-vs-pipecat-2026-09-12.md` §9 named one combination that would reverse the
Pipecat choice: **a monthly floor comparable to LiveKit Ship's, AND no India region.** Both halves
had to hold. Neither does.

| Question | Answer | Class |
|---|---|---|
| Does Pipecat Cloud have a mandatory monthly floor? | **No.** No platform fee, subscription, seat fee or minimum spend listed. `$0` at zero usage. | REPORTED |
| Does Pipecat Cloud have an India region? | **Yes — `ap-south`, Mumbai**, appearing in ordinary deployment configuration with no enterprise-only qualification. | REPORTED |

**§9 is not triggered. The Pipecat decision stands.**

## 2. Runtime pricing, both candidates

| | Pipecat Cloud | LiveKit Cloud `Ship` |
|---|---|---|
| Monthly fee | none | `$50` |
| Runtime rate | `agent-1x` at `$0.01` per **active minute** | `$0.01`/agent-minute after allowance |
| Included | — | `5,000` agent min + `5,000` third-party SIP min |
| Included concurrency | `50` active sessions **per deployment** (default) | `20` concurrent agent sessions |
| Reserved capacity | optional, `$0.0005`/reserved minute | — |
| SIP media surcharge | none listed (carrier bills directly) | `$0.004`/min after allowance |

At our USD/INR planning rate the monthly runtime bill is:

| Billed runtime minutes | Pipecat | LiveKit Ship |
|---:|---:|---:|
| 0 | **₹0** | ₹4,775 |
| 500 | ₹478 | ₹4,775 |
| 2,000 | ₹1,910 | ₹4,775 |
| 5,000 | ₹4,775 | ₹4,775 |

⚠ The relayed report used `USD 1 = ₹95.50`, and an earlier relayed report from the same agent used
`₹95.7245`. **Neither is our rate.** `apps/api/core/fx.py` holds the live ladder (D-589) and
`billing/rates.py` holds the frozen plan rate; any figure that reaches a bill or a rate card is
struck from those, never from this table. The table is for ranking, not for money.

**They converge only at 5,000 minutes.** Below that Pipecat is cheaper by the whole floor, and at
zero — which is where this product is today and will be throughout the build — the difference is
₹4,775/month against nothing.

### 2.1 The billing risk nobody can close from a document

Pipecat bills **active session duration: instantiation + running + teardown**, not connected call
time, and **no startup duration, teardown duration or rounding quantum is published**.

For an inbound receptionist — many short calls, busy tones, early hangups — this is the difference
between a cost model and a guess. A 20-second call could plausibly bill closer to a minute, and
`usage_events.unit_cost_paid` would then carry a number derived from the wrong quantity. **It is a
trial measurement and it must happen before the first client minute is billed** (hard rule 7).

## 3. LiveKit's India entitlement is not established

The India SIP endpoint (`{sip_subdomain}.india.sip.livekit.cloud`) and the `ap-south` agent region
are both documented — but **whether either is available on the `$50` Ship plan is UNKNOWN.** The
region pages do not mark them Scale-only; the pricing page does not promise them on Ship.

This matters for the record rather than the decision: the "India SIP plus Mumbai worker"
architecture that made LiveKit attractive is **technically documented and commercially unproven at
the entry tier.** Anyone re-opening this comparison must settle that before treating it as a
like-for-like ₹4,775.

## 4. What stayed unknown, for both

Recorded so nobody re-derives it and nobody assumes silence means acceptable:

| | Pipecat Cloud | LiveKit Cloud |
|---|---|---|
| Numerical SLA + credit schedule | not found | not found |
| Public postmortems | not found | not found |
| 6–12 month incident count | not extractable | not extractable |
| DPA self-serve or sales-gated | not found | not found |
| Explicit "we do not train on customer data" clause | not found | not found |
| Where logs / traces / session metadata are stored | not found | not found |
| Default log retention, and whether configurable | not found | not found |
| Complete sub-processor list with locations | not found | not found |
| ISO 27001 | not found | not found |
| DPDP-specific terms | not found | not found |
| Charges for logs, storage, egress, build minutes | not found | n/a |
| Trial credits | not found | Build tier limits not verified |

**Neither vendor's region documentation is sufficient to support an India data-localization claim.**
Mumbai compute does not establish that control-plane data, logs, traces, crash dumps or support
access stay in India. That is a contract question, and this product has already withdrawn one
residency claim (D-449) for exactly this class of reasoning — see `CLAUDE.md`.

### 4.1 Turn detection is still unmeasured, and it is the number we most want

`orchestrator-livekit-vs-pipecat-2026-09-12.md` §4 established from source that both frameworks ship
semantic turn detection, and that this — not geography — is the term dominating our latency gap
(650 ms of inherited fixed-timeout endpointing, 1.3× the whole 500 ms voice-to-voice target).

**No published benchmark exists for either model** on precision/recall, false-endpoint rate,
time-to-decision, Telugu, Telugu-English code-switching, or 8 kHz G.711 telephony audio. A vendor
calling a detector "multilingual" is not evidence that it handles narrowband Telugu.

So the strongest engineering argument for leaving Bolna rests on a mechanism whose value to *this*
product is entirely unmeasured. That is not a reason to abandon it — it is the first thing the trial
must measure, and it is the reason the trial exists.

## 5. The carrier leg — where the real findings are

### 5.1 An irreversible account decision, before anything else

**Indian numbers require the Plivo organisation to be created in Plivo's India data region, and the
data region of an existing organisation cannot be changed.** Getting this wrong means abandoning the
organisation and creating another.

This is the first operational instruction of the whole migration and it precedes every line of code.

### 5.2 Calevate is a RESELLER, and that adds a stage to onboarding we have not designed

Plivo distinguishes:

- **Direct Brand** — one compliance application, for the brand's own calls.
- **Reseller** — **a separate approved compliance application for each customer.**

Calevate sells agents to other businesses. We are a reseller. Therefore **every tenant needs its own
compliance application, accepted, before that tenant's number can be rented or assigned.**

What each tenant must supply — any ONE of:

- GST Certificate with an active GSTIN
- Certificate of Incorporation with CIN
- Udyam Registration Certificate with a valid Udyam number

The first application must be **signed by an authorised signatory and carry a visible company
seal**. **PAN alone is refused.** Uploads are PDF/JPEG/PNG, ≤ 5 MB per file, filename ≤ 99
characters. A number can only be purchased once the application reads `accepted`, and purchase
carries a `compliance_application_id`. Numbers are owned by the main account and may be assigned to
a subaccount.

Approval is quoted as typically **5 minutes** for `022`/`080` landline numbers. For `140` and `160`
the SLA is described as separate and **its duration is not published**.

**This is a product finding, not a vendor detail.** It means the tenant lifecycle gains a gating,
human-signature-bearing KYC stage between "client signs up" and "client has a number" — with a
document store, a status the console must show, a blocked state the dial gate must respect, and a
per-tenant identifier (`compliance_application_id`) that belongs beside `phone_numbers`. None of
that exists today.

Also recorded: **calls from an Indian Plivo number must originate from a number rented on that
account** — arbitrary caller ID is not permitted. That is consistent with `CallContext.from_e164`
(D-420) and is a constraint the dial gate already has the shape to enforce.

### 5.3 160-series is BFSI-only — now CORROBORATED, not merely suspected

Plivo's own number-class table, as relayed:

| Class | Permitted use |
|---|---|
| Landline (`022`, `080`, …) | **Non-BFSI** businesses; service and transactional calls |
| `140` | Any business; **promotional only**; additional setup |
| `160` | **BFSI businesses only**; service and transactional; additional setup |

D-420 recorded, from a different source, that 160-series header registration requires an **RBI/SEBI
certificate** which *"a clinic, a salon or a coaching centre cannot produce"*. **Two independent
sources now say the same thing.** The 160-series exclusion of our vertical is no longer a single
unconfirmed reading — it is the working assumption.

### 5.4 ⚠ AND A DIRECT CONTRADICTION THAT DECIDES THE PRODUCT

The same table says landline series is for **non-BFSI businesses, service and transactional calls**.
The TRAI voice directive, as relayed in the same research, **prohibits using ordinary mobile or
fixed-line numbers for promotional, service or transactional commercial calls**. This tree's own
`docs/SECURITY-COMPLIANCE.md` §1 says 140 is *"exclusively for promotional robo-calls"* and 160 is
*"for transactional/service"* — with no third option.

Three statements, and they cannot all be true:

| If | Then |
|---|---|
| **Plivo is right** | A clinic can take and make service/transactional calls on an `022`/`080` landline number, and **D-420's conclusion that our SMB clients are 140-series-only is wrong.** |
| **TRAI is right** | The landline path is non-compliant for commercial calls, D-420 stands, and every clinic campaign is promotional on 140. |

**The stakes are the largest single number in the BRD.** `docs/BRD.md:322` records answer rates of
**8–20% on promotional numbers against 45–65% on 160-series/recognised numbers**. Whether our
clinics can place service calls at all is worth more than the entire orchestrator decision this
document was written to support.

**It is not resolved here, and must not be resolved by preferring either source.** Both are
REPORTED; both hosts are egress-blocked from this container. It needs the TRAI directive and
Plivo's India number page read from the primary source by a human, and the answer filed in
`docs/evidence/` with the date and reader — the same standard gate 20 applies to the Azure region.

**Until then, nothing may be built, priced, or promised on the assumption that a landline number can
carry a commercial service call.**

### 5.5 Exotel: not eliminated, not evaluable

Exotel supplies Indian numbers (ExoPhone) and documents a Voice Streaming / WebSocket integration,
and Pipecat lists Exotel among its telephony integrations (confirmed in-tree:
`src/pipecat/serializers/exotel.py`). Everything commercially decisive is **not found**: number
classes by circle, 140/160 availability, streaming eligibility per class, DLT responsibility split,
per-minute rates, monthly rental, concurrency and CPS limits, and any Exotel-authored Pipecat guide.

**Plivo is the better-documented fit** — it publishes a Pipecat integration demonstrating
`SarvamSTTService` + `SarvamTTSService` against a `+91` outbound call, which is very nearly our exact
architecture. Exotel may well offer better hands-on Indian regulatory support; that is a plausible
commercial belief and **not a documented fact**, and it should not move the decision until Exotel
supplies the list above in writing.

### 5.6 What Plivo does NOT tell us about DLT

Plivo clearly runs the **number-side** compliance workflow: collecting documents, reviewing
applications, linking accepted applications to numbers, and suspending an application after
unresolved UCC complaints.

The following allocation is **not established**, and every one of them is load-bearing for
`SECURITY-COMPLIANCE.md` §3's compliance gate:

```
who owns the tenant's DLT Principal Entity account
whether Plivo is the registered Telemarketer, or we must nominate one
who registers voice headers / originating numbers
who registers content templates
whether AI-generated dynamic speech must map to an approved template
who performs consent-template registration
whether Plivo performs DNC / NCPR scrubbing
whether Plivo enforces permitted calling windows
```

"`140` and `160` require additional setup" is not a responsibility matrix. **Our compliance gate
must keep assuming these are ours until a carrier contract says otherwise** — which is what it
already does, and this document changes nothing about it.

## 6. What only a trial settles

Ranked by what would most change a decision:

1. **Does Plivo/Exotel media actually reach the Mumbai worker**, or does it terminate TLS at a US
   edge first? Region documentation proves where the container runs, not where the packets go.
2. **`smart_turn` on real 8 kHz Telugu**: decision latency p50/p95, false-endpoint rate, and
   behaviour on short acknowledgements (అవును, సరే, హా, ఓకే).
3. **What an active minute actually bills** — connected time, or container lifecycle.
4. **Cold-start time without a reserved instance**, against inbound answer-time expectations.
5. Whether `022`/`080`, `140` and `160` each support bidirectional streaming.
6. Per-tenant compliance application turnaround for `140`/`160`.
7. Whether blind and warm transfer survive the provider-WebSocket architecture.
8. Written PE/TM/DLT responsibility split.

## 7. Standing conclusion

**Pipecat Cloud, with Plivo as the carrier**, unchanged from 12 Sep and now with the commercial half
supporting it rather than merely not contradicting it: no floor during a build phase of unknown
length, an India region, and the only publicly documented Pipecat + Sarvam + Indian-carrier
integration in existence.

Conditional on §6.1–6.4. And **independent of all of it**, §5.4 is the question this product should
answer first, because it decides what our clients can legally do with the thing we are building.
