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
  Views dashboard, leads, recordings; adds KB content, which goes to the agent with no
  approval step (D-658); pays invoices.
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
   preview-and-approve, recording the client's own number, usage/margin view, spend caps.
5. Billing: metered ledger; prepaid credit in volume packs at one published card for every client, plus an optional platform-wide monthly platform fee paid separately (D-707, 10 Oct 2026, superseding the setup fee + monthly retainer with included minutes +
   overage); hard caps.
6. Compliance built-in: an agent that ALWAYS answers truthfully when asked whether it is
   an AI or whether the call is recorded (unconditional, D-163); AI disclosure and a
   recording notice at call start, each a per-agent choice the client makes and is
   accountable for; recording consent, DND/DNC checks, DLT-classified campaigns, PII
   redaction in transcripts (see SECURITY-COMPLIANCE.md).
7. Client-initiated AI actions from the CRM (decided Jul 2026, D-21; competitor parity+):
   (a) "Call this lead" — owner role dispatches a single AI call from the Leads table,
   with an optional free-text per-call context note appended to the agent's CallContext;
   runs the same compliance pre-checks as webhook dispatch (DNC, calling hours, caps).
   (b) "AI callback" on needs-follow-up calls — one click re-dispatches the agent with
   context from the flagged call, via the engine's context-injection webhook (Outpero's
   equivalent button only tells the human to call; ours closes the loop with AI).
   Boundaries: extraction schemas (the per-agent variables the AI extracts) are now
   self-serve — the client (owner role) CAN add/edit/delete their agents' variables, and
   admins/superadmin can too (D-460 supersedes D-21's admin-only clause; each field carries
   an optional free-text `reason` hint, edits go live on save as a new schema version). Lead
   statuses stay the fixed enum in v1 (custom tags/statuses only if pulled by a client).
8. Self-serve first run and trial (D-853, D-854, D-855, D-863, D-918): every new account,
   signed up or invited, starts a 7-day free trial with 15 test-call minutes and no agent.
   The owner builds the first agent in "Meet your agent": the jobs it does, a brief in their
   own words with up to three files beside it (a price list, a menu), a few follow-up
   questions written for their business, a build they watch, the opening line edited in
   place, and a test call. A test call may come from any agent that is ready.
9. Knowledge belongs to the client and every agent of that client uses it (D-689). A file
   added after onboarding suggests a script change to every agent, one tap to keep, that
   keeps what the owner wrote (D-923). A file is never refused for its symbols: arrows are
   spelled out and symbols the font lacks are left out (D-925).
10. Account closure and erasure: erasing a client account also deletes its agents, its
    callers' contact records that only its calls reached and its own workspace at the voice
    platform, by code; it waits while a call inside the 90-day recording floor has no
    recording copy in our own storage (D-922). A stopped account's rented number is held, not renewed,
    and released before the next monthly renewal unless the client tops up or reopens
    (D-860).
11. Hand-offs and help: a caller the agent cannot help is handed to the business's own team
    with their name and number, by email or the client's own connected WhatsApp, during or
    after the call (D-904); Pip, the in-app assistant, does the client's work in every area
    of the dashboard, with one confirmation for anything that reaches callers or spends
    credit (D-893).

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
  ThinnestAI's own voices on Telugu is an ear test we should run (OPERATIONS §2 gate T-6). The
  product is mature and self-serve.
  **OUR ANSWER TO THE TIER LADDER IS A DIFFERENT SHAPE (D-547, D-687).** We ship **TWO** voice
  rungs, not three — **Clear** (ThinnestAI's own stack) and **Studio** (**Cartesia**, the same
  vendor their ₹7 "exclusive native Telugu" tier uses, on our key through ThinnestAI) — and the
  rung is chosen **per agent**, not per account. The discount for buying more is NOT bonus
  credits and is NOT an "effective" rate the buyer has to compute: it is the per-minute rate
  itself, **frozen on the credit that purchase bought** and spent oldest-purchase-first (§6.1).
  So there is no gap between the headline and the effective number for us to be caught in,
  which is the trick §6 already refuses to play. Studio costs more per minute and is priced
  accordingly. The Cartesia voices on offer are the ones our key reaches, listed through
  ThinnestAI (`GET /byok/voices`, THINNEST-INTEGRATION §4a) and enabled by our admin.
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
    per-agent **KB** (docs/webpages, on-demand retrieval) with a teach flow;
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
    **AI disclosure is optional for them** ("scriptable" but not required) — **and since
    D-163 the OPENING disclosure is a client choice for us too, so the honest edge has
    moved and narrowed rather than disappeared**: what is mandatory for us and absent for
    them is that the agent cannot be SCRIPTED INTO LYING. Ask ours whether it is a human
    and it says it is an AI; ask whether the call is recorded and it says yes — composed
    server-side, appended after the client's script, verified against the voice platform
    on every publish. Theirs is a scriptable line and nothing underneath it. Do not sell
    "we always announce it"; sell "ours cannot be made to deny it". **Raw caller PII
    renders un-redacted** in their dashboard (we default to
    `text_redacted` + role-gated raw), **data may be processed outside India** (do NOT
    answer this with a residency claim of our own — F-1 is open, `docs/DEPLOYMENT.md`
    says India co-location is not required for the stack holding transcripts, and the
    landing page was scrubbed of exactly this sentence. What IS sellable today is the
    processing-location DISCLOSURE: we name every sub-processor and where it runs, in
    writing, before signature), and their **liability is capped at 3 months of fees with Terms §9
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
  bundled, BYOK platform fee unpublished — selected by D-31 and deleted by D-639; Trikon ₹5/min
  all-in (no public API, no BYOK); Bolti ₹6/min; Ringg ₹6/min (no BYOK); ThinnestAI ₹1.5/min —
  retired on vendor risk by D-31 and adopted as the engine by D-678 (6 Oct 2026; production since
  7 Oct 2026). Non-India platforms are not competitive for us:
  **Vapi** eliminated (₹4.40/min hosting fee survives BYOK + no India region),
  Retell ₹8–12, Bland unusable in India, ElevenLabs ₹7–10.5. Our own orchestration loop was
  built (D-592) and removed (D-763); it is not on the roadmap.
  Risk: any supplier going direct to SMBs (Risk R-03).
- **US platforms** (Vapi, Retell, Bland): strong tech, India telephony surcharges + USD
  billing make them uncompetitive for our segment.

## 6. Pricing & Revenue Model (decided)

**One pricing model (D-707, 10 Oct 2026).** Every client buys prepaid credit in volume packs at
the same published per-minute card, with an optional platform-wide monthly platform fee set in
the ops console and paid separately. There is no setup fee and no retainer; existing managed
clients moved to credits, and invoices issued before then are honoured. D-707 superseded D-34's
two motions (self-serve and managed) and D-11's setup fee, retainer and overage; both rows stay
in the decision log as the record.

### 6.1 The rate card (D-728)

1 credit = ₹1. A call is charged per minute at the rate of the **voice rung of the agent that
took it**, at the rate frozen on the credit being spent (D-547), oldest purchase first, in
30-second steps (D-681, `billing/rates.py::client_billed_minutes`). The discount for buying more
is the per-minute rate itself, never bonus credits or an "effective" rate the buyer has to
compute. Founder decision of 11 Oct 2026 (D-728): flat on every pack.

| Pack | Clear | Studio |
|---|---|---|
| starter ₹2,000 | ₹4.50 | ₹6.00 |
| growth ₹5,000 | ₹4.50 | ₹6.00 |
| scale ₹10,000 | ₹4.50 | ₹6.00 |
| plus ₹15,000 | ₹4.50 | ₹6.00 |
| pro ₹25,000 | ₹4.50 | ₹6.00 |
| max ₹50,000 | ₹4.50 | ₹6.00 |

**`billing/credit_packs.PACK_CATALOGUE` is the single source.** No page holds a price: every
figure renders from the API, tests derive card rates from the catalogue rather than retyping
them, and margins are recomputed from it against `billing/rates.py::cost_floor_inr_per_min`
rather than copied. `Settings.self_serve_inr_per_min` moves with the Clear entry rung. This card
replaced the 14 Sep 2026 one (D-601: Clear ₹4.00 flat, Studio ₹7.00 at the ₹2,000 pack falling
in ₹0.30 steps to ₹5.50 at the ₹50,000 pack). Studio may come down towards ₹5.00 only once
Studio volume fills a Cartesia plan, and then through the ops console's scheduled card with its
30-day notice (D-728). A cell below cost is refused by the ops console (`card_refusals`); a
cell under the 20% gross-margin target is warned, not refused, and the fix for a thin cell is a
founder decision, never a nudged rate.

**Credit bought in a pack lasts 12 months** from the day it is added, stated with its date
before payment and on the Billing page, with an email 30 days before it lapses (D-897,
switched on 27 Oct 2026; Terms revision 19, clause 6.1). It applies only once the account has
accepted that revision: credit added before acceptance, credit bought before 27 Oct 2026 and
credit a super admin grants never lapse (D-900, D-890). New accounts start on a 7-day,
15-minute free trial (D-853).

**Do not publish a headline per-minute rate without the monthly platform fee beside it** — the
effective-₹/min rule in TRD §10.2 applies to our own copy as much as to a competitor's.

### 6.2 What a minute costs us

ThinnestAI hosts the whole call (D-678..D-682). The per-minute rates below are VENDOR-STATED and
reach money only through an operator's attestation in the ops console (hard rule 7); the plan
and evidence are `docs/THINNEST-INTEGRATION.md` §4a and §5, and the `unit_cost_paid` arithmetic
is TRD §10.0.

| Rung | What speaks | Vendor rate (VENDOR-STATED) | All-in at the 2.36% wallet top-up fee (D-754) | Gross margin at the card |
|---|---|---|---|---|
| **Clear** | ThinnestAI's own stack end to end, in the band the console setting `thinnest_clear_voice_band` names | Studio band ₹2.50/min (default, D-792) or Premium band ₹2.00/min; ThinnestAI console, founder-relayed 24 Oct 2026 (D-878) | ₹2.559 or ₹2.0472 | 43.1% or 54.5% at ₹4.50 |
| **Studio** | Cartesia on our key through ThinnestAI's voice-only BYOK; ThinnestAI's STT, LLM and telephony | ₹1.50/min including the line, plus Cartesia's own charge to our key | ₹1.535 plus Cartesia's ₹2.06–3.42 per call-minute (at 571 characters a minute, by plan and volume; cartesia.ai/pricing read 11 Oct 2026), about ₹3.60–4.96 | 40% down to 17% at ₹6.00 |

With our own model switched on (`thinnest_own_model`, D-764/D-834) the minutes change shape:
Clear runs on BYOK scope `llm` at the band's own minute, and Studio on scope `llm_voice` at
₹1.00/min flat (`snapshots/2026-10-19/pages/api-reference/bring-your-own-keys.md:28`), each
plus our Gemini key's tokens; the switch is off today. Both margins are before GST. Our
pay-as-you-go account has the Studio band, 100 customer workspaces and 20 concurrent calls
without a monthly plan (VENDOR-STATED 23 Oct 2026, `docs/vendor/thinnest-replies-2026-10-12.md`
§28); the plan to move to Scale at 10 active clients and Enterprise at 50 is the founder's,
agreed with ThinnestAI in the same exchange. A Studio rung's cost is a curve
in volume, not a number: Cartesia sells monthly plans, so a Studio minute is dearest just after
each plan upgrade. Cartesia bills in dollars; the floor converts at the live USD→INR rate the
platform already publishes, while the hard refusal stays frozen at the founder's planning rate,
₹95 to the dollar (D-768), so a currency tick can never make the card on sale un-recordable.

### 6.3 What a client calls the two voices

**Clear** and **Studio**. No client-facing surface names a vendor as a product tier (founder,
7 Sep 2026; D-679 for every client-facing text). Admin screens call ThinnestAI's own bands
"ThinnestAI Premium band" / "ThinnestAI Studio band"; clients see only Clear and Studio. The
names are defined once, at `billing/rates.py::VOICE_TIER_LABELS`, and travel to every screen
over the wire. Every money column and wire field spells the RUNG, not a vendor:
`credit_lots.clear_inr_per_min` / `studio_inr_per_min` (migration `f1c40d8b6e93`, which refuses
against a non-empty table because a lot's rates are frozen at purchase),
`billing/rates.py::VoiceTier = Literal["clear", "studio"]`, the credit-lot and pack responses,
and `usage_events.meta.voice_tier`. Two reasons: the vendor behind a rung must be able to change
without a client-visible rename (a client who bought "Studio" was sold a voice, not a supplier),
and `standard`/`premium` are Outpero's rung names (TRD §10.3) and ThinnestAI's band names, so
using them would read as a copy and would collide with the vendor's vocabulary on admin screens.

### 6.4 Fixed costs and burn

- Fixed: no ThinnestAI plan fee while we stay on pay as you go with raised limits (§6.2);
  infra ₹7–10k/month (ESTIMATE); numbers and misc.
- Recommended burn ceiling despite "whatever it takes": **₹35k/month** pre-revenue
  (infra + platform minimums + DLT + one paid tool). Spending above this before client #1 buys
  nothing; the constraint is build time and sales, not money.

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
   launch so low pickup is never blamed on the AI. Since D-815 (18 Oct 2026) 140-series
   promotional calling is not offered: outbound is service and transactional only, under
   the no-cold-calls pledge.

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
| R-01 | ~~**No legal entity decided**~~ **AMENDED (D-461): the entity is DECIDED and this row is now about the REGISTRATIONS.** `docs/legal/LEGAL-OPS-PLAYBOOK.md` §0/§3 (24 Aug 2026, the legal source of truth) fixes it: a **sole proprietor** trading under the product name Calevate — no company, no LLP, no CIN, and the playbook is explicit that incorporating would make it stale. What still blocks outbound is Calevate's own **DLT Telemarketer registration**, which follows **Udyam**. Note the correction the old text also carried: **PE registration is the CLIENT's**, in their own name (playbook §10.4) — we are the TM they bind, and we cannot file a PE for them. | Certain until the TM registration exists | Critical | Udyam (MSME) → DLT TM registration under the proprietor's PAN. Each client takes their own PE registration (₹5,900 first TSP) and binds our TM-ID; we accept the chain. Inbound-only launch is the fallback while pending. |
| R-02 | Engine vendor risk — REALIZED twice before: ThinnestAI retired by D-31, then Bolna deleted by D-639. ThinnestAI now hosts the whole call (numbers, telephony, STT, LLM, TTS, recording; D-678..D-682), so one vendor carries every call | Medium | High | The VoiceEngine adapter (TRD §5) and its conformance suite keep a replacement adapter cheap; we store only our normalized schemas and copy recordings to our own storage; one ThinnestAI customer workspace per client (D-693) keeps each client's data separable; the first-call checklist (`runbooks/thinnest-first-live-call.md`) and OPERATIONS §2 T-series gates before client traffic. There is no second engine to fail over to: rollback is redeploying the previous image (D-763). |
| R-03 | Platform goes direct to SMBs / commoditization | Medium | Medium | Moat = service layer, Telugu GTM, schema-driven CRM, eval process, switchable engine. |
| R-04 | ~~Gemini 2.5 family retirement 16 Oct 2026~~ **WITHDRAWN: the date belonged to preview snapshots, and the GA ids carry no announced shutdown** | n/a | None outstanding | Gemini is on offer again (D-456) and `gemini-2.5-flash-lite` is the platform's own default (`PLATFORM_DEFAULT_LLM_MODEL`); the 16 Oct 2026 date was propagated from our own `model_lifecycle.py` as if it were a vendor fact, which is what hard rule 11 now forbids. `ModelLifecycle.retirement_stance` separates "the vendor announced nothing" from "nobody looked", and `scripts/check_model_lifecycle.py` is the mechanism if a retirement is announced for any selectable model: the date held as data in one place and a test that fails the build before it, never a calendar reminder or a widened runway constant. The first extraction pass stays on Sarvam permanently (`GEMINI_EXTRACTION_DEFAULT is False`). |
| R-05 | TRAI enforcement (5 complaints/10 days ⇒ TSP action; 15-day suspension first offense; blacklist on repeat) | Low if compliant | Critical | Correct 140/160 classification, template registration, DNC scrub, calling-hours discipline; compliance gate in campaign launcher (FLOWS.md §5). |
| R-06 | DPDP exposure (recordings = personal data; consent-only basis; full compliance mandatory by 13 May 2027) | Medium | High | Consent ledger, disclosure line, PII redaction, retention TTLs, deletion-with-proof from v1 (SECURITY-COMPLIANCE.md). |
| R-07 | Cold-start sales stall | Medium | High | §7 plan; demo-first; pilot pricing; weekly pipeline review. |
| R-08 | Two-person team overbuild (platform before client) | Medium | High | ROADMAP gate: client #1 live on a partly-manual stack before multi-tenant polish. |
| R-09 | Runaway usage cost (client campaign misfire) | Low | Medium | Per-tenant hard caps enforced pre-dispatch; prepaid credit; alerts. |
| R-10 | Telugu voice quality below expectation — no rung has a recorded ear test on a real call yet | Medium | Medium | Two rungs, chosen **per agent** (D-547, D-687): **Clear** speaks ThinnestAI's own voices and **Studio** speaks Cartesia on our key through ThinnestAI, priced as two per-minute rates on every pack and frozen on the credit each purchase buys (§6.1, `billing/credit_packs.PACK_CATALOGUE`). So the mitigation if one rung's Telugu disappoints is the other, with a caveat that is part of the mitigation: Telugu–English code-mixing is **absent from Cartesia's docs** and must not be promised (Hinglish is documented; Telugu-English is not) — VENDOR-PUBLISHED, relayed research over `docs.cartesia.ai`, 7 Sep 2026, `docs/evidence/cartesia-tts-verification-2026-09-06.md` §A4, host egress-blocked here. The founder has placed Telugu test calls in production (24–28 Oct 2026), which shaped the call rules (D-877, D-887, D-894, D-910, D-912, D-921); the recorded ear test, OPERATIONS §2 gate T-6, is not filed. |
| R-11 | **Self-serve motion creates telecom-compliance exposure** (D-34): anyone can sign up and dial, but TRAI/DLT liability lands on us as Telemarketer. A single abusive self-serve account can trigger TSP action against our Telemarketer registration — which is one registration for the whole platform — and damage every client on it | Medium once self-serve ships | **Critical** | Non-negotiable, ships WITH the self-serve flow, not after: platform-fixed calling hours (not user-editable); DNC scrub on **every** dispatch path incl. instant (Hard Rule 5 — this is precisely where Outpero fails, teardown §9c); an AI disclosure sentence on every agent, mandatory and non-blank, whose in-call delivery the client may switch off and is audited for doing (D-163) while the truthful ANSWER when asked stays unconditional; durable versioned consent-attestation ledger; per-account concurrency + spend caps; business KYC verified before any account dials or buys a number (numbers are bought in the client's own business name, in its own ThinnestAI workspace, D-693); AUP with enforcement teeth (throttle/suspend on abuse signals); the accepted no-cold-calls pledge (D-692); the complaint-spike campaign pause that resumes only after the client reviews it (D-773); and the big red switch. **There is no manual review of the first campaign** (D-783, founder, 15 Oct 2026, superseding D-51: "this [adds] friction between the client and us while they try Calevate in trial"). Residual: a self-serve or trial account can dial a campaign nobody at Calevate has read. |

## 10. Assumptions Log (all remaining assumptions — everything else is decided/verified)

A-1 WITHDRAWN with Bolna (D-639). The engine is ThinnestAI (D-678); its per-minute rates are
    VENDOR-STATED and reach money only through an operator's attestation (§6.2).
A-2 WITHDRAWN with the rented engine (D-639): it was about that vendor's bundled voices.
A-3 WITHDRAWN: the Telugu ear test is now OPERATIONS §2 gate T-6 (R-10).
A-4 WITHDRAWN with Bolna (D-639). On ThinnestAI the call record comes from its signed
    `call.completed` / `call.analysed` webhooks and the call list, and we copy the recording.
A-5 Measured voice-to-voice latency ≤ ~1.1s p50 on a real PSTN call — measure.
A-6 ThinnestAI's charge per call (`costMicro`) matches the attested rate per billed minute plus
    the 2.36% wallet top-up fee — confirmed per call by the hourly charges sweep
    (`workers/engine_charges.py`, D-690, D-754) once real calls are placed.
A-7 Entity choice does not delay DLT beyond 4 weeks.
A-8 Concurrency is ThinnestAI's account limit (OPERATIONS §2 gate T-7: raised to 20 for our
    pay-as-you-go account, VENDOR-STATED 23 Oct 2026, replies §28; not observable without 6+
    calls at once), divided per customer workspace; dispatch is held to the console-managed
    `thinnest_max_concurrent_calls`, which is never set above the granted figure.
Each assumption has an owner (Sri) and is closed by the verification session (OPERATIONS.md §2) or week-1 admin tasks.
