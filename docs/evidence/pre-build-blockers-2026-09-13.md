# Before the first line of Pipecat code: what is settled, what is asked, what blocks nothing

**Date:** 13 September 2026
**Purpose:** collect every external question the orchestrator migration raised, name who can
answer each, and separate the ones that block **code** from the ones that block only the **first
live outbound call**. The second group is much larger than the first, and the first is nearly
empty — which is the point of this document.

## 0. The decision, so nobody re-litigates it

**The orchestrator is Pipecat.** Recorded at
`docs/evidence/orchestrator-livekit-vs-pipecat-2026-09-12.md` §7, on five grounds read from
source at pinned commit `f67c18af` — chiefly that `src/pipecat/transports/livekit/` exists while
LiveKit Agents ships no Pipecat pipeline, so the choice preserves the alternative and the reverse
would not.

§9 of that document named the one thing that would reverse it: a monthly floor comparable to
LiveKit Ship's **and** no India region, both required. `docs/evidence/
orchestrator-commercial-and-carrier-2026-09-13.md` §1 established neither holds — no mandatory
floor, and `ap-south` (Mumbai) self-serve. **The decision stands and is not open.**

**The carrier is Plivo**, on the same two documents: first-class `plivo.py` serializer in-tree,
the only published Pipecat + Sarvam + Indian-carrier integration in existence, and a documented
India compliance API. Exotel stays a live alternative and is not eliminated — it is
**unevaluable** on public material (`orchestrator-commercial-and-carrier` §5.5).

### 0.1 Three architecture decisions, founder, 13 Sep 2026

Asked because each genuinely forks the work, and answered so nothing downstream has to guess:

| Fork | Decision | What follows |
|---|---|---|
| **Where the worker runs** | **Pipecat Cloud, `ap-south` (Mumbai)** — not our own VPS | They own scaling, rolling deploys and call draining, which is the operational burden a one-person team should not carry. It also **promotes P-1 and P-4 from curiosities to blockers on the first billed minute**: what an "active minute" covers, and whether Plivo media reaches Mumbai without a US hop. A Pipecat Cloud account is now needed — added as BLOCKER-2. |
| **First milestone** | **Inbound and outbound together** — full parity before anything ships | The adapter targets the whole 27-operation protocol rather than an inbound subset, and the conformance suite must pass in full. Outbound still cannot dial a client until the §6 carrier letter is answered, but the code does not wait for it. |
| **The Bolna adapter** | **Keep it selectable; delete it in one commit once Pipecat has placed a real call** | Hard rule 2's conformance suite exists precisely so several adapters coexist and `Settings.engine` chooses. A broken Pipecat path then never leaves this product with no working engine. The deletion is a planned, single, reviewable commit — not a slow rot of dead code. |

> ### ⚠ BLOCKER-2 — a Pipecat Cloud account, with `ap-south` selected
>
> Follows directly from the first decision. Needed to answer P-1 through P-7, and to measure
> cold-start time against inbound answer expectations before we promise anything.
>
> **Owner:** founder. **Blocks:** the billing model and the first deploy, not the code.

## 1. WHAT BLOCKS CODE: one account action, nothing else

**The regulatory questions in §3 do not block the build.** They decide *which number we dial
from*, not how the pipeline works. The Pipecat worker, the adapter against our 27-operation
`VoiceEngine` protocol, the conformance suite, the control-plane operations that move in-house —
all of it can be written, tested and reviewed before any of §3 is answered.

The one thing that must happen in the right order:

> ### ⚠ BLOCKER-1 — create the Plivo organisation in the **India data region**
>
> Indian numbers require it, and **an existing organisation's data region cannot be changed**
> (`orchestrator-commercial-and-carrier` §5.1). Getting this wrong means abandoning the account
> and starting over.
>
> **Owner:** founder. **Cost:** none. **Blocks:** any carrier-facing work, including obtaining
> test credentials.

Everything else in this document blocks the first live call, not the first commit.

## 2. WHAT WE CAN START IMMEDIATELY

In dependency order, none of it waiting on anybody:

1. **The adapter spec** — map the 27 `VoiceEngine` operations onto Pipecat; specify the ten that
   have no vendor equivalent and move into our control plane (`create_agent`, `update_agent`,
   `get_agent`, `delete_agent`, the four KB operations, `set_llm_credential`, `list_voices`).
2. **The tenant-lifecycle change** for the per-tenant carrier compliance application
   (`orchestrator-commercial-and-carrier` §5.2) — a gating, human-signature-bearing KYC stage
   with a document store, a console status, a blocked state the dial gate respects, and a
   `compliance_application_id` beside `phone_numbers`. **None of it exists today.**
3. **The Pipecat pipeline itself**, locally: Sarvam `saaras:v4` STT → our BYOK LLM → Sarvam
   `bulbul:v3` / Cartesia TTS, with `smart_turn` turn detection. No account needed; it is a
   library.
4. **Regulation 4 autodialer notice** as a product object — advance written notice to the
   originating access provider before any autodialled campaign. We implement nothing like it
   (`number-series-inbound-vs-outbound` §3.3).
5. **Metering that records both quantities** — connected carrier duration AND Pipecat active
   session duration. Designing for both now costs nothing and closes §4.1 without a migration.

## 3. WHAT MUST BE ASKED, AND OF WHOM

### 3.1 The carrier's India compliance team — Plivo

Ask **inside the compliance-application thread** at KYC submission, not L1 support. The draft
letter is §6.

| # | Question | Why it matters |
|---|---|---|
| C-1 | Under what TRAI regulation, direction, DoT order or Code-of-Practice clause may a non-BFSI private medical clinic make **service voice calls** from its DLT-registered ordinary geographic DID rather than a `1601` number? | The whole outbound service-call class |
| C-2 | Does bidirectional **media-streaming WebSocket** work on every Indian number class you issue — `022`/`080` landline, `140`, `160`? | Pipecat's transport depends on it; unverified per class |
| C-3 | Monthly rental and per-minute inbound/outbound rates for each Indian number class | No public prices found anywhere |
| C-4 | Approval SLA for `140` and `160` applications (you publish ~5 minutes for `022`/`080`; these are described as separate and the duration is unpublished) | Onboarding time per tenant |
| C-5 | Concurrent-call and calls-per-second limits on an India account | Campaign pacing design |
| C-6 | Is **caller ID preserved** end to end, and does `P-Asserted-Identity` survive? | The dial gate approves a number that must actually ring |
| C-7 | Do **blind and warm transfer** work over the media-streaming path, as opposed to SIP? | A declared `VoiceEngine` capability |
| C-8 | **Who registers the DLT Principal Entity, the Telemarketer, the voice header and the content templates** — you, the clinic, or us? | Unallocated in every document read |
| C-9 | Do you perform **DNC / NCPR scrubbing**, or must we? And do you enforce calling windows? | Our compliance gate assumes these are ours |
| C-10 | In your reseller model, is **Calevate** a Telemarketer with Aggregator Function, or an unregulated software processor? | Decides whether we need our own registration |

### 3.2 The DLT platform desk — TATA portal

D-420 records ₹5,900 PE registration there with a director-signed LOA.

| # | Question |
|---|---|
| T-1 | For a private medical clinic registering as Principal Entity **for voice**, what number series do you allot for service calls **today**? |
| T-2 | What happens to that allotment when healthcare is notified for `1601`? Is there a migration path or a re-registration? |
| T-3 | Is there a **voice header** concept distinct from an SMS header, and does a 10-digit DID get registered as one? *(This is §2.5's open clause in `number-series-inbound-vs-outbound` — the branch of Reg 3(1) the whole model may rest on.)* |
| T-4 | Must a **voice script** be registered as a content template, and how is that satisfied by dynamic AI speech? |
| T-5 | Current fee and turnaround for PE registration, and what an authorised signatory must produce |

### 3.3 Indian telecom counsel — before client #1 dials

One narrow question, a few hours of their time, not a retainer. Brief in §7.

### 3.4 TRAI — free, slow, parallel

A written query. They may not opine on a private commercial arrangement, but **having asked is
itself evidence of good faith** if anyone later questions it. Same question as counsel's.

### 3.5 Pipecat / Daily — a trial account settles these

| # | Question |
|---|---|
| P-1 | What exactly does a billed **active minute** cover — connected time, or container start and teardown? For a 3-minute call, how many minutes bill? |
| P-2 | Rounding quantum, and whether a failed pre-answer session bills at all |
| P-3 | **Cold-start time** without a reserved instance, against inbound answer expectations |
| P-4 | Does Plivo media reach the **Mumbai** worker, or terminate TLS at a US edge first? |
| P-5 | Charges for logs, metrics retention, storage, egress, build minutes |
| P-6 | DPA: self-serve or sales-gated; and the explicit no-training-on-customer-data clause |
| P-7 | Numerical SLA and credit schedule |

### 3.6 Measurements only a real call can produce

| # | Measurement |
|---|---|
| M-1 | `smart_turn` decision latency p50/p95 on **8 kHz Telugu** |
| M-2 | False-endpoint rate on short acknowledgements — అవును, సరే, హా, ఓకే |
| M-3 | Telugu-English **code-switch** false-interruption rate |
| M-4 | Voice-to-voice p50/p95/p99 from Airtel, Jio and Vi handsets |
| M-5 | Whether the 650 ms of inherited turn-detection latency actually falls, and by how much |

M-5 is the one that justifies the whole migration. Everything else in this document is
housekeeping beside it.

## 4. WHAT WE MUST NOT DO WHILE THESE ARE OPEN

From `number-series-inbound-vs-outbound` §7, restated because it is easy to forget under delivery
pressure:

- Do not claim a clinic may make service calls from a geographic number **as settled** — nor that
  it may not. The position is a transition gap.
- Do not treat DLT registration of an ordinary DID as satisfying the special-series requirement.
- Do not write "unconditionally compliant with TCCCPR" anywhere.
- Do not cite another vendor's practice as authority for ours.
- Do not tell a client that inbound answering requires DLT registration. It does not, and saying
  so adds cost and friction for no legal reason.

## 5. THE ONE COMMERCIAL FACT TO KEEP IN VIEW

**The Sender is the clinic, not Calevate.** A first violation bars outgoing service on **every
telecom resource the Sender holds** for 15 days — including the practice's main phone line —
with restoration priced per resource and each DID on a SIP trunk counting separately.

A clinic losing its main number for a fortnight because of a campaign we ran ends that
relationship and the reputation behind it. **That is the largest single risk in this product**,
it lands on the client rather than on us, and our client contract must allocate it explicitly:
who registers as PE, who warrants the consent basis, who bears a misclassified campaign. That
belongs in the MSA beside the existing legal set, and is better drafted with counsel's answer in
hand than guessed at.

## 6. LETTER — to the carrier's India compliance team

> **Subject: Regulatory basis for service voice calls by non-BFSI healthcare entities**
>
> We are onboarding as a reseller and will be submitting per-customer compliance applications for
> private medical clinics. Before we do, we need to record the regulatory position in writing.
>
> **1.** Please identify the TRAI regulation, TRAI direction, DoT order or operative
> Code-of-Practice clause under which a non-BFSI private medical clinic may make **service voice
> calls** (appointment reminders, confirmations, reschedules — no promotional content) from its
> DLT-registered ordinary geographic DID, rather than from a `1601`-series number.
>
> We are aware that TCCCPR as amended on 12 February 2025 requires commercial communication to
> use registered headers or special-series resources (Regulations 3 and 22(1)(i)(A)), that DoT
> Order 16-2/2023-AS-III/TRAI/N115 of 30 June 2026 created the `1601` series, and that TRAI's
> direction of 10 August 2026 opened Phase I to utilities and logistics/courier only. Healthcare
> is not in that phase. We would like to understand the basis on which such traffic is carried
> today.
>
> **2.** Does bidirectional media-streaming over WebSocket operate on **every** Indian number
> class you issue — `022`/`080` geographic, `140`, `160`? Please confirm per class.
>
> **3.** What are the monthly rental and per-minute inbound/outbound rates for each of those
> classes?
>
> **4.** You publish an approval time of approximately five minutes for `022`/`080` compliance
> applications and describe `140` and `160` as having a separate SLA. What is that SLA?
>
> **5.** What are the concurrent-call and calls-per-second limits on an India account, and how
> are they raised?
>
> **6.** Is the caller ID we set preserved to the terminating network, and is
> `P-Asserted-Identity` carried?
>
> **7.** Do blind and warm transfer operate over the media-streaming path, as distinct from SIP
> trunking?
>
> **8.** In a reseller arrangement where each customer is the Principal Entity, **who registers
> the DLT Principal Entity, the Telemarketer, the voice header and the content templates** — your
> organisation, the customer, or ours?
>
> **9.** Do you perform DNC / NCPR preference scrubbing before connecting a call, and do you
> enforce permitted calling windows? If not, what evidence of our own pre-check do you require?
>
> **10.** In your reseller model, is a software platform that originates calls on the customer's
> behalf classified as a **Telemarketer with Aggregator Function**, or as a processor requiring no
> registration of its own?
>
> A written answer to question 1 in particular is a prerequisite for us placing customer traffic.
>
> **Sufficient answer to question 1 would read along these lines:** *"Until healthcare entities
> are notified for migration to the 1601 series, this carrier permits a duly verified private
> medical clinic to originate non-promotional service calls from the clinic's allotted ordinary
> business number, subject to PE/DLT registration, consent/customer-relationship requirements, DNC
> controls, autodialer notification and the carrier's applicable Code of Practice."*

## 7. BRIEF — to Indian telecom counsel

> **Matter:** number-series eligibility for AI-assisted service voice calls by private healthcare
> entities under TCCCPR as amended.
>
> **We need a short written opinion on one question:**
>
> May a private medical clinic, registered as a Principal Entity, place AI-assisted **service**
> voice calls — appointment reminders, confirmations, reschedules, containing no promotional
> content — from its DLT-registered ordinary 10-digit number, given that healthcare is not
> included in TRAI's Phase-I `1601` notification and no clinic migration deadline has been
> published?
>
> **The instruments we believe are operative:**
>
> - TCCCPR 2018, and the **Second Amendment Regulations, 2025** (notified 12 Feb 2025) —
>   particularly Regulations 3(1), 3(2), 4, 22(1)(d) and 22(1)(i)(A)
> - TRAI Press Release No. 11/2025, 12 Feb 2025
> - TRAI Direction on `1600` adoption, 19 Nov 2025, and on IRDAI-regulated entities, 16 Dec 2025
> - DoT Order No. **16-2/2023-AS-III/TRAI/N115**, 30 June 2026, creating `1601ABCXXX`
> - TRAI Direction No. **M-5/11/(1)/2022-QoS (E-6703)**, 10 Aug 2026, and PR No. 113/2026 —
>   Phase-I sectors
>
> **Five sub-questions, in priority order:**
>
> 1. Does Regulation 3(1)'s **"registered headers"** branch extend to voice calls — i.e. can a
>    DLT-registered 10-digit number satisfy it — or does the voice leg admit only the
>    special-series branch?
> 2. Does TCCCPR reach a business **answering** a subscriber-initiated inbound call at all? Our
>    reading is that it does not, because the operative definitions are framed as calls *"made by
>    a Sender to"* a recipient. Please confirm or correct.
> 3. Is an appointment reminder a **Service Voice Call** under Reg 2(bh)(i) rather than a
>    Transactional Voice Call, given Reg 2(bt)'s thirty-minute window?
> 4. Does an **interactive generative-AI voice agent** constitute a "Robo-Call" for Regulation 4,
>    and is advance notice required per sender, per campaign, per number or per objective?
> 5. Where a SaaS platform originates calls on a clinic's behalf using the clinic's number, what
>    is the platform's status in the telemarketer chain, and may one entity hold both Sender and
>    Telemarketer registrations?
>
> **We are not asking for a compliance programme** — only a written view on 1 and 2, with 3–5
> addressed briefly. We have the primary documents and can supply them.

## 7a. LETTER — to Gnani support, on the TTS leg and voice cloning

**Why this exists (founder decision, 13 Sep 2026).** Sarvam's public TTS API exposes no
clone identifier — `speaker` is a closed enum — so a cloned voice cannot be addressed through
it by any orchestrator (`number-series-inbound-vs-outbound` context; the Sarvam finding is in
the 12 Sep research). Gnani's cloning IS API-addressable and the founder ran it end to end in
Telugu on 6 Sep (`docs/evidence/gnani-evaluation-2026-09-06.md` §1.4, FOUNDER-OBSERVED).

**Scope: the TTS leg only.** Sarvam `saaras:v4` stays on STT — cloned voices are a TTS
problem, Gnani STT would save ₹0.05/call-minute (§1.2 of that evaluation), and Sarvam's STT is
first-class in Pipecat with Telugu support. Swapping it too would buy five paise and cost a
maintained integration.

**Q1 blocks the build.** If each utterance counts against the 60 req/min cap, Gnani TTS cannot
carry ten concurrent lines on the self-serve tier, and building the service first would be
building it for nothing.

> **Subject: Vachana TTS — concurrency limits, cloned-voice terms, and 8 kHz telephony output**
>
> We are building an AI voice-agent product for Indian SMBs and are evaluating Vachana TTS for
> the synthesis leg, with cloned voices as the primary reason. We hold a self-serve account and
> have run cloning successfully in Telugu. Five questions before we commit engineering to it.
>
> **1. The TTS rate limit — this is our blocking question.** Your pricing page prints
> **60 requests/minute** for Text to Speech, and prints a separate **20 concurrent sessions**
> figure for Speech-to-Text WebSocket but no concurrency figure for TTS.
>
> Over `wss://api.vachana.ai/api/v1/tts`, does **one open WebSocket session count as one
> request**, or does **each synthesis request within that session count separately**?
>
> This decides whether the product is possible: at ten concurrent calls, each producing roughly
> 4–5 agent utterances a minute, we would issue 40–50 synthesis requests a minute. Under the
> second reading we would exhaust the cap at steady state, before any peak.
>
> **2. Is there a concurrent-session limit for TTS WebSocket**, and what is it? If the
> self-serve limits are too low for us, what tier raises them and at what price?
>
> **3. Cloned voices — commercial and legal terms.** Your pricing page lists TTS at
> Rs 27 / 10,000 characters. For a cloned voice created through Voice Cloning:
> - Is synthesis billed at that same rate, or is there a premium?
> - Is there a one-time charge to create a clone, and how many may one account hold?
> - **What rights does Gnani take over the uploaded reference audio and the resulting voice
>   embedding?** Our customers are clinics, and the voice will often be a named doctor's. We
>   need to tell them, in writing, who may use that voice and for what.
> - Is the reference audio or the embedding used to train or improve any Gnani model?
> - How long is a `speaker_embedding` valid — is it a permanent artefact we may cache, or does
>   it expire or require regeneration?
>
> **4. Telephony audio format on the cloned-voice endpoint.** Our calls run over an Indian PSTN
> carrier at **8 kHz G.711**. The cloned-voice documentation shows a default `audio_config` of
> 44100 Hz linear PCM.
>
> Does the cloned-voice endpoint (`model: vachana-vc-v1`, over both REST and
> `wss://api.vachana.ai/api/v1/tts`) accept **8 kHz mu-law output directly**? If it does not, we
> must resample every utterance, which costs latency on a budget we are already tight against.
>
> **5. Latency and reliability.** Do you publish a time-to-first-audio figure for cloned-voice
> synthesis over the WebSocket endpoint? Is there an SLA, a status page, or a DPA available to
> self-serve customers? And does Gnani offer a Data Processing Agreement suitable for a customer
> handling Indian health-adjacent personal data under the DPDP Act?
>
> A precise answer to question 1 is what we need first; the rest can follow.

**Filing the answer.** It goes into `docs/evidence/` with the date and who read it, and Q1's
answer is what converts `GnaniTTSService` from a plan into work. Until it arrives the TTS leg
stays on Sarvam Bulbul v3 and nothing is blocked — the swap is a service class and a config
value, not a redesign.

## 8. A cheap experiment worth running first

Place one inbound and one outbound call through Outpero and **record the exact number presented
on each leg.**

- Same ordinary number both ways → that is the market pattern, and a concrete data point to put
  to the carrier alongside question 1.
- Outbound on a `140` while inbound is ordinary → the market splits the legs by call class, and
  our design should too. That would be a design input, not merely a compliance one.

Costs nothing, and it sharpens every letter above.
