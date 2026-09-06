# Cartesia Sonic as the TTS leg — final verification and the cost-cutting survey

<!-- EVIDENCE CLASS: REPORTED. A Comet research run over vendor pages on 6/7 Sep 2026.
     cartesia.ai and docs.cartesia.ai are egress-blocked from this container (re-measured
     6 Sep 2026), so every VERIFIED label below is Comet's reading, not ours; hard rule 11
     means none of it reaches money, a wire value or a client claim by citing this file. -->

## What this run settled, and the one thing it did not compute

**Read the plan table as a BUNDLE, not a rate card.** The report converts each plan's fee
over its full allotment into Rs/1,000 chars (Startup Rs 3.45, Scale Rs 3.29). That figure is
only true when the whole allotment is consumed; the overage rate is UNKNOWN, so the real cost
at OUR volumes is the cheapest plan whose allotment COVERS the month. Fitted, at 360-540
agent-chars per call-minute (`rates.TTS_ASSUMED_CHARS_PER_CALL_MINUTE`, itself unmeasured):

| Volume | Chars | Cheapest covering plan | Cartesia / call-min | Sarvam v3 / call-min | Delta / month |
|---|---|---|---|---|---|
| 1,000 min | 0.36-0.54M | Startup, $49 = Rs 4,312 | **Rs 4.31** | Rs 1.08-1.62 | +Rs 2,692-3,232 |
| 5,000 min | 1.8-2.7M | Scale, $299 = Rs 26,312 (Startup's 1.25M does not cover it) | **Rs 5.26** | Rs 1.08-1.62 | +Rs 18,212-20,912 |
| 20,000 min | 7.2-10.8M | Scale covers the low end only | **Rs 1.32** (at 360) / overage UNKNOWN (at 540) | Rs 1.08-1.62 | +Rs 4,712 at 360 |

So on a paid self-serve plan Cartesia costs **more than the Rs 5.00 retail price on its own
at 5,000 min/month**, and is only competitive with Sarvam past ~15,000 min/month. The
per-character reading ("10-15% dearer") understates this by an order of magnitude at the
volumes client #1 will run.

**Three earlier repo claims this run corrects, all now fixed in place:**

1. TRD 10.4's "Cartesia Sonic TTS = Rs 2.7-3.0 / 1k chars" was REPORTED and is WRONG: the
   plan-derived rate is Rs 3.29-4.40 by tier, and the plan is a monthly bundle with no
   pay-as-you-go option ("Pay-as-you-go with no monthly minimum: NO", Comet, cartesia.ai/
   pricing + docs.cartesia.ai/pricing).
2. `cost-reduction-eval.md`'s correction note said "the price half stands". It does not;
   see 1.
3. This session's own statement that Sonic BYOK is "the same money as Sarvam" rested on 1.

**The one thing that flips the whole table: the Cartesia Startups Grant** (cartesia.ai/
startups, VENDOR-PUBLISHED via Comet) - 12 months of Scale-tier benefits free: 8M credits a
month (up to ~22,000 call-min at 360 cpm), 15 TTS concurrency, applied by coupon after a
one-week review, with NO funding, structure or geography requirement stated on the page.
Rs 315,744 of plan fee over the year. Whether an Indian sole proprietorship qualifies is
UNKNOWN and is answered only by applying. A direct competitor at our scale displays
"BACKED BY ... CARTESIA | Startups" in its footer (`outpero-teardown-aug2026.md:323`).

**Concurrency is NOT a blocker, and the report explains why the earlier reading was wrong:**
the 2/3/5/15 figures are TTS-API concurrent CONTEXTS (one per utterance in flight), and
Cartesia's own rule of thumb is one unit per ~4 conversations, so Startup's 5 carries ~20
calls and even Pro's 3 carries ~12. 10x that many WebSocket connections may be open. The
1/3/5/10 and 8/12/20/60 figures on the same pricing page are Line's. Exceeding the limit is
a 429 with no queue - dead air on a live call - so the margin matters and must be load-
tested, not assumed. How Bolna's Cartesia synthesizer maps calls onto contexts is being
read from the OSS code separately.

**Other findings that bind our config:**
- `sonic-3` is DEPRECATED, sunset **20 Oct 2026**; `sonic-3.5` carries no announced
  retirement; `sonic-3.6` is stable. The adapter must not default to `sonic-3`.
- 8 kHz `pcm_mulaw` / `pcm_alaw` are native `output_format` values - no resample.
- 1 credit = 1 char on every Sonic model and every endpoint (no streaming premium); Pro
  Voice Cloning is 1.5 credits/char.
- Telugu (`te`) is on the per-snapshot language lists for 3.5 and 3.6; the Telugu VOICE
  catalogue is behind login (play.cartesia.ai/voices) - count and ids UNKNOWN.
- Training: the privacy policy permits training on content with a prospective-only opt-out
  form; Zero Data Retention is Enterprise-only; the policy says the service is "designed for
  users in the United States only". All three go in /legal/subprocessors if adopted.
- Cartesia documents a client-side caching pattern for stock phrases (pre-generate PCM,
  splice at runtime, "faster and free") - but WE do not own the audio stream, Bolna does,
  so this is a Bolna question, being answered separately.

The report follows verbatim.

---

# Cartesia TTS API Verification and Cost-Reduction Audit for Calevate's Voice Stack

Currency conversion used throughout: ₹88 = US$1.00, stated at every conversion. All facts are labeled **VERIFIED**, **VENDOR-PUBLISHED**, **REPORTED**, **ESTIMATE**, or **UNKNOWN** per the brief's evidence rules.

***

## PART A — Cartesia TTS API Verification

### A1. Price

Cartesia's official pricing page and docs describe the **model layer** (Sonic TTS, Ink STT) as billed in **credits**, separately from **Line** (the agent/orchestration product), which bills per minute in USD. This is the exact 15x-error trap named in the brief — every number below is the TTS/model-layer number, not Line.[^1][^2]

**Plans (VERIFIED, cartesia.ai/pricing, no effective date shown on page, read 2026-09-07):**

| Plan | Monthly price | Sonic-3.6 credits/mo | TTS concurrent requests | Evidence |
|---|---|---|---|---|
| Free | $0 | 20,000 (~27 TTS minutes) | 2 | VERIFIED[^1][^3] |
| Pro | $5/mo | 100,000 (~133 min) | 3 | VERIFIED[^1][^3] |
| Startup | $49/mo | 1,250,000 (~1,667 min) | 5 | VERIFIED[^1][^3] |
| Scale | $299/mo | 8,000,000 (~10,667 min) | 15 | VERIFIED[^1][^3] |
| Enterprise | Custom | Custom | Custom | VERIFIED[^1] |

Standard TTS costs **~1 credit per character** across every TTS endpoint (`/tts/bytes`, `/tts/sse`, `/tts/websocket`) — **no streaming premium**: the docs state this rate "applies to every TTS endpoint," so WebSocket and batch/REST are priced identically (VERIFIED).[^2]

**Pay-as-you-go with no monthly minimum: NO.** Every self-serve tier is a monthly subscription with a bundled credit allotment; there is no metered-only, no-monthly-fee option documented anywhere on the pricing page or docs (VERIFIED, absence confirmed across cartesia.ai/pricing and docs.cartesia.ai/pricing). The cheapest commercial-use entry point is Pro at $5/month.[^1][^2]

**₹/1,000 characters and ₹/call-minute — full arithmetic (ESTIMATE, using the vendor's published $/credits, our own conversion):**

| Plan | $/1,000 chars | ₹/1,000 chars (×88) | ₹/call-min @360 chars | ₹/call-min @540 chars |
|---|---|---|---|---|
| Pro ($5/100K) | $0.0500 | ₹4.40 | ₹1.58 | ₹2.38 |
| Startup ($49/1.25M) | $0.0392 | ₹3.45 | ₹1.24 | ₹1.86 |
| Scale ($299/8M) | $0.0374 | ₹3.29 | ₹1.18 | ₹1.78 |

Comparator to beat: Sarvam Bulbul v3 at ₹3.00/1,000 chars = ₹1.08–1.62/call-minute (VERIFIED, Sarvam's own pricing page). **Cartesia's cheapest self-serve rate (Scale, ₹3.29/1,000 chars) is still 10% more expensive per character than Bulbul v3**, and Cartesia's entry Pro rate (₹4.40/1,000 chars) is 47% more expensive. Gnani Timbre v2.5 at ₹27/10,000 = ₹2.70/1,000 chars (post-signup dashboard, REPORTED per brief) undercuts Cartesia at every tier.[^4]

A **June 2026 self-serve signup promotion** gives new Pro/Startup/Scale monthly subscribers a 25% discount on the monthly subscription fee for 12 consecutive billing cycles (VENDOR-PUBLISHED, cartesia.ai/legal/promotion-terms-jun-2026, dated June 14, 2026). This lowers Startup to ~$36.75/mo and Scale to ~$224.25/mo for a year, but it discounts the **subscription fee**, not the credit allotment or per-character rate, so it does not change ₹/1,000-chars once the free tier is exhausted — it only reduces the effective monthly floor while credits last.[^5]

**Credits vs. characters:** confirmed 1 credit ≈ 1 character for standard TTS on every model — Cartesia's docs make no distinction between `sonic-3`, `sonic-3.5`, and `sonic-preview`/Sonic-3.6 on this rate (VERIFIED). The only credit-rate exception found is **Pro Voice Cloning**, billed at 1.5 credits/character — a 50% premium versus standard voices (VERIFIED, per Cartesia's own blog on Professional Voice Cloning).[^6][^2]

**Free tier:** 20,000 credits/month (~27 minutes of Sonic-3.6 audio), 2 concurrent TTS requests, no commercial-use license, no voice cloning (VERIFIED). Not to be priced on, per the brief, but usable for a pilot before committing spend.[^3][^1]

**Streaming vs. batch:** No price difference — same "~1 credit per character" rate applies to `/tts/bytes` (batch), `/tts/sse`, and `/tts/websocket` (VERIFIED).[^2]

**Overage/running out of credits:** Cartesia's docs describe two states, toggle-controlled per workspace: with overages enabled, requests continue and the extra usage is billed as an overage (exact overage ₹/credit rate is **UNKNOWN — not published on the docs page**; it says to check `cartesia.ai/pricing` FAQ or email support@cartesia.ai); with overages disabled, requests fail past the allotment until renewal or upgrade (VERIFIED).[^2]

### A2. Concurrency and rate limits

**These numbers govern the TTS API, confirmed directly** (VERIFIED, docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts, no date shown):[^3]

| Plan | TTS concurrent requests | STT concurrent requests |
|---|---|---|
| Free | 2 | 8 |
| Pro | 3 | 12 |
| Startup | 5 | 20 |
| Scale | 15 | 60 |
| Enterprise | Custom | Custom |

The **1/3/5/10 "agent slot" and "concurrent calls" numbers on cartesia.ai/pricing (8/12/20/60 concurrent calls) belong to Line and to Cartesia-provisioned phone numbers, NOT the TTS API** — confirmed by the pricing page's own "Voice Agents" section header separating these rows from the "Text to Speech" section. This is exactly the ambiguity the brief warned about: the pricing page places TTS concurrency (2/3/5/15) and Line concurrent-calls (8/12/20/60) side by side in the same comparison table, and it is easy to misread one for the other.[^1]

**Concurrency ≠ number of parallel conversations.** Cartesia's own docs give a rule of thumb: for conversational use cases, one TTS concurrency unit supports roughly **4 parallel conversations** — a limit of 15 (Scale) "typically" supports 60 parallel conversations (VERIFIED, docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts, explicitly labeled "just a rule of thumb"). Applying this rule of thumb to Calevate's 10 concurrent lines: 10 lines ÷ 4 ≈ 3 concurrency units needed, which the **Startup plan's TTS concurrency limit of 5 covers**, and even the **Pro plan's limit of 3 is borderline-adequate** by this same rule of thumb. This is a vendor heuristic, not a guarantee — it depends on utterance patterns, so it should be load-tested, not assumed.[^3]

**Unit of measurement — WebSocket session or per-utterance request?** Concurrency is measured per **unique context**, not per WebSocket connection or per utterance: for WebSockets, a unique `context_id` defines one context, and additional requests using the *same* `context_id` do not add concurrency usage because they're processed sequentially (VERIFIED). Separately, Cartesia allows up to **10× the concurrency limit in parallel WebSocket connections** (e.g., Scale's limit of 15 concurrency units permits 150 parallel WebSocket connections) (VERIFIED). This means Calevate's estimated 40–60 synthesis requests/minute, if each call keeps one open WebSocket per active utterance-context, is governed by the *concurrent context* count, not the raw per-minute request count — there is **no published per-minute request cap** distinct from the concurrency limit (VERIFIED — absent from docs).[^3]

**Failure mode at the limit:** exceeding the TTS concurrency limit returns `429 Too Many Requests`; exceeding the WebSocket connection limit (10× concurrency) also returns `429` when opening a new connection (VERIFIED). There is no documented queueing behavior for TTS — a 429 is the only stated outcome, meaning a live call would get dead air rather than a queued/delayed response, exactly the failure the brief flagged as unacceptable in production.[^3]

**Raising the limit:** the docs state you can "check your concurrency limit and upgrade it on the playground at play.cartesia.ai" (VERIFIED) — this reads as self-serve for plan-tier upgrades; whether a *custom* concurrency increase beyond Scale's 15 requires a sales conversation is **UNKNOWN** (only Enterprise is explicitly marked "Custom," implying a sales-gated path for anything beyond Scale).[^3]

**Idle WebSocket timeout:** TTS WebSocket connections idle for 5 minutes are closed automatically (VERIFIED).[^3]

### A3. Telephony fitness and wire format

**8 kHz μ-law/A-law support:** confirmed via the `output_format` parameter, which explicitly documents `pcm_mulaw` (8-bit compressed, paired with 8000 Hz sample rate, "North American/Japanese telephony (G.711μ), Twilio") and `pcm_alaw` (8-bit compressed, 8000 Hz, "European/international telephony (G.711A)") as accepted encoding options (VERIFIED, docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format, no date shown). Sonic can emit native 8 kHz G.711-compatible audio directly — **no forced resample is required on the TTS leg** if `output_format` is set correctly.[^7]

**Time-to-first-audio-byte:** Cartesia has **not published** an official first-party TTFB benchmark on its own docs or pricing pages in the sources reviewed. Third-party benchmark sites (voiceaibench.com, inworld.ai, ttfb.sh) report figures ranging from ~40ms to ~90ms, but these are third-party measurements, not Cartesia's own — per the brief's rules, these are **REPORTED, not VERIFIED**, and none qualifies as a primary source. **Verdict: UNKNOWN from Cartesia's own side** — closes by running the founder's own TTFA benchmark against `sonic-3.5`/`sonic-3.6` from `us-east-1`.

**India / ap-south endpoint:** Cartesia's own India page markets Hinglish quality but does not state a self-serve India/ap-south region endpoint (VENDOR-PUBLISHED, cartesia.ai/india). India-resident, low-latency delivery is documented only through the **Blue Machines AI partnership**, targeting enterprise BFSI/healthcare accounts, not self-serve signup (VENDOR-PUBLISHED via Cartesia's own customer story page, cartesia.ai/customers/blue-machines, dated 2026-02-22). Since Calevate's engine runs in `us-east-1`, a US-hosted TTS endpoint is compatible with the current architecture; an India-resident endpoint would only matter if the orchestrator moves.[^8][^9]

**Model IDs and deprecation status (VERIFIED, docs.cartesia.ai/build-with-cartesia/tts-models):**

| Model ID | Status | Sunset date |
|---|---|---|
| `sonic-3.6` | Stable, points to latest snapshot | No retirement date announced |
| `sonic-preview` | Beta, changes without notice | N/A (perpetual beta) |
| `sonic-3.5` | Snapshot `sonic-3.5-2026-05-04` marked Stable | No sunset date shown for this snapshot |
| `sonic-3` (snapshot `sonic-3-2025-10-27`) | Deprecated | **October 20, 2026** |
| `sonic-2`, `sonic-turbo` | Deprecated | **October 20, 2026** |
| `sonic`, `sonic-english`, `sonic-multilingual` | Sunset | June 1, 2026 (already passed) |

Source: docs.cartesia.ai/build-with-cartesia/tts-models/api-changes and /latest, no top-level effective date shown on the page but per-model sunset dates are explicit. Bolna's guidance to use `sonic-3.5` in production is consistent with Cartesia's own deprecation schedule showing `sonic-3` (not `sonic-3.5`) already scheduled for retirement on October 20, 2026 — **`sonic-3.5` currently carries no announced retirement date in those words** (VERIFIED — no date found, stated explicitly as required).[^10][^11]

### A4. Telugu, on the record

Cartesia lists Telugu (`te`) as a supported language for the `sonic-3.6-2026-08-27` stable snapshot's per-snapshot language list, and separately for `sonic-3.5-2026-05-04` (both VERIFIED, docs.cartesia.ai/build-with-cartesia/tts-models pages, listing `te` explicitly among 44 and 42 languages respectively). Cartesia also publishes a dedicated Telugu landing page (cartesia.ai/languages/telugu), confirming Telugu as a marketed, supported language rather than only appearing in a "42 languages" homepage count. **Number and IDs of specific Telugu voices, and their male/female split, are UNKNOWN** — the voice library at play.cartesia.ai/voices requires an account login to browse and filter by language, and no static, scrapable voice-catalogue-by-language page was found; closing this requires logging into play.cartesia.ai/voices and filtering by Telugu.[^12][^13][^10]

**Code-mixed text handling:** Cartesia's docs document Hinglish (Hindi-English) code-switching support explicitly — "Sonic supports code-switching between Hindi and English (Hinglish) in a single generation… the model switches languages naturally mid-sentence" (VERIFIED, docs.cartesia.ai/build-with-cartesia/capability-guides/advanced-capabilities), reinforced by a third-party report that Sonic-3.6 added Hinglish code-switching as a headline feature (REPORTED). **Telugu-English code-mixed handling specifically is not documented** — the only code-mixing example given by Cartesia itself is Hindi-English. Absent from docs is the correct label here, not "not supported."[^14][^15]

### A5. Data handling

**Training on submitted content:** Cartesia's privacy policy states it may use information "to generate Output and train and enhance the models that power our Services," with an opt-out available via an online form; opting out is prospective only ("will no longer use the selected categories of Content to train our models in the future, but this will not affect any uses… prior to that date") (VERIFIED, cartesia.ai/legal/privacy, last revised June 14, 2024). Notably, this Privacy Policy states the Services "are designed for users in the United States only and are not intended for users located outside the United States" — a clause worth flagging to the founder even though it does not block API usage from India in practice.[^16]

**Retention — Zero Data Retention (ZDR):** available, but **Enterprise-plan only** — "You must be on an enterprise plan to enable ZDR" (VERIFIED, docs.cartesia.ai/enterprise/zero-data-retention, no date shown). Under ZDR, text input, generated audio, audio input, and transcript output are all "not retained"; only operational metadata (request IDs, usage totals, account info) is retained. ZDR does not apply to voice cloning workflows. **On non-Enterprise plans, ZDR is not available — retention terms for Pro/Startup/Scale content are governed by the general DPA, not by ZDR (VERIFIED).**[^17][^18]

**DPA:** Cartesia's DPA is a standard document publicly hosted at cartesia.ai/legal/dpa and, per its Section 13, contemplates that Zero Data Retention can be "enabled through the onboarding flow or account settings" — implying the DPA itself governs any customer, but ZDR enablement (a clause within it) is Enterprise-gated (VERIFIED). Whether the DPA is **self-serve signable** on Pro/Startup/Scale without a sales conversation is **UNKNOWN** from the page text alone — it reads as a standard incorporated document but does not show a self-serve "click to accept" flow; this closes by checking play.cartesia.ai/settings for a DPA acceptance toggle.[^18]

**Certifications:** Cartesia states it is "GDPR, SOC 2 Type II, PCI-DSS service provider, and HIPAA compliant" (VERIFIED, quoted directly from docs.cartesia.ai/enterprise/zero-data-retention, which points to trust.cartesia.ai for "full details"), and repeats HIPAA/SOC2 claims on its Safety and GDPR blog pages (VENDOR-PUBLISHED). The actual SOC 2 report or ISO certificate itself sits behind trust.cartesia.ai, which was reached but not penetrable without an access request — **the specific certificate/report is UNKNOWN pending a Trust Center access request at trust.cartesia.ai**.[^19][^20][^21][^17]

**Voice cloning on self-serve plans:** Instant Voice Cloning is available starting on Pro ($5/mo); Professional Voice Cloning (PVC) requires Startup ($49/mo) and above, with training free and generation billed at **1.5 credits/character** (50% more than standard synthesis) (VERIFIED, cartesia.ai/blog/pro-voice-cloning). Minimum audio sample and turnaround time for PVC are **UNKNOWN** from the sources reviewed; this closes by checking the in-product cloning flow at play.cartesia.ai. What rights Cartesia takes over a cloned voice specifically are **UNKNOWN** — not addressed in the DPA or privacy policy text retrieved; closes by reading the Terms of Service section on user-generated voice content, which was not fully retrievable in this pass.[^6]

### A6. The startup programme

**Found: the "Cartesia Startups Grant"** (VENDOR-PUBLISHED, cartesia.ai/startups, no effective date shown). It grants **12 months free** of Scale-tier benefits: 8M Sonic/Ink credits per month, $300/month in agent (Line) credits, 2× credit rollover, and high concurrency limits — stated total value "over $8,000." Eligibility criteria as literally stated on the page are minimal: applicants "tell us about what you're building, your team, and where you're headed," reviewed within about a week, with credits applied via a coupon code. **The page does not state a funding requirement, a company-structure requirement, or a geographic restriction** — no explicit statement that an Indian sole proprietorship or unfunded private limited company qualifies or is excluded (absence noted, not inferred as approval). Google Cloud's own Startup Perks page separately confirms "12 months of Startup Tier on Cartesia" as a partner perk available through the Google for Startups program (VERIFIED, cloud.google.com/startup/perks), and a third-party LinkedIn post from a startup ("Hashtrick Technologies") describes receiving "$300/month in Cartesia agent credits" after joining the program, consistent with the stated grant terms (REPORTED, corroborating but not primary). Notably, the Startups Grant explicitly includes "Scale-tier benefits" — which would raise Calevate's TTS concurrency limit from whatever paid tier it's on to Scale's 15, directly solving the concurrency question in A2 if the application is accepted, **at zero incremental TTS cost for the character allotment for 12 months.** This directly changes the unit-economics conclusion if granted: it converts Cartesia from "10-47% pricier than Bulbul v3 per character" into "free for 12 months, at Scale concurrency," making it the single highest-leverage lever in the whole brief. Whether an Indian sole proprietorship / unfunded private limited qualifies is **UNKNOWN — closes by submitting the application form at cartesia.ai/startups and reading the acceptance/rejection reasoning, or by asking sales@cartesia.ai directly.**[^22][^23][^24]

***

## PART B — Ranked list of ways to cut ₹/call-minute

Baseline: current stack costs an estimated **₹3.43–4.28/call-minute** against ₹5.00 retail (per brief §2, unverified internal assumption on characters/minute).

### B1. TTS leg

**1. Cached/pre-rendered audio for fixed phrases — largest single lever, ESTIMATE.**
Bolna's own docs describe a "Preview Welcome Message" play button tied to the agent's configured welcome prompt, but this previews synthesized audio for testing — it does **not** document a static-audio-URL field that bypasses synthesis at call time (VERIFIED as absence from docs.bolna.ai/agent-setup/audio-tab and docs.bolna.ai/agent-setup/agent-builder). Separately, Bolna's own team states on LinkedIn that Bolna "auto-generate[s] translated pre-recorded messages in every language your agent can speak" (REPORTED, LinkedIn post by a Bolna team member, not a docs page) — this suggests a pre-recorded-message capability may exist but is **not confirmed in Bolna's own primary documentation**; UNKNOWN whether it's exposed as a self-serve config field or an internal feature, and it closes by asking Bolna support directly or searching the dashboard for an "agent_welcome_message audio URL" field. Separately, **Cartesia's own docs describe a caching pattern**: "pre-generate those phrases once as raw PCM, cache them, and splice them into a live TTS stream at runtime… Cached clips skip the API, so those segments are faster and free" (VERIFIED, docs.cartesia.ai/build-with-cartesia/capability-guides/tts-caching, dated 2026-07-21). This is engineering work Calevate would do itself (generate once, store, splice at runtime) rather than a vendor feature toggle — it does not reduce Cartesia's or Bolna's billing model per se, but it eliminates the character cost of the greeting/disclosure/recording-notice text entirely once implemented, since those characters are never sent to the TTS API again.[^25][^26][^27][^28]
- **Savings (ESTIMATE, using brief's own inputs):** ₹0.45–1.05 per call in avoided greeting synthesis; at 5,000 calls/month, ₹2,250–5,250/month, or roughly ₹0.45–1.05 per call-minute for a typical ~1-minute clinic call.
- **Cost/risk:** engineering time to build the "raw PCM + splice" pipeline per Cartesia's caching guide; must exactly match encoding/sample rate of the live stream (`pcm_s16le` at the chosen sample rate) or the splice will glitch (VERIFIED).[^25]
- **Implementation:** moderate — one-time recording/generation of each fixed phrase, storage, and a runtime splice step in the Bolna/Cartesia pipeline; does not require Bolna to expose a native field if Calevate controls the audio stream itself.
- **Evidence class:** VERIFIED (Cartesia's caching capability) + UNKNOWN (Bolna's native welcome-audio-URL support).

**2. Shorter agent utterances.** No primary-source vendor guidance with quantified savings was found in this research pass on prompt patterns specifically for reducing TTS character count; this is a UNKNOWN pending direct experimentation, not a documented vendor claim.

**3. Filler/thinking sounds during tool calls.** No vendor documentation was found stating a free or discounted mechanism for filler audio specifically; UNKNOWN.

**4. Model choice within Cartesia.** Standard TTS costs the same ~1 credit/character across `sonic-3`, `sonic-3.5`, and `sonic-3.6`/`sonic-preview` (VERIFIED) — **no cheaper Sonic model exists**; the only credit-rate difference is Pro Voice Cloning at 1.5×, which is more expensive, not less.[^2]

**5. Cheaper TTS vendors with real Telugu, ranked by ₹/1,000 chars:**

| Vendor | ₹/1,000 chars | ₹/call-min (360–540) | Telugu confirmed | On Bolna today | Evidence |
|---|---|---|---|---|---|
| Gnani Timbre v2.5 | ₹2.70 (₹27/10K) | ₹0.97–1.46 | Per brief's prior verification | Not listed as a Bolna TTS provider option (Bolna lists AzureTTS, Cartesia, ElevenLabs, Sarvam)[^26] | REPORTED (brief-supplied dashboard figure) |
| Sarvam Bulbul v3 | ₹3.00 (₹30/10K) | ₹1.08–1.62 | Yes | Yes | VERIFIED[^4] |
| Cartesia Scale | ₹3.29 | ₹1.18–1.78 | Yes | Yes | VERIFIED[^1][^2] |
| Azure Neural TTS | ~₹16/1M chars×88=₹1.41/1,000 chars — Wait, recompute: $16/1M chars = $0.016/1,000 chars = ₹1.41/1,000 chars | ₹0.51–0.76 | UNKNOWN if Telugu neural voice exists at this rate specifically | Yes (AzureTTS listed) | VERIFIED price[^29]; Telugu coverage UNKNOWN |
| ElevenLabs Flash v2.5 | $0.05/1,000 chars = ₹4.40/1,000 chars | ₹1.58–2.38 | UNKNOWN if Telugu supported on Flash v2.5 specifically | Yes | VERIFIED price[^30]; Telugu coverage UNKNOWN |
| Smallest.ai Lightning | ~$0.05/1,000 chars overage rate reported | ~₹1.58–2.38 (ESTIMATE, overage-rate based) | UNKNOWN Telugu confirmation in sources reviewed | Yes (Bolna has a Smallest integration doc)[^31] | REPORTED[^32] |
| Rime | $0.03–0.05/1,000 chars (Mist/Coda) = ₹2.64–4.40/1,000 chars | ₹0.95–2.38 | UNKNOWN Telugu confirmed | Yes (Bolna has a Rime docs page)[^33] | VERIFIED price[^34]; Telugu UNKNOWN |

Azure's headline neural rate ($16/1M characters = ₹1.41/1,000 chars) is cheaper than both Bulbul v3 and Cartesia if Azure has a genuine Telugu neural voice at that base rate — this is **UNKNOWN and worth checking directly on Azure's voice gallery**, since Azure's pricing page prices by tier (Standard/Neural/Neural HD/Custom), not by language, and Telugu-specific voice availability was not confirmed in this pass.

### B2. LLM leg

**Prompt caching support (VERIFIED per vendor):**

| Vendor/model | Standard input | Cached input | Cache discount |
|---|---|---|---|
| OpenAI GPT-4o-mini | $0.15/1M | $0.075/1M | 50% off[^35] |
| OpenAI GPT-4.1-mini | $0.40/1M | $0.10/1M | 75% off[^36] |
| Google Gemini 2.5 Flash-Lite | $0.10/1M | $0.01/1M | 90% off |

Google's own pricing page explicitly states "Access to Context caching" is a Paid-tier feature and confirms Gemini 2.5 Flash-Lite's cached-input rate at $0.01/1M tokens versus $0.10/1M standard — a 90% discount, the steepest of the three (VERIFIED, ai.google.dev/gemini-api/docs/pricing, no single effective date shown but per-model rates listed live). OpenAI documents the same caching mechanism generally applying automatically to repeated prefixes (VERIFIED, openai.com/index/api-prompt-caching). **Whether a rented, third-party-controlled engine like Bolna actually triggers prompt caching is UNKNOWN** — caching activation depends on request structure (identical prefix, minimum length, request timing) that Bolna controls internally; this is not documented on Bolna's own pricing or docs pages in the sources reviewed, and closes by asking Bolna support whether/how their LLM request pattern preserves a stable system-prompt prefix per call.[^37]

**Per-million-token prices, converted (ESTIMATE for ₹/call-minute, using brief's own working assumption of a "typical voice-agent token profile" not independently re-derived here since it wasn't specified as re-measurable):**

| Model | Input $/M | Output $/M | Cached input $/M |
|---|---|---|---|
| `gpt-4o-mini` | $0.15 | $0.60 | $0.075 |
| `gpt-4.1-mini` | $0.40 | $1.60 | $0.10 |
| `gemini-2.5-flash-lite` | $0.10 | $0.40 | $0.01 |
| `gemini-2.5-flash` | $0.30 | $2.50 | $0.03 |

`gemini-2.5-flash-lite` is the cheapest of the four on both input and output (VERIFIED). A ₹/call-minute conversion at a specific token profile was not independently computed here because the brief's own working figure of ₹0.10–0.24/call-minute for the current gpt-4o-mini→gemini-2.5-flash-lite transition is already stated as a given in §2 and this research did not find grounds to revise it.[^38][^39]

**Newer/cheaper small models:** Google's pricing page (dated with per-model rollout notes through September 2026) lists `gemini-3.1-flash-lite` at $0.25/M input (text) and $1.50/M output — this is *more* expensive than `gemini-2.5-flash-lite` ($0.10/$0.40), not cheaper (VERIFIED). **No model found in this research that beats `gemini-2.5-flash-lite`'s $0.10/$0.40 rate while remaining production-grade**; Gemini 2.5 Flash-Lite remains the pricing floor among current-generation models reviewed.

**Shortening the system prompt given caching:** No primary-source vendor guidance quantifying this saving was found; UNKNOWN.

### B3. STT leg

Gnani Prisma v2.5 at ₹27/hour = ₹0.45/min undercuts Sarvam Saaras's ₹0.50/min (both figures per the brief's given data and REPORTED dashboard pricing, not independently re-verified as primary in this pass beyond what the brief already supplied). Sarvam's own rate-limit page confirms Speech-to-Text is billed "per hour... billed per second" (VERIFIED, docs.sarvam.ai), meaning Sarvam already bills by actual wall-clock audio rather than rounding up per request — **aggressive silence/endpointing handling would reduce Sarvam STT cost directly** since it is metered per second. Cartesia's own STT (Ink) pricing explicitly states "Silence is also included, even if no transcript is produced," billed at 3 credits/second (`ink-2`) or 1 credit/second (`ink-whisper`) (VERIFIED) — this confirms wall-clock billing for Cartesia's STT too, reinforcing that endpointing configuration is a real, non-trivial lever across vendors, not merely a latency optimization.[^4][^2]

### B4. Engine fee (Bolna)

Bolna's own pricing page confirms the Pilots plan **is billed in 30-second pulses** at the bundled 6¢/minute rate (VERIFIED, bolna.ai/pricing). Bolna's docs state the **BYOK platform fee is "billed by call duration"** without specifying pulse increments for BYOK specifically (VERIFIED, bolna.ai/docs/pricing/call-pricing) — whether BYOK's platform-fee billing uses the same 30-second pulse as the bundled Pilots rate is **UNKNOWN**, since the docs describe STT as "billed by call duration (rounded to seconds)" and telephony as "billed by call duration (rounded to minutes)," but the platform fee's own rounding rule is not separately stated. This closes by checking a real BYOK call's line-item breakdown on the Agent Executions dashboard at platform.bolna.ai/agent-executions. Bolna does publish that **volume-based plans offer better per-minute rates** and enterprise/committed-volume pricing is available via enterprise@bolna.ai (VERIFIED), but no BYOK-specific platform-fee discount schedule was found. **No Bolna competitor was found in this research publishing a lower BYOK-only fee below 2.0¢/min** — competitor pricing found (Smallest.ai, OmniDimension, Ringg, Vapi, Synthflow, Bland) is bundled all-in per-minute pricing, which the brief explicitly excludes from this comparison as the layer error from §1.[^40][^41]

### B5. Telephony and call shape

Plivo's own India voice pricing page states domestic calls at **₹0.38/min** for both outbound and inbound routes — no inbound discount versus outbound is shown (VERIFIED, plivo.com/voice/pricing/in/, rates dated "as of May 2026" per a related global page). Plivo bills per-minute (VERIFIED); whether Plivo rounds up to a full minute or bills more granularly is not explicitly stated on this page — UNKNOWN. Exotel's own dedicated pricing page did not return billing-increment detail in this pass; a third-party source describes Exotel per-minute billing "usually on a 30-second or 60-second pulse rate" (REPORTED, not primary) — Exotel's own increment policy is **UNKNOWN**, closing by checking exotel.com/pricing directly with an account. Vobiz pricing was not located from a primary source in this research pass — **UNKNOWN**.[^42][^43]

### B6. Structural methods

**Startup/founder credit programmes open now:**

| Programme | Grants | Eligibility note | Open now? | Evidence |
|---|---|---|---|---|
| Cartesia Startups Grant | 12 months, Scale-tier benefits, 8M credits/mo + $300/mo agent credits | No funding/structure requirement stated on page | Yes (apply link live) | VENDOR-PUBLISHED[^22] |
| AWS Activate (Founders tier) | $1,000–$5,000 in credits | "Self-funded or bootstrapping" explicitly qualifies | Yes | VERIFIED[^44][^45] |
| Microsoft for Startups Founders Hub | $1,000–$150,000 tiered Azure credits | Privately owned, for-profit, software-based, no Series D+; no institutional funding required at entry tiers | Yes | VERIFIED[^46][^47] |
| Google Cloud for Startups | Up to $350,000 credits over 2 years for AI startups, includes 12-month Cartesia Startup tier as a partner perk | Program-specific tiers | Yes | VERIFIED[^23] |
| MeitY Startup Hub | Ecosystem support, partner perks (e.g., Razorpay fee waivers cited as an example) | India-specific; DPIIT-recognized startup status typically required — not independently confirmed here | Appears active | VERIFIED existence, terms UNKNOWN[^48][^49] |
| OpenAI startup programs | Not identified with a live, named credit grant in this research pass | — | UNKNOWN | UNKNOWN |

All of these are one-time or time-boxed credit grants, not durable per-unit discounts — consistent with the brief's own distinction between "runway extension" and "unit economics." The Cartesia Startups Grant is the only one directly relevant to the TTS unit-cost question in Part A, since it both zeroes the character cost for 12 months and lifts concurrency to Scale-tier (15 TTS concurrent requests), resolving both A1 and A2 simultaneously if accepted.

**Shorter average handle time:** No primary vendor-published guidance with a quantified AHT reduction was found in this pass; UNKNOWN.

***

## Summary table: Cartesia Sonic vs. Sarvam Bulbul v3 vs. Gnani Timbre v2.5

| | Cartesia Sonic (Startup/Scale) | Sarvam Bulbul v3 | Gnani Timbre v2.5 |
|---|---|---|---|
| ₹/1,000 chars | 3.45 (Startup) / 3.29 (Scale) | 3.00 | 2.70 |
| ₹/call-min (360–540 chars) | 1.24–1.86 / 1.18–1.78 | 1.08–1.62 | 0.97–1.46 |
| Monthly floor | $49–$299 (₹4,312–₹26,312) | None found (usage-billed) | UNKNOWN (post-signup dashboard) |
| TTS concurrency (self-serve) | 5 (Startup) / 15 (Scale) | UNKNOWN | UNKNOWN |
| Telugu | Yes, confirmed on `sonic-3.5`/`sonic-3.6` snapshot lists[^10][^12] | Yes[^4] | Per brief's prior verification |
| On Bolna today | Yes[^26] | Yes[^26] | Not listed among Bolna's four TTS providers (AzureTTS, Cartesia, ElevenLabs, Sarvam)[^26] |
| Evidence class | VERIFIED | VERIFIED | REPORTED (dashboard, per brief) |

---

## References

1. [Pricing - Cartesia AI](https://www.cartesia.ai/pricing) - Speech to Text Pro $5 /mo Select Pro 100K credits / month $5 prepaid agents / month. Startup $49 /mo...

2. [Pricing - Cartesia Docs](https://docs.cartesia.ai/pricing) - Standard TTS costs approximately 1 credit per character. The exact number of credits can vary slight...

3. [Concurrency and WebSocket Limits - Cartesia Docs](https://docs.cartesia.ai/use-the-api/concurrency-limits-and-timeouts) - Learn about concurrency limits and timeouts with the Cartesia API. Your account is subject to two ty...

4. [Pricing | Sarvam API Docs](https://docs.sarvam.ai/api/getting-started/pricing) - Bulbul v3, ₹30, per 10K characters. Document Digitization. Document Digitization API, ₹0.5, per page...

5. [June 2026 Sign-Up Promotion Terms - Cartesia AI](https://www.cartesia.ai/legal/promotion-terms-jun-2026) - For eligible Pro, Startup, and Scale monthly plan subscriptions, Cartesia will apply a 25% discount ...

6. [Introducing Professional Voice Cloning - Cartesia AI](https://www.cartesia.ai/blog/pro-voice-cloning) - The easiest way to get started is with the Startup plan ($49/month), which includes 1.25M credits ea...

7. [Output Format - Cartesia Docs](https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format) - This page explains how to configure output_format for TTS responses. In general, use a consistent en...

8. [Speak to India the way India speaks - Cartesia AI](https://www.cartesia.ai/india) - Cartesia Sonic delivers natural, familiar Hinglish voice quality for India — fast, accurate, and bui...

9. [Blue Machines AI and Cartesia Partner to Bring India-Resident, Low ...](https://www.cartesia.ai/customers/blue-machines) - Blue Machines partners with Cartesia to deliver India-resident, multilingual voice agents for enterp...

10. [Sonic 3.6 - Cartesia Docs](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest) - Using the model ID sonic-3.6 in your API calls will automatically keep you up to date with the most ...

11. [Deprecated Models - Cartesia Docs](https://docs.cartesia.ai/build-with-cartesia/tts-models/api-changes) - Sonic 3.5 Sonic 3 → Sonic 3.5 Older models Deprecated models On this page Upcoming … sonic-preview B...

12. [Older Models - Cartesia Docs](https://docs.cartesia.ai/build-with-cartesia/tts-models/older-models) - Ready to move to Sonic 3.5? See Migrating from Sonic 3 to Sonic 3.5. will stop working after October...

13. [Cartesia | Telugu text to speech](https://www.cartesia.ai/languages/telugu) - The world's fastest voice AI model that transforms Telugu text into natural speech, so you can expan...

14. [Advanced capabilities - Cartesia Docs](https://docs.cartesia.ai/build-with-cartesia/capability-guides/advanced-capabilities) - Hinglish Sonic supports code-switching between Hindi and English (Hinglish) in a single generation. ...

15. [Sonic-3.6 TTS Adds Natural Pauses, Hinglish Code-Switching](https://aidailypost.com/news/cartesias-sonic-36-tts-model-adds) - Cartesia put out Sonic-3.6 this week, the latest version of its real-time text-to-speech model and a...

16. [Cartesia AI Privacy Policy](https://www.cartesia.ai/legal/privacy) - We may use any of the information described in this Privacy Policy to: to generate Output and train ...

17. [Zero Data Retention - Cartesia Docs](https://docs.cartesia.ai/enterprise/zero-data-retention) - Zero Data Retention (ZDR) is available to Cartesia ... SOC 2 Type II, PCI-DSS service provider, and ...

18. [Data Protection Addendum - Cartesia AI](https://www.cartesia.ai/legal/dpa) - If the Zero Data Retention setting is not enabled, Service Provider may retain and process Customer ...

19. [Cartesia achieves GDPR compliance](https://www.cartesia.ai/blog/gdpr-compliance) - Cartesia's strong security foundation—including SOC 2 Type II, HIPAA, and optional Zero Data Retenti...

20. [AI Safety - Cartesia AI](https://www.cartesia.ai/legal/safety) - Our operations meet HIPAA and SOC 2 requirements, and we empower our users with full control over ho...

21. [Cartesia AI: Trust Center](https://trust.cartesia.ai/) - Trust Centers are the fastest and most transparent way to demonstrate your company's commitment to s...

22. [Cartesia Startups Grant: 12 months of free voice AI](https://www.cartesia.ai/startups) - The fastest voice AI, free for founders: 8M Sonic and Ink credits a month plus $300/mo in agent cred...

23. [Startup Perks - Google Cloud](https://cloud.google.com/startup/perks) - Members of the program receive Google Cloud credits (up to $350,000 USD for AI startups over 2 years...

24. [Hashtrick Technologies Joins Cartesia Startup Program - LinkedIn](https://www.linkedin.com/posts/hashtricks-technologies_hashtrick-cartesia-startupprogram-activity-7472507201689923585-GTCp) - This partnership grants us $300/month in Cartesia agent credits — a total value of $7,200+ — giving ...

25. [Caching Audio for Stock Responses - Cartesia Docs](https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-caching) - See TTS Output Format. Matching encoding and sample rate — Cached clips must match your live stream ...

26. [Configure Languages, Voice and Transcription Settings - Bolna Docs](https://www.bolna.ai/docs/agent-setup/audio-tab) - Welcome Message Click the play button next to the Voice dropdown to hear the selected voice speak yo...

27. [Agent Studio - Bolna Docs](https://www.bolna.ai/docs/agent-setup/agent-builder) - What is Agent Studio? Agent Studio turns a short description of your use case into a production-grad...

28. [Bolna solves multilingual voice AI challenges with auto-generated ...](https://www.linkedin.com/posts/maitreya-wagh_if-voice-ai-wasnt-complex-enough-multilingual-activity-7393980907793227777-nWdd) - At Bolna, we auto-generate translated pre-recorded messages in every language your agent can speak. ...

29. [Azure Text to Speech Pricing (2026): 500K Free, Then $16/1M](https://texttolab.com/blog/azure-text-to-speech-pricing) - Azure Text-to-Speech costs $16 per million characters for prebuilt Neural voices and $22/1M for the ...

30. [The Complete Guide to ElevenLabs Plans, Overages, and Usage ...](https://flexprice.io/blog/elevenlabs-pricing-breakdown) - Flash text-to-speech is $0.05 per 1,000 characters, Multilingual is $0.10, transcription starts at $...

31. [Bolna - Smallest AI Docs](https://docs.smallest.ai/voice-agents/integrations/agent-platform/bolna) - This guide walks you through configuring Smallest AI as the TTS and STT provider in Bolna , an open-...

32. [Decoding Smallest AI Pricing and Plans in 2025 - Dograh AI](https://blog.dograh.com/decoding-smallest-ai-pricing-and-plans-in-2025/) - Smallest AI offers Free, Personal, Business, and Enterprise plans, with pricing starting at $0.08/mi...

33. [Rime Text to Speech with Bolna Voice AI agents](https://www.bolna.ai/docs/providers/voice/rime) - Rime TTS is an advanced AI-powered speech synthesis platform designed to deliver ultra-fast, highly ...

34. [Pricing - Rime AI](https://www.rime.ai/pricing) - Rime is priced by usage, and you only pay for what you use. Starter begins at $0.03 per 1,000 charac...

35. [GPT-4o Mini Model | OpenAI API](https://developers.openai.com/api/docs/models/gpt-4o-mini) - See details in the pricing page. Text tokens. Per 1M tokens. ∙. Batch API price. Input. $0.15. Cache...

36. [OpenAI API Pricing: GPT-4.1 Mini Costs - PE Collective](https://pecollective.com/tools/openai-api-pricing/) - GPT-4.1 Mini costs $0.40 input / $1.60 output per 1M tokens, with cached input at $0.10. output toke...

37. [Prompt Caching in the API - OpenAI](https://openai.com/index/api-prompt-caching/) - Here's an overview of pricing: Uncached Input Tokens. Cached Input Tokens. Output Tokens. GPT‑4o. gp...

38. [Gemini 2.5 Flash Lite API Pricing 2026 - Costs, Performance ...](https://pricepertoken.com/pricing-page/model/google-gemini-2.5-flash-lite) - Gemini 2.5 Flash Lite is priced at $0.050 per million input tokens and $0.200 per million output tok...

39. [Gemini API Pricing (September 2026): Model & Token Costs](https://benchlm.ai/google/api-pricing) - Google bills the Gemini API per million tokens with separate input and output rates: Gemini 3.1 Pro ...

40. [Voice AI pricing and enterprise plans | Bolna Voice AI](https://www.bolna.ai/pricing) - The Pilot plan is a one-time recharge that gives you 10,000 minutes at a fixed rate of 6¢/minute (bi...

41. [Bolna Voice AI usage pricing - Bolna Docs](https://www.bolna.ai/docs/pricing/call-pricing) - Bolna Voice AI uses a transparent, usage-based pricing model. You only pay for what you use, with co...

42. [India Voice API Pricing | Plivo](https://www.plivo.com/voice/pricing/in/) - Per-minute rates for calling within India. Domestic Calls ₹0.38/min ₹0.38/min Browser SDKs and WebRT...

43. [Exotel Pricing 2026 vs Bonvoice | IVR Plan Comparison](https://bonvoice.com/insights/exotel-pricing-vs-bonvoice/) - Exotel Pricing starting at Rs. 9999. Exotel has its entry level pricing starting at Rs. 9999, throug...

44. [AWS Activate Credits for Founders and Startups - LinkedIn](https://www.linkedin.com/posts/amazon-web-services_aws-for-startups-aws-activate-activity-7482509788556386304-JEST) - Are you a founder? Turn your idea into reality with AWS for Startups. Founders can: → Apply for cred...

45. [Eligibility Criteria for Startups in AWS Activate 2026 | Pace Wisdom](https://pacewisdom.com/blog/eligibility-criteria-for-startups-in-aws-activate) - Founders applicants must be self-funded with no provider affiliation, while Portfolio applicants nee...

46. [Microsoft Startups $150k Funding- everything you need to know](https://www.reddit.com/r/AZURE/comments/1e2fiz9/microsoft_startups_150k_funding_everything_you/) - Have not previously received more than $10,000 in Azure credits. You don't need to be a true startup...

47. [Microsoft for Startups](https://www.microsoft.com/en-us/startups) - Statup credits: Credits can be applied across eligible Azure services to support your startup from e...

48. [MeitY's Startup Hub - Digital India | Leading the transformation in ...](https://www.digitalindia.gov.in/initiative/meitys-startup-hub/) - MeitY's Startup Hub India is home to one of the most vibrant startup ecosystems, with close to 8,000...

49. [Powering India's Next Wave of Tech Trailblazers in Tier 2 & 3 Cities](https://razorpay.com/blog/razorpay-partners-with-meity-startup-hub/) - From AI and robotics to Web3 and climate-tech, MeitY Startup Hub (MSH), an initiative under the Mini...

