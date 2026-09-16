<!-- EVIDENCE CLASSES IN THIS FILE, AND THE DISTINCTION IS LOAD-BEARING (hard rule 11):

     VERIFIED-VENDOR-SOURCE — read in this repository's own pinned tree, in this session.
       `pipecat-ai==1.10.0` under `.venv/`, hash-pinned by `uv.lock`. Cited `file:line`.
     RELAYED-VENDOR-PUBLISHED — a vendor page a research agent read on 16 Sep 2026 and the
       founder relayed. The URL and date are recorded so the next reader can re-check; NOBODY
       IN THIS REPOSITORY HAS OPENED THESE PAGES, because `www.plivo.com`, `api.plivo.com`
       and the Exotel doc hosts are egress-blocked from this container.
     RELAYED-REGULATOR — TRAI/DoT text, same route, same caveat.
     NOT PUBLISHED — the public sources were searched and did not answer. This is a FINDING,
       not an absence of research, and it is what the vendor question lists at the end exist
       to close.

     Nothing here is a decision. `docs/ROADMAP.md` is where a carrier gets chosen, and no
     entry has been written: the commercial half cannot be settled from public sources at
     all (see §6), so choosing now would be choosing without the deciding fact. -->

# Carrier evaluation: Plivo vs Exotel for the Pipecat leg (16 Sep 2026)

## Why this exists

D-592 replaced a rented voice engine with our own Pipecat container, which moved the carrier
from "something the engine dealt with" to a vendor we integrate directly. `voice_worker/
carrier.py` is the only module in this repository that knows the carrier is Plivo, and its
own docstring already recorded that no claim in it came from Plivo's documentation — the
host is egress-blocked, so every Plivo-shaped fact was read out of Pipecat's client of that
protocol instead.

This file is the first time the carrier question has been asked with the vendors' own pages
in evidence, and the first time Exotel has been considered at all.

## What we already had, and it is stronger evidence than anything relayed

**EVIDENCE CLASS: VERIFIED-VENDOR-SOURCE.** Pipecat ships first-class serializers for BOTH
vendors, and they differ in two ways this repository's code already cares about.

| | Plivo | Exotel |
| --- | --- | --- |
| Serializer | `pipecat/serializers/plivo.py` | `pipecat/serializers/exotel.py` |
| Audio on the wire | 8 kHz μ-law | 8 kHz PCM / Linear16 (`exotel.py:49`) |
| Dialled and calling number on the handshake | **`None`** — not parsed (`runner/utils.py:250-262`) | populated via `ExotelCallData` (`:283`) |
| Hangup from the serializer | ONE REST endpoint (`plivo.py:184`) | **no hangup path in the module** |
| Named as a supported provider | yes (`runner/utils.py:551`) | yes (`:551`) |

Two consequences for our code, both already true before any research was commissioned:

* `carrier.route_of` does NOT route by dialled number, because on Plivo there is none to
  route by. On Exotel there would be — that is a design the carrier choice would unlock
  rather than require.
* `carrier_routes.py:150` pins `contentType="audio/x-mulaw;rate=8000"` in the answer
  document. §1 below shows why that line is load-bearing: **Plivo's own default is
  `audio/x-l16`**, and Pipecat's Plivo serializer decodes μ-law. Inheriting the default
  would have produced garbled audio on the first call, with nothing naming the cause.

## §1 Real-time streaming

**RELAYED-VENDOR-PUBLISHED unless marked.**

| | Plivo | Exotel |
| --- | --- | --- |
| Feature | **AudioStream**; `POST /v1/Account/{auth_id}/Call/{call_uuid}/Stream/` with `bidirectional=true` (plivo.com/docs/voice/api/audio-streams) | **AgentStream**, via the Voicebot applet, a direct Connect API, or Legs `start_stream` (developer.exotel.com/docs/agentstream/developer-guide) |
| Outbound origination into a stream | `POST /Call/` with an `answer_url` returning XML carrying the stream instruction | `POST https://api.in.exotel.com/v1/accounts/{sid}/calls/connect` with `streamurl` and `streamtype=bidirectional` |
| Carrier → app format | configurable L16 @ 8/16/24 kHz or μ-law @ 8 kHz; **default `audio/x-l16;rate=8000`** | Linear16 PCM @ 8/16/24 kHz, 8 kHz default |
| App → carrier format | `playAudio` takes L16 or μ-law @ 8 or 16 kHz — note 24 kHz is NOT listed here | same PCM stream |
| ⚠ documented contradiction | — | the applet docs say Linear16 while the Legs API `start_stream` example says `audio/x-mulaw;rate=8000`. **Unresolved in public sources** |
| Max session | stream default 86,400s but the Call API's own max is 14,400s, so the call limit binds first | **Voicebot streams cap at 60 MINUTES**; `timelimit` up to 14,400s does not extend the stream |
| Concurrency | NOT PUBLISHED | `GET /activestreams` returns `max_allowed_streams` per account; the documented `100` is an example, not an entitlement. **Our limit NOT PUBLISHED** |
| Streaming surcharge | a stream object carries its own `bill_duration`/`billed_amount`, so it is metered separately — **India rate NOT PUBLISHED** | AgentStream is **expressly excluded from standard plans** and separately priced. **Rate NOT PUBLISHED** |
| Media-plane location | India numbers require an India-region organization, but the physical media-server location is **NOT PUBLISHED** | `api.in.exotel.com` is a Mumbai **API** endpoint; that is not a statement about where RTP/WebSocket media is anchored. **NOT PUBLISHED** |

**Consequence for the latency budget.** Neither vendor publishes enough to show compliance
with our 500 ms voice-to-voice budget. It is measurable and must be measured from Pipecat
Cloud `ap-south`: WebSocket RTT, first-media delay, interruption/`clear` latency, and a full
STT→LLM→TTS turn. A vendor's regional API endpoint is not evidence about the media path.

**The Exotel 60-minute stream cap is a product constraint, not a footnote.** Our Pipecat
manifest leaves `max_session_duration` at the platform default; on Exotel the carrier would
end the stream first.

## §2 Hanging up a live leg — where the two genuinely diverge

| | Plivo | Exotel |
| --- | --- | --- |
| Endpoint | `DELETE /v1/Account/{auth_id}/Call/{call_uuid}/`, HTTP 204 | "terminated using leg actions", but **no URL, method or body in public docs. NOT PUBLISHED** |
| Auth | HTTP Basic, `AUTH_ID`:`AUTH_TOKEN` | HTTP Basic, key:token (the scheme is published; the operation is not) |
| Works during an active stream? | documented for any ongoing call, but not explicitly for a streaming one — **include in acceptance testing** | NOT PUBLISHED |
| Stop-stream vs hang-up | separate: `DELETE …/Stream/{id}/` stops media, not the call | a stream `stop` event exists; nothing documents a message that ends the PSTN leg |

**TWO INDEPENDENT ROUTES AGREE HERE, WHICH IS WHY THIS IS THE STRONGEST FINDING IN THE
FILE.** Plivo's own docs describe the hangup; Pipecat's Plivo serializer implements exactly
one REST call and it is that one (`plivo.py:184`). Exotel's docs do not describe it and
Pipecat's Exotel serializer has no hangup path. The vendor's documentation and an
independent implementer of that documentation reached the same conclusion separately.

**Why it is money and not tidiness.** `sources` describes `PLIVO_AUTH_ID` as *"read by
Pipecat to hang the call up; a leg nobody hung up goes on billing."* Closing a WebSocket is
not hanging up a phone call. On Exotel this is currently an unknown with a meter running.

## §3 Outbound dialling

| | Plivo | Exotel |
| --- | --- | --- |
| Answering-machine detection | `machine_detection` on call creation, async result to `machine_detection_url`, can hang up on detection | published, **documented as beta**, ~3–5s async result, returns `human`/`machine`/`notsure`/`na`, docs state **~60–75% accuracy** (a vendor blog claims 80%; the docs win) |
| AMD cost | NOT PUBLISHED | NOT PUBLISHED |
| **Client's own number as caller ID** | **NOT SUPPORTED IN INDIA** — Verified Caller ID is unavailable; outbound must use a Plivo-rented Indian number under an accepted compliance application | **NOT PERMITTED** — masking an owned number as caller ID is disallowed; calls present an Exophone |
| Per-client regulatory identity | documented: "Reseller" mode, a separate compliance application per customer, each associated with the rented number | **NOT PUBLISHED** whether each client can be mapped as a separate regulatory sender |

⚠ **NEITHER VENDOR CAN PRESENT A CLIENT'S OWN NUMBER ON OUTBOUND IN INDIA.** This is a
product fact, not a configuration gap, and it is the same on both. Checked against
`apps/web/src` on 16 Sep 2026: no marketing or console copy currently promises otherwise, so
nothing needs correcting — but nothing may start promising it either.

## §4 Numbers and the regulatory structure

**RELAYED-REGULATOR.** TRAI's clarification of 10 July 2026 (PR No. 91 of 2026): **140xx is
mandated for promotional calls by entities in any sector**, while **1600xx is for
service/transactional calls from RBI-, SEBI-, IRDAI- and PFRDA-regulated entities and
government**. A phased 1601-series rollout for further specified sectors began Aug 2026.

⚠ **THIS REFRAMES THE QUESTION, AND OUR OWN BLUEPRINT ALREADY HALF-KNEW IT.**
`docs/FLOWS.md:524` records **140-series → Vobiz, 160-series → Plivo**, and
`docs/LEGAL-SURFACE.md:1284` already says the 160-series route requires an **RBI/SEBI
certificate**. Put beside the TRAI text: **our SMB clients are not BFSI, so 160/1600 is not
available to them at all.** Their outbound path is 140-series — which our blueprint routes
through a THIRD vendor, and which:

* **Plivo publicly lists**, available to any business making promotional calls, with
  additional setup. Cost and activation SLA NOT PUBLISHED.
* **Exotel does not publish** a procurement page, price, eligibility process or SLA for.

So "Plivo vs Exotel" is not the whole outbound question. The real one is which carrier can
**stream AND serve 140-series for a reseller** — and whether Vobiz, which our blueprint names
for 140, can stream at all. That last is unasked and unanswered.

### PE / TM and DLT

| | Plivo | Exotel |
| --- | --- | --- |
| Multi-tenant model | "Direct Brand" vs "Reseller"; a reseller submits a separate compliance application per customer. Does not publicly map these onto TCCCPR's PE/TM registrations | **NOT PUBLISHED** whether Exotel registers us as TM, each client as PE, validates existing registrations, or is itself the registered TM |
| What the vendor does | accepts compliance applications, binds one to each number, surfaces UCC complaints with proof deadlines, enforces suspensions. Does NOT promise to complete a client's external PE/TM registration | documents account KYC and an NCPR whitelist mechanism; no current end-to-end voice-DLT responsibility matrix found |
| Pre-dial NCPR/DND scrubbing | NOT PUBLISHED that every Voice API destination is scrubbed before dialling — **do not assume** | a whitelist mechanism is documented (an NCPR subscriber who contacted an Exophone is whitelisted for transactional calls for six months); the present 140/160 DLT scrubber workflow is not |
| Complaint liability | proof of opt-in within five business days; unresolved complaints can block the compliance ID and escalate to suspension. Obligations sit on the sender. No published indemnity allocation for PE vs TM vs SaaS reseller | **NOT PUBLISHED** |

**WE ARE A MULTI-TENANT RESELLER, AND THAT IS A REGULATORY STRUCTURE RATHER THAN A BILLING
ARRANGEMENT.** Every client is a Principal Entity and Calevate is the Telemarketer
(`CLAUDE.md`, domain vocabulary). A carrier with no documented way to express that
relationship cannot onboard client #2, whatever its price. Plivo publishes one; Exotel's is
the single largest NOT PUBLISHED in this file.

### AI-generated voice calls

No final TRAI text creating a synthetic-voice disclosure rule was found by either route. A
draft Third Amendment consultation ran during 2026 and a BSNL **stakeholder submission**
discusses advance DLT declaration for A2P/robo-calls — **stakeholder material is not a
direction and must not be cited as one.** Neither vendor publishes an India policy on
synthetic-voice calls.

This does not relax anything for us: hard rule 5's disclosure obligation is OURS and is
enforced server-side regardless of what any regulator requires of a carrier.

## §5 Data and compliance

| | Plivo | Exotel |
| --- | --- | --- |
| India region | Indian numbers require an India-region organization, and the region cannot later be changed. Data-centre operator/city NOT PUBLISHED | Mumbai API endpoints published; media, recordings, CDRs, backups and support copies NOT addressed |
| Live audio processing location | NOT PUBLISHED | NOT PUBLISHED (a vendor blog claims "India infra" — a blog is not a data-location commitment) |
| Recording default | optional on the Calls API; India default retention NOT PUBLISHED | opt-in rather than default-on; **90-day default retention**, subject to account and plan |
| Retention configurable / deletable | NOT PUBLISHED | recording can be omitted; exact retention choices, minimum retention and deletion behaviour NOT PUBLISHED |
| DPDP / DPA | NOT PUBLISHED | a vendor-authored DPDP guide exists (guidance, not contract); the FAQ offers a DPA **on request for enterprise accounts processing EU data** — not a promise to every low-spend Indian account |
| Training / secondary use of call content | **NOT PUBLISHED** | **NOT PUBLISHED** |

⚠ **THE TRAINING QUESTION IS UNANSWERED FOR BOTH, AND WE HAVE BEEN HERE BEFORE.** The Sarvam
reading (27 Aug 2026) found a ToS clause permitting model training on Inputs and Outputs,
which narrowed a client-facing promise. Our promise in `/legal/dpa` cl.2, `/legal/privacy` §6
and `/legal/subprocessors` §3.4 is unqualified; a carrier that may analyse or train on call
audio would narrow it again. **A no-training clause is a contract requirement, not a
preference**, and neither vendor's public pages answer it.

## §6 Pricing — the finding is that there is no finding

**Neither vendor publishes the numbers this workload needs.** Not inbound or outbound India
PSTN rates in usable form, not number rental by series, and — critically — not the
bidirectional streaming rate, which both meter separately and neither prices publicly.

What IS published: Exotel's standard bundles (Dabbler ₹9,999/5 months, Believer
₹19,999/11 months, Influencer ₹49,499/11 months; 1 credit = ₹1) **explicitly exclude
AgentStream**, and Indian invoices add 18% GST. Plivo's Voice API bills from answer with a
60-second minimum and increment.

**WE SELL AT ABOUT ₹5/MIN WITH NO MONTHLY FEE.** The all-in carrier cost per billed customer
minute — including rounding behaviour and the streaming line item — is the number the
business model rests on, and it does not exist in public. **No carrier can be chosen on
public information.** That is the gate, and it is commercial rather than technical.

## §7 Onboarding, for a sole proprietorship

| | Plivo | Exotel |
| --- | --- | --- |
| Documents | one of GST certificate, Certificate of Incorporation, or Udyam registration; first application signed with a visible business seal. Without incorporation, GST or Udyam is the route | GST/MSME, Shop & Establishment, FSSAI or similar trade certificate, plus proprietor PAN, address/ID proof and photograph |
| Multi-tenant onboarding | documented: Reseller mode, one compliance application per client | NOT PUBLISHED |
| Self-serve | compliance applications and number rental in-console; AgentStream-equivalent entitlement may still need sales | signup, trial and KYC online; **AgentStream is a separate sales offering** |
| Published KYC time | ~5 minutes for 080/022; 140 and 160 have a separate, unpublished SLA | one page says under 30 minutes, the developer guide says 1–3 business days for review — **plan on 1–3 days** |
| Trial covers streaming? | NOT PUBLISHED | 7-day trial with ₹500 credits, but AgentStream is excluded from standard plans and not promised in trial |
| Time to first real streamed call | **NOT PUBLISHED** | **NOT PUBLISHED** |

## §8 Reliability

Status pages: `status.plivo.com`, `status.exotel.com`. Plivo reported intermittent India
inbound/outbound failures on 11 Sep 2026 (06:02–06:35 UTC, carrier-partner fix). Exotel
reported planned Gujarat disruptions on 7 and 12 Sep and a rolled-back Mumbai pilot-number
migration on 3 Sep.

Plivo's SLA defines priorities and exclusions but no general uptime percentage in the text
reviewed, and excludes carrier-related issues from support liability. Exotel advertises 99.5%
standard / 99.9%+ custom, without establishing that those apply to AgentStream, Indian PSTN
availability, or a low-spend account. Service credits NOT PUBLISHED for either.

A status page is not a substitute for synthetic call monitoring across Airtel, Jio, Vi and
BSNL destinations.

## What this file does NOT decide

Nothing. In particular it does not name a carrier, because §6 shows the deciding fact is
absent from every public source consulted. What it does establish:

1. **The strongest technical discriminator is the hangup** (§2), agreed by two independent
   routes, and it costs money when it is missing.
2. **The strongest structural discriminator is the multi-tenant compliance model** (§4).
   Plivo publishes one; Exotel does not. For a product whose second client is a regulatory
   event, that outranks price.
3. **The question is not two-way.** 140-series is what non-BFSI SMBs can actually use, our
   blueprint routes it through Vobiz, and whether Vobiz streams has never been asked.
4. **The commercial half is unanswerable from public sources** and needs two quotes.

## Appendix A — questions to put to PLIVO

Ask for written answers; a sales call that is not followed by email is not evidence.

1. India bidirectional AudioStream rate in INR, ex-GST, with the billing increment. Is it
   charged in addition to the PSTN minute?
2. India inbound and outbound PSTN rates for ordinary DID, 140-series and 160-series, with
   the billing trigger and increment, and the treatment of failed, ringing, voicemail and
   sub-60-second calls.
3. Monthly rental and one-time setup by number series.
4. AudioStream concurrency limit for our account, and how it is raised.
5. **Where is AudioStream media processed and terminated, physically?** Will you commit in
   writing to India-only media routing and recording storage for an India-region account?
6. Is `DELETE /Call/{call_uuid}/` supported while an AudioStream is active, and does billing
   stop at the 204?
7. AMD: charge per minute or per invocation, and any India-specific accuracy guidance.
8. 140-series: cost, eligibility documents, process and activation SLA. Same for 160-series.
9. **As a reseller with many SMB clients, exactly which DLT/TCCCPR registrations are ours,
   which are each client's, and which do you perform?** Who is the registered Telemarketer?
10. Is every Voice API destination scrubbed against NCPR before dialling, or is DND handled
    only after a complaint?
11. UCC complaint liability: how is it allocated between Plivo, Calevate as SaaS reseller,
    and the client as Principal Entity? Provide the contractual language.
12. Recording retention default, configurable range, guaranteed deletion time, storage
    location.
13. DPDP DPA, subprocessor schedule, breach notice, audit rights, and **an explicit
    no-training / no-secondary-use commitment covering call audio and transcripts**.
14. Minimum commitment, annual contract or onboarding charge for AudioStream in India.
15. Trial scope: can we place unrestricted outbound Indian calls with bidirectional
    streaming before signing?
16. Contractual uptime, service credits, and support response times at our spend level.

## Appendix B — questions to put to EXOTEL

The first four are gating. If any is unanswered, the rest do not matter yet.

1. **The exact API to terminate a live call leg**: URL, method, body, auth. Does it work
   while a Voicebot/AgentStream WebSocket is open, and does billing stop immediately?
2. **The multi-tenant compliance workflow.** We are a SaaS reseller; each SMB client is the
   Principal Entity and Calevate the Telemarketer. Does each client need its own Exotel
   account, a subaccount, or a per-client compliance application? Who registers whom?
3. **140-series numbers**: do you provision them, at what cost, under what eligibility
   documents, and with what activation SLA?
4. **AgentStream pricing**: per-minute rate ex-GST, whether it is additional to the PSTN
   minute, minimum spend, and contract term.
5. Resolve the documented format contradiction: the Voicebot applet documents Linear16 while
   the Legs API `start_stream` example specifies `audio/x-mulaw;rate=8000`. Which applies to
   a direct `calls/connect` integration, and is it configurable?
6. The 60-minute Voicebot stream cap: is it raisable, and what happens to the PSTN leg when
   it is reached?
7. AgentStream concurrency included at low volume, and how `max_allowed_streams` is raised.
8. **Where is AgentStream media processed and terminated, physically?** `api.in.exotel.com`
   is an API endpoint; will you commit in writing to India-only media and recording storage?
9. All-in inbound and outbound PSTN rates applicable to an AgentStream call, with billing
   trigger and increment, and the treatment of failed, ringing, voicemail and sub-60-second
   calls.
10. Number rental by ordinary DID, mobile, 140 and 1600/1601 series.
11. AMD: is it GA or still beta, what does it cost, and what is current India accuracy?
12. Current 140/160 DLT voice scrubbing mechanics: who performs the NCPR check, and when
    relative to dialling?
13. UCC complaint liability allocation between Exotel, Calevate, the client PE and the
    underlying Access Provider. Provide the contractual language.
14. Recording retention: configurable range beyond the 90-day default, guaranteed deletion
    time, and storage location.
15. DPDP DPA availability for a low-spend Indian account, subprocessor schedule, and **an
    explicit no-training / no-secondary-use commitment covering call audio and transcripts**
    — including any AI or analytics services applied to our calls.
16. AgentStream activation time from signed order, support tier, uptime SLA and service
    credits.
17. Is AgentStream available during trial, with unrestricted outbound Indian calling?
