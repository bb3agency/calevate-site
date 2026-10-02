# Research consolidation, 6–7 September 2026 — engine, speech vendors, unit cost, graph agents

**What this is.** One document holding everything researched across 6–7 Sep 2026, in the
four Comet browser-research threads the founder ran and the two in-repo passes that
followed them. The source files live outside the repo (the founder's `Downloads/`); this
is the copy the repo keeps, with every figure carrying its evidence class and — where the
repo already holds a different number — the discrepancy named rather than smoothed over.

| Thread | Source artefact (founder's Downloads, 6–7 Sep) | Section |
| --- | --- | --- |
| Should Calevate replace Bolna, and with what? | `cometreplacebolnaprompt.md` → `Calevate voice-engine decision.md` | §2 |
| Gnani.ai as TTS / STT / platform / company | `cometgnaniresearchprompt.md` → `Gnani.ai Decision Document.md` | §3 |
| Cartesia TTS API verification + every way to cut ₹/min | `cometcartesiafinalverification.md` → `Cartesia TTS API Verification & AI Phone Call Cost Reduction — Calevate.md` | §4, §5 |
| Bolna graph agents — static-greeting hybrid | Comet passes (final one pasted 7 Sep) + mirror read | §6 → `docs/evidence/bolna-graph-agent-static-greeting.md` |
| US clients / operating from India | in-session research (first answered 30 Aug, filed 7 Sep) | §7 → `docs/legal/US-CLIENTS-CONSTRAINTS.md` |

**Evidence classes** (hard rule 11): **VERIFIED** = vendor's own page/docs/code read on the
stated date · **VENDOR-PUBLISHED** = vendor marketing/blog · **REPORTED** = a third party, or
a dashboard screenshot · **ESTIMATE** = arithmetic with inputs shown · **UNKNOWN** = no
source; what closes it is named. **REPO** = a value already in this tree, which is a claim
with its own class, not proof. Comet's reads were on 6 Sep (engine, Gnani) and 7 Sep
(Cartesia); pages that showed no effective date are marked so in the source documents.

---

## 0. The decisions, in one screen

| Question | Answer | Confidence |
| --- | --- | --- |
| Replace Bolna as the engine? | **No.** Stay, instrument, keep a LiveKit Mumbai spike in a branch. | High on ¢; contingent on a latency measurement never taken |
| Switch TTS from Sarvam Bulbul v3 to Cartesia Sonic? | **Not on price.** Cartesia is 10–47% dearer per character on every self-serve tier and has a monthly floor Sarvam does not. **The Cartesia Startups Grant is the one thing that flips it** — 12 months of Scale tier free. | Quality: closed by ear test (founder). Cost: VERIFIED. Grant eligibility: UNKNOWN |
| Adopt Gnani TTS? | **Blocked on a plugin.** Cheapest Telugu TTS found (₹2.70/1k chars, REPORTED dashboard) but Gnani is not in hosted Bolna's TTS enum, so it needs OSS-plugin work Calevate cannot deploy on hosted Bolna. | Protocol VERIFIED; price REPORTED; route to production: none today |
| Adopt Gnani STT? | **Blocked** — cheaper (₹0.45/min vs ₹0.50) but no tunable endpointing, no phrase hints on realtime, and not in Bolna's transcriber enum. | Same |
| Gnani as the engine? | **Reject.** Production deployment is "handled by the Gnani Agents team"; no BYOK on STT/TTS/LLM found. | High |
| Move greeting/goodbye to Bolna graph-agent static nodes? | **Not yet.** Four live checks first (welcome billed?, GET returns `nodes`?, Sarvam static cache builds?, per-node invariant design). | Docs VERIFIED from mirror; the measurements are unmade |
| Serve US clients? | **Not as a sole proprietor doing outbound.** Inbound-only is the only defensible shape; the binding constraint is the founder's own scope freeze, not a statute. | High |
| Biggest single cost lever found | **Pre-rendered audio for the fixed greeting + AI disclosure + recording notice** — ₹0.45–1.05 per call (ESTIMATE). Same lever whether via Bolna static nodes (§6) or a Cartesia splice pipeline (§5). | ESTIMATE on an unmeasured char count |

---

## 1. The baseline every thread measured against — and where the repo disagrees with it

The three briefs handed Comet the same "given" facts. Most match the repo; three do not,
and the mismatches matter because they move every ₹ figure in §2–§5.

| Given to Comet | Repo value | Where | Verdict |
| --- | --- | --- | --- |
| Client price ₹5.00/min, no monthly fee | `self_serve_inr_per_min` 6→5 (D-466) | `docs/ROADMAP.md` D-466 | Matches |
| Sarvam Bulbul v3 ₹30/10,000 chars | `TTS_INR_PER_10K_CHARS = 30.0000` | `apps/api/billing/rates.py:79` | Matches. Founder re-read the Sarvam catalogue 27 Aug: `bulbul:v3`, no v4 row (`rates.py:99-106`) |
| Sarvam Saaras STT ₹0.50/min | `STT_INR_PER_HOUR = 30.0000` (= ₹0.50/min) | `rates.py:156` | Matches |
| 360–540 TTS chars per call-minute | Same assumption, flagged UNMEASURED | `docs/TRD.md:1324-1330` (§10.1); pilot gate 12 | Matches — and is the single biggest unmeasured lever on the TTS line |
| Bolna BYOK platform fee 2.0¢/min | 2.0¢ from a founder dashboard screenshot, 20 Aug 2026 | D-423; OPERATIONS gate 12(a) | Matches. **VERIFIED-DASHBOARD**, not a commercial term; gate 12 target is ≤ ~₹1.50 and is NOT met |
| **FX ₹88 = US$1** | **`LIST_PRICE_USD_INR = 95.66`** for every vendor list price in billing; D-423 used the vendor's own implied **₹92** | `rates.py:230-263`; D-423 | **DISAGREES.** At ₹95.66 the 2¢ slice is ₹1.91 (not ₹1.76), bundled 6¢ is ₹5.74 (not ₹5.28), Cartesia Scale is ₹3.58/1k chars (not ₹3.29). Every USD→₹ number in §2–§5 is understated by ~8% relative to the repo's own rate. Rankings do not change; margins do. |
| All-in cost ₹3.43–4.28/min | `SELF_SERVE_COST_FLOOR_INR_PER_MIN = 3.70`; D-466 records "cost ~₹3.4–4.3/min, ~22–30% gross margin knowingly accepted" | `rates.py:858`; D-466 | Consistent |
| LLM ₹0.10–0.24/min | TRD §10.1 (`gpt-4o-mini`, Azure) | `docs/TRD.md` §10.1 | Matches; platform default is now `gemini-2.5-flash-lite` (CLAUDE.md) whose catalogue price is `verified=False` until attested |
| Telephony ~₹0.35–0.50/min | TRD §10.4 uses ₹0.50–1.35 blended in/out | `docs/TRD.md:1650` | Comet found Plivo India domestic **₹0.38/min in and out** (VERIFIED, plivo.com/voice/pricing/in/, "as of May 2026") — narrower than the TRD band |
| 10 concurrent lines | Bolna `concurrency.max` default 10, documented API max 10 | Comet VERIFIED, `create-v2.md` | Matches sizing exactly — "a second clinic on the same agent without a documented raise is a production incident" |

**Action from this table:** pick one FX for the repo's prose. `rates.py` already argues
(`:230-263`) why `LIST_PRICE_USD_INR` is a named constant and not the live quote; the
evidence docs should quote it, not ₹88. Nothing below has been re-converted — the source
documents' ₹ figures are reproduced as written, at ₹88, so they can be checked against the
originals.

---

## 2. Engine decision — stay on hosted Bolna (Comet, read 6 Sep 2026)

### 2.1 Verdict as written

> "Do not replace hosted Bolna as the production engine. The only published bundled Bolna
> rate ($0.06/min = ₹5.28/min) already exceeds Calevate's ₹5.00/min client price, so the
> product only works if the unpublished BYOK platform slice stays near the REPORTED
> 2.0¢/min. No scored alternative is cheaper than that reported slice at 1,000 and 5,000
> minutes once inbound concurrency of 10 is honoured. The case against Bolna is real and is
> India-routing: BYOK calls are forced through US servers. That is a reason to measure the
> current stack and to spike LiveKit Cloud in Mumbai, not a reason to cut over."

### 2.2 Early eliminations (each on a named row of the 12-row capability contract)

| Candidate | Died on | Evidence |
| --- | --- | --- |
| Sarvam Voice Agents | Rows 7/9 (no Plivo, no generic SIP inbound) AND BYOK: "does not support bringing your own models at any part of the stack" | VERIFIED, docs.sarvam.ai |
| Retell | Telugu — no `te-IN` in the Create Voice Agent language enum | VERIFIED |
| Gnani, Ozonetel, Exotel, Knowlarity | Not scored — demo-gated; public API/BYOK/concurrency UNKNOWN | — (Gnani then researched separately, §3) |
| Vobiz | Not an engine — Bolna's own DLT page uses Vobiz for 140-series, Plivo for 160-series | VERIFIED |

### 2.3 Capability matrix — the cells that decided it

Survivors: hosted Bolna, Bolna OSS, LiveKit Cloud, Pipecat Cloud, Vapi, Cartesia Line,
Smallest Atoms, ElevenLabs Agents, self-host Mumbai VPS. Legend: N native · W wrapper we
host · X absent from docs · ? UNKNOWN.

- **Only hosted Bolna is N on all three BYOK legs AND has a hosted config object with GET
  read-back AND a KB object AND per-call script override AND Plivo inbound binding.**
  LiveKit/Pipecat/Cartesia Line are deployed code (`lk agent deploy`, image, git) — rows 4,
  5, 6, 12 become Calevate engineering.
- Sarvam STT/TTS streaming: N on Bolna (`saaras:v4`, `te-IN`, `stream: true`,
  `endpointing: 250` — VERIFIED `create-v2.md`), N on LiveKit (first-party plugin, default
  `bulbul:v3`, last commit 5 Sep 2026), N on Pipecat (plugin default `bulbul:v3`), W on Vapi
  (Calevate-hosted bridge), X on Cartesia Line (Sonic only), X on Smallest.
- **Warm transfer / whisper: X on Bolna, N on LiveKit (beta `WarmTransferTask`), N on Vapi
  on Twilio (Plivo ?).** The one client-visible feature a migration would buy.
- ⚠ **Hosted Bolna accepting `bulbul:v3` is UNKNOWN** — Bolna's preferred-models page still
  lists `bulbul:v2`, while Pipecat's Sarvam plugin source (3 Sep 2026) says the Sarvam API
  now rejects v2. Close: `PATCH` synthesizer to `sarvam.bulbul:v3`, then `GET` and confirm.
  **Our `rates.py` prices v3 and `agents/voices.py` is v3-only (D-466); if hosted Bolna
  rejects v3 on the wire, the product is billing a voice it cannot play.** This is the
  highest-priority UNKNOWN in the whole corpus for us specifically.

### 2.4 Cost table (₹88/USD, Plivo carrier minutes excluded, free tiers excluded, monthly floors shown as monthly ₹)

| Vendor / tier | Class | 1,000 min | 5,000 min | 20,000 min |
| --- | --- | --- | --- | --- |
| Bolna BYOK platform slice 2.0¢, ₹0 floor | REPORTED | ₹1.76/min · ₹1,760 | ₹1.76 · ₹8,800 | ₹1.76 · ₹35,200 |
| Bolna bundled preferred-models $0.06 | VERIFIED (30-s pulses, PAYG) | ₹5.28 · ₹5,280 | ₹5.28 · ₹26,400 | ₹5.28 · ₹105,600 |
| LiveKit Cloud Ship $50 + $0.014/min | VERIFIED rates; additive-fee reading ESTIMATE | ₹5.63 · ₹5,632 | ₹2.11 · ₹10,560 | ₹1.45 · ₹29,040 |
| LiveKit Cloud Scale $500 + $0.013/min (region pinning needs this) | same | ₹45.14 | ₹9.94 | ₹3.34 · ₹66,880 |
| Pipecat Cloud scale-to-zero $0.01/min | VERIFIED; ~10 s cold start — unusable for inbound | ₹0.88 | ₹0.88 | ₹0.88 |
| Pipecat Cloud 10 warm instances + $0.01 active | ESTIMATE ($216/mo reserved) | ₹19.89 · ₹19,888 | ₹4.68 | ₹1.83 · ₹36,608 |
| Vapi $0.05/min, 10 lines incl., US/EU only | VERIFIED | ₹4.40 | ₹4.40 | ₹4.40 |
| Cartesia Line $0.06/min | VERIFIED; no Sarvam BYOK | ₹5.28 | ₹5.28 | ₹5.28 |
| Smallest Atoms hosting $0.01/min | VERIFIED hosting slice only | ₹0.88 | — | — |
| E2E C3.8GB ×2 boxes, compute only | VERIFIED ₹3/hour; SIP + Redis UNKNOWN; GST extra | ₹4.32 · ₹4,320 | ₹0.86 | ₹0.22 · ₹4,320 |

**Unit-economics reading:** bundled Bolna (₹5.28) loses money on every minute at ₹5.00.
Vapi leaves ₹0.60 before Sarvam/Azure/Plivo/GST. LiveKit Ship undercuts REPORTED Bolna only
at 20,000 min and only if the $50 is additive as modelled. Pipecat warm is ₹19.89/min at
clinic volume. **Every Mumbai-resident option introduces a monthly rupee floor the clinic
is not charged.**

Bolna's published BYOK sentence: "You only pay your providers directly, plus Bolna's
platform fee." The fee is not on the pricing page — **UNKNOWN, close via
`cost_breakdown.platform` on one BYOK execution or billing@bolna.ai.**

### 2.5 Concurrency

| Platform | 10 lines | 25 lines | Note (VERIFIED) |
| --- | --- | --- | --- |
| Bolna hosted API | Fits (default = max = 10) | Commercial conversation | Pilots SKU "up to 100 concurrent", $600 = 12,000 min |
| LiveKit Ship | Fits (cap 20) | Fail | Scale $500/mo starts at 50 |
| Pipecat | Fits if 10 reserved | Fits if 25 reserved | 1 session per instance, pool max 50 |
| Vapi | Fits | +15 × $10 = ₹13,200/mo | — |
| Cartesia Line | Startup 20 / Pro 12 | Fail | Line caps, not TTS API caps (see §4) |
| Smallest PAYG | Fits | Fits (20) | — |

### 2.6 Latency — nobody has a number for our stack

- Bolna default region **AWS us-east-1** (VERIFIED, `concepts/security.md`); India
  residency (ap-south-1) is enterprise-only and **"If you connect your own API keys for any
  provider… calls will automatically route through US servers regardless"** (VERIFIED,
  `enterprise/indian-server-configuration.md`). So BYOK ⇒ US hairpin, today, on every turn.
- Bolna turn-detection floor: `endpointing: 250` + `incremental_delay: 400` = **650 ms
  before the LLM is invoked** (VERIFIED create-agent defaults) — already 150 ms over our
  500 ms p50 budget before STT, LLM, TTS or network.
- Inter-region RTT ap-south-1 → us-east-1: **185.52 ms** (ESTIMATE, cloudping.co, 6 Sep) —
  the extra hop a Mumbai orchestrator would remove. Not a last-mile saving; Hyderabad PSTN
  last-mile is UNKNOWN and common to all candidates.
- LiveKit's own India blog: ~1.67 s end-to-end on GPT-4o + Cartesia + Deepgram
  (VENDOR-PUBLISHED, different stack). Misses our budget on a faster English stack.
- **Our 500/800 ms budget is a Calevate number, not a vendor SLO, and voice-to-voice has
  never been measured on the current stack.**

### 2.7 The case for staying (mandatory section, argued sincerely)

₹0 monthly floor; the REPORTED 2¢ slice is the only platform ¢ leaving room under ₹5; Plivo
inbound (`POST /inbound/setup`, `allow_multiple` Plivo-only) is a shipped object with DLT +
KYC already done for current tenants; hosted config object + KB + per-call script override +
`cost_breakdown` per leg (unique among vendors scored) are production; webhook security is
documented as **no HMAC, source-IP verification, three fixed egress IPs `13.203.39.153`,
`13.126.9.249`, `13.202.133.53`** (VERIFIED `security.md`, 6 Sep) — which is exactly what
Calevate built; migration is 18–28 (LiveKit) or 22–35 (Pipecat) engineering days
(ESTIMATE) on a solo founder during clinic onboarding — the largest real cost, absent from
every ¢ table.

### 2.8 Ranked recommendation

1. **Stay on hosted Bolna.** Strongest risk: BYOK forces US routing; V2V unmeasured;
   `bulbul:v3` acceptance UNKNOWN; 2¢ unpublished; API concurrency max 10; `DELETE` of an
   agent destroys all batches and executions.
2. **LiveKit Cloud Ship in ap-south** — only survivor that is Mumbai + Sarvam-native +
   Plivo + warm-whisper. Risk: deployed code; $50 floor; region pinning Scale-only
   ($500 = ₹44,000/mo); observability stays US/EU.
3. **Pipecat Cloud ap-south** — cheapest active ¢, no platform fee, native Plivo WebSocket.
   Risk: inbound cannot scale to zero (₹19,008/mo for 10 warm); no agent-config API/KB/
   campaigns/cost API; Cloud SOC 2 UNKNOWN.

Not ranked: Vapi (US/EU, ₹4.40 eats the price), Cartesia Line (no Sarvam BYOK, no India
region), Smallest (no Sarvam BYOK, Plivo unnamed), ElevenLabs Agents (BYO STT/TTS absent,
$99 + $0.08/min), Bolna OSS (control plane closed — "self-host J with extra steps"),
self-host J (₹4,320 compute + 3 a.m. on-call).

### 2.9 Two-week proof for #1

**Week 1 — measure the incumbent, 10 Telugu inbound calls on the current Plivo number:**
ring-to-first-audio; V2V p50/p95 (Calevate-instrumented); barge-in kill time; STT-final →
TTS-first-byte. Pull `GET /executions/{id}` and copy `cost_breakdown` for every leg
including `platform`. `PATCH` synthesizer → `sarvam.bulbul:v3`, `GET`, confirm it stuck.
**Go/no-go:** p95 ≤ 800 ms AND `cost_breakdown.platform` ≤ 2.5¢ AND v3 reads back → stay,
no spike. Otherwise week 2.

**Week 2 — LiveKit Ship spike, not a cutover:** one Plivo SIP trunk into LiveKit ap-south /
SIP india; one Telugu agent on LiveKit Sarvam STT + TTS `bulbul:v3` + the same Azure v1
`base_url`; ten calls on a spare number; same four latency numbers plus cold time-to-first-
audio after `lk agent deploy`, and whether warm transfer actually whispers on Plivo. Do NOT
rebuild KB, campaigns or the meter.

### 2.10 Top ten UNKNOWNs (engine)

1. Bolna BYOK platform ¢/min — `cost_breakdown.platform` or billing@bolna.ai.
2. Hosted Bolna accepts `bulbul:v3` — PATCH + GET on `/v2/agent/{id}`.
3. V2V p50/p95 on current stack — week-1 test.
4. Bolna recording retention / deletion / DPDP — "contact support for retention policy";
   SOC 2 is "contact support@bolna.ai", VAPT "A+" vendor-claimed.
5. LiveKit $50 Ship: prepaid credit or additive seat — livekit.io/pricing or sales.
6. LiveKit region pinning on Ship — docs say Scale only.
7. Vapi warm transfer on Plivo BYO trunk.
8. Pipecat Cloud DPA / SOC 2 (Daily's is not Pipecat Cloud's).
9. Mumbai VPS all-in for 10 concurrent (SIP + Redis + 18% GST + bandwidth).
10. Bolna OSS Sarvam transcriber in `master` — README lists Deepgram; `feat/sarvam-transcriber`
    branches deleted; raw fetch of `providers.py` timed out 6 Sep.

### 2.11 Things that would change the answer

Bolna publishes a Mumbai BYOK region · `cost_breakdown.platform` > 3¢ or BYOK starts being
billed at 6¢ · clients accept a monthly platform fee · measured V2V > 1.5 s p95 AND LiveKit
spike < 800 ms on the same stack · Sarvam adds Plivo + BYOK to Voice Agents · Vapi ships an
India region + Plivo warm transfer · Pipecat publishes SOC 2 and a sub-second inbound warm
pool that is not ₹19,008/mo · a 25-line SKU is sold (Bolna max 10 and LiveKit Ship 20 both
fail).

### 2.12 What the replacement would have to implement (for the record)

`create_agent`, `update_agent`, `get_agent`, `delete_agent` (Bolna's is destructive of
executions — preserve Calevate copies first), `start_outbound_call`, `list_executions`,
`get_execution`. Events: started/ringing/answered/ended/failed; transcript (**Bolna's public
transcript is a flat string with no timestamps — VERIFIED gap vs Vapi/Retell utterance
objects**); recording URL; `cost_breakdown`; transfer events; in-call tool calls. Controls:
temperature, max tokens, endpointing ms, `incremental_delay`, interruption sensitivity, TTS
stability/similarity, voice id, `te-IN`, LLM `base_url` + model, STT model, transfer
destination, KB id, per-call script override. Also from the survivor notes: Bolna rate
limits 500 req/min on `/call`, `/v2/agent/{id}`, executions; 1,000 elsewhere; India routing
LLM is Azure OpenAI only, no custom keys; training-on-customer-data sentence **absent from
`security.md`**.

---

## 3. Gnani.ai — four axes (Comet, read 6 Sep 2026)

### 3.1 Company (axis D) — ADOPT IF pricing and DPDP unknowns close

- Entity **Gnani Innovations Private Limited**, Bangalore jurisdiction (VERIFIED, EULA).
  Founded 2016; founders Ganesh Gopalan (CEO), Ananth Nagaraj (CTO), Bharath Shankar
  (VERIFIED About page — marketing, not a filing). No CIN/registered address on any
  Gnani-owned page — UNKNOWN.
- Funding: Series B, $14M+ across 3 rounds, last 30 Mar 2026; FY25 revenue ₹56.9 Cr
  (+144.7%) — all **REPORTED** (Inc42). No acquisition found — UNKNOWN (absence of evidence).
- Headcount: Inc42 says 283 and "96" on the same page (REPORTED, self-inconsistent);
  Gnani says "250+" (VENDOR-PUBLISHED).
- **Four products, as Gnani names them:** (1) **Agent Builder** (no-code console); (2)
  **Agent Builder Platform API** (`api.inya.ai/platform`); (3) **Gnani Speech APIs /
  "Vachana"** — STT/TTS/voice-cloning at `api.vachana.ai`, **the only self-serve one**
  (`app.gnani.ai/voice`); (4) **Gnani Artha** — self-hosted open-weight stack (Evon v3.3
  LLM, Prisma v2.5 ASR, Timbre v2.5 TTS), Hugging Face "by request", Plexus layer
  "Early Access — waitlist".
- No named clinic/healthcare customer on any Gnani page ("200+ enterprises" unattributed,
  VENDOR-PUBLISHED). Certifications "SOC 2, ISO 27001, GDPR, HIPAA, PCI-DSS" are a
  marketing FAQ line, no certificate/trust portal (VENDOR-PUBLISHED). No status page, no
  SLA, no changelog (Timbre v2.0 "deprecated soon" appears across docs with no release
  notes — a finding in itself). Support: "save the requestId… contact Gnani support";
  Discord; no SLA. EULA is generic software boilerplate (device/IP/GPS telemetry clause);
  Privacy Policy is a web template; **no DPA, no grievance officer, no training opt-out
  clause for the cloud APIs** — UNKNOWN. Artha's "DPDP/RBI/IRDAI residency" claim is
  scoped to on-prem only.

### 3.2 TTS (axis A) — BLOCKED ON pricing, and on the Bolna enum

- Model `timbre-v2.5` (v2.0 deprecated). **42 voices, 10 Indian languages + English +
  Hinglish. Telugu: 5 dedicated female voices — Suhana, Lehara, Lavanya, Yukti, Varuni —
  first-class `te-IN`** (VERIFIED). Hindi 13, Indian English 6. Code-mixing: documented
  `hi-en` value + `auto` detection; **no `te-en`** — Telugu-English mixing rides `auto`,
  which resolves Latin-only input to English. Real gap for a Telugu clinic.
- Voice cloning: 5–30 s reference → `speaker_embedding` `[1,768]` bf16 → `model:
  "vachana-vc-v1"`. Price/turnaround/rights UNKNOWN.
- Controls: `speed` 0.85–1.15 only. **No SSML** — the supplied Introduction doc claims SSML;
  the live API reference shows no SSML field. **Disagreement flagged; treat SSML as absent.**
  Strong text-normalisation pipeline (numbers, currency, dates, honorifics) — useful for
  phone numbers and times.
- **Telephony: emits 8 kHz G.711 natively** (`container=mulaw|alaw`, VERIFIED). Streaming
  via SSE and WebSocket. No documented barge-in/cancel — UNKNOWN. **TTFB UNKNOWN** — measure
  via `wss://api.vachana.ai/api/v1/tts`, header `X-API-Key-ID`.
- **Price: no public pricing page.** Competitor blog says none exists (REPORTED). The
  **Cartesia brief then supplied "Gnani Timbre v2.5 at ₹27 per 10,000 characters =
  ₹2.70/1,000 chars, from their post-signup dashboard"** — REPORTED (founder dashboard).
  STT promo: "2,000 free STT minutes" (VENDOR-PUBLISHED, launch blog). Standalone TTS key
  without the platform: architecturally yes (own base URL, own signup, `gnani-vachana` on
  PyPI); billing terms UNKNOWN.
- **Bolna plugin build assessment (the decisive section):** WebSocket → `StreamSynthesizer`;
  static header `X-API-Key-ID` (no short-lived token — compatible with a static-key store);
  one JSON request `{text, voice, model, language, audio_config{sample_rate:8000,
  encoding:"pcm_mulaw"}}`; responses are JSON frames `start` → `audio` (base64) → `complete`
  (`is_final: true`); error frame `{"type":"error"}`; keepalive UNKNOWN; official async SDK
  `gnani-vachana` (Py 3.10+). Four-file Bolna OSS change per its `synthesizer/README.md`.
  **"Buildable on protocol grounds; the business blocker is price."**
- ⚠ **The blocker the Gnani doc understates and the engine doc makes explicit:** hosted
  Bolna's synthesizer `provider` is a **closed enum with no custom/websocket TTS slot**. A
  plugin lives in Bolna OSS, which we do not run (§2.8 — OSS is "self-host J with extra
  steps"). So Gnani TTS has **no route to production on our current engine** regardless of
  price. It becomes live only if Bolna adds a `gnani` slug, or we self-host.

### 3.3 STT (axis B) — BLOCKED ON pricing and endpointing tunability

- `gnani-prisma-v2.5`; REST (≤60 s clips), Realtime WebSocket `wss://api.vachana.ai/stt/v3/
  stream`, Batch. Telugu `te-IN` first-class across all three. `en-IN` accepts English-Hindi
  mixed audio → Latin output; no explicit English-Telugu. **No Telugu WER with a named test
  set** — "#1 on 8 of 9 Indian languages, Kathbath Noisy 8kHz" is VENDOR-PUBLISHED and does
  not say whether Telugu is the ninth.
- Realtime: headers `x-api-key-id`, `lang_code`, `x-sample-rate` (8k/16k/44.1k/48k),
  `x-format` (verbatim/transcribe). Events `connected` → `processing` (VAD end-of-speech) →
  `transcript` (`segment_id`, `latency` ms). **Segment-level only, no word timestamps.**
  **Endpointing threshold NOT tunable** on the realtime API. Diarization and phrase hints
  are Batch-only or Agent-Builder-only (`advanceSettings.phraseConfig`, 100 phrases, weights
  0–2.0) — **not available if we BYOK the raw STT into Bolna.**
- Price: none published. The Cartesia brief later supplied **₹27/hour = ₹0.45/min**
  (REPORTED dashboard) vs Sarvam ₹0.50. Not in Bolna's transcriber enum (ten providers in
  the mirror's `providers/transcriber/`, listed in §4.8; Gnani absent) — same
  production-route problem as TTS.

### 3.4 Platform (axis C) — REJECT

- **"Deployment to live infrastructure is handled by the Gnani Agents team… Only agents in
  Production are eligible"** (VERIFIED). Organisations are created by Gnani, not the UI.
- STT/TTS BYOK: impossible (`asrParams.provider` / `ttsParams.provider` show only
  `"gnani"`). LLM `base_url`: not found (`llmParams` shows Gnani's own "Pampa Go").
  Customer-owned DLT number binding, per-call caller ID, inbound-binding API, warm transfer/
  hunt: all UNKNOWN (not in retrieved docs). Blind transfer, FAQ KB (100 Q&A), script-only
  PATCH, post-call webhook (`postCallTriggerAPIConfig`, **no HMAC — absent from docs**),
  conversation logs/stats (**no per-call cost field**) — native. Rich turn control
  (`endSilenceTimeout` default 800 ms, `barge`, `minWordsForBargeIn`, denoiser, DTMF).
  Disposition codes are BFSI-collections shaped (PTP, RTP, CLBK, RNR, DND…). Concurrency,
  pricing at any volume: UNKNOWN. Deleting an agent: only the owner can; effect on
  recordings UNKNOWN.

### 3.5 Gnani vs the field (only Gnani and Sarvam were in scope; rest left UNKNOWN by rule)

| Vendor | ₹/1,000 chars | ₹/call-min (360–540) | Floor | Telugu | On hosted Bolna | Class |
| --- | --- | --- | --- | --- | --- | --- |
| Gnani Timbre v2.5 | UNKNOWN in this doc → **₹2.70** in the Cartesia doc | ₹0.97–1.46 | UNKNOWN | 5 dedicated voices | **No** | protocol VERIFIED, price REPORTED |
| Sarvam Bulbul v3 | ₹3.00 | ₹1.08–1.62 | ₹0 (PAYG) | multilingual (11 languages) | Yes | VERIFIED |

### 3.6 Ready-to-send email (to hello@gnani.ai, the only address found — EULA footer)

Seven numbered questions: standing ₹/1k-char TTS and ₹/min STT prices outside promos;
monthly minimum on self-serve Vachana; rate limits (req/s, concurrent WS) on a paid key;
retention + signable DPA + DPDP grievance officer; training opt-out without enterprise
contract; whether Agent Builder binds a customer-owned DLT Plivo/Exotel number; whether
deleting an agent deletes recordings and whether a per-call deletion endpoint exists. Full
text is in the source document §6.6.

### 3.7 What would change the Gnani answer

Standing TTS price ≤ ₹3.00/1k published · **Bolna adds a `gnani` synthesizer slug** (drops
plugin cost to zero — the one that matters for us) · self-serve production deployment ·
confirmed LLM `base_url` BYOK + third-party number binding · a signed DPA + grievance officer.

---

## 4. Cartesia TTS API — verified at the right layer (Comet, read 7 Sep 2026)

### 4.1 The trap this brief existed to avoid

Cartesia sells the **TTS API (Sonic, by the character, in credits)** and **Line (agent
platform, $0.06/min, agent-slot caps)**. A previous analysis conflated them into a ~15×
error. **TRD §10.4 / §10.4a compare Bolna against Cartesia *Line*** — correct for the
question they asked (engine vs engine) but **not the question now, which is TTS leg vs TTS
leg with Bolna kept.** Every number below is the TTS-API number.

### 4.2 Price (VERIFIED, cartesia.ai/pricing + docs.cartesia.ai/pricing, no effective date shown)

| Plan | $/mo | Sonic credits/mo | TTS concurrent requests | ₹/1,000 chars (ESTIMATE ×88) | ₹/call-min @360–540 |
| --- | --- | --- | --- | --- | --- |
| Free | 0 | 20,000 (~27 min) | 2 | — (no commercial use) | — |
| Pro | 5 | 100,000 (~133 min) | 3 | ₹4.40 | ₹1.58–2.38 |
| Startup | 49 | 1,250,000 (~1,667 min) | 5 | ₹3.45 | ₹1.24–1.86 |
| Scale | 299 | 8,000,000 (~10,667 min) | 15 | ₹3.29 | ₹1.18–1.78 |
| Enterprise | custom | custom | custom | — | — |

- **~1 credit per character on every TTS endpoint; no streaming premium; same rate on
  `sonic-3`, `-3.5`, `-3.6`** (VERIFIED). Only exception: Pro Voice Cloning at 1.5×.
- **Pay-as-you-go with no monthly minimum: NO** (VERIFIED, absence confirmed). Cheapest
  commercial entry is Pro $5/mo.
- **Cartesia Scale is 10% dearer per character than Bulbul v3; Pro is 47% dearer.** Gnani
  ₹2.70 (REPORTED) undercuts every tier.
- June 2026 promo: 25% off the *subscription fee* for 12 cycles (VENDOR-PUBLISHED) — does
  not change ₹/char.
- Overage: toggle per workspace; overage ₹/credit **UNKNOWN** (not on docs; ask support).

### 4.3 Concurrency (VERIFIED, docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts)

- TTS concurrent requests Free 2 / Pro 3 / Startup 5 / Scale 15. **The 8/12/20/60
  "concurrent calls" and 1/3/5/10 agent slots on the pricing page are Line's, not the TTS
  API's** — they sit side by side in one table and are easy to misread.
- Rule of thumb (vendor's own, "just a rule of thumb"): one concurrency unit ≈ 4 parallel
  conversations → **10 lines ≈ 3 units → Startup (5) covers it; Pro (3) is borderline.**
  Load-test, do not assume.
- Concurrency is per unique `context_id`, not per WebSocket or utterance; up to 10× the
  limit in parallel WebSocket connections; **no separate per-minute request cap** (absent
  from docs). **At the limit: 429, no queueing → dead air on a live call.** Idle WS closed
  at 5 min. Raising: self-serve up to Scale on play.cartesia.ai; beyond, UNKNOWN (sales).

### 4.4 Telephony fitness, models, Telugu

- `output_format` accepts **`pcm_mulaw` and `pcm_alaw` at 8000 Hz** (VERIFIED) — no forced
  resample on the TTS leg.
- **TTFB: UNKNOWN from Cartesia's own side** (third-party 40–90 ms figures are REPORTED and
  not citable). India/ap-south endpoint: not self-serve; only via the Blue Machines
  enterprise partnership (VENDOR-PUBLISHED). Fine while the engine is in us-east-1.
- Model status (VERIFIED, tts-models pages): `sonic-3.6` stable, no retirement announced;
  `sonic-preview` perpetual beta; **`sonic-3.5` (snapshot 2026-05-04) stable, no sunset
  date announced — stated in those words**; `sonic-3`, `sonic-2`, `sonic-turbo` deprecated,
  **sunset 20 Oct 2026**; `sonic`, `sonic-english`, `sonic-multilingual` sunset 1 Jun 2026.
  Bolna's "use `sonic-3.5` in production" (mirror `providers/voice/cartesia.md:66`) is
  consistent.
- **Telugu `te` is on the per-snapshot language lists for `sonic-3.5-2026-05-04` (42) and
  `sonic-3.6-2026-08-27` (44)** (VERIFIED) plus a dedicated cartesia.ai/languages/telugu
  page. **This closes U7 of the graph-agent doc.** Telugu voice count/ids/gender: UNKNOWN
  (voice library is behind login). Code-mixing documented for Hinglish only; Telugu-English
  absent from docs.

### 4.5 Data handling

- Privacy policy (last revised 14 Jun 2024): may use content "to train and enhance the
  models"; opt-out via form, **prospective only**. **"Services are designed for users in the
  United States only and are not intended for users located outside the United States"** —
  flagged; does not block API use in practice.
- **Zero Data Retention is Enterprise-only** (VERIFIED). Non-enterprise retention is governed
  by the general DPA (cartesia.ai/legal/dpa), whose self-serve signability is UNKNOWN.
- "GDPR, SOC 2 Type II, PCI-DSS service provider, HIPAA compliant" (VERIFIED as a statement
  on the ZDR docs page); the reports sit behind trust.cartesia.ai access request — UNKNOWN.
- Cloning: Instant on Pro+, Professional on Startup+ at 1.5 credits/char; rights over a
  cloned voice UNKNOWN.

### 4.6 The startup programme — the highest-leverage item in the corpus

**Cartesia Startups Grant** (VENDOR-PUBLISHED, cartesia.ai/startups, no date): **12 months
of Scale-tier benefits free — 8M Sonic/Ink credits/month, $300/month Line credits, 2×
rollover, Scale concurrency (15)** — "over $8,000" value. Eligibility as stated: "tell us
about what you're building, your team, and where you're headed"; reviewed in ~a week;
coupon code. **No funding, entity-type or geography requirement is stated** — absence
noted, not inferred as approval. Also reachable as a Google for Startups perk (VERIFIED,
cloud.google.com/startup/perks). A direct Indian competitor shows "BACKED BY · sarvam ·
CARTESIA | Startups" in its footer (founder observation, REPORTED).

**If granted:** 8M chars/month ≈ 14,800–22,200 call-minutes at 360–540 chars/min — above
the 20,000-minute scenario's low end — at ₹0 TTS cost for 12 months, with concurrency
solved. It converts Cartesia from "10–47% dearer than Bulbul v3" into "free for a year on
the voice the founder prefers". **Whether an Indian sole proprietorship qualifies: UNKNOWN
— closes by applying at cartesia.ai/startups or emailing sales@cartesia.ai.** A credit that
expires is a runway extension, not a unit economic; at month 13 the Scale rate card (₹3.29)
returns unless the volume by then justifies it.

### 4.7 Verdict on Cartesia (in the brief's required form)

**ADOPT IF the Startups Grant is awarded** (then: install the key at
`platform.bolna.ai/auth/cartesia`, set `sonic-3.5`, measure TTFB and char density in week 1
of §2.9). **Otherwise BLOCKED ON price** — Scale at ₹3.29/1k chars + ₹26,312/mo floor is a
₹0.10–0.16/min increase over Bulbul v3 plus a fixed cost the ₹5.00 SKU cannot carry at
1,000–5,000 minutes. The quality preference is real and is the founder's; it does not pay
for itself at the rate card.

### 4.8 Three-row summary

| | Cartesia Sonic (Startup / Scale) | Sarvam Bulbul v3 | Gnani Timbre v2.5 |
| --- | --- | --- | --- |
| ₹/1,000 chars | 3.45 / 3.29 | 3.00 | 2.70 |
| ₹/call-min (360–540) | 1.24–1.86 / 1.18–1.78 | 1.08–1.62 | 0.97–1.46 |
| Monthly floor | $49–$299 (₹4,312–26,312) | none | UNKNOWN |
| TTS concurrency | 5 / 15 | UNKNOWN | UNKNOWN |
| Telugu | VERIFIED on snapshot lists | VERIFIED | 5 voices VERIFIED |
| On hosted Bolna today | Yes | Yes | **No** |
| Class | VERIFIED | VERIFIED | REPORTED price |

**Provider-list disagreement between the two Comet documents — RESOLVED from the mirror
(7 Sep 2026, VERIFIED):** the Gnani brief said hosted Bolna's TTS enum has nine providers;
the Cartesia doc said the Audio tab lists four. Both are true at different layers.
`bolna-findings/mirror/pages/providers/voice/` holds exactly nine pages — `aws-polly`,
`azure`, `cartesia`, `deepgram`, `elevenlabs`, `maya`, `rime`, `sarvam`, `smallest` — and
`agent-setup/audio-tab.md:117` says the dashboard dropdown offers "**AzureTTS**,
**Cartesia**, **ElevenLabs**, or **Sarvam**". API surface = nine; dashboard = four; Gnani
is on neither. Likewise the transcriber directory holds ten (`assemblyai`, `azure`,
`deepgram-flux`, `deepgram`, `elevenlabs`, `gladia`, `openai`, `pixa`, `sarvam`,
`soniox`) — wider than the five the Gnani brief named — and Gnani is not among them.

---

## 5. Every way found to cut ₹ per call-minute (Comet Part B, 7 Sep 2026), ranked

Baseline ₹3.43–4.28/min against ₹5.00 (repo floor constant ₹3.70).

| Rank | Lever | Saving (ESTIMATE unless marked) | Cost / risk | Class |
| --- | --- | --- | --- | --- |
| 1 | **Pre-rendered audio for the fixed greeting + AI disclosure + recording notice** (150–350 chars synthesised fresh on every call today) | **₹0.45–1.05 per call; ₹2,250–5,250/mo at 5,000 calls** | Two routes: (a) **Bolna graph-agent static nodes** — vendor feature, cache built at save, zero TTS cost (§6; VERIFIED in mirror, gated on four live checks); (b) **Cartesia's documented caching pattern** — "pre-generate as raw PCM, cache, splice into the live stream… faster and free" (VERIFIED, tts-caching guide 21 Jul 2026) — but that is engineering on a stream Bolna controls, so on hosted Bolna route (a) is the only real one. Bolna's LinkedIn claim of "auto-generated pre-recorded messages in every language" is REPORTED and matches the static-node feature | VERIFIED feature / ESTIMATE saving |
| 2 | **Prompt caching on the LLM leg** | Cached input: OpenAI `gpt-4o-mini` 50% off ($0.075/M), `gpt-4.1-mini` 75% off ($0.10/M), **Gemini 2.5 Flash-Lite 90% off ($0.01/M vs $0.10)** (VERIFIED, vendor pricing pages) | **Whether Bolna's request pattern triggers the cache is UNKNOWN** (stable prefix, min length, timing are Bolna's to control). Ask Bolna support. | VERIFIED prices / UNKNOWN activation |
| 3 | **Endpointing / silence handling on STT** | Sarvam bills STT "per hour… billed per second" (VERIFIED, docs.sarvam.ai) — wall-clock audio, so silence is paid for. Cartesia Ink also bills silence (3 credits/s `ink-2`). | Aggressive endpointing is a direct saving, not only a latency win. Interacts with the 250 ms + 400 ms floor in §2.6. | VERIFIED |
| 4 | **Cheaper TTS with real Telugu** | Gnani ₹2.70 (REPORTED) saves ₹0.11–0.16/min vs Bulbul v3 | No route on hosted Bolna (§3.2). Azure Neural TTS $16/1M chars = **₹1.41/1k** would halve the TTS line **if a Telugu neural voice exists at that rate — UNKNOWN**, worth checking Azure's voice gallery; Azure is in Bolna's enum. ElevenLabs Flash ₹4.40, Rime ₹2.64–4.40, Smallest ~₹1.58–2.38/min — Telugu UNKNOWN on all three | mixed |
| 5 | **Cheaper STT** | Gnani Prisma ₹0.45 vs Sarvam ₹0.50 = ₹0.05/min | Not in Bolna's transcriber enum; no tunable endpointing | REPORTED |
| 6 | **LLM model choice** | `gemini-2.5-flash-lite` $0.10/$0.40 per M in/out is the floor among production-grade models; `gemini-3.1-flash-lite` is *dearer* ($0.25/$1.50) (VERIFIED) | Already the platform default (CLAUDE.md); needs the Google key installed and price attested before it runs | VERIFIED |
| 7 | **Bolna platform-fee pulse** | Pilots bundled rate bills in 30-s pulses (VERIFIED). **Whether the BYOK platform fee rounds to 30 s, 1 s or 1 min is UNKNOWN** — on a 90-s clinic call per-minute rounding is 33% | Read one BYOK execution's line items at platform.bolna.ai/agent-executions | UNKNOWN |
| 8 | **Telephony** | Plivo India domestic **₹0.38/min in and out** (VERIFIED, "as of May 2026"); no inbound discount. Billing increment UNKNOWN. Exotel and Vobiz increments UNKNOWN | — | VERIFIED rate |
| 9 | **Startup credits (runway, not unit economics)** | Cartesia Startups Grant (§4.6); AWS Activate Founders $1k–5k (self-funded qualifies, VERIFIED); Microsoft for Startups Founders Hub $1k–150k Azure (VERIFIED); Google Cloud for Startups up to $350k for AI startups + the Cartesia perk (VERIFIED); MeitY Startup Hub (exists; terms UNKNOWN, DPIIT recognition usually needed) | All time-boxed | VERIFIED/VENDOR-PUBLISHED |
| — | Shorter utterances, filler audio, shorter system prompt, shorter AHT | No quantified vendor guidance found — UNKNOWN | — | UNKNOWN |

**Total achievable, independent items only:** lever 1 (₹0.45–1.05/call) is the only one
with a number attached that we can act on with the current engine; lever 2 is potentially
the second largest and is one support email from being known; lever 4's Azure-Telugu
question is one voice-gallery lookup. Everything else is < ₹0.20/min or blocked on a route.

**The five things to do, in order (from the brief's required output, reconciled with §2.9):**
1. Apply for the Cartesia Startups Grant (one form; changes the TTS answer if accepted).
2. Run week 1 of §2.9 — ten Telugu calls, `cost_breakdown` per leg, `bulbul:v3` PATCH+GET.
3. Read one BYOK execution's line items for the platform-fee pulse and the welcome-message
   synthesizer cost (this is also U1 of §6 in one read).
4. Ask Bolna support two questions in one mail: does the BYOK request pattern preserve a
   stable system-prompt prefix (prompt caching), and is `agent_welcome_message` synthesised
   per call or cached.
5. Check Azure's voice gallery for a Telugu neural voice at the $16/1M base rate.

---

## 6. Bolna graph agents — the static-greeting hybrid (mirror read 7 Sep 2026)

Full evidence in `docs/evidence/bolna-graph-agent-static-greeting.md`. Summary:

- **Comet reported eight `graph-agent/*` pages as unloadable. All eight are in the hash-
  pinned mirror.** Seven of its UNKNOWNs closed from evidence we already had.
- Static nodes (VERIFIED `static-nodes.md`): `node_type: "static"`, `static_message` string
  or `{lang: text}` map, **audio pre-rendered at SAVE with the agent's TTS voice, zero
  LLM/TTS cost at call time, re-save to regenerate**; vendor's own table says ~50 ms vs
  ~800 ms and "Zero" vs "LLM tokens + TTS characters" (VENDOR-PUBLISHED, unmeasured by us).
  `repeat_after_silence_seconds` + `_silence_repeats` for escalation.
- Variables substitute in prompts, welcome message and edge conditions; **`static_message`
  is not listed and a save-time clip cannot hold a call-time value — UNKNOWN whether
  `{var}` in a static message substitutes, renders literally or fails.** Clinic-name
  greeting is fine (constant per agent).
- Router nodes: silent, ≤ 1 routing-LLM call per turn, defaults to Groq if a key exists —
  not needed for a linear greeting → conversation → goodbye graph.
- Validation: editor blocks save on errors; **API-side 4xx behaviour UNKNOWN.** Export JSON
  = the Agents API create body (VERIFIED) — the tool for discovering per-node override JSON
  keys, which are UNKNOWN. Version history is per agent, not per node.
- `agent_information` is a global prompt "applied to every LLM call" — a single seam for
  hard rule 5's invariants. **But `GET /agent` declares neither `agent_welcome_message` nor
  `llm_agent.llm_config.nodes`** (mirror `api-reference/agent/get.md:55-90`; OPERATIONS
  ~line 230 already tracks the welcome half) — so verification against the engine, which
  hard rule 5 requires on every publish and drift sweep, may be impossible. That, not
  cost, is the likely blocker.
- **Verdict: DO NOT MIGRATE YET.** Four conditions: welcome billed as synthesizer chars on a
  live execution; `GET` returns `nodes`; a Sarvam static node builds its cache on save; a
  ROADMAP §6 entry on per-node invariant enforcement. Ten UNKNOWNs registered, five free.

---

## 7. US clients and operating from India (filed 7 Sep 2026)

Full memo in `docs/legal/US-CLIENTS-CONSTRAINTS.md`. Summary: the binding constraint is the
founder's own scope freeze (`LEGAL-OPS-PLAYBOOK.md` §0 — "No foreign clients") and sole-
proprietor status, not a statute. US outbound AI calling sits under TCPA post the FCC's
Feb 2024 AI-voice ruling: prior express *written* consent for marketing, $500–$1,500 per
call uncapped, technology providers named directly; plus California B.O.T. Act, Florida
FTSA, Oklahoma OTSA, all-party recording consent in 11–12 states (strictest applies across
lines), HIPAA BAAs with every vendor touching PHI. From India: GST/OIDAR export triggers
registration, LUT, FIRC/SOFTEX, W-8BEN in the founder's personal name, reverse charge on
every foreign vendor bill, E&O/cyber insurance. **The product is India-shaped in the dial
gate on purpose** (IST window `compliance/service.py:477`, INR, TRAI DND, DLT PE–TM, Sarvam,
Plivo/Exotel/Vobiz). Recommendation: inbound-only US if anything, never outbound as an
individual.

---

## 8. Consolidated UNKNOWN register across all threads, by what closes them

**Free — one API call or one dashboard read:**
- `cost_breakdown.platform` on any BYOK execution → Bolna BYOK ¢ (E1), pulse rounding (C7)
- `cost_breakdown.synthesizer` on a greeting-only call → is the welcome billed (G-U1)
- `PATCH` + `GET` `/v2/agent/{id}` synthesizer → hosted `bulbul:v3` accepted (E2) — **top priority**
- `GET /agent/{id}` on a graph agent → does `nodes` come back (G-U2)
- `POST /agent` with an invalid graph → API validation status (G-U5)
- Editor export of a node with an LLM override → JSON keys (G-U6)
- `bolna-findings/mirror/pages/providers/voice/` listing vs live Audio tab → TTS enum (four
  or nine)

**One email each:**
- billing@bolna.ai — BYOK fee in writing (gate 12a), volume tiers (12b), KB billing (12g)
- support@bolna.ai — retention/deletion/DPDP (E4), prompt-cache prefix behaviour (C2),
  welcome synthesis per call vs cached
- hello@gnani.ai — the seven questions in §3.6
- sales@cartesia.ai / cartesia.ai/startups — grant eligibility for an Indian proprietor
- support@cartesia.ai — overage ₹/credit; DPA self-serve signability
- sales@livekit.io — Ship $50 prepaid vs additive; region pinning on Ship
- legal@daily.co — Pipecat Cloud DPA / SOC 2

**A measurement (the two-week proof, §2.9):**
- V2V p50/p95 on our stack (E3); TTS chars per call-minute (TRD gate 12); Cartesia TTFB;
  Gnani TTFB; Sarvam static-node cache-on-save (G-U3); `{var}` in `static_message` (G-U4)

**Not closable from here:**
- Bolna OSS Sarvam transcriber in `master` (raw GitHub fetch timed out)
- Azure Telugu neural voice at the $16/1M rate (voice gallery)
- Cartesia Telugu voice ids (behind login)
- Vapi warm transfer on Plivo (trial call)

---

## 9. What this consolidation changes in the repo, and what it does not

**Changes nothing in code.** No decision in this document is a ROADMAP §6 entry yet,
because every one of them waits on a measurement or an email named in §8 — which, per the
tempo rule, are the only deferrals allowed a timeline, and each is named.

**Two things the repo should absorb from this pass without waiting:**
1. **FX consistency.** Evidence prose quotes ₹88; `rates.py` bills at ₹95.66; D-423 used
   the vendor's implied ₹92. Three rates in one repo is the D-103/D-105 defect class. The
   constant already has the argument for itself; the docs should cite it.
2. **The `bulbul:v3` wire question (E2) is not a vendor curiosity — it is whether the single
   voice we sell (D-466) is accepted by the engine we run.** It costs one PATCH and one GET.

**One correction to carry forward:** the engine decision's cost table and TRD §10.4 both
compare against Cartesia *Line*; the TTS-leg comparison (§4) is a different product at a
different layer and must never be pasted into the §10.4 table. When TRD §10 is next
re-verified (its header says quarterly), §10.4 stays as the engine comparison and a new
subsection (§10.5 and §10.6 already exist — the exit plan and the two-engine Cartesia plan)
should carry §4.8's three-row TTS-leg table at the repo's FX.
