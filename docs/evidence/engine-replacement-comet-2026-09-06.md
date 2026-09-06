<!-- EVIDENCE CLASS: REPORTED. Produced by the founder's Comet research run on 6 Sep 2026
     against the brief in the session that wrote it; the vendor pages it cites were read by
     Comet, not from this container (docs.sarvam.ai, www.bolna.ai, docs.livekit.io and the
     rest are egress-blocked here). Every VERIFIED label below is Comet's, and hard rule 11
     means it may not be restated as fact from this file alone — re-read the cited page, or
     the bolna-findings/ mirror where one exists, before any number here reaches money, a
     wire value or a client-facing claim. Stored verbatim apart from the expired chart link.
     The report ends after the first paragraph of "The case for staying on Bolna"; the
     founder confirmed that is the whole of it. -->

# Calevate voice-engine decision

**Read date:** 2026-09-06. **FX:** ₹88 = US$1.00 on every conversion in this document. **Pricing-page dates:** none of the vendor pricing pages cited below displayed an effective date.

**Verdict:** Do not replace hosted Bolna as the production engine. The only published bundled Bolna rate ($0.06/min = ₹5.28/min) already exceeds Calevate's ₹5.00/min client price, so the product only works if the unpublished BYOK platform slice stays near the **REPORTED** 2.0¢/min (₹1.76/min at ₹88). No scored alternative is cheaper than that reported slice at 1,000 and 5,000 minutes once inbound concurrency of 10 is honoured. The case against Bolna is real and is India-routing: BYOK calls are forced through US servers. That is a reason to **measure** the current stack and to **spike LiveKit Cloud in Mumbai**, not a reason to cut over.

## How this document treats evidence

A claim about a vendor is asserted only from that vendor's own page, docs, OpenAPI, SDK, GitHub, pricing, terms, privacy policy or DPA. Evidence class is attached at the point of use:

| Class | Meaning |
| --- | --- |
| VERIFIED | Primary page or source file read on 2026-09-06 |
| VENDOR-PUBLISHED | Vendor's own marketing or blog number, not an independent measurement |
| REPORTED | Calevate-observed (dashboard screenshot). Not on the vendor pricing page |
| ESTIMATE | Arithmetic from published inputs, with the inputs shown |
| UNKNOWN | Not filled. The page or mailbox that would close it is named |

Calevate facts in the next section are taken as given and are not re-researched.

## Calevate constraints (given)

- Multi-tenant SaaS. Telugu-first clinic inbound reception. Client price **₹5.00/min** flat, no monthly fee.
- Volumes to price: 1,000 / 5,000 / 20,000 call-minutes/month. **10 concurrent lines.**
- Hosted Bolna, US-east-1. BYOK: Sarvam Saaras STT, Sarvam Bulbul TTS, Azure OpenAI East US 2 `gpt-4o-mini` (moving to Gemini 2.5 Flash-Lite). LLM must be OpenAI-compatible `base_url` + static key per agent.
- Telephony: client-owned Plivo 160-series DLT numbers. Calevate holds no carrier credential.
- Bolna BYOK platform fee **unpublished**. Observed **2.0¢/min**, written here as ₹1.76/min at ₹88 (**REPORTED**). The brief's ≈₹1.84 used a different FX; this document does not.
- Bundled preferred-models rate **$0.06/min = ₹5.28/min** (**VERIFIED**).
- India residency is enterprise-only and **excludes BYOK**.
- Voice-to-voice latency has never been measured. Budget 500 ms p50 / 800 ms p95. Paper floor is endpointing 250 ms + 400 ms incremental delay before the model starts.
- Post-call: unsigned webhooks plus poll of executions; copy recordings to own storage; meter cost.
- Engine isolated behind Python `VoiceEngine`. Replacement cost is measured against that interface.

## Early eliminations

A platform that cannot take a customer-owned Indian DLT-registered number or a Plivo SIP trunk is out (rows 7 and 9). Telugu-first also requires `te-IN` on STT, not a marketing language list.

| Candidate | Result | Why |
| --- | --- | --- |
| Sarvam Voice Agents | Fail rows 7 and 9 | BYO telephony is Exotel, Twilio, Smartflo, Pulse, Intalk or Vobiz. Plivo is absent. Generic SIP inbound is absent. ([Bring Your Own Telephony](https://docs.sarvam.ai/conversations/deploy/telephony/bring-your-own.md), 2026-09-06, **VERIFIED**). Separate hard fail on BYOK: "Voice Agents does not support bringing your own models at any part of the stack" ([Build Your Voice Agent](https://docs.sarvam.ai/conversations/build/create-agent.md), **VERIFIED**). |
| Retell | Passes 7/9; blocked on Telugu | Language enum on Create Voice Agent has no `te-IN` (**VERIFIED**, [Create Voice Agent](https://docs.retellai.com/api-references/create-agent)). Do not treat "100+ LLMs" as Azure OpenAI v1; Retell custom LLM is OpenAI-compatible but Telugu is the hard stop. |
| Gnani, Ozonetel, Exotel, Knowlarity | Not scored | Public agent APIs, BYOK fields, concurrency and Plivo-as-customer-trunk are **UNKNOWN**. Demo-gated. Not eliminated on 7/9; not shortlisted. |
| Vobiz | Not an engine | Bolna's own DLT page uses Vobiz for **140-series** telemarketing, Plivo for **160-series** transactional. ([How to Get 140 and 160-Series Phone Numbers](https://www.bolna.ai/docs/guides/inbound/obtaining-regulated-phone-numbers.md), **VERIFIED**). Calevate is 160-series inbound reception. |

Survivors for the rest of this document: hosted Bolna, Bolna OSS, LiveKit Cloud, Pipecat Cloud, Vapi, Cartesia Line, Smallest Atoms, ElevenLabs Agents (Plivo named), self-host Mumbai VPS.

## Capability matrix

Legend: **N** = native on the published API or plugin. **W** = wrapper Calevate must host. **X** = absent from the docs at the cited URL (not the same as "unsupported"). **?** = UNKNOWN.

| Row | Bolna hosted | Bolna OSS | LiveKit Cloud | Pipecat Cloud | Vapi | Cartesia Line | Smallest Atoms | Self-host J |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 STT BYOK streaming Sarvam `te-IN` | N | ? | N | N | W | X | X | N |
| 2 TTS BYOK streaming Sarvam Bulbul | N (`bulbul:v2` preferred; `v3` **?**) | N historical | N default `v3` | N default `v3` | W | X (Sonic only) | X (own TTS) | N |
| 3 LLM Azure OpenAI v1 or OpenAI-compat `base_url` + key | N | N | N | N | N | ? | X in agent body | N |
| 4 Hosted config object, GET read-back | N | X (code is the agent) | X (`lk agent deploy`) | X (deployed image) | N | X (git deploy) | N (limited) | X |
| 5 Campaigns / batch outbound | N | N in OSS | X | X | N | X | N | W |
| 6 Knowledge base object | N | ? | X | X | N | X | X | W |
| 7 Numbers: customer Plivo DLT | N inbound setup | W (self SIP) | N SIP | N Plivo WebSocket | N SIP | N SIP any country | N SIP "any" | N |
| 8 Caller ID = that number | N | W | N | N | N | N | N | N |
| 9 Inbound bind to agent | N `allow_multiple` Plivo-only | W | N dispatch | N | N | N | N | W |
| 10 Blind / cold transfer | N | N | N | N | N | ? | N | W |
| 11 Warm transfer / whisper | X in public docs | X | N (beta) | W | N on Twilio; Plivo **?** | X | X | W |
| 12 Per-call script override | N | N | W (code) | W (code) | N | W | ? | W |

Sources for the N/X/? cells, all read 2026-09-06:

- Bolna STT `saaras:v4`, `te-IN`, `stream: true`, `endpointing: 250` — [Create Agent (v2)](https://www.bolna.ai/docs/api-reference/agent/create-v2.md). Preferred TTS still `elevenlabs` / `sarvam.bulbul:v2` — [Preferred models](https://www.bolna.ai/docs/pricing/preferred-models.md). Hosted Bolna accepting `bulbul:v3` is **UNKNOWN** (Pipecat's Sarvam plugin source states the Sarvam API now rejects v2, last touch 2026-09-03).
- Bolna inbound Plivo — [Setup Inbound](https://www.bolna.ai/docs/api-reference/inbound/setup-inbound.md). `allow_multiple` is Plivo-only — [Update Inbound Agent](https://www.bolna.ai/docs/api-reference/inbound/update-inbound-agent.md).
- LiveKit Sarvam STT/TTS streaming, default `bulbul:v3`, `te-IN`, last commit 2026-09-05 — [LiveKit Agents sarvam.py](https://github.com/livekit/agents/blob/main/livekit-plugins/livekit-plugins-sarvam/livekit/plugins/sarvam/tts.py) and [STT plugin docs](https://docs.livekit.io/agents/models/stt/plugins/sarvam/). Warm transfer — [WarmTransferTask](https://docs.livekit.io/recipes/warm-transfer/). Plivo SIP — [Plivo SIP trunking](https://docs.livekit.io/telephony/start/provider-specific/plivo/).
- Pipecat Plivo WebSocket `wss://api.pipecat.daily.co/ws/plivo` and regional `wss://{region}.api.pipecat.daily.co/ws/plivo` — [Pipecat Cloud Plivo WebSockets](https://docs.pipecat.ai/guides/telephony/plivo-websockets). `ap-south` self-serve — [Regions](https://docs.pipecat.ai/pipecat-cloud/regions). Sarvam TTS default `bulbul:v3` — plugin source 2026-09-03.
- Vapi custom LLM `base_url` + headers — [Fine-tuned OpenAI models](https://docs.vapi.ai/customization/custom-llm/fine-tuned-openai-models). Sarvam via Calevate-hosted WS/HTTP bridges — [Sarvam + Vapi](https://docs.sarvam.ai/cookbook/integrations/vapi.md). Warm transfer "supported on Twilio calls" — [Call forwarding](https://docs.vapi.ai/calls/call-forwarding). HMAC webhooks — [Server events](https://docs.vapi.ai/server-url/events).
- Cartesia Line SIP any country — [Line telephony](https://docs.cartesia.ai/line/docs/telephony). Ink STT + Sonic TTS built-in; BYO STT/LLM **absent from docs**.
- Smallest SIP "any provider" (Plivo not named) — [Your own telephony](https://docs.smallest.ai/atoms/phone-numbers/your-own-telephony). No Sarvam BYOK in the agent body.
- Bolna OSS: MIT, v0.10.230 tagged 2026-09-05, ≥100 commits in six months — [bolna-ai/bolna](https://github.com/bolna-ai/bolna). Hosted control plane is closed source. Sarvam **transcriber** in current OSS tree is **UNKNOWN** (README lists Deepgram; GitHub activity shows deleted `feat/sarvam-transcriber` branches). Releases mention Sarvam bulbul-2 TTS.

## Cost table

Plivo carrier minutes are **excluded** everywhere. Free tiers are not used (they cap at 1–3 concurrent; the product runs 10). Monthly floors are shown as monthly ₹ even at 1,000 minutes. No amortization of a seat fee into a per-minute that Calevate does not pay. No averaging of free and paid.

LiveKit Ship $50/month is treated as an **additive** monthly fee on top of $0.01/min agent + $0.004/min third-party SIP. The [LiveKit pricing page](https://livekit.io/pricing) (no date shown) does not state that the $50 is prepaid usage credit. If it is prepaid credit, 1,000-minute and 5,000-minute totals equal the floor only; that reading is **UNKNOWN**.

Pipecat "scale-to-zero" is shown and then discarded for inbound clinics: documented cold start is about 10 seconds. The honest clinic row is **10 reserved instances** at $0.0005/min each × 43,200 minutes/month = $216/month = ₹19,008, plus $0.01/min active. ([Pipecat Cloud pricing](https://docs.pipecat.ai/pipecat-cloud/pricing), no date shown.)

*(chart omitted — "Platform cost against Calevate client price of ₹5.00 per minute" — the source was a presigned S3 URL that expired)*

| Vendor / tier | Evidence | 1,000 min | 5,000 min | 20,000 min |
| --- | --- | --- | --- | --- |
| Bolna BYOK platform slice 2.0¢/min, ₹0 floor | **REPORTED** (dashboard). Not on [call-pricing](https://www.bolna.ai/docs/pricing/call-pricing.md) | ₹1.76/min · ₹1,760 | ₹1.76/min · ₹8,800 | ₹1.76/min · ₹35,200 |
| Bolna bundled preferred-models $0.06/min | **VERIFIED** [call-pricing](https://www.bolna.ai/docs/pricing/call-pricing.md). 30-second pulses. PAYG, no monthly floor | ₹5.28/min · ₹5,280 | ₹5.28/min · ₹26,400 | ₹5.28/min · ₹105,600 |
| LiveKit Cloud Ship $50 + $0.014/min | **VERIFIED** rates; additive-fee reading **ESTIMATE**. 20 concurrent included. Region pinning is Scale-only ($500 = ₹44,000) | ₹5.63/min · ₹5,632 | ₹2.11/min · ₹10,560 | ₹1.45/min · ₹29,040 |
| LiveKit Cloud Scale $500 + $0.013/min | Same sources. Required for 25 lines and for region pinning | ₹45.14/min · ₹45,144 | ₹9.94/min · ₹49,720 | ₹3.34/min · ₹66,880 |
| Pipecat Cloud scale-to-zero $0.01/min | **VERIFIED**. Cold start about 10 s. Not usable for inbound | ₹0.88/min · ₹880 | ₹0.88/min · ₹4,400 | ₹0.88/min · ₹17,600 |
| Pipecat Cloud 10-warm + $0.01/min active | **ESTIMATE** from published reserved and active rates | ₹19.89/min · ₹19,888 | ₹4.68/min · ₹23,408 | ₹1.83/min · ₹36,608 |
| Vapi $0.05/min, 10 lines included | **VERIFIED** [Vapi pricing](https://vapi.ai/pricing). Extra lines $10/line/month. US/EU only | ₹4.40/min · ₹4,400 | ₹4.40/min · ₹22,000 | ₹4.40/min · ₹88,000 |
| Retell $0.055 + Cartesia $0.015 | **VERIFIED** rates; Telugu blocked. Shown only so the ¢ is not tempting | ₹6.16/min · ₹6,160 | ₹6.16/min · ₹30,800 | ₹6.16/min · ₹123,200 |
| Cartesia Line $0.06/min | **VERIFIED**. No Sarvam BYOK in docs | ₹5.28/min · ₹5,280 | ₹5.28/min · ₹26,400 | ₹5.28/min · ₹105,600 |
| Smallest Atoms hosting $0.01/min | **VERIFIED** hosting slice. All-in $0.09–$0.21 uses Smallest STT/TTS, not Sarvam | ₹0.88/min hosting only | same | same |
| E2E C3.8GB × 2 boxes (compute only) | **VERIFIED** ₹3/hour, 4 vCPU / 8 GB, [E2E pricing](https://www.e2enetworks.com/e2e-pricing-page). GST extra. SIP server + Redis **UNKNOWN** | ₹4.32/min · ₹4,320 | ₹0.86/min · ₹4,320 | ₹0.22/min · ₹4,320 |

**Unit-economics test against ₹5.00/min.** The published Bolna bundled rate (₹5.28) loses money on every minute. Vapi (₹4.40) leaves ₹0.60/min before Sarvam, Azure, Plivo and GST. Cartesia Line matches bundled Bolna and leaves nothing. LiveKit Ship is more expensive than reported Bolna BYOK at 1,000 minutes (₹5.63 vs ₹1.76) and still more expensive at 5,000 (₹2.11 vs ₹1.76); it undercuts reported Bolna only at 20,000 minutes (₹1.45 vs ₹1.76) and only if the $50 is additive as modelled. Pipecat 10-warm is unusable at 1,000 minutes (₹19.89) and still worse than reported Bolna at 5,000 (₹4.68). Self-host compute looks cheap at 20,000 minutes and is not an engine cost: it is an on-call job.

Bolna's published sentence on BYOK is: "You only pay your providers directly, plus Bolna's platform fee." The fee amount is **not on the pricing page** (**UNKNOWN**, close via `cost_breakdown` on one BYOK execution or billing@bolna.ai).

## Concurrency table

| Platform | 10 lines | 25 lines | What is purchased | Evidence |
| --- | --- | --- | --- | --- |
| Bolna hosted API default | Fits | Unknown extra | `concurrency.max` default **10**, documented maximum 10 on the API field | **VERIFIED** [Create Agent (v2)](https://www.bolna.ai/docs/api-reference/agent/create-v2.md). Pilots plan "Upto 100 concurrent calls" is a **separate** commercial SKU at $600 = 12,000 minutes ([call-pricing](https://www.bolna.ai/docs/pricing/call-pricing.md)) |
| LiveKit Ship | Fits (cap 20) | Fail | Ship 20 concurrent. Scale "starts at 50", up to 600, $500/month | **VERIFIED** [Quotas and limits](https://docs.livekit.io/deploy/admin/quotas-and-limits/) |
| LiveKit Scale | Fits | Fits | $500/month = ₹44,000 floor before minutes | Same |
| Pipecat Cloud | Fits if 10 instances reserved | Fits if 25 reserved | 1 session per instance; max pool 50. Reserved $0.0005/min per instance | **VERIFIED** [Pipecat Cloud pricing](https://docs.pipecat.ai/pipecat-cloud/pricing) |
| Vapi | Fits (10 included) | +15 × $10 = $150/month = ₹13,200 | $10 per extra concurrent line per month | **VERIFIED** [Vapi pricing](https://vapi.ai/pricing) |
| Cartesia Line | Fits Startup 20 / fails Pro 12 | Fail both listed caps | Pro 12, Startup 20 | **VERIFIED** Line plans |
| Smallest Atoms PAYG | Fits | Fits (20 PAYG) | 20 concurrent, no extra concurrency fee on PAYG | **VERIFIED** [Atoms FAQs](https://docs.smallest.ai/atoms/faqs) |
| Self-host LiveKit OSS | Fits on 4 cores / 8 GB (docs: 10–25 jobs) | Borderline | [Self-hosted deployments](https://docs.livekit.io/deploy/custom/deployments/) | **VENDOR-PUBLISHED** capacity, not a Calevate load test |

Calevate's current Bolna default cap of 10 is exactly the sizing number. A second clinic on the same agent without a documented raise is a production incident, not a pricing footnote.

## Latency table

No vendor in this set publishes a Telugu + Sarvam Saaras + Bulbul v3 + Azure `gpt-4o-mini` voice-to-voice p50/p95. Calevate has never measured the current stack. The 500 ms / 800 ms budget is a Calevate number, not a vendor SLO.

| Path | Published number | Region | Transit vs US-hosted | Evidence |
| --- | --- | --- | --- | --- |
| Bolna default | None | AWS `us-east-1` | Baseline | **VERIFIED** [Security](https://www.bolna.ai/docs/concepts/security.md): "By default, Bolna processes calls on infrastructure in the US (AWS us-east-1)." |
| Bolna India residency | None | `ap-south-1` Mumbai | Removes the US hairpin **only if BYOK is off** | **VERIFIED** [Indian server configuration](https://www.bolna.ai/docs/enterprise/indian-server-configuration.md): "If you connect your own API keys for any provider (transcriber, synthesizer, or LLM), calls will automatically route through US servers regardless of other configuration settings." |
| Bolna turn-detection floor | 250 ms endpointing + 400 ms `incremental_delay` = 650 ms before the LLM is invoked | n/a | n/a | **VERIFIED** create-agent transcriber defaults. This floor is already 150 ms over the 500 ms p50 budget **before** STT, LLM, TTS or network |
| LiveKit Cloud Mumbai | About 1.67 s end-to-end | `ap-south` agent + `india` SIP | Uses GPT-4o + Cartesia + Deepgram, **not** Calevate's stack | **VENDOR-PUBLISHED** LiveKit India blog. Misses the 500 ms budget on a different, faster-English stack |
| Pipecat Cloud | Cold start about 10 s; no V2V SLO | `ap-south` self-serve | n/a | **VERIFIED** pricing/docs |
| Inter-region RTT used as transit assumption | 185.52 ms RTT `ap-south-1` → `us-east-1` | AWS regions, not a Hyderabad caller | **ESTIMATE** of orchestrator hairpin, not last-mile | [CloudPing](https://www.cloudping.co/) read 2026-09-06. Last-mile Hyderabad PSTN is **UNKNOWN** and is common to every candidate |

Assumption shown, not invented as a Hyderabad-to-Mumbai last-mile: one extra inter-region RTT of **185.52 ms** sits on every Bolna-BYOK turn that hairpins India → `us-east-1` → India. That is **ESTIMATE**, class-labelled, and it is **not** a 100–200 ms last-mile saving. A Mumbai orchestrator removes that RTT and does not, on LiveKit's own published 1.67 s figure, land inside 500 ms p50.

## The case for staying on Bolna

Staying is not inertia. It is the only option that is already a `VoiceEngine` behind a Python interface, already bound to client-owned Plivo 160-series numbers, and already native on all three BYOK legs including Sarvam `te-IN`.

**₹0 monthly floor.** Every scored alternative that is Mumbai-resident (LiveKit Ship, Pipecat 10-warm, two E2E boxes) introduces a monthly rupee number that Calevate does not charge the clinic. At 1,000 minutes that floor is ₹5,632 (LiveKit Ship additive), ₹19,888 (Pipecat 10-warm) or ₹4,320 (E2E compute only).