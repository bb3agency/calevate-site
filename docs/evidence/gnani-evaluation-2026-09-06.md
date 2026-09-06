# Gnani.ai — evaluation for the TTS leg, the STT leg, and as an engine

<!-- Two sources, two evidence classes, and they must not be blended. -->

**READ THIS FIRST — what is verified and what is not.**

This file holds TWO documents. Part 1 is what the FOUNDER observed by driving the Gnani
dashboard and API logged in as an account holder on 6 Sep 2026 — **VERIFIED-DASHBOARD**, the
same class as D-423's Bolna 2.0c/min observation. Part 2 is a Comet research run over Gnani's
public pages on the same day — **REPORTED**: those pages are egress-blocked from this
container, Comet read them, not us. Where the two disagree, Part 1 wins and the disagreement
is recorded rather than resolved silently.

Hard rule 11 applies to every figure below. Nothing here may reach `unit_cost_paid`, a wire
value, or a client-facing claim by citation of this file alone.

---

## Part 1 — FOUNDER-OBSERVED, logged in (VERIFIED-DASHBOARD, 6 Sep 2026)

### 1.1 The pricing page exists, behind login

`app.gnani.ai/voice/pricing`. This is why Part 2 records the price as UNKNOWN and why every
public aggregator says Gnani publishes none: the price is real and is post-signup only.

Credit model: **1 credit = Rs 1**, one-time purchase, credits do not expire. No monthly
subscription and no recurring commitment shown. The FAQ states a minimum purchase amount
exists but the page does not show the figure; the founder's own account holds
995.79 / 1,000 credits after test use, so the minimum is at most Rs 1,000 and behaves as
prepaid top-up rather than a floor.

| Service | Price | Unit | Rate limit as printed |
|---|---|---|---|
| Speech to Text (REST) | Rs 27.00 | per hour | 60 req/min |
| Speech to Text (WebSocket) | Rs 27.00 | per hour | **20 concurrent sessions** |
| Speech to Text (Batch) | Rs 27.00 | per hour | 60 req/min |
| Text to Speech | Rs 27.00 | per 10,000 chars | **60 req/min** |

Internally consistent with the page's own worked examples: Rs 1,000 buys 37.04 hours of STT
(1000 / 27) and 370,370 characters of TTS (1000 / 0.0027).

### 1.2 What that is against Sarvam, arithmetic shown

TTS: Rs 27 / 10,000 chars = **Rs 2.70 per 1,000 chars**, exactly **0.900x** Sarvam Bulbul v3's
Rs 3.00 (`billing/rates.TTS_INR_PER_10K_CHARS`). At this repo's 360-540 agent-chars-per-
call-minute band (`rates.TTS_ASSUMED_CHARS_PER_CALL_MINUTE`, itself an UNMEASURED assumption):

| Leg | Gnani | Sarvam | Saving per call-minute |
|---|---|---|---|
| TTS @ 360 chars/min | Rs 0.972 | Rs 1.080 | Rs 0.108 |
| TTS @ 540 chars/min | Rs 1.458 | Rs 1.620 | Rs 0.162 |
| STT | Rs 0.450 (27/60) | Rs 0.500 | Rs 0.050 |
| **Both legs** | | | **Rs 0.158 - 0.212** |

Monthly, on the whole speech stack: Rs 158-212 at 1,000 min · Rs 790-1,060 at 5,000 min ·
Rs 3,160-4,240 at 20,000 min. **Real, and small.** Cost is not the reason to move; it is the
reason a move is not blocked.

### 1.3 THE RATE LIMIT IS THE FINDING, AND IT IS NOT IN THE COMET REPORT

TTS prints **60 req/min** and no concurrent-session figure, while STT prints 60 req/min for
REST/Batch and **20 concurrent sessions** for WebSocket. So Gnani measures a WebSocket leg in
SESSIONS where it has one to measure — and the TTS row shows no session figure at all,
despite `wss://api.vachana.ai/api/v1/tts` being documented.

Why it matters, at this deployment's sizing of 10 concurrent lines: at 360-540 chars/min and
an utterance of roughly 100 characters, one call issues 3.6-5.4 agent utterances a minute, so
ten lines issue **36-54 requests a minute against a printed cap of 60** — 60-90% consumed at
STEADY STATE, before the ~4x peak this repo's own capacity note assumes. If a WebSocket
stream counts as one request the cap is irrelevant; if each utterance counts, Gnani TTS
cannot carry ten lines on the self-serve tier at all. **UNKNOWN, and it is question one.**

### 1.4 Voice cloning — run end to end, in Telugu

Playground -> Voice Cloning -> "+ Voice Clone": record live (with a Neutral/Angry/Sad/Happy/
Surprise/Disgusted mood picker) or upload .wav/.mp3/.m4a, max 25 MB, **minimum 10 seconds**.
Using an existing cloned voice ("Umesh", male) with the language set to Telugu, the founder
generated
`namaskaram, idi clone chesina voice test` (in Telugu script) and got playable audio in about
two seconds. The cloned-voice language list covers Hindi, English, Bengali, Gujarati,
Kannada, Malayalam, Marathi, Punjabi, Tamil, **Telugu**.

This is the one thing in the whole evaluation that no competitor's catalogue can answer: it
is a voice nobody else on any platform can select. Cloning PRICE, turnaround and the RIGHTS
Gnani takes over a cloned voice are **UNKNOWN** and are question two.

### 1.5 The cloning API, and why it fits a Bolna plugin

Two steps, both static-key:

1. `POST https://api.vachana.ai/api/v1/tts/voice-clone/embeddings`, header
   `X-API-Key-ID`, multipart `audio_file` of a 5-30s clean reference clip. Returns
   `{embedding: "<base64>", shape: [1,768], dtype: "torch.bfloat16"}` — **a cacheable static
   blob, not a short-lived token.**
2. Synthesise with it three ways: REST `POST /api/v1/tts/inference`, SSE, or realtime
   **`wss://api.vachana.ai/api/v1/tts`** — same `X-API-Key-ID` header, no refresh.

WebSocket request carries `text`, `model` (`vachana-vc-v1` for cloned), `audio_config` and the
`speaker_embedding`. Server answers `start` -> repeated
`{"type":"audio","data":{"chunk_index":N,"audio":"<base64 PCM>","is_final":false}}` ->
`complete`; errors as `{"type":"error","error":"SYNTHESIS_FAILED"}`.

**The documented default `audio_config` is 44100 Hz linear PCM.** Part 2 reports that the REST
reference documents `container=mulaw`/`alaw` forcing 8 kHz G.711; the founder did not see an
8 kHz mu-law example on the cloned-voice pages. Whether the CLONED-voice endpoint accepts
8 kHz mu-law is therefore **UNKNOWN** and is question three — on a Plivo PSTN leg the
alternative is resampling 44.1 kHz down to 8 kHz on every utterance.

### 1.6 Gnani Agents is closed to this account, and the docs show no voice field

Switching the dashboard's product picker to "Gnani Agents" returns a hard block:
*"Unsupported Email Type - We do not support personal email addresses for Gnani Agents."*
So the Agent Builder's voice picker could not be inspected.

From the Agent Builder docs the founder did read (`docs.gnani.ai/A02_Agent`), the agent config
fields are greeting, ending message, LLM provider/model, knowledge base, temperature, max
tokens, language, region/timezone, description. **There is no voice-selection field, no TTS
model field, and no reference to `speaker_embedding` anywhere in the agent config.** So
whether a cloned voice can be used INSIDE a Gnani agent is **UNKNOWN** — not "probably yes".

Telephony, from the same doc tree: the documented flow is **Whitelisting Numbers**
(`A04_Whitelisting`) — add your own number, verify by OTP, and it appears in a "Trigger Agent
Call" dropdown so Gnani can ring you to TEST an agent. That is a test mechanism, not DID
provisioning. No buy-a-number feature, no SIP-trunk or BYO-carrier page, and **no mention of
TRAI DLT, DND, entity or template ids anywhere**. The only carrier named in the whole
Integrations section is Twilio, and only for outbound SMS branding.

### 1.7 Two price books, and a REPORTED figure that must not be mixed with Part 1

A third-party comparison blog asserts Gnani charges Rs 14/min for contact-centre minutes at
1,000-5,000 min, tapering to Rs 6/min at 100,000+. That is **REPORTED**, from a competitor's
blog, and it is an order of magnitude away from the Rs 27/10,000-char Speech API price in
Part 1. They are evidently two different product lines with two different price books; do not
let the platform figure contaminate the speech-leg figure, in either direction.

### 1.8 Support address

`hello-inya@gnani.site`, from the docs header (founder-observed). Part 2 found
`hello@gnani.ai` in the EULA footer. Both are recorded; neither has been used.

---

## Part 2 — Comet research run over Gnani's PUBLIC pages (REPORTED, 6 Sep 2026)

Filed verbatim below. Read it knowing that its single largest conclusion — "pricing is
UNKNOWN, and it could independently kill the option" — is SUPERSEDED by Part 1 section 1.1:
the price exists, is post-signup, and is 10% under Sarvam. Its protocol findings, its Telugu
voice catalogue and its Agent Builder capability scoring are the parts that carry weight.

## 0. Scope and evidentiary method

This report evaluates Gnani.ai (Gnani Innovations Private Limited) against Calevate's four axes: TTS vendor, STT vendor, voice-agent platform, and company. Every claim is labeled with an evidence class (VERIFIED / VENDOR-PUBLISHED / REPORTED / ESTIMATE / UNKNOWN) and traced to its source. Currency conversions use ₹88 = US$1.00 throughout, arithmetic shown.

***

## 1. Gnani as a company (axis D)

**Legal entity and structure.** The contracting entity is "M/s. Gnani Innovations Private Limited, India," per the EULA jurisdiction clause (Bangalore, Karnataka courts). Third-party company-data aggregator Inc42 lists the same legal name, founding year 2016, Bengaluru HQ, and founders Ananth Nagaraj and Ganesh Gopalan — this is **REPORTED**, not primary, since Inc42 is not Gnani's own page. Gnani's own "About Us" page independently corroborates 2016 founding and names three co-founders: Ganesh Gopalan (CEO), Ananth Nagaraj (CTO), and Bharath Shankar (Chief Product & Engineering Officer) — this is **VERIFIED** from a Gnani-owned page, though it is a marketing page, not a filing. No CIN, registered address, or filing was located on any Gnani-owned page — **UNKNOWN**.[^1][^2][^3]

**Funding and ownership.** Inc42 reports Series B stage, total funding $14.00M+ across 3 rounds, last round 30 March 2026, and FY25 revenue of ₹56.9 Cr (up 144.7% from FY24's ₹23.3 Cr) — all **REPORTED**, sourced from a third-party aggregator, not Gnani's own site. No funding round, amount, or investor was found announced on gnani.ai itself. **No evidence of an acquisition or being acquired was found anywhere** — Gnani's own roadmap graphic shows independent milestones through a projected "Global Leader" 2030 stage, implying no acquisition to date, but this is not an explicit statement and should be treated as **UNKNOWN (absence of evidence)**.[^2][^3]

**Headcount.** Inc42 lists 283 employees (last 90 days) in one place on the same page and "96 individuals" in an FAQ answer on the same page — an internal inconsistency in the third-party source itself; both figures are **REPORTED**, not Gnani-published. Gnani's own About page states "250+ AI Trailblazers" as a headline statistic — **VENDOR-PUBLISHED**.[^3][^2]

**Product lines, exactly as Gnani names them.** Gnani's own pages name four distinct offerings: (1) **Agent Builder** — the no-code console for building voice/chat agents, at docs.gnani.ai/introduction; (2) **Agent Builder Platform API** — REST management of agents/FAQs/conversations, base URL `api.inya.ai/platform`; (3) **Gnani Speech APIs** (branded "Vachana") — STT/TTS/voice-cloning APIs at base URL `api.vachana.ai`; (4) **Gnani Artha** — a separate "sovereign AI stack" of self-hosted, open-weight models (Evon v3.3 LLM, Prisma v2.5 ASR, Timbre v2.5 TTS) for on-premise/VPC deployment, distributed via Hugging Face "by request," with a Plexus agentic-workflow layer that is explicitly labeled "Early Access — join the waitlist". Of these, **only the Speech APIs (self-serve signup via app.gnani.ai/voice, per Quick Start) show a self-serve creation path today**; the Agent Builder platform requires Gnani's team to provision organizations ("Organizations are not created through the UI... contact us and we will create it for you") and deployment to production is explicitly "handled by the Gnani Agents team," not self-serve. Artha/Plexus is demo/waitlist-gated.[^4][^5][^6][^7][^8][^9]

**Named customers.** No named enterprise customer list, logo wall, or case study naming an Indian healthcare/clinic customer was found on any Gnani-owned page during this research. Gnani's About FAQ makes an unattributed aggregate claim of "200+ enterprises in banking, insurance, healthcare, and government" without naming any — **VENDOR-PUBLISHED**, not traceable to a named customer. **UNKNOWN**: any specific Indian clinic/healthcare customer name.[^3]

**Certifications.** Gnani's own About-page FAQ states: "Gnani is SOC 2 certified, ISO 27001 certified, and compliant with GDPR, HIPAA, and PCI-DSS". This is **VENDOR-PUBLISHED** — it is a marketing-page assertion, not a linked certificate, audit report, or trust-portal page (unlike, for comparison, OpenAI's dedicated trust portal with dated SOC 2 report periods). No SOC 2 Type I/II distinction, no certificate number, and no MeitY empanelment or STQC listing was found — **UNKNOWN** on all specifics.[^10][^3]

**Status page / SLA.** No official Gnani status page or published uptime SLA was found. A third-party monitor (downrightnow.in) reports "~99.5% expected uptime" — this is **REPORTED** by an unaffiliated third party, not a Gnani commitment, and should not be relied upon. **UNKNOWN**: any contractual SLA.[^11]

**Changelog / breaking changes.** No dedicated changelog page was found. However, the docs themselves show an active, undocumented-elsewhere migration in progress: Timbre v2.0 is marked "deprecated soon" in favor of v2.5 across multiple pages (Quick Start, TTS REST, Available Voices, TTS Realtime). This is a real, dated deprecation signal (found across docs verified 5–11 August 2026) but there is no consolidated release-notes page — this absence is itself a finding: no changelog exists as a discoverable page. **UNKNOWN**: full 18-month breaking-change history.[^8][^12][^13]

**Support model.** The docs repeatedly instruct developers to "save the requestId... you will need it if you contact Gnani support", and Discord channels are given for docs feedback. No published support SLA, hours, or named-contact guarantee for a self-serve/SMB tier was found — **UNKNOWN**.[^6][^14][^15][^4]

**Data handling / DPDP posture.** Gnani's EULA (jurisdiction: Bangalore courts, Arbitration and Conciliation Act 1996) governs the "Gnani Product" generically and includes broad indemnification-from-Gnani clauses and a data-collection clause (Section 11) authorizing collection of device/IP/GPS/MAC-address telemetry for "statistical purposes" and sharing aggregated trend data with "organizations, vendors" — this is **VERIFIED** text from Gnani's own EULA page, though it reads as boilerplate anti-malware software language rather than an API/voice-specific DPA. The Privacy Policy page found is a generic web-privacy template (cookies, "Publisher," billing address collection) that does not specifically address voice/telephony data, retention periods, or DPDP grievance-officer contact — **VERIFIED as the current published text, but it does not answer the DPDP-specific questions asked**. No dedicated DPA, no named grievance officer, and no explicit training-on-customer-data opt-out clause were found on any Gnani-owned legal page. Separately, Gnani's Artha marketing page claims "DPDP, RBI and IRDAI residency requirements are met by where the model runs" for the **on-premise Artha product specifically**, not for the standard cloud Speech API/Agent Builder — this is **VENDOR-PUBLISHED** and scoped only to the self-hosted product. **UNKNOWN**: DPA availability, grievance officer, training-data opt-out for the cloud APIs Calevate would actually use.[^7][^16][^1]

***

## 2. Gnani as a TTS vendor (axis A)

### Models, voices, and languages

The current model is **Timbre v2.5** (`model: "timbre-v2.5"`), with Timbre v2.0 marked deprecated and slated for removal. The catalogue lists **42 voices across 10 Indian languages plus English and Hinglish**. **Telugu specifically** has 5 dedicated voices — Suhana, Lehara, Lavanya, Yukti, Varuni, all female, described with personas ranging from "warm/empathetic" to "friendly" and "conversational" — this is a first-class language slot with its own `language` code `te-IN`, not merely multilingual-model coverage. Hindi has 13 voices (the deepest catalogue); Indian English has 6. **Code-mixing**: the API documents an explicit `hi-en` ("Hinglish") language value with a dedicated voice (Poorvi), and separately an `auto` detection mode that resolves script to a language profile, including a documented "Hinglish (code-mixed)" resolution path for mixed Devanagari+Latin text — this is a traced, documented mechanism, not just a marketing claim. However, there is **no equivalent documented "te-en" (Telugu-English) code-mixed value** — only `hi-en` is enumerated; Telugu code-mixing would have to rely on `auto` detection, which is documented to have limitations (Latin-only input always resolves to English under `auto`). This is a real gap for Calevate's Telugu-clinic use case.[^12][^13][^17][^8]

**Voice cloning**: a two-step embeddings-then-synthesize flow. Upload 5–30 seconds of reference audio to `POST /api/v1/tts/voice-clone/embeddings`, receive a `speaker_embedding` (shape `[1,768]`, dtype `torch.bfloat16`), then pass it to any synthesis endpoint with `model: "vachana-vc-v1"`. No pricing, turnaround time, or rights-transfer clause for cloned voices was found in the docs — **UNKNOWN**.[^18][^19]

**Controls**: `speed` (0.85–1.15, or string shortcuts "slow"/"medium"/"fast") is a documented API parameter. No pitch parameter, no SSML tag support, and no emotion/style parameter were found anywhere in the TTS REST, SSE, or WebSocket docs — the only "control" surface documented is `speed` plus a comprehensive **text-normalization (TN) pipeline** that expands numbers, currency, dates, honorifics, and identifiers automatically (this is thoroughly documented and useful for a clinic use case with phone numbers, PIN codes, times) — **VERIFIED**, but SSML itself is **absent from docs** at every TTS page examined. The attached Introduction doc's claim "SSML supported on TTS for fine-grained control" is **contradicted** by the actual TTS REST/SSE/WebSocket API reference pages, which show no SSML parameter — **flagging this disagreement**: supplied docs (attached_file:3) assert SSML support; the live API reference at docs.gnani.ai/api/TTS/tts-inference documents no SSML field. Treat SSML as **absent from the current API surface**, contradicting the marketing claim in the Introduction page.[^20][^12]

### Audio and telephony fitness

Confirmed via the TTS REST reference: output supports `container=mulaw` or `container=alaw`, which **force 8000 Hz G.711** output — directly PSTN-compatible, no downsampling needed. This directly answers the brief's key question: **yes, Gnani TTS can emit 8 kHz μ-law/A-law PCM natively** — **VERIFIED**. Streaming is available via SSE (chunked, base64-encoded JSON events) and via WebSocket (lowest latency). No documented barge-in/cancel-mid-utterance API call was found on any TTS page — **UNKNOWN, absent from docs**.[^21][^8][^12]

### Latency

No published time-to-first-byte or real-time-factor figure was found for TTS anywhere in the docs. The STT WebSocket page does publish transcript latency examples (e.g., "latency: 320" ms in a sample payload) for STT, but this is a sample value, not a benchmark claim, and does not apply to TTS. **UNKNOWN** for TTS TTFB. To measure it directly: connect to `wss://api.vachana.ai/api/v1/tts` with header `X-API-Key-ID: <key>`, send `{"text":"...", "voice":"Suhana", "model":"timbre-v2.5", "language":"te-IN", "audio_config":{"sample_rate":8000,"encoding":"pcm_mulaw"}}`, and time from send to first `audio` message.[^22][^21]

### Pricing

**No pricing page, free-tier credit count, or rate-limit table for TTS was found on any Gnani-owned page.** A third-party blog (Tabbly, a competitor) explicitly states: "Gnani.ai does not publish any pricing information on its website... No per-minute call rates, no monthly subscription tiers, no setup fees, no free trial options listed, no pay-as-you-go plans," and estimates ₹4–₹20+/min for the bundled platform — this is **REPORTED**, from a competitor's marketing blog, not from Gnani, and should be treated with caution, but it corroborates the primary-source finding of an absent pricing page. Separately, Gnani's own blog post announcing "Vachana STT" (their new STT-only product) mentions "2,000 free STT minutes" for that specific STT launch and, per a secondary LinkedIn summary of the same launch, "one lakh free minutes" for early enterprise adopters — these are STT-specific promotional numbers, not TTS pricing, and are **VENDOR-PUBLISHED** (from Gnani's own blog) for STT only. **No standalone TTS price, no ₹/1,000-characters figure, no monthly floor, and no confirmation of self-serve credit-card signup for TTS were found** — all are **UNKNOWN**. Given the brief's decisive comparator (Sarvam Bulbul v3 at ₹30/10,000 chars = ₹3.00/1,000 chars), **the ₹/1,000-char comparison for Gnani cannot be completed from documents — it is UNKNOWN**, and the exact resolution action is: email hello@gnani.ai (found in the EULA footer) or sign up at app.gnani.ai/voice to see if a pricing/billing page appears post-signup.[^23][^24][^25][^26][^1]

**Standalone-vs-bundled**: the Speech APIs (Vachana STT/TTS/VC) are documented as a separate product from Agent Builder, with their own base URL, own signup flow (`app.gnani.ai/voice`), and their own SDK (`gnani-vachana` on PyPI) — this is **VERIFIED** as architecturally standalone, i.e., a TTS-only API key without buying the Agent Builder platform is directly implied by the docs' framing, though actual account-level bundling/billing terms remain **UNKNOWN**.[^6][^8]

### Data handling on the TTS leg

No TTS-specific data-retention or training-opt-out clause was found. The About-page FAQ's general assurance ("No customer voice data is used for model training without explicit agreement") is **VENDOR-PUBLISHED**, unscoped to a specific product tier, and not quoted from a clause in the Privacy Policy or Terms — the actual Privacy Policy page found is a generic template with no voice-specific retention language. **UNKNOWN**: retention period, cross-border transfer clause, DPA availability, and grievance officer contact for the Vachana API specifically.[^16][^3]

### The integration question (§3.6) — build assessment for a Bolna synthesizer plugin

This is answerable concretely and favorably from the docs:

- **Protocol**: WebSocket. Endpoint is `wss://api.vachana.ai/api/v1/tts`. This maps to Bolna's `StreamSynthesizer` base class, not `BaseSynthesizer`.[^21]
- **Authentication**: static header `X-API-Key-ID: <api_key>`, passed at WebSocket upgrade time — **not** a short-lived token. This is compatible with a static-key credential store (no blocker).[^8][^21]
- **Request shape to open a stream and push text**: after connecting, send one JSON message: `{"text": "...", "voice": "Suhana", "model": "timbre-v2.5", "language": "te-IN", "audio_config": {"sample_rate": 8000, "encoding": "pcm_mulaw"}}`.[^21]
- **Response shape of an audio chunk**: server streams JSON text messages, each containing a `base64`-encoded audio field, with message types `start`, `audio` (repeated), then `complete` carrying `is_final: true`. This is JSON-wrapped base64, not raw binary frames — a plugin's `_process_audio_chunk` will need a base64-decode step, which is a minor but real implementation detail (Cartesia/ElevenLabs's Bolna integrations also decode base64, so this is a known pattern, not a novel blocker).[^8][^21]
- **Closing/errors/keepalive**: the docs describe "Either side closes the connection at any time," and an `{"type":"error","message":"..."}` JSON frame for errors. No explicit keepalive/ping interval is documented — **UNKNOWN**, worth testing empirically before production use.[^21]
- **Official Python SDK**: yes — `pip install gnani-vachana`, requiring Python 3.10+, with a `GnaniTTSRealtimeClient` class that wraps the WebSocket lifecycle for async iteration. Package licence and exact last-release date were not stated on the docs page — **UNKNOWN**; check PyPI directly for `gnani-vachana`.[^12][^21]
- **What would make a plugin hard**: none of the classic blockers (short-lived tokens, mandatory per-request session creation, non-standard handshake) appear in the documented flow. The main non-trivial work is: (a) base64 chunk decoding, (b) confirming no keepalive ping is required to avoid idle disconnects, (c) registering `te-IN` + preferred Telugu voice (e.g., `Lavanya` or `Suhana`) as defaults, and (d) adding the four Bolna-side artifacts per its README (`StreamSynthesizer` subclass, `SynthesizerProvider` slug, a `SYNTHESIZER_CONFIG_MODELS` entry, and a `SUPPORTED_SYNTHESIZER_MODELS` registration)[per user's stated Bolna repo knowledge, not independently re-verified here]. **This is a straightforward, well-specified integration on Gnani's side** — the primary open blocker is pricing, not protocol.

***

## 3. Gnani as an STT vendor (axis B)

**Models**: `gnani-prisma-v2.5` for REST/Realtime/Batch. REST (`POST https://api.vachana.ai/stt/v3`) handles clips up to 60s; Realtime is WebSocket (`wss://api.vachana.ai/stt/v3/stream`); Batch (`/stt/v3/batch/jobs`) handles long/bulk async jobs.[^27][^28][^29][^30]

**Telugu, Hindi, English, and code-mixing**: Telugu (`te-IN`) is a first-class supported language across REST, Realtime, and Batch, with native-script examples shown in the docs. English (`en-IN`) is documented to "accept English-Hindi mixed audio and generate output in English (Latin script)" — a real, traced code-mixing mechanism, though it is scoped to English-Hindi, not explicitly English-Telugu. **No WER/accuracy benchmark for Telugu specifically, with a named test set, was found on any Gnani-owned page** — the About-page FAQ's "#1 ranking... top performance across 8 of 9 Indian languages on the Kathbath Noisy 8kHz benchmark" is **VENDOR-PUBLISHED**, unscoped as to whether Telugu is one of the "top" 8 or the one exception, and not linked to a benchmark report. **UNKNOWN**: Telugu-specific WER number.[^30][^27][^3]

**Streaming protocol details**: WebSocket at `wss://api.vachana.ai/stt/v3/stream`, headers `x-api-key-id`, `lang_code`, optional `x-sample-rate` (8000/16000/44100/48000), `x-format` (verbatim/transcribe for ITN). Server sends `connected` → `processing` (VAD end-of-speech signal) → `transcript` (with `segment_id`, `segment_index`, `latency` in ms) JSON messages. **No word-level timestamps are documented** — only segment-level `audio_duration_ms` and a single `latency` figure per segment; this is a real gap relative to Calevate's stated need for per-turn timestamps (segment-level timestamps exist; word-level do not, per the documented schema).[^29]

**Endpointing/VAD**: the server performs VAD-based end-of-speech detection natively and emits a `processing` event when it fires. However, the *millisecond threshold is not exposed as a tunable parameter* in the STT WebSocket connection headers documented — only sample rate, language, and ITN format are configurable; **endpointing latency itself is not tunable via this API**, an important limitation versus the brief's hope for adjustable VAD.[^29]

**Diarization, punctuation, phrase hints**: Diarization (`with_diarization`, max `num_speakers: 2`) and ITN-based number/date/currency formatting are documented **only for Batch STT**, not for Realtime. Realtime STT has no diarization or phrase-hint/custom-vocabulary parameter documented anywhere in the STT WebSocket reference — this is a real gap for Calevate's clinic/doctor-name use case; the Agent Builder platform's `advanceSettings.phraseConfig` (up to 100 custom phrases, weighted 0.0–2.0) is a **separate, agent-platform-level feature**, not part of the raw Speech API. So phrase hints exist only if Calevate adopts the full Agent Builder platform (axis C), not if it BYOKs the raw STT API into Bolna.[^31][^30]

**Pricing**: same finding as TTS — **no published per-minute STT price was found on any Gnani-owned page.** The only concrete number is the promotional "2,000 free STT minutes" / "one lakh free minutes" tied to the Vachana STT product launch blog post, which is **VENDOR-PUBLISHED** but promotional, not a standing price. **UNKNOWN**: standing ₹/minute price, monthly floor, standalone availability terms beyond the free-tier promotion.[^24][^25]

**Integration against Bolna's transcriber contract**: Bolna's documented transcribers are Azure, Deepgram, Deepgram Flux, OpenAI, and Sarvam[per user's stated knowledge]. Gnani's STT Realtime WebSocket (`wss://api.vachana.ai/stt/v3/stream`, static `x-api-key-id` header, raw 16-bit PCM binary frames at 1,024 bytes/frame, real-time cadence) is structurally similar to what a Bolna `Transcriber` plugin would need, and an official async Python SDK (`gnani-vachana`, with `GnaniSTTStreamClient`) already exists. As with TTS, protocol and auth are well-specified and static-key-compatible; the open item is again pricing, plus the missing phrase-hints/diarization-at-realtime gap noted above.[^29]

***

## 4. Gnani as a voice-agent platform (axis C)

Access requires Gnani-provisioned Organizations for team use, though "if you are working alone, you may use your Personal workspace" — implying a Personal workspace may be self-serve, but this is not explicitly confirmed as credit-card self-serve; deployment to live production traffic is explicitly **not** self-serve ("Deployment to live infrastructure is handled by the Gnani Agents team... Only agents in Production are eligible for deployment"). This is a material finding: **the platform is demo/managed-deploy-gated for going live**, even if configuration itself can be done directly via API.[^9]

| # | Capability | Status | Evidence |
|---|---|---|---|
| 1 | STT choice (BYOK) | Impossible — `asrParams.provider` example shows only `"gnani"`; no third-party ASR provider field documented | [^31] |
| 2 | TTS choice (BYOK) | Impossible — `ttsParams.provider` example shows only `"gnani"`; no third-party TTS provider field documented | [^31] |
| 3 | LLM choice | Achievable-with-work/UNKNOWN — `llmParams` shows `provider: "gnani"` with Gnani's own "Pampa Go" model in the example; no `base_url`/custom-endpoint field was found in the documented schema, unlike Bolna's explicit `custom` LLM provider + `base_url` support | [^31][^32] |
| 4 | Agent hosting | Native — Agent is a config object created/read via `POST /v1/agents` and `GET /v1/agents/{botId}`, returning `botId` | [^33][^31] |
| 5 | Campaigns | Native (not required by Calevate) — `AgentCallTriggers`/Trigger Call endpoint exists for outbound test/production calls with `clientReferenceId` | [^34][^5] |
| 6 | Knowledge base | Native — FAQ-based KB, up to 100 Q&A pairs per agent, `faqEnabled` boolean readable via Get Agent, managed via `/v1/agents/{botId}/faqs` | [^31][^5] |
| 7 | Numbers (customer-owned DLT number) | UNKNOWN — no documentation found describing SIP trunk or customer-owned-number binding; only a "Whitelisting Numbers" flow for *testing* against caller numbers was found, which is not the same as binding an inbound DID | [^35] |
| 8 | Caller ID per call (outbound) | UNKNOWN — Trigger Call docs were not detailed enough on this point in what was retrieved | [^34] |
| 9 | Inbound binding via API | UNKNOWN — not found in the documentation retrieved | — |
| 10 | Blind transfer | Native — `callTransferConfig` with `details[]` array of `phoneNumber`/`countryCode`/`prompt`/`message`, toggled by `callTransferConfigStatus` | [^31] |
| 11 | Warm transfer (whisper) / hunt list | UNKNOWN — the documented `callTransferConfig` schema shows only a flat list of transfer targets with messages, no whisper-to-human-first field or ordered-hunt/no-answer-retry field was found | [^31] |
| 12 | Script-only PATCH | Native — Update Agent is explicitly "all request body fields are optional — only fields you include are modified," so a greeting/prompt-only PATCH is directly supported | [^36] |

**Post-call webhook**: `hasPostCallTrigger: true` plus `postCallTriggerAPIConfig` (`url`, `method`, optional `headers`) triggers a POST after each call. The payload includes `conversation_id`, `detected_language`, and `STAGE_CODE` in snake_case, mirroring the Stats API's `overallCallDisposition`/`utteranceAnalytics` fields. **No HMAC signature or shared-secret header field was found documented anywhere** — the schema shows only `hasHeaders`/optional custom `headers` you configure yourself, not a Gnani-provided signing scheme. Treat webhook authenticity verification as **absent from docs** — Calevate would need to add its own shared-secret header manually via the `headers` field, since Gnani does not appear to sign requests itself.[^5][^37][^31]

**Poll API**: `Get Conversation Logs` (paginated, filterable by date/agent/environment/status) and `Get Conversation Stats` (per-conversation detail) both exist. Per-call cost was **not found** in any documented response field of Stats or Logs — `averageAgentLatency`, `callDuration`, `overallCallDisposition`, and full `utteranceAnalytics` are returned, but no `cost` or `billedAmount` field appears in the verified example response. **UNKNOWN**: whether per-call cost is retrievable by API at all, or only via invoice.[^37][^38]

**Disposition codes**: a standard set (PTP, RTP, AP, CLBK, WRNG, DSCN, RNR, DND) is documented, all evidently designed for debt-collection/BFSI use cases rather than clinic reception — Calevate would define custom codes via its own disposition prompt, which the platform explicitly supports ("Your agent's disposition prompt may produce additional codes beyond this list").[^39][^37]

**Turn control**: extensively documented via `advanceSettings` — `barge` (interruption allowed), `initialMessageBarge`, `useDenoiser` + `suppressionLevel` (20–100), `enableItnForAsr`, `maxSpeechDuration` (1–240s), `speechInitialSilenceTimeout`, `endSilenceTimeout` (ms, default 800), `speechSegmentationSilenceTimeout`, `minWordsForBargeIn`, `minTimeToBarge`, `enableDtmf`, and `phraseConfig` (up to 100 custom phrases, weighted 0–2.0). This is a genuinely rich, well-specified turn-control surface — notably richer than the raw Speech API's STT WebSocket, which lacks tunable endpointing.[^31]

**Concurrency, deletion, and org structure**: no concurrency cap or tier pricing was found documented. Agent deletion has nuanced, documented behavior: if a non-owner deletes a shared agent, only their membership is removed and the agent survives; **only the bot owner can permanently delete an agent from the Organization**. Whether permanent deletion also destroys call history/recordings, and whether a per-call deletion API exists for DPDP erasure requests, was **not found documented** — **UNKNOWN**, a real gap the brief specifically flagged as a retention hazard to check before any deployment.[^9]

**Pricing at 1,000/5,000/20,000 min/month**: **no pricing was found for the Agent Builder platform on any Gnani-owned page.** Tabbly's competitor blog reiterates "no per-minute call rates... no free trial options" as a criticism of Gnani specifically — **REPORTED**, from a competitor, but consistent with the primary-source absence. All volume-tier and monthly-floor figures are **UNKNOWN**.[^23]

***

## 5. Gnani vs. the field

| Vendor | ₹/1,000 chars | ₹/call-min (360–540 chars/min) | Monthly floor | Telugu | Streaming | Published TTFB | On hosted Bolna today | Evidence class |
|---|---|---|---|---|---|---|---|---|
| Gnani TTS | UNKNOWN | UNKNOWN | UNKNOWN | First-class (5 dedicated voices, `te-IN`)[^13] | WebSocket (`wss://api.vachana.ai/api/v1/tts`)[^21] | UNKNOWN | No (absent from closed provider enum) | Mixed — protocol VERIFIED, price UNKNOWN |
| Sarvam Bulbul v3 | ₹3.00[^26] | ₹1.08–1.62 (₹3.00×0.36–0.54) | ₹0 (pay-as-you-go Starter tier)[^26] | Multilingual coverage (11 languages)[^26] | Not confirmed streaming-websocket in this research | UNKNOWN | Yes | VERIFIED (pricing page) |
| Cartesia Sonic | UNKNOWN (not researched this round) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Yes (named in Bolna enum) | UNKNOWN |
| ElevenLabs | UNKNOWN (not researched this round) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Yes (named in Bolna enum) | UNKNOWN |
| Smallest lightning-v2 | UNKNOWN (not researched this round) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Yes (named in Bolna enum) | UNKNOWN |
| Rime | UNKNOWN (not researched this round) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Yes (named in Bolna enum) | UNKNOWN |
| Maya | UNKNOWN (not researched this round) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Yes (named in Bolna enum) | UNKNOWN |
| Deepgram Aura | UNKNOWN (not researched this round) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | No (not in Bolna synthesizer list) | UNKNOWN |
| Azure TTS | UNKNOWN (not researched this round) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Yes (named in Bolna enum) | UNKNOWN |
| AWS Polly Neural | UNKNOWN (not researched this round) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Yes (named in Bolna enum) | UNKNOWN |

Only Gnani and Sarvam were in-scope for deep primary-source research this round per the query's stated priority (Gnani vs. the ₹3.00/1,000-char Sarvam comparator); the remaining rows are left UNKNOWN rather than filled with unverified guesses, per the binding rules of evidence.

***

## 6. Required outputs

### 6.1 Verdict on axis A (TTS)

The quality question cannot be answered from documents — it is an ear test. Gnani's Telugu voice catalogue (5 dedicated `te-IN` voices: Suhana, Lehara, Lavanya, Yukti, Varuni) is verifiably first-class and code-native (not a multilingual-model afterthought), and the API can emit 8kHz μ-law/A-law directly for telephony with no downsampling step, over a documented WebSocket with static-key auth compatible with Bolna's plugin contract. **However, cost cannot be compared to Sarvam Bulbul v3's known ₹3.00/1,000-char rate because no Gnani TTS price was found on any page — this is the single largest open unknown and could independently kill the option regardless of voice quality.** To run the ear test: call `POST https://api.vachana.ai/api/v1/tts/inference` with `{"text": "నమస్తే, మీరు ఎలా ఉన్నారు?", "voice": "Lavanya", "model": "timbre-v2.5", "language": "te-IN", "speed": 1.0, "audio_config": {"sample_rate": 8000, "container": "mulaw"}}` and header `X-API-Key-ID: <trial-key>`, holding the same Telugu sample sentence constant across Sarvam Bulbul v3 for a side-by-side listen.[^13][^12][^21]

### 6.2 Comparison table

See §5 above.

### 6.3 Four axis verdicts

**Axis A (TTS): BLOCKED ON pricing.** Gnani is not on hosted Bolna's closed provider enum, so any adoption requires a custom plugin — a well-specified, achievable build given the documented WebSocket protocol and static-key auth. But without a published ₹/1,000-char or ₹/minute price, it is impossible to know if it beats Sarvam's ₹1.08–1.62/call-minute floor. The exact unknown that unblocks this: a price quote from hello@gnani.ai or a post-signup billing page at app.gnani.ai/voice.[^21]

**Axis B (STT): BLOCKED ON pricing and endpointing tunability.** Telugu is first-class and the WebSocket protocol/SDK are well-documented and Bolna-plugin-compatible, but real-time STT lacks tunable endpointing and phrase-hints (both are Batch-only or Agent-Builder-only features), and no standing per-minute price beyond a time-limited promotional free-minutes offer was found.[^24][^27][^30][^31][^29]

**Axis C (Platform): REJECT because production deployment is not self-serve.** Deployment to live traffic is explicitly routed through "the Gnani Agents team," not an API call, which directly fails the brief's exclusion rule for any platform gated behind a managed process rather than a customer-owned-number/self-serve flow. Additionally, LLM BYOK (`base_url`) and TTS/STT BYOK were not found in the documented agent config schema — the platform appears to mandate Gnani's own ASR/LLM/TTS stack, which fails capability rows 1–3 outright.[^9][^31]

**Axis D (Company): ADOPT IF the pricing and DPDP-specific unknowns close favorably.** The company shows real operating signals (Series B funding reported, ₹56.9 Cr FY25 revenue reported, active product shipping with dated docs updates through August–September 2026), and no evidence of an acquisition or discontinuation was found. But no primary certificate for SOC 2/ISO 27001 was located (only a marketing-page assertion), no DPA or grievance officer was found, and no status-page SLA exists — these are real diligence gaps for a clinic-data (potentially health-adjacent) use case before any commitment.[^40][^2][^3]

### 6.4 Integration build assessment

See §2 "The integration question" above — reproduced in full detail there. Summary: WebSocket, static `X-API-Key-ID` header, JSON-in/base64-JSON-out framing, official async Python SDK (`gnani-vachana`) available, no short-lived-token blocker, no mandatory session-creation handshake found. This is a **buildable** Bolna plugin on protocol grounds alone; the business blocker is price, not engineering effort.

### 6.5 Top ten UNKNOWNs, ranked by decision impact

1. **Gnani TTS price** (₹/1,000 chars or ₹/minute) — closes at: email hello@gnani.ai, or sign up at app.gnani.ai/voice and check for a post-signup billing/pricing page.
2. **Gnani STT price** (standing rate beyond the promotional free-minutes offer) — same action as #1.
3. **Any monthly floor / minimum commitment on Speech APIs** — same action as #1; specifically ask "is there a monthly minimum spend on the Vachana self-serve tier?"
4. **Agent Builder platform BYOK for LLM (`base_url`) and third-party ASR/TTS** — closes at: request the full Update Agent request-body schema (not just Get Agent response schema) from Gnani support, or test directly against a trial `botId`.
5. **Whether the platform can bind a customer-owned Plivo/Exotel DLT-registered Indian number, or only Gnani-provisioned numbers** — closes at: ask Gnani support directly; not found in any retrieved doc page.
6. **Agent/call-history/recording deletion behavior** — does deleting an agent destroy call recordings? Closes at: test empirically in a trial Organization, or ask support.
7. **SOC 2/ISO 27001 certificate itself** (Type I vs II, scope, date) — closes at: request the actual attestation letter or trust-portal link from Gnani (no dedicated trust portal was found, unlike OpenAI's).[^10]
8. **DPA availability and named grievance officer for DPDP compliance** — closes at: ask hello@gnani.ai directly, referencing DPDP Section 8 obligations.
9. **Voice-cloning cost, turnaround, and rights** — closes at: sign up and attempt the embeddings flow, or ask support for commercial terms.
10. **Post-call webhook signing (HMAC or shared secret)** — closes at: inspect actual webhook headers received in a trial agent's `postCallTriggerAPIConfig.headers` field, or ask support whether Gnani signs outgoing webhooks at all.

### 6.6 Ready-to-send email to Gnani

**To: hello@gnani.ai** (found in the Gnani EULA footer, the only support address located on a Gnani-owned page)[^1]

> Subject: Pricing and integration questions — Vachana Speech APIs (self-serve)
>
> Hi Gnani team,
>
> We're evaluating Vachana TTS/STT for a Telugu-first voice-AI product on AWS, BYOK into a third-party orchestration engine. Could you answer:
>
> 1. What is the standing per-1,000-character price for Timbre v2.5 TTS, and per-minute price for Prisma v2.5 STT, outside of promotional free minutes?
> 2. Is there a monthly minimum commitment or platform fee on the self-serve Vachana tier?
> 3. What are the rate limits (requests/sec, concurrent WebSocket streams) on a paid self-serve key?
> 4. Do you retain submitted text/audio, and for how long? Is there a signable DPA, and who is the named grievance officer under India's DPDP Act?
> 5. Is training on customer audio/text opt-out available without an enterprise contract?
> 6. For the Agent Builder platform: can we bind a customer-owned, DLT-registered Indian Plivo/Exotel number, or only Gnani-issued numbers?
> 7. Does deleting an agent delete its call recordings/transcripts, and is there a per-call deletion endpoint?
>
> Thank you,
> [Calevate founder]

### 6.7 What would change the answer

- If Gnani publishes a standing TTS price at or below ₹3.00/1,000 characters (Sarvam Bulbul v3 parity), axis A moves from BLOCKED to a real contender given the confirmed WebSocket/8kHz-mulaw/static-key protocol fit.
- If Bolna adds a `gnani` synthesizer slug to its closed enum, the custom-plugin engineering cost drops to zero.
- If Gnani confirms self-serve production deployment (not routed through "the Gnani Agents team"), axis C moves off automatic rejection.
- If Gnani confirms LLM `base_url` BYOK and third-party number binding, capability rows 1–3 and 7 on the platform scorecard flip from Impossible/UNKNOWN to Native.
- If a signed DPA and named grievance officer are produced on request, axis D's compliance gap closes for an Indian-SMB healthcare-adjacent use case.

---

## References

1. [Introduction – Agent Builder - Gnani Docs](https://docs.gnani.ai/introduction) - > ## Documentation Index
> Fetch the complete documentation index at: https://docs.gnani.ai/llms.txt...

2. [platform-introduction](https://docs.gnani.ai/Platform/platform-introduction) - > ## Documentation Index
> Fetch the complete documentation index at: https://docs.gnani.ai/llms.txt...

3. [Key capabilities](https://docs.gnani.ai/api/introduction/introduction) - > ## Documentation Index
> Fetch the complete documentation index at: https://docs.gnani.ai/llms.txt...

4. [Indian Language Text to Speech API | Indic TTS | Gnani AI](https://www.gnani.ai/text-to-speech-api) - Neural TTS built for Indian conversational AI: 10 languages, MOS 4.23, p95 latency under 250ms, with...

5. [Gnani.ai Raises $10 Mn in Series B Funding Led by Aavishkaar ...](https://www.linkedin.com/posts/inc42_inc42-news-ai-activity-7444653458911051776-tdwL) - Generative AI (GenAI) startup gnani.ai has raised $10 Mn (around ₹94 Cr) in its Series B funding rou...

6. [Text-to-Speech (Streaming) - Gnani Docs](https://docs.gnani.ai/api/TTS/tts-sse) - Stream audio in chunks as it's generated via Server-Sent Events. TTS inference. Use timbre-v2.5 … vo...

7. [Gnani AI | The Frontier Voice AI Company for Enterprise](https://www.gnani.ai/) - Gnani AI builds enterprise voice AI agents, ASR, TTS and voice biometrics in 40+ languages. Trusted ...

8. [Gnani Timbre v2.0 API — Text-to-Speech by Gnani | Pricing ...](https://www.callmissed.com/models/gnani-timbre-v2-0) - Gnani Timbre v2.0 is a strong fit for Indian contact-center and voice-agent deployments that primari...

9. [Voice AI Startup Gnani.ai Secures Fresh Funding to Expand Global ...](https://www.cxodigitalpulse.com/voice-ai-startup-gnani-ai-secures-fresh-funding-to-expand-global-footprint/) - Gnani.ai, a voice-first generative AI company, has secured Rs 68 crore (approximately $7.17 million)...

10. [Quick Start - Gnani Docs](https://docs.gnani.ai/api/introduction/quick-start) - Make your first speech-to-text, text-to-speech or voice-cloned TTS API request in minutes. Sample ra...

11. [Gnani.ai Features & Pricing: 11.5/14 Score | Agentic Index](https://agenticindex.io/vendors/gnani-ai) - Gnani publishes no list pricing; model APIs and enterprise deployments are quoted through sales. Ent...

12. [Total Funding, Rounds & Investors - Gnani.ai - Inc42](https://inc42.com/company/gnani-ai/funding/) - Gnani.ai has raised a total of $14.00 million across 3 funding rounds and the last round was raised ...

13. [Voice Cloned TTS (Streaming) - Gnani Docs](https://docs.gnani.ai/api/VC/vc-sse) - Stream cloned voice audio in chunks via Server-Sent Events. Reduces latency compared to Voice Cloned...

14. [GitHub - Gnani-AI/API-service: This is the official ...](https://github.com/gnani-ai/API-service) - Gnani.ai will immediately remove access if the user is found to be using the APIs for commercial pur...

15. [Gnani.ai Raises $7M Series B Led by Aavishkaar Capital](https://theaiworld.org/news/gnaniai-raises-7m-series-b-led-by-aavishkaar-capital) - Gnani.ai secures Rs 68 crore in a Series B round led by Aavishkaar Capital, reaching an $87M valuati...

16. [Pipecat Plugin - Gnani Docs](https://docs.gnani.ai/pipecat/introduction) - REST-based text-to-speech for non-streaming use cases. Returns the complete audio in a single respon...

17. [Text-to-Speech (REST) - Gnani Docs](https://docs.gnani.ai/api/TTS/tts-inference) - For streaming playback, see TTS Streaming or TTS Realtime. Passing numbers, IDs, dates, or currency ...

18. [Gnani.ai Secures $4M in Funding | PDF | Investing - Scribd](https://www.scribd.com/document/880051743/Gnani-ai-Funding-Google-Search) - Gnani.ai, a voice-first generative AI startup, has raised $4 million (Rs 30 crore) in a Series A fun...

19. [Privacy Policy - Gnani AI](https://www.gnani.ai/privacy) - Learn how Gnani.ai collects, uses, and protects your data. Read about categories of data, security p...

20. [End User License Agreement | Gnani.ai](https://www.gnani.ai/legal/eula) - Terms for installing and using Gnani.ai software and services. Covers license grant, acceptable use,...

21. [ISO27001 Certification: A proof that information security](https://www.gnani.ai/resources/blogs/iso27001-certification-a-proof-that-information-security-has-been-integral-to-gnanis-dna-from-the-start) - Alongside ISO 27001, Gnani.ai's website also lists SOC 2 Type 2, HIPAA and GDPR among its certificat...

22. [Voice AI Case Studies | Enterprise Results | Gnani.ai](https://www.gnani.ai/customer-stories) - Real results across BFSI, telecom, and healthcare. See how enterprises cut AHT, improve collections,...

23. [Privacy - Ginni AI](https://ginni.ai/privacy) - We retain Personal Data for the period necessary to fulfill the services requested by our users, com...

24. [End-User License Agreement - Voice Biometrics](https://voicebiometrics.ai/end-user-license-agreement/) - GNANI INNOVATIONS PRIVATE LIMITED, INDIA (HEREINAFTER REFERRED TO AS “ GNANI”) AND YOU SHALL HAVE TH...

25. [SOC2 Report & ISO 27001 Certificate - Sentry](https://docs.sentry.io/security-legal-pii/security/soc2/) - Learn about where you can access Sentry's latest SOC2 report and ISO 27001 certificate.

26. [Gnani Ai : The Indian Voice AI Startup Transforming ...](https://beststartup.in/gnani-ai-startup-transforming-voice-tech-in-india/) - Telecom companies, banks, insurance firms, law enforcement agencies, and healthcare providers are th...

27. [Jobs at www.gnani.ai: Explore current Opportunities - Wellfound](https://wellfound.com/company/gnani-ai-1/jobs) - www.gnani.ai hasn't added any jobs yet. Get notified when www.gnani.ai posts new jobs. ... Product D...

28. [Cloud AI Privacy: Data Retention Explained | NanoGPT](https://nano-gpt.com/blog/cloud-ai-privacy-data-retention-explained) - Retention periods vary from days to years. Risks include data breaches, re-identification from anony...

29. [ISO27001 Certification: A proof that information security](https://www.gnani.ai/resources/blogs/iso27001-certification-a-proof-that-information-security-has-been-integral-to-gnanis-dna-from-the-start-c39a1) - Implementing the highest security standards to protect customer information, and with a constant foc...

30. [15 AI in Healthcare Case Studies [2026] - DigitalDefynd](https://digitaldefynd.com/IQ/ai-in-healthcare-case-studies/) - Explore AI in healthcare case studies and discover how artificial intelligence is transforming patie...

31. [1,000+ Gnani.ai jobs in India - LinkedIn](https://in.linkedin.com/jobs/gnani.ai-jobs) - 1,000+ Gnani.ai Jobs in India · AI Engineer · Artificial Intelligence Engineer · Back End Developer ...

32. [Why Gnani.ai has the best Conversational AI Platform (Proof Included)](https://www.gnani.ai/resources/blogs/why-gnani-ai-has-the-best-conversational-ai-platform) - Our processes align with the General Data Protection Regulation (GDPR), allowing us to handle person...

33. [Gnani.ai Launches Vachana Indic Speech-to-Text Model](https://www.gnani.ai/resources/blogs/gnani-ai-launches-vachana-stt-a-foundational-indic-speech-to-text-model-trained-on-one-million-hours-under-the-indiaai-mission) - Gnani.ai launches Vachana STT, a foundational Indic speech-to-text model. Book a Demo December 19, 2...

34. [Free AI Credits for Text, Writing, Image, Audio, Video | 1minAI](https://1min.ai/free-credits) - Get free credits to explore top AI tools for your business. Sign up for our free AI SaaS plan and un...

35. [Supported Providers for Bolna Voice AI - Bolna Docs](https://www.bolna.ai/docs/providers) - Explore the list of providers supported by Bolna Voice AI, including integrations for telephony, tra...

36. [Sarvam API Pricing | TTS, STT, LLM & More](https://www.sarvam.ai/api-pricing) - Detailed API pricing ; Text to speech · Real-time₹3.00per 1,000 characters ; Speech to text · Real-t...

37. [Gnani.ai Pricing vs. ₹2/Min, Why Indian Businesses Are ... - Tabbly](https://www.tabbly.io/blogs/gnani-ai-pricing-vs-tabbly) - Enterprise AI voice platforms with opaque pricing models like Gnani.ai typically charge in the range...

38. [Free AI Voice Generator - 174 Voices, 37 Languages | Free.ai](https://free.ai/voice/) - Free AI voice generator with 174 realistic voices across 37 languages. Create natural-sounding AI vo...

39. [List all Voice AI Agents API - Bolna Docs](https://www.bolna.ai/docs/api-reference/agent/v2/get_all) - List all Voice AI agents under your account, along with their names, statuses, and creation dates, u...

40. [Bulbul v3 - Text-to-Speech by Sarvam AI - CallMissed (Call Missed)](https://www.callmissed.com/models/bulbul-v3) - pricing from $0.3. At $0.30 per 10K characters, it is competitively priced for high-volume TTS workl...

