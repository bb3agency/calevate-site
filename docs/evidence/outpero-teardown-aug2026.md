# Outpero Product Teardown — August 2026 (authenticated, in-product)

**Provenance.** Live walkthrough of `app.outpero.com` on 10 Aug 2026 using a real
account (Raghava Organics), plus their marketing site and their own shipped code/network
traffic. Everything here is observed first-party, not inferred. This supersedes the
July-2026 external teardown in BRD §5 (which was demo-video + marketing only).

**Scope note.** All reading was of screens and API responses the app itself loads for
this logged-in account. No other tenant's data was accessed; their gated `/admin/*`
endpoint correctly returned 403 and was not probed. No test calls were placed (they cost
real credits). Features, flows, pricing and IA are fair competitive learning; their copy,
code and assets are theirs.

---

## 0. TL;DR — what changed and what it means

- **They are not a "beginner service shop."** Outpero is the product of **OpenDG Pvt Ltd**,
  a Hyderabad agency founded 2014 (ISO 9001:2015). They productised a decade of manual
  phone-lead work — **the exact thesis Calevate is built on**, shipped by an incumbent.
- **The product is real, self-serve, and mature.** Agent builder, schema-driven CRM,
  campaigns, KB, in-call actions, analytics, GST billing — all shipped and polished.
- **Their stack is ~our planned stack** (React SPA + FastAPI-style REST + Supabase auth),
  running on **Sarvam + Cartesia** models — not the OmniDimension-class platform we assumed.
- **Entry price is ~20× below ours** (₹1,899/mo, ₹0 setup vs our ₹40–75k setup + retainer).
  This is the one finding that forces a decision — see §9 (D-11).
- **Our differentiators narrowed but did not vanish.** They already ship auto
  knowledge-gap detection (we claimed that as ours). Our real edges are now: typed/validated
  extraction, hard server-side compliance (consent ledger + DLT + always-on disclosure),
  transcript redaction-by-default, engine isolation, and a genuine QA/regression process.
- **Their unbuilt flank: Inbound.** Marketing sells "inbound 24/7"; the product marks
  Inbound Calls **"coming soon."** A receptionist product is open.

---

## 1. Verified technical architecture

| Layer | Outpero | Source of truth |
|---|---|---|
| Frontend | React SPA (Vite, code-split: react/supabase/framer-motion/charts), on Cloudflare | JS bundle names + CF beacon/`cdn-cgi/rum` |
| Auth | **Supabase** (JWT bearer; API rejects cookie fetch with "Missing bearer token") | `vendor-supabase` bundle + API behavior |
| Backend | Custom REST at **`api.outpero.com`**, FastAPI-shaped resource routes | Live XHR capture |
| Voice models | **Sarvam + Cartesia** | `sarvam-logo.png` + `cartesia-logo.png` in their own assets |
| Numbers | India **mobile** numbers, bought in-app | "Available mobile numbers · India" |
| Edge | Cloudflare | insights beacon |

**Confirmed API endpoints** (the SPA's own calls): `GET /accounts/me`, `/employees`,
`/billing`, `/billing/usage?days=30`, `/numbers`, `/campaigns`, `/calls?limit=1000`,
`/calls/live`, `/notifications`, `/stats/dashboard`, `/stats/performance`,
`/stats/analytics?days=7&granularity=day`, and a gated `/admin/health` (403). That list
*is* their domain model: accounts, employees, campaigns, calls, numbers, billing, stats.

**Read for us:** this is almost exactly the Calevate target architecture (SPA + modular
REST monolith + separate gated admin realm). Three deliberate differences remain our edge:
we isolate the voice engine behind the `VoiceEngine` adapter (they appear directly coupled
to Sarvam/Cartesia); we enforce Postgres FORCEd RLS for hard tenant isolation (theirs is
unverified behind a custom API); we split admin/client into separate Clerk realms.

**Note on their model stack:** Cartesia is a low-latency English-first TTS; Sarvam is the
Indic specialist. Their "native Telugu" premium voices are most plausibly Sarvam (or their
own), with Cartesia for English/latency. We are BYOK-Sarvam for both legs, so this is not
a quality gap for us — but it confirms Sarvam is the Telugu workhorse for serious players.

---

## 2. The agent ("employee") config model — their core IP

An employee has eight config tabs: **Overview · Instant leads · Call script · Training ·
Actions · Post-Call · Voice(₹) · Settings**. The design is genuinely good; details worth
adopting are flagged **[ADOPT]**.

### 2.1 Call script — a branching section-graph (not a raw prompt)
- **Opening line** with `{{variable}}` interpolation.
- Up to **15 sections**; each is either a natural-language "what to do here" (≤4,000 chars)
  or a verbatim "say exactly this."
- **Conditional branching** per section ("go to X when Y") + a default route → a real
  conversation state machine. **[ADOPT]** — richer than a flat prompt, still no-code.
- **Adherence slider** Flexible(1)↔Strict(5): "improvises freely, never invents facts" →
  "sticks to sections exactly, adds nothing." **[ADOPT]** — a clean single knob for the
  hallucination/naturalness tradeoff.
- **End-of-call rules**: built-in "purpose done" + custom hangup conditions.
- **"Swara" AI copilot** edits the whole flow by voice or text ("handle a price objection",
  "add urgency before closing"). **[ADOPT — high value]** — this is their onboarding moat;
  it removes the blank-prompt problem.
- Clean variable model: **pre-call vars come from the lead webhook**; **captured vars are
  defined in Post-Call**. Same variable names flow through script, webhook, and campaign CSV.

### 2.2 Voice — and this is their pricing lever
- Language modes: **Telugu+English** (speaks Telugu, switches to English when the caller
  does) or English; plus **"Also speak Hindi (Beta)."**
- **Voice catalog is tier-priced** — this is how ₹3/5/7 works:
  - **Premium ₹7/min** — "exclusive Outpero native Telugu speakers" (P01/P02/P06/P07/P09)
  - **Standard ₹5/min** (S03/S36/S39/S41/S47)
  - **Value ₹3/min** — "budget-friendly Telugu" (V01–V04)
  - Filter by personality × language × gender.
- Voices are **admin-curated** from a "Voices catalog" (confirms their admin/tenant split).
- **Ambient sound bed** (office/call-center/restaurant/quiet/retail, volume slider) so the
  agent "sounds like a real place." **[ADOPT — cheap humanization]**

### 2.3 Post-Call — extraction + delivery
- **Capture variables** ("what the agent extracts"), applied **immediately, no redeploy**.
  Example agent captured `specific_products`, `quantity_frequency`, `order_status`.
- **⚠ Their extraction is untyped.** On their one real call, `quantity_frequency` was
  filled with **"Delhi"** — a location, not a quantity. **This is our wedge:** our typed
  `extraction_schema` (type/enum/required + Pydantic validation + retry, TRD §7) rejects
  and corrects exactly this class of error. Demonstrable quality edge.
- **Post-call webhooks** POST recording/transcript/outcome to the client's system. Tell:
  the webhook **fires early and summary/outcome/extracted fields "may be null" until
  classification finishes a few seconds later** — their post-call classification is async
  and they don't gate the webhook on it. (Our reliability triad + outbox handles this more
  cleanly: we emit a settled event.)

### 2.4 Actions — in-call tools
- Master "Enable API actions" switch. **WhatsApp mid-call** via **Interakt / AiSensy /
  Meta Cloud API** (the BSPs Indian SMBs actually use). **Custom API** (any external call).
  **Google Calendar** booking/availability. **[ADOPT integration list]** — Interakt/AiSensy
  are the concrete WhatsApp targets for our follow-up + in-call actions.

### 2.5 Training — KB + quality loop
- Teach facts; **the AI classifies fact-vs-rule and you approve before saving [ADOPT].**
- **Documents**: upload brochure/policy or add a webpage, retrieved "only when relevant" (RAG).
- **Test-chat sandbox**, metered at **0.05 credits/message**.
- **⚠ "Where Harish struggled on real calls — found automatically from actual
  conversations."** This is auto knowledge-gap detection — which **BRD §5 currently claims
  as our D-15 differentiator.** They ship it. Our edge must now be the *closed loop*
  (regression-on-every-change + client-facing QA reports + human curation), not the mere
  existence of gap surfacing. **Competitive-claim correction required.**

### 2.6 Calling policy (Settings/Instant-leads) — dispatch + compliance
Client-configurable: call delay, calling window + days + holidays, out-of-hours handling
(auto-send/manual/skip/next-open/+3h/+6h/next-day), **retry up to 3 attempts**, **Respect
Do-Not-Call list**, **max concurrent**, **duplicate-lead window** (same number within N
min skipped). Equivalent in spirit to our FLOWS §5 — but exposed as self-serve config,
where we enforce compliance server-side.

---

## 3. Pricing & billing model (complete)

**Everything runs on credits; 1 credit = ₹1; credits never expire; 18% GST handled.**

- **Hire fee (the plan):** **₹1,899/employee/month** (₹2,241 incl GST). Building, scripting
  and **test calls are free**; you pay only when an employee **goes live on its own number**.
  Each plan includes **₹500 credits/mo + its own number + instant/bulk/inbound + unlimited
  edits/training**, 30-day renew, cancel anytime. Employees sit in **Draft until hired**; a
  lapsed plan **pauses** (never deletes) the employee.
- **Talk-time (credits):** voice tier sets the rate — **₹3 / ₹5 / ₹7 per minute** (value/
  standard/premium), billed **per talk-minute rounded up to 30-sec blocks; ring/unanswered
  not charged.** (Verified: a 1:08 call on P09-premium billed 1.5 min × ₹7 = ₹10.50.)
- **Top-up packs (volume-bonus credits):** ₹999→199 min · ₹2,999(+150)→629 min ·
  ₹9,999(+800)→2,159 min · ₹24,999(+2,500)→5,499 min · ₹50,000(+6,000)→11,200 min.
  Effective Standard rate slides only ₹5.02→₹4.46/min — a shallow ~11% max volume discount.
- **Enterprise (>₹50,000):** custom per-minute rates, higher concurrency, named contact,
  **₹1,899 hire fee waived.**

**Effective first-month out-of-pocket for an SMB:** Outpero ≈ **₹2,241** (one employee,
GST-in) vs Calevate D-11 ≈ **₹55k–105k** (setup + first retainer). That gap is the decision.

---

## 4. Telephony & compliance posture

- Buy/verify/attach **India mobile numbers** in-app; the number is the caller ID.
- **Platform-enforced calling hours** (not just user config): **bulk 9 AM–9 PM, instant
  callbacks 6 AM–10 PM.** No bought/scraped lists. **Auto-DNC** on request.
- **Consent = self-attestation checkbox** at campaign launch ("I confirm these contacts
  have consented…"). **Liability sits on the client's business** ("you are the caller").
  DLT/DND is a **disclaimer only** — no visible hard DLT template binding or consent ledger.
- **Recording retention: 90 days then auto-deleted; transcript + summary kept while account
  active.** Matches our D-14 90-day floor. **⚠ Their UI shows raw PII (phone, location)
  with no visible redaction** — we redact transcripts by default and gate raw text (a DPDP
  edge).

**Read:** their compliance is real but **lighter** than ours (fixed hours + DNC +
self-attestation) vs our always-on disclosure + consent ledger + campaign compliance gate +
DLT PE/TM. That is both a differentiation and a risk they carry.

---

## 5. CRM, results & analytics (the BRD §5 "feature floor")

- **Leads & Results** — lead-rollup (deduped by contact): tiles Total/Qualified/Pending
  callback/Hot; **table/grid/kanban** views; filters by channel/employee/time/outcome/Hot;
  export.
- **All Conversations** — call-centric: filters by direction, recording, length buckets,
  channel, **outcome (Qualified/Interested/Callback/Not interested/Missed/No answer/Busy/
  Call failed/Voicemail)**, sentiment, employee, source; column chooser; CSV export; inline
  captured fields + AI summary per row.
- **Per-employee call log** — extraction vars as **dynamic columns** (schema-driven CRM,
  = our D-09), with field/duration/credits filters + export.
- **Performance** — connect rate, conversion funnel (Calls→Connected→Qualified), outcomes,
  by-channel, **busiest hours**, **employee leaderboard**, date ranges, export.

**Read:** essentially at parity with our planned SURFACES dashboard. No analytics gap to
exploit; our CRM edge is upstream (typed extraction feeding cleaner columns) and in trust
surfaces (redaction, QA reports, latency badges).

---

## 6. Full product surface map

Sidebar: **Overview** (Dashboard, My Employees, New employee, Talk to an employee) ·
**Calling** (Instant Leads, Bulk Campaigns, Inbound Calls *coming soon*) · **Results &
setup** (Leads & Results, All Conversations, Train Employees, Phone Numbers, Performance,
Billing, Settings). Onboarding = "describe the job → we build the employee," with a 13-item
industry preset grid and a **Swara guided 5-question voice setup**.

---

## 7. Where they map to our existing plan (parity — no action)

Schema-driven CRM (D-09) · fixed outcome enum (D-21) · instant-lead webhook dispatch ·
bulk campaigns w/ concurrency+retry+schedule · CSV export w/ column chooser · 90-day
recording retention (D-14) · dashboard analytics (SURFACES) · admin/tenant split · per-call
transcript+recording+summary+sentiment. **We are not behind on these.**

---

## 8. What to adopt / enhance (build-time backlog seeds)

1. **Branching section-graph script builder** + **adherence slider** — better than a flat
   prompt; keep it no-code. (Admin console agent editor.)
2. **AI copilot for flow editing** ("Swara" analog) — highest-leverage onboarding UX; removes
   the blank-prompt wall. Enhance: ours can also propose extraction schema + compliance line.
3. **Tiered voice catalog as a pricing/quality lever** — maps cleanly onto our BYOK voice
   choices; lets us offer a value/premium ladder without new infra.
4. **Ambient sound bed** — trivial humanization win.
5. **Fact-vs-rule teach flow with approve-before-save** — good KB UX on top of our
   preview-and-approve gate.
6. **In-call action integrations**: Interakt/AiSensy/Meta Cloud WhatsApp + Google Calendar
   as first concrete targets.
7. **Test-chat sandbox** (metered) to let clients probe an agent pre-launch.
8. **Runway framing in billing** ("~13 min left, 5 min on premium") — good money UX.

## 9. Where we win (sharpen these in positioning)

- **Typed, validated extraction** vs their untyped capture (the "Delhi in quantity" bug).
- **Hard compliance**: always-on disclosure + consent ledger + campaign compliance gate +
  DLT PE/TM, vs their fixed-hours + self-attestation.
- **Transcript redaction-by-default + role-gated raw text** vs their raw-PII UI (DPDP).
- **Engine isolation + conformance suite** (swap engines cheaply) vs their model coupling.
- **QA/regression as a closed loop** + client-facing QA reports, vs their gap-surfacing only.
- **Inbound receptionist** — they haven't shipped it; we can lead there.

## 9b. Legal, security & compliance posture (added — full policy-set read, Aug 2026)

Read in full: Terms (25 Jul), Privacy (28 Jul), Refund (25 Jul), Security & Sub-processors
(25 Jul), Acceptable Use (1 Aug), Contact. **This section corrects two overstatements in an
earlier draft of §4/§9** — their compliance is stronger than a first pass suggested.

**Entity & people.** OPENDG PRIVATE LIMITED · **GSTIN 36AACCO6812H1ZH** · Regus, Krishe
Sapphire, Madhapur, Hyderabad 500081 · founder **Vatsal Sarakadam** (vatsal@outpero.com) ·
support@outpero.com, **response within 1 business day** · Grievance Officer named per IT Act
2000 · governing law India, **exclusive jurisdiction Hyderabad**.

**⚠ CORRECTION 1 — they DO keep a consent ledger.** Privacy §2: when a client accepts Terms
or confirms contacts consented, they keep *"a durable record of that confirmation (who, when,
and which policy version) as evidence, **not just a UI checkbox**."* So the campaign checkbox
is backed by a versioned attestation record. Our edge is **not** "we have a consent ledger and
they don't" — it is that ours records *end-caller* consent captured in-call, whereas theirs
records the *client's assertion about* the caller.

**⚠ CORRECTION 2 — their DLT/telecom posture is substantive, not a disclaimer.** The AUP
binds clients to **TRAI TCCCPR + NCPR/DND**, forbids caller-ID spoofing and bought/scraped
lists, requires a lawful basis per number, and requires the client to **produce evidence of
that basis (plus their privacy policy and the recording) within 24 hours** of a complaint.

**The genuinely load-bearing constraint they carry (and buyers will miss):** numbers bought
through Outpero are provisioned on a licensed Indian operator after **KYC** and are
**"for transactional and service calls… NOT for unsolicited promotional or marketing
calling."** That is effectively the 160-series restriction. Their "bulk campaign" product is
therefore only lawful over existing-relationship/opt-in lists — a real ceiling on the cold-
outbound use case, with **penalties and number suspension expressly the client's to bear.**

**Where our compliance edge genuinely survives:**
- **AI disclosure is optional for them.** AUP §4: the platform *"supports this (e.g. scriptable
  disclosure lines) but does not decide your legal obligations for you."* Our Hard Rule 5 makes
  a non-null disclosure line mandatory on every agent. This edge is real and now precisely stated.
- **PII redaction.** Their dashboard renders raw caller PII (phone, location, captured fields)
  with no redaction layer observed; we default every transcript to `text_redacted` and gate raw
  text behind role check + audit_log write.
- **Data residency.** Privacy §4: *"Some of these providers may process data on servers located
  outside India."* Our stack is India-resident by design (D-13/DEPLOYMENT).
- **Liability & SLA — the sharpest sales wedge.** Terms §11 caps total liability at **the fees
  paid in the preceding 3 months** — *the exact cap that helped disqualify ThinnestAI (D-31)* —
  and Terms §9 states they **"do not guarantee the Service will be uninterrupted, error-free, or
  available at all times."** That **directly contradicts the "99.9% Uptime SLA guarantee"
  advertised on their `/ai-employee` page.** Marketing promises an SLA the contract withholds.
  Verifiable, and fair to raise in any competitive conversation.
- **Money risk sits with the buyer.** Hire fee non-refundable once activated; credits
  non-refundable/non-transferable with no cash value; **unused balance forfeited on account
  closure**; refunds only for duplicate charges, undelivered payments, or verified platform bugs
  (5–7 business days). Prepaid-only, no auto-debit, balance never goes negative (Razorpay).

**Their security posture is genuinely good — treat as the bar, not a weakness.** Containerised,
single TLS termination, HSTS/CSP/frame-ancestors, non-root containers, dropped Linux
capabilities, auto unhealthy-container recovery; **agent-creation API, DB and cache on a private
network** with only dashboard/API/call-media+webhook exposed; **admin impersonation logged and
auditable** (their equivalent of our D-22); **72-hour incident notification target**; responsible
disclosure via support@. Sub-processor *categories* are published but **names are withheld**
("available on request") — which is why our Sarvam+Cartesia identification came from their
marketing assets, not their legal pages.

**★ Architectural capability we do not have planned — mid-call cross-provider failover.**
Security §4: *"The three voice-processing legs — speech-to-text, language model, and
text-to-speech — can each fail over to an alternate provider **mid-call** if the primary one
degrades or errors, so a single third-party outage doesn't necessarily drop your calls."* This
is the substance behind their "heals itself in milliseconds" marketing. **Our current design has
no in-call failover** — a single Sarvam/Gemini/engine degradation drops or damages the call.
Worth evaluating deliberately (note: it partly *depends on* engine-level control, which argues
for the phase-2 self-orchestration path rather than a rented engine). Also relevant: their
Google Calendar integration is exemplary privacy engineering — narrowest scopes, tokens
AES-128-CBC+HMAC encrypted at rest under a separate key, decrypted only in-memory in one
endpoint, never logged/returned/sent to the engine, **no calendar content ever enters a prompt**
(only a yes/no availability bit in their own fixed wording), hard-deleted on disconnect. A
pattern worth copying wholesale for our own OAuth integrations.

**Confirmed sub-processors** (from their own policies): **Supabase** (auth), **Razorpay**
(payments), **PostHog EU** (setup-flow analytics only, session replay with fields masked, never
on leads/calls/recordings screens), plus unnamed telephony, STT/TTS, LLM, cloud/object storage.

**★ Model stack now confirmed by their own footer, not inferred.** The `/ai-employee` footer
carries **"BACKED BY · sarvam · CARTESIA | Startups"** — i.e. Sarvam plus Cartesia's startup
programme. Combined with `sarvam-logo.png` / `cartesia-logo.png` shipping in their assets, the
**Sarvam + Cartesia** stack is established from first-party evidence. Their legal pages
deliberately keep sub-processors unnamed, so the marketing footer is the disclosure. Read for
us: the Telugu-quality leader in this market is **Sarvam either way** — the same models we
already BYOK — so their "native Telugu" advantage is a *voice-catalog and tuning* advantage,
not a model advantage we cannot match.

**Same footer repeats the SLA claim.** It renders **"All systems operational · 99.9% Uptime
SLA"** beside "© 2026 Outpero. A product by OpenDG Private Limited. Made in India, for India."
This is the *third* placement of a 99.9% SLA promise (marketing page, app footer, plan copy)
against Terms §9's explicit refusal to guarantee availability — the contradiction is systematic,
not a one-off typo.

**Footer IA** (all targets captured): *Explore* → Main Homepage, Platform Overview (`/#platform`),
All Products (`/#products`), About (`/about`) · *AI Employee* → How it works, **Reliability**
(`#why-it-wins`), Pricing, The dashboard — all anchors on `/ai-employee` · *Legal & Support* →
Contact, Privacy, Terms, Refund.

**`/about`** is pure agency positioning (outcome-first, business-audit-always, ROI-tracked;
three systems: Revenue Capture ₹60k+, Ops Efficiency ₹1L+, Digital Salesman/Web Capture ₹50k+;
plus 19 pre-built solutions from ₹14,999; free 30-minute strategy call; founder reachable at
vatsal@). Two things worth noting: it carries **no team page, no client names, no testimonials
and no case studies** — consistent with every other page on the property, so *"zero verifiable
customer proof"* remains true across their entire estate and stays our strongest counter-pitch.
And it **does not repeat opendg.org's "founded 2014 / 194+ businesses grown" claim** — the
parent-company credibility story is absent from the Outpero-branded property, so a prospect
comparing us sees no track record either.

**Docs site** (`docs.outpero.com`, 27 topics): confirms **one employee = exactly one channel**
(instant / bulk / inbound — cannot mix; switchable later), and that inbound is **"coming soon."**
Sections include employee lifecycle, call script & flow, voice & sound, actions & integrations,
post-call data & webhooks, publishing changes, versions & starting over, calling rules &
responsibilities, call log, leads, conversations.

## 9c. Docs site — operational limits, rate card, and a compliance gap (all 27 topics)

*(Their docs SPA serves stale body text to extractors; read via screenshots. Routes:
`#overview #reliability #howitfits #postcall #inbound #credits #numbers #training` + 19 more.)*

**★ Their DNC does not cover instant calls.** `#howitfits`: *"Do-not-call list coverage —
Applies to Bulk campaigns with the toggle on. **Not yet applied to Instant.**"* Their flagship
"call every lead within 30 seconds" channel does **not** scrub the do-not-call list. Our Hard
Rule 5 requires DNC propagation before the next dispatch tick on **every** path. This is now
our single most concrete compliance differentiator — and a live regulatory exposure they carry.

**Operational limits worth matching or beating:**
- **Max call length: 10 min default, adjustable 10 s – 1 hr**, call auto-ends at the cap —
  explicitly a cost-runaway guard. **We have no equivalent. [ADOPT]**
- **3 live campaigns** is the account-wide ceiling.
- **A number = one line.** Instant and Bulk contend for it ("whichever gets there first takes
  it; the other waits and retries — neither is prioritised"); two Bulk campaigns queue on one
  number, **oldest first**.
- **Precedence rule [ADOPT]:** *"Script decides content, rules decide conduct, voice only
  changes delivery — in that order."*
- **Split publish semantics by blast radius [ADOPT]:** script/action/webhook edits need an
  explicit "Apply to live calls"; voice, capture variables and training go live immediately.
- Dials only when hired **and** toggled on **and** published.

**Graceful degradation — the best engineering on their platform [ADOPT]:** continuous
mid-call health monitoring with inaudible switch to a healthy backup provider; if a **Premium
voice is under strain the call goes out on a Value voice and is billed at the lower Value
rate** — *"it never works the other way around; a call never silently upgrades you into
premium pricing"*; if nothing healthy is available the call **doesn't start** rather than
starting broken (outbound auto-retries); and on mid-call failure the agent gives *"a short,
natural spoken apology and ends the call cleanly, instead of just going silent."*

**Complete credit rate card** (`#credits`): signup bonus 100 credits once · first-hire bonus
300 once · Value 3 / Standard 5 / Premium 7 credits per minute · **AI script generation 0.2
credits/use** · **training sandbox chat 0.05 credits/message** · hire ₹1,899+GST/30 days ·
billed by the second, **rounded up to the nearest 30-second block** · at zero balance the
agent *"wraps up with a graceful goodbye rather than cutting off mid-sentence."*
*(Inconsistency: docs say signup = 100 credits; their pricing page says 20.)*

**Post-call webhooks** (`#postcall`): trigger conditions **Every call / Completed only /
Voicemail only**, plus a **one-click test-send** that fires a realistic sample payload before
go-live **[ADOPT — good DX]**.

**Number provisioning** (`#numbers`): setup fee + first month from credit balance; **KYC on
first purchase only — PAN then Aadhaar via DigiLocker's official consent flow**, "registers
the number to a real, verified person, as regulation requires"; auto-activates on clearance;
assignable as inbound / outbound / both. Rental price never published.

**Training** (`#training`): teach by typing, speaking, **or photographing** (a printed price
list yields facts like *"2BHK units start at ₹42 lakhs"* plus rules like *"never quote below
the listed minimum even if the caller pushes"*), review/flip fact↔rule before saving;
documents pulled *"only when a call actually calls for it"* (RAG); the gap loop *"watches real
calls for moments the employee visibly struggled, didn't know something, answered incorrectly,
or dodged a question"* and surfaces one-tap suggestions **quoting exactly what happened**.

**Inbound confirmed unshipped** (`#inbound`): *"Coming soon. Inbound employees can't be created
yet, and a number set up for inbound currently plays a short message to callers rather than
holding a full live conversation, **even if your setup looks complete on screen**."* Their
marketing sells inbound 24/7. The receptionist flank is open.

## 9d. Their integration contracts — the material for beating them on API/webhooks

**★ Lead intake contract (published verbatim in their docs):**

```
POST https://api.outpero.com/leads/in/<your-employee-token>
Content-Type: application/json

{ "phone": "+91 XXXXX 43210",
  "name": "Priya Reddy",
  "source": "facebook_ad",
  "budget": "40-50 lakhs",
  "area": "Gachibowli" }
```
- **`phone` is the only mandatory field.** *"Any field beyond `phone` becomes a pre-call
  variable your script can reference as `{{budget}}`, `{{area}}`"* — a **schemaless,
  self-describing payload**. Elegant for onboarding; it is also why their extraction is
  untyped and why "Delhi" landed in a quantity field.
- **Auth = a per-employee token in the URL path**, plus an **optional secret header**.
  No signature, no timestamp, no replay protection. *(Weaker than what we should ship.)*
- **Test webhook** runs a sample lead through without placing a call, and **Webhook
  activity** shows what arrived and whether it was **accepted / deduplicated / rejected**.
  **[ADOPT both — this is excellent integration DX.]**
- Lead sources: generic webhook · **Google Sheets** (add a row → the employee calls it) ·
  **Meta/Facebook Lead Ads — via Zapier, NOT native** · Zapier/Make. **Native Meta Lead Ads
  is an open gap we can take.**

**Calling policy (instant), with a number that contradicts their own UI:** call delay ·
calling window · out-of-window handling (next window open / +3h / +6h / next day / hold for
manual release) · **retry ladder "call again after N minutes", capped at 9 steps = 10 attempts
total.** ⚠ The employee Settings UI states "**up to 3 attempts total**" — their docs and their
product disagree; verify before quoting either.

**Working a lead by hand:** a **Test call** panel dials any number one-off; **Call now** on the
Leads page redials *through whichever employee last handled that lead*; leads on hold or awaiting
a retry collect under **Needs attention** with early release. **[ADOPT "Needs attention" —
it is the operational queue our SURFACES dashboard is missing.]**

**Actions are only four** — Calendar booking · Sheets (read *or write* mid-conversation) ·
Custom API · WhatsApp. All opt-in per employee, none on by default. **No timeout, retry or
error-handling semantics are documented anywhere** — consistent with the missing tool-call
budget found earlier.

**Publishing model — two speeds by blast radius [ADOPT]:**

| Change | Applies |
|---|---|
| Call script, flow, actions, webhooks | needs an explicit **"Apply to live calls"** |
| Voice, capture variables, training | **immediate — no publish step** |

Their stated rationale is sound: script/action edits change what the agent *says and does
mid-call* and deserve a deliberate push; voice/extraction/training are lower-risk and
higher-frequency. An unsaved-changes banner offers **Apply to live calls** or **Undo changes**
— *"nothing goes live silently in the background."*

**Versioning is shallow:** *"Outpero keeps your last **3** published versions, restorable at
any time."* No diffs, no author/audit trail, no environments. **Switch channel** rebuilds a
hired employee between Instant and Bulk without a second hire fee or re-provisioning;
**Start from scratch** wipes script/training/call history while keeping the number, credit
assignment and billing history.

**⚠ Their post-call webhook payload is NOT published** — only a prose field list (recording
URL, transcript, duration, status, hangup reason, timestamps always; summary/outcome/extracted
vars filled in a few seconds later after classification, so they *"may be null"*). The intake
payload is documented; the outbound one is not. **A published, versioned outbound schema is a
cheap, visible win for us.**

### Where this hands us concrete API/webhook differentiation

| Their behaviour | What we ship instead |
|---|---|
| URL-path token + optional secret header | **HMAC-signed** webhooks, timestamped, replay-protected (SEC-COMP §5) |
| Fire-once outbound, may arrive with null fields | **Transactional outbox**, retries, **delivery log + replay** (D-30 reliability triad) |
| Outbound payload undocumented | **Published, versioned schema + OpenAPI-generated client** |
| Meta Lead Ads only via Zapier | **Native Meta Lead Ads** ingest |
| Untyped `{{variables}}` | **Typed extraction schema** with validation + retry (TRD §7) |
| 3 versions, no diff/audit | **Full version history + diffs + audit_log**, staging→promote |
| Tool timeouts undocumented | **Documented, enforced in-call tool budget** with filler masking |
| DNC on bulk only | **DNC on every dispatch path** (Hard Rule 5) |

## 10. The D-11 pricing collision (decision required — see ROADMAP D-34)

Outpero's productised self-serve tier (₹0 setup, ₹1,899/mo, ₹3–7/min) **invalidates the
evidence D-11 cited** ("Outpero's ₹60k+ setup pricing norms"). The ₹60k+ figure still
exists, but only on their **agency** packages — the *product* an SMB actually shops sits at
~₹2,241 first month. This does not automatically break D-11 (we sell a managed service with
curation, QA, and compliance a ₹1,899 self-serve plan does not include), but the sales
narrative and the doc's justification must be revisited. Tracked as **D-34** (open).
