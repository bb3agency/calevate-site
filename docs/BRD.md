# Calevate — Business Requirements Document (BRD)

Version 1.0 · July 2026 · Owners: Sri (founder), BuiltByThree
Status: Decision-complete. All choices below were made deliberately; changes require a decision-log entry (see ROADMAP.md §6).

---

## 1. Vision

Calevate ("call + elevate", calevate.tech) is a managed AI voice-agent service for Indian SMBs.
Businesses get a 24/7 AI phone employee that answers/makes calls in their customers' language
(Telugu-first, all Indian languages by architecture), qualifies leads, books appointments,
extracts structured data into a built-in CRM, and hands hot leads to humans — replacing manual
telecalling at a fraction of the cost.

Calevate is **platform + service**, not a self-serve tool: we build, tune, monitor, and are
accountable for each client's agent. The technology layer (dashboards, CRM, extraction,
billing) is productized; the last mile (onboarding, prompt/KB curation, campaign management)
is our human service and our moat.

Parent brand: BuiltByThree. Calevate runs as a product brand; the operating legal entity is
**TBD and is the #1 pre-launch blocker** (see §9, Risk R-01).

## 2. Problem & Opportunity

- SMBs miss inbound calls (lost revenue) or staff telecallers at ₹18–25k/month each plus
  supervision, with no nights/weekends coverage.
- Outbound lead follow-up is slow; speed-to-lead determines conversion, and manual dialing
  cannot call a fresh web/Meta lead within seconds.
- Existing options: US platforms (USD billing, weak Indic languages, India telephony
  surcharges), Indian self-serve platforms (client does everything themselves), or local
  resellers like Outpero (service-only, hand-built per client, Telugu/Hindi, built on a
  third-party no-code platform).

Wedge: an India-native managed offering with (a) genuinely multilingual architecture,
(b) a real client dashboard + mini-CRM with **client-customizable extraction data points**,
(c) transparent all-in economics, (d) an engineering-grade quality process (per-client
regression testing) that reseller competitors do not expose.

## 3. Target Market & Personas

Launch market: India, Telugu-first (AP/Telangana), pan-India multi-language by config.
Verticals: launch templates for **clinics/healthcare** and **real estate**; insurance,
education, D2C as fast-follow templates. No vertical lock: extraction schemas are
per-client configurable (see TRD §7).

Personas:
- **P1 Calevate Admin (Sri/team):** onboards clients, builds agents, monitors quality,
  manages billing. Uses admin console.
- **P2 Client Owner (SMB owner):** buys outcomes ("no missed calls", "qualified leads").
  Views dashboard, leads, recordings; approves KB content; pays invoices.
- **P3 Client Staff:** works the Leads table daily; must NOT see billing or org settings.
- **P4 Caller (end customer):** speaks Telugu/Hindi/mixed; expects a natural, fast,
  honest conversation; has DPDP/TRAI rights (disclosure, consent, opt-out).

## 4. Product Scope (business level)

In scope v1:
1. Inbound AI receptionist per client (answer, resolve FAQs from client KB, book/capture,
   escalate) and outbound calling (instant lead callback via webhook; bulk campaigns with
   retry/scheduling/concurrency).
2. Client dashboard: call metrics, sentiment, after-hours capture, repeat-caller flags,
   busiest hours, per-call transcript + recording + AI summary + resolved/needs-follow-up tags.
3. Leads mini-CRM: columns driven by per-client extraction schema; status management;
   filters; CSV export; hot-lead notifications (email/WhatsApp).
4. Admin console: client onboarding wizard, agent config, KB management with
   preview-and-approve, number provisioning, usage/margin view, spend caps.
5. Billing: metered ledger; plan = setup fee + monthly retainer with included minutes +
   overage; prepaid credit + hard caps.
6. Compliance built-in: AI disclosure at call start, recording consent, DND/DNC checks,
   DLT-classified campaigns, PII redaction in transcripts (see SECURITY-COMPLIANCE.md).
7. Client-initiated AI actions from the CRM (decided Jul 2026, D-21; competitor parity+):
   (a) "Call this lead" — owner role dispatches a single AI call from the Leads table,
   with an optional free-text per-call context note appended to the agent's CallContext;
   runs the same compliance pre-checks as webhook dispatch (DNC, calling hours, caps).
   (b) "AI callback" on needs-follow-up calls — one click re-dispatches the agent with
   context from the flagged call, via the engine's context-injection webhook (Outpero's
   equivalent button only tells the human to call; ours closes the loop with AI).
   Boundaries that stay managed-service: extraction schemas remain admin-edited
   (clients request changes through us); lead statuses stay the fixed enum in v1
   (custom tags/statuses only if pulled by a client).

Out of scope v1 (explicit): white-label/reseller tiers; ~~self-serve signup~~ (**pulled
back IN by D-34/D-39** — the second motion; `POST /v1/auth/signup` ships behind an
intake flag that defaults to OFF, SURFACES §2c); non-voice channels as products (WhatsApp
used only for follow-up notifications); building our own STT/TTS/LLM; GPU self-hosting
(phase-3 trigger only).

## 5. Competitive Landscape (as researched, July 2026)

- **Outpero** (direct comp, Telugu) — **re-scoped Aug 2026 after an authenticated in-product
  teardown** (full evidence: `docs/evidence/outpero-teardown-aug2026.md`; the July demo-only
  read below is superseded). Outpero is the product of **OpenDG Pvt Ltd**, a Hyderabad agency
  founded 2014 (ISO 9001:2015) — NOT a beginner service shop. They productised a decade of
  manual phone-lead work, i.e. **our own thesis, shipped by an incumbent with a client base
  and local GTM.** Verified stack: React SPA + Supabase auth + custom FastAPI-style REST
  (`api.outpero.com`). **TTS vendors read directly from their shipped JS (11 Aug 2026):
  `value→sarvam_per_min`, `standard→smallest_per_min`, `premium→cartesia_per_min`** — i.e.
  their ₹3 tier is **Sarvam**, ₹5 is **Smallest.ai**, and the ₹7 "exclusive native Telugu"
  tier is **Cartesia**. Every one of those three is also on Bolna's supported-TTS list, so
  **whether they self-orchestrate or rent an orchestrator is NOT established** — do not assert
  it either way. Consequence for us: every model they use is available to us at published
  rates, so their tiering is a packaging choice, not a moat; whether Cartesia genuinely beats
  Bulbul v3 on Telugu is an ear test we should run. The product is mature and self-serve.
  - **Pricing (the material change):** ₹0 setup · **₹1,899/employee/mo** (₹2,241 incl GST,
    includes ₹500 credits + a number) · talk-time **₹3/₹5/₹7 per min** by voice tier
    (value/standard/premium), 30-sec-block billing, ring/unanswered free; volume-bonus credit
    packs (effective ~₹4.46–5.02/min at standard); Enterprise >₹50k waives the hire fee. An
    SMB's first month ≈ ₹2,241 vs our D-11 ≈ ₹55–105k — **this collides with D-11's pricing
    rationale; tracked as D-34 (open).** The old "₹60k+ setup" figure survives only on their
    high-touch AGENCY packages, not the product an SMB actually buys.
  - **Feature FLOOR (all shipped, verified — treat as our client-app floor; in §4 scope unless
    marked):** branching section-graph script builder with a Flexible↔Strict adherence slider
    and an **AI copilot ("Swara") that edits the whole flow by voice/text**; tiered voice
    catalog (personality×language×gender) that doubles as the price lever; ambient-sound bed;
    per-agent **KB** (docs/webpages, on-demand retrieval) with a teach-and-approve flow;
    in-call actions (**WhatsApp via Interakt/AiSensy/Meta Cloud**, Custom API, Google Calendar);
    schema-driven extraction → dynamic CRM columns; leads rollup (table/grid/kanban) + call log
    + conversations viewer with a full outcome enum; Performance suite (connect rate, conversion
    funnel, busiest hours, employee leaderboard); calling policy (hours/days/holidays/retry×3/
    DNC/concurrency/dedup); bulk campaigns (CSV/paste/load, concurrency, auto-retry, schedule,
    **recurring daily/weekly**); post-call webhooks; GST billing.
  - **Gaps we exploit (revised — two former "gaps" are now closed by them, so drop them):**
    their extraction is **untyped** (observed mis-fill: a location written into a
    quantity field) — our typed+validated `extraction_schema` is a real quality edge;
    on compliance, be precise — **their posture is substantive, not light** (TCCCPR/NCPR-bound
    AUP, KYC'd numbers, a *durable versioned consent-attestation record*, 24h evidence
    production, fixed calling hours, auto-DNC), so the honest edges are narrower and sharper:
    **AI disclosure is optional for them** ("scriptable" but not required — ours is mandatory
    per Hard Rule 5), **raw caller PII renders un-redacted** in their dashboard (we default to
    `text_redacted` + role-gated raw), **data may be processed outside India** (we are
    India-resident by design), and their **liability is capped at 3 months of fees with Terms §9
    explicitly disclaiming any availability guarantee — contradicting the "99.9% Uptime SLA"
    on their own marketing page** (the sharpest, most verifiable sales wedge; it is also the
    exact cap that helped disqualify ThinnestAI in D-31). Note too that their bought numbers are
    contractually **transactional/service-only — not for promotional calling**, capping cold
    outbound. Further: **engine coupling** (they bind to Sarvam/Cartesia directly) vs our adapter
    + conformance isolation; and **Inbound is unbuilt** ("coming soon" in-product despite the
    marketing) — a receptionist product is open to us. Conversely they hold one capability we do
    not plan: **mid-call cross-provider failover on all three voice legs** (see teardown §9b).
    NOTE: two edges the July read claimed —
    "no exposed QA/eval process" and "hand-built not schema-driven" — are now WRONG: they ship
    auto knowledge-gap detection ("where the agent struggled, found automatically") and a
    schema-driven CRM. Our QA edge is now the *closed loop* (regression-on-every-change +
    client-facing QA reports + human curation), not the mere existence of gap-surfacing.
  - Positioning note retained: their branding is Telugu-first; genuine sustained Telugu quality
    across dialects remains the field's open flank, and is a measured claim not a given.
- **OmniDimension**: platform Outpero-class resellers use; ~$0.04/min usage, white-label
  program; 3,500-token prompt guidance; USD/US entity. We deliberately do NOT build on it
  (competitor's supplier; no differentiation; usage visible to their ecosystem).
- **Supplier pool / price anchors** (verified Aug 2026, D-31/D-32): **Bolna** 6.00¢→4.51¢
  bundled, BYOK platform fee unpublished — SELECTED as primary; Trikon ₹5/min all-in
  (no public API, no BYOK); Bolti ₹6/min; Ringg ₹6/min (no BYOK); ThinnestAI ₹1.5/min
  — RETIRED on vendor risk (D-31). Non-India platforms are not competitive for us:
  **Vapi** eliminated (₹4.40/min hosting fee survives BYOK + no India region),
  Retell ₹8–12, Bland unusable in India, ElevenLabs ₹7–10.5. Self-orchestration
  (LiveKit Cloud / Pipecat) is a phase-2 path, not a launch option (ROADMAP §5).
  Risk: any supplier going direct to SMBs (Risk R-03).
- **US platforms** (Vapi, Retell, Bland): strong tech, India telephony surcharges + USD
  billing make them uncompetitive for our segment.

## 6. Pricing & Revenue Model (decided)

**Two motions, one product (D-34, resolved Aug 2026).** A self-serve org and a managed org are
the same `organizations` row distinguished by a plan/tier column — nothing forks.

**Motion B — SELF-SERVE (new, lands M2):** no setup fee · sign-up with email/password or
Google, or by admin invite link · **prepaid credits** (1 credit = ₹1) · per-minute talk-time
priced by voice tier · monthly per-agent activation fee · hard spend caps. Positioned against
Outpero's ₹1,899/mo + ₹3–7/min. **Set the tier prices only after pilot gate 12 fixes the Bolna
BYOK fee** — our verified model cost is ₹1.04–1.31/min (Bulbul v2 + Sarvam LLM) to
₹1.58–2.12 (v3 + Sarvam), so a ₹3/₹5/₹7-style ladder is reachable, but the platform fee
decides the floor (TRD §10.1–10.3). **Do not publish a headline per-minute rate without the
monthly fee beside it** — that is the trick we called out in their marketing, and the
effective-₹/min rule in TRD §10.2 applies to our own copy too.

**Motion A — MANAGED (unchanged, the client-#1 path and where the margin is):**
- **Setup fee:** ₹40,000–₹75,000 one-time (agent build, KB curation, number + DLT setup,
  test-call sign-off). Funds the build, filters non-serious buyers.
- **Monthly retainer:** ₹15,000–₹30,000 including 1,000–2,000 minutes, dashboard/CRM
  access, monitoring, prompt iterations, support.
- **Overage:** ₹6–8/min, auto-billed; hard cap per client, raisable on request.
- Inbound-heavy clients priced at the favorable end (telephony cost ₹0.4–0.9/min inbound
  vs ₹0.6–1.8/min outbound); outbound-campaign-heavy clients at the upper end.

Rationale (recorded): at 1–2 clients, fixed costs (~₹7–10k infra) make pure ₹5/min
loss-making; retainer structure is profitable from client #1 and converts unknown client
volume into included-minutes + overage (volume risk sits with the client). Do not fight
self-serve platforms at ₹5/min; sell against the ₹18–25k/month human telecaller.

Unit economics (blended, verified rates):
- All-in variable cost: **₹3.0–3.6/min** launch stack (₹2/min platform fee scenario),
  falling to **₹1.7–2.3/min** in phase 2 (self-orchestrated). See TRD §10.
- Target gross margin on usage ≥ 60% at plan rates; setup + retainer are high-margin.
- Fixed: infra ₹7–10k/mo; engine/Sarvam minimums + numbers + misc ~₹3k/mo.

Recommended burn ceiling despite "whatever it takes": **₹35k/month** pre-revenue
(infra + platform minimums + DLT + one paid tool). Spending above this before client #1
buys nothing; the constraint is build time and sales, not money.

## 7. Go-To-Market (cold start — no warm prospects)

Client #1 strategy (pick lowest-friction path first):
1. **Pilot pricing:** first 2 clients get 50% setup fee + month-1 retainer discount in
   exchange for a written case study + referenceability. Never free — free clients don't
   engage.
2. **Demo-first selling:** a live Telugu demo agent on a real number IS the pitch. Build
   the clinic-booking demo agent before any sales outreach; prospects call it themselves.
3. **Channels:** BuiltByThree's existing 2 web clients (upsell/referral ask); AP/Telangana
   business networks (Sri's regional connections); walk-in demos to clinics/RE offices with
   the demo number on a card; LinkedIn/WhatsApp outreach with a 60-second recording of the
   agent handling a real call.
4. **Sales asset list (build in parallel with product):** demo agent + number; 1-page
   pricing sheet anchored vs telecaller cost; the "we regression-test your agent" quality
   one-pager; recorded demo video.
5. Expectation-setting script for outbound clients: 140-series promotional answer rates
   run 8–20% industry-wide (vs 45–65% on 160-series/recognized numbers) — set this before
   launch so low pickup is never blamed on the AI.

KPI targets (first 90 days post-launch): 2 signed clients; ≥1 case study; demo agent
handling ≥100 test calls; churn 0.

## 8. Success Metrics

Business: MRR, gross margin/client, setup revenue, CAC (time-based), referral count.
Product: answer rate, AI-resolved %, needs-follow-up %, hot-lead → client-contacted time,
extraction accuracy (spot-audited), client weekly active usage of Leads table.
Quality: voice-to-voice latency p50/p95 (target ≤1.1s p50), task-success rate on regression
suite, transcription error rate on names/numbers (Telugu), escalation correctness.

## 9. Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R-01 | **No legal entity decided** → cannot do DLT PE registration → all outbound blocked | Certain until resolved | Critical | Decide entity (BuiltByThree entity vs new LLP) in week 1; DLT PE reg (₹5,900 first TSP) immediately after. Inbound-only launch is the fallback while pending. |
| R-02 | Engine vendor risk — REALIZED for ThinnestAI (retired by D-31: zero verifiable customers, no SLA, unresponsive) and now tracked for **Bolna** (funded + real customers, but: unpublished BYOK fee, unsigned webhooks, US-region recordings pre-Enterprise) | Medium | High | VoiceEngine adapter (TRD §5) keeps a second adapter cheap; store only our normalized schemas; Bolna pilot scorecard (OPERATIONS.md §2) before commitment; fee/residency/erasure/agency terms in writing. |
| R-03 | Platform goes direct to SMBs / commoditization | Medium | Medium | Moat = service layer, Telugu GTM, schema-driven CRM, eval process, switchable engine. |
| R-04 | Gemini 2.5 family retirement 16 Oct 2026 | Certain | **Low → NEUTRALISED, and the migration is DONE (D-35/D-36/D-127)** | Sarvam 105B is free per token and runs the extraction leg permanently (`GEMINI_EXTRACTION_DEFAULT is False`, D-127 G-7), so no post-call path was ever exposed to this date. The one Gemini path that exists — the user-triggered dashboard AI on Vertex AI `asia-south1` — was written on **3.x Flash-Lite** (`calevate_shared.engine.GEMINI_DEFAULT_LLM`) rather than migrated to it later, and `tests/sarvam_model_identifier_test.py` fails the build on any shipped module that names a 2.x identifier. What is still owed is the regression run, which is blocked outside this repo on a Sarvam key and egress (§7 fixtures). |
| R-05 | TRAI enforcement (5 complaints/10 days ⇒ TSP action; 15-day suspension first offense; blacklist on repeat) | Low if compliant | Critical | Correct 140/160 classification, template registration, DNC scrub, calling-hours discipline; compliance gate in campaign launcher (FLOWS.md §5). |
| R-06 | DPDP exposure (recordings = personal data; consent-only basis; full compliance mandatory by 13 May 2027) | Medium | High | Consent ledger, disclosure line, PII redaction, retention TTLs, deletion-with-proof from v1 (SECURITY-COMPLIANCE.md). |
| R-07 | Cold-start sales stall | Medium | High | §7 plan; demo-first; pilot pricing; weekly pipeline review. |
| R-08 | Two-person team overbuild (platform before client) | Medium | High | ROADMAP gate: client #1 live on a partly-manual stack before multi-tenant polish. |
| R-09 | Runaway usage cost (client campaign misfire) | Low | Medium | Per-tenant hard caps enforced pre-dispatch; prepaid credit; alerts. |
| R-10 | Telugu voice quality below expectation (Bulbul v3 untested by us; **v2 is live at half price — D-35 corrects the earlier "discontinued" note**) | Medium | Medium | Ear-test v3 **vs v2** in the pilot (OPERATIONS §2 gate 3 + the D-35 scorecard item); quality is a per-client config choice, and the v3/v2 gap is also our value/premium tier lever (TRD §10.3). |
| R-11 | **Self-serve motion creates telecom-compliance exposure** (D-34): anyone can sign up and dial, but TRAI/DLT liability lands on us as Telemarketer. A single abusive self-serve account can trigger TSP action against our numbers and damage every client on the platform | Medium once self-serve ships | **Critical** | Non-negotiable, ships WITH the self-serve flow, not after: platform-fixed calling hours (not user-editable); DNC scrub on **every** dispatch path incl. instant (Hard Rule 5 — this is precisely where Outpero fails, teardown §9c); mandatory non-null AI disclosure per agent; durable versioned consent-attestation ledger; per-account concurrency + spend caps; number provisioning gated behind KYC; AUP with enforcement teeth (throttle/suspend on abuse signals); and manual review of the first campaign for any self-serve account. |

## 10. Assumptions Log (all remaining assumptions — everything else is decided/verified)

A-1 SUPERSEDED by D-31 (engine now Bolna): the open commercial unknown is Bolna's
    BYOK platform fee (unpublished; negotiation target ≤ ~₹1.5/min) — closed by the
    pilot's written quote.
A-2 Their in-house Vega STT + Aero TTS may bundle into the flat fee — verify pricing vs BYOK Sarvam.
A-3 SUPERSEDED (Jul 2026): their docs list only Bulbul V3 (11 languages); v2 appears
    discontinued. Remaining question: V3 Telugu ear-test vs their bundled voices, and
    confirm the TTS price band on the account (TRD §10 updated to the V3 band).
A-4 RESOLVED (Jul 2026, docs-verified): the voice.call.ended webhook is a trigger, not a
    payload. Get Call returns transcript + recording URL (presigned, 1-hour expiry) +
    INR cost breakdown + analysis in one extra request — within verification item 1's
    pass criteria. Live confirmation still happens at the verification session.
A-5 Measured voice-to-voice latency ≤ ~1.1s p50 on a real PSTN call — measure.
A-6 Exotel/Vobiz effective rates within researched bands — confirm on rate card.
A-7 Entity choice does not delay DLT beyond 4 weeks.
A-8 UPDATED by D-31 (engine now Bolna): Pilots plan advertises "up to 100 concurrent
    calls" but per-plan concurrency, API rate limits and dispatch pacing are otherwise
    unpublished. Real ceiling = MIN(platform concurrency, Sarvam BYOK-tier
    concurrency, SIP trunk channels). Closed by pilot item 8 — all three numbers in
    writing.
Each assumption has an owner (Sri) and is closed by the verification session (OPERATIONS.md §2) or week-1 admin tasks.
