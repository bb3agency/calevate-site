# Outpero — Raw Research Log (Aug 2026)

The **working notes** from the authenticated teardown, in the order they were captured.
Exported from the local rememory store so the raw evidence travels with the repo.

- **Conclusions** live in `outpero-teardown-aug2026.md` — read that first.
- **This file** is the audit trail: what was observed, when, from which surface, and which
  claims were later **corrected**. Two parts were wrong and are marked inline.
- Method rules that came out of this: `docs/RESEARCH-DISCIPLINE.md`.

Provenance: live walkthrough of `app.outpero.com` on a real account (Raghava Organics),
their marketing site, `docs.outpero.com` (27 topics), their full legal set, and their
shipped JS bundle. No other tenant's data was accessed; their gated `/admin/*` returned 403
and was not probed. No test calls were placed.

---

## Part 1 — Tech stack & API surface

**Frontend:** React SPA (Vite), code-split (`vendor-react`, `vendor-supabase`,
`vendor-motion`, `vendor-charts`), served via Cloudflare.
**Auth:** Supabase — the API rejects cookie-based fetch with `{"detail":"Missing bearer
token"}`, i.e. Supabase JWTs in an `Authorization` header.
**Backend:** custom REST at `api.outpero.com`, FastAPI-shaped.

Endpoints the SPA calls: `GET /accounts/me`, `/employees`, `/billing`,
`/billing/usage?days=30`, `/numbers`, `/campaigns`, `/calls?limit=1000`, `/calls/live`,
`/notifications`, `/stats/dashboard`, `/stats/performance`,
`/stats/analytics?days=7&granularity=day`, plus a gated `/admin/health` (403 — correct
authz). **That list is their domain model.**

Code-split chunks name their features: `Dashboard`, `industryPresets`, `CallLogTable`,
`ExportPanel`, `csv`, `columnPrefs`, `wav`, `Onboarding`.

Architecture note: **`GET /calls?limit=1000`** — the call log is fetched client-side with no
server pagination. A smell worth not copying.

**Metering data point (one real call in the account):** Harish employee, Instant channel,
Qualified/Positive, 1:08 talk time, **₹10.50 charged**, extracted `specific_products=millets`,
`quantity_frequency=Delhi` (a mis-extraction — see Part 5).

---

## Part 2 — Agent ("employee") config surface

Eight tabs: Overview · Instant leads · Call script · Training · Actions · Post-Call ·
Voice(₹) · Settings.

**Call script is a branching section-graph, not a prompt.** Opening line with `{{variable}}`
interpolation; up to **15 sections**, each either a natural-language instruction (≤4,000
chars) or a verbatim "say exactly this"; **conditional branching** per section ("go to X
when Y") plus a default route; a **Flexible↔Strict adherence slider** (1–5); built-in
end-of-call rule plus custom hangup conditions; and **"Swara"**, an AI copilot that edits the
whole flow by voice or text.

Clean variable split: **pre-call vars come from the lead webhook; captured vars are defined
in Post-Call.** Same names flow through script, webhook and campaign CSV.

**Voice tab is the pricing lever.** Language modes Telugu+English / English, plus "Also speak
Hindi (Beta)". Voices are admin-curated from a "Voices catalog". Ambient-sound bed
(office/call-centre/restaurant/quiet/retail) with a volume slider.

**Billing mechanic decoded:** credits = talk-time **rounded up to a 30-second block** ×
voice-tier ₹/min. Proof: P09 (premium, ₹7/min), 1:08 → 1.5 min × ₹7 = **₹10.50**, exactly
the charge shown.

> ⚠ **CORRECTED IN PART 9b.** This part originally guessed the premium tier was a cloned
> *Sarvam* voice. Their shipped code says the opposite — see the correction below.

---

## Part 3 — Training/KB, Actions, Calling Policy

**Training tab = KB + quality loop.** Teach a fact or rule (typed, spoken, **or photographed**
— a printed price list yields facts like "2BHK units start at ₹42 lakhs" plus rules like
"never quote below the listed minimum"); the AI classifies fact-vs-rule and **you approve
before saving**. Documents for longer material, retrieved "only when a call actually calls
for it". Test-chat sandbox metered at **0.05 credits/message**.

**★ "Where Harish struggled on real calls — found automatically from actual conversations."**
Automatic knowledge-gap detection. **This erodes part of our D-15 claim** — BRD §5 previously
said they had "no exposed QA/eval process". They ship gap-surfacing; our edge narrows to the
*closed loop* (regression-on-every-change + client-facing QA reports + human curation).

**Actions (in-call tools):** master switch, WhatsApp via **Interakt / AiSensy / Meta Cloud
API**, **Custom API**, **Google Calendar**. All opt-in per employee, none on by default.

**Calling policy (client-configurable):** call delay, calling window, calling days, holidays,
out-of-window handling, retry ladder, **Respect Do-Not-Call list**, max concurrent, duplicate
lead window.

**Extraction is untyped** — named capture variables only, no type/enum/required system.

---

## Part 4 — Pricing, campaigns, telephony

**Billing:** 1 credit = ₹1, credits never expire, GST handled. **Hire fee ₹1,899/employee/mo**
(₹2,241 incl GST) — building/scripting/**test calls are free**, you pay when an employee goes
live. Includes ₹500 credits/mo + its own number. Employees sit in **Draft until hired**; a
lapsed plan **pauses** (never deletes).

**Talk-time:** ₹3 / ₹5 / ₹7 per min by voice tier, 30-sec-block rounding, ring/unanswered free.

**Top-up packs (Standard-tier effective rates):** ₹999→199 min (₹5.02) · ₹2,999(+150)→629
(₹4.77) · ₹9,999(+800)→2,159 (₹4.63) · ₹24,999(+2,500)→5,499 (₹4.55) · ₹50,000(+6,000)→11,200
(₹4.46). **Volume discount is shallow — ~11% max.**

**Enterprise (>₹50,000):** custom rates, higher concurrency, named contact, **hire fee waived**.

**Bulk campaign config:** concurrency slider, calling window/days/holidays, skip opted-out
(DNC, on by default), **skip recently-called across campaigns**, CSV/paste/load import,
auto-retry, schedule-for-later, **recurring daily/weekly**. Compliance is a **self-attestation
consent checkbox**.

**Telephony:** India **mobile** numbers bought in-app. **Platform-enforced calling hours —
bulk 9 AM–9 PM, instant callbacks 6 AM–10 PM** (not user-editable). Auto-DNC on request.
Liability on the client ("your business is the caller").

---

## Part 5 — CRM, retention, analytics

Three result views: **Leads & Results** (lead-rollup, deduped by contact; table/grid/**kanban**),
**All Conversations** (call-centric; filters by direction, recording, length bucket, channel,
outcome, sentiment, employee, source; CSV export), and a **per-employee call log** with
extraction vars as dynamic columns.

Outcome enum: Qualified · Interested · Callback · Not interested · Missed · No answer · Busy ·
Call failed · Voicemail.

**Retention (stated):** *"Call recordings are kept for 90 days, then automatically deleted —
the transcript and summary stay for as long as your account is active."* Matches our D-14
90-day floor.

**Performance suite:** connect rate, conversion funnel (Calls→Connected→Qualified), outcomes,
by-channel, **busiest hours**, **employee leaderboard**.

**★ Extraction-quality wedge:** on their one real call, `quantity_frequency` was populated
with **"Delhi"** — a location in a quantity field. Their capture variables are untyped. Our
typed `extraction_schema` (type/enum/required + Pydantic validation + retry, TRD §7) rejects
exactly this. **No PII redaction observed** — raw phone numbers and locations render freely.

---

## Part 6 — Legal, security, compliance (with 2 corrections)

Read in full: Terms (25 Jul), Privacy (28 Jul), Refund (25 Jul), Security & Sub-processors
(25 Jul), Acceptable Use (1 Aug), Contact.

**Entity:** OPENDG PRIVATE LIMITED · GSTIN 36AACCO6812H1ZH · Madhapur, Hyderabad · founder
**Vatsal Sarakadam** · support replies "within 1 business day" · India law, **exclusive
jurisdiction Hyderabad**.

> ⚠ **CORRECTION 1 — they DO keep a consent ledger.** Privacy §2: accepting Terms or
> confirming consent produces *"a durable record of that confirmation (who, when, and which
> policy version) as evidence, **not just a UI checkbox**."* Our edge is narrower than first
> stated: theirs records the *client's assertion about* the caller; ours records **end-caller
> consent captured in-call**.

> ⚠ **CORRECTION 2 — their DLT posture is substantive, not a disclaimer.** The AUP binds
> clients to TRAI **TCCCPR + NCPR/DND**, bans caller-ID spoofing and bought/scraped lists,
> and requires **evidence production within 24 hours** of a complaint.

**★ The sharpest verifiable wedge:** Terms §11 caps liability at **fees paid in the preceding
3 months** — the exact cap that helped disqualify ThinnestAI — and Terms §9 states they *"do
not guarantee the Service will be uninterrupted, error-free, or available at all times."*
This **contradicts the "99.9% Uptime SLA" advertised in three places** (marketing bullets,
site footer, plan copy). Systematic, not a typo.

**★ Their numbers are transactional-only:** provisioned on a licensed Indian operator after
KYC and *"for transactional and service calls… **not** for unsolicited promotional or
marketing calling."* Effectively the 160-series restriction — a real ceiling on cold outbound,
with penalties **the client's to bear**.

**Money risk on the buyer:** hire fee non-refundable once activated; credits
non-refundable/non-transferable; **unused balance forfeited on account closure**.

**Their security posture is good — treat as the bar:** containerised, single TLS termination,
HSTS/CSP, non-root containers, dropped Linux capabilities, **agent-creation API + DB + cache on
a private network**, **admin impersonation logged and auditable**, **72-hour incident
notification**. Sub-processor *categories* published, **names withheld**.

**★ Capability we do not plan — mid-call cross-provider failover.** Security §4: *"The three
voice-processing legs — STT, LLM and TTS — can each fail over to an alternate provider
**mid-call**."*

**Google Calendar handling is exemplary — copy this pattern:** narrowest scopes; tokens
AES-128-CBC+HMAC encrypted at rest under a separate key; decrypted only in-memory in one
endpoint; never logged/returned/sent to the engine; **no calendar content ever enters a
prompt** (only a yes/no availability bit in their own wording); hard-deleted on disconnect.

**Confirmed sub-processors:** Supabase (auth), Razorpay (payments), PostHog EU (setup-flow
analytics only, never on leads/calls/recordings screens).

---

## Part 7 — Footer, positioning, `/about`

Footer reads **"BACKED BY · sarvam · CARTESIA | Startups"** — vendor/startup programmes.
Combined with `sarvam-logo.png` and `cartesia-logo.png` in their assets, this established the
model stack from first-party evidence.

Footer also renders **"All systems operational · 99.9% Uptime SLA"** — the third placement of
the SLA claim contradicted by their Terms.

**`/about`** is pure agency positioning (outcome-first, ROI-tracked; three systems at
₹60k/₹1L/₹50k; 19 pre-built solutions from ₹14,999).

**★ Zero customer proof across the entire estate** — no team page, no client names, no
testimonials, no case studies on the homepage, `/about`, `/ai-employee`, the dashboard, or
the docs. `/about` also omits opendg.org's "founded 2014 / 194+ businesses / ISO 9001" story,
so the Outpero brand shows **no track record of its own**.

---

## Part 8 — Docs site (27 topics)

*Method note: their docs SPA serves **stale body text** to text extraction — read via
screenshots. Hash routes: `#overview #reliability #howitfits #postcall #inbound #credits
#numbers #training` + 19 more.*

**★ Their DNC does not cover instant calls.** `#howitfits`: *"Do-not-call list coverage —
Applies to Bulk campaigns with the toggle on. **Not yet applied to Instant.**"* Their flagship
"call every lead in 30 seconds" channel does **not** scrub DNC. **Our single most concrete
compliance differentiator**, and a live regulatory exposure they carry.

**Operational limits:** max call length **10 min default, adjustable 10 s – 1 hr** (an
explicit cost-runaway guard — we have none); **3 live campaigns** account-wide; **a number =
one line**, with Instant and Bulk contending for it ("whichever gets there first takes it").

**Precedence rule:** *"Script decides content, rules decide conduct, voice only changes
delivery — in that order."*

**Graceful degradation:** continuous mid-call health monitoring with inaudible switch to a
healthy backup; **if a Premium voice is under strain the call runs on a Value voice and is
billed at the lower Value rate** — *"it never works the other way around."* If nothing healthy
is available the call **doesn't start** rather than starting broken. On mid-call failure the
agent gives *"a short, natural spoken apology and ends the call cleanly, instead of just going
silent."*

**Credit rate card:** signup bonus 100 credits · first-hire bonus 300 · Value 3 / Standard 5 /
Premium 7 per min · **AI script generation 0.2 credits/use** · **training sandbox 0.05
credits/message** · hire ₹1,899+GST/30 days. *(Inconsistency: docs say signup = 100 credits;
their pricing page says 20.)*

**Number provisioning:** setup fee + first month from credits; **KYC on first purchase only —
PAN then Aadhaar via DigiLocker**; auto-activates on clearance.

**★ Inbound confirmed NOT shipped:** *"Coming soon. Inbound employees can't be created yet, and
a number set up for inbound currently plays a short message to callers rather than holding a
full live conversation, **even if your setup looks complete on screen**."*

---

## Part 9 — Integration contracts

**★ Lead intake contract, published verbatim in their docs:**

```
POST https://api.outpero.com/leads/in/<your-employee-token>
Content-Type: application/json

{ "phone": "+91 XXXXX 43210", "name": "Priya Reddy",
  "source": "facebook_ad", "budget": "40-50 lakhs", "area": "Gachibowli" }
```

- **`phone` is the only mandatory field.** *"Any field beyond `phone` becomes a pre-call
  variable your script can reference as `{{budget}}`, `{{area}}`"* — schemaless and
  self-describing. Elegant onboarding; also **the root cause of the untyped-extraction bug**.
- **Auth = a per-employee token in the URL path**, plus an **optional secret header**. No
  signature, no timestamp, no replay protection.
- **Test webhook** runs a sample lead through *without placing a call*; **Webhook activity**
  shows each delivery as **accepted / deduplicated / rejected**.
- Sources: generic webhook · Google Sheets · **Meta/Facebook Lead Ads via Zapier, NOT native**
  · Zapier/Make.

**Calling policy contradiction:** docs say the retry ladder is capped at 9 steps = **10
attempts**; the employee Settings UI says **"up to 3 attempts total."**

**Working a lead by hand:** Test call panel; **Call now** redials *through whichever employee
last handled that lead*; held/retrying leads collect under **"Needs attention"** with early
release.

**Actions are only four:** Calendar booking · Sheets (read *or write* mid-conversation) ·
Custom API · WhatsApp. **No timeout, retry or error-handling semantics documented anywhere.**

**Publishing model — two speeds by blast radius:** script/flow/actions/webhooks need an
explicit **"Apply to live calls"**; voice/capture-variables/training apply **immediately**.
Unsaved-changes banner offers Apply or Undo — *"nothing goes live silently in the background."*

**Versioning is shallow:** *"keeps your last **3** published versions, restorable at any
time."* No diffs, no audit trail, no environments. **Switch channel** rebuilds an employee
between Instant and Bulk without a second hire fee; **Start from scratch** wipes
script/training/history while keeping the number and billing.

**⚠ Their post-call webhook payload is never published** — prose field list only (recording
URL, transcript, duration, status, hangup reason, timestamps always; summary/outcome/extracted
vars filled seconds later after classification, so they *"may be null"*). Intake is documented;
outbound is not.

---

## Part 9b — Corrections from their shipped code (supersede Parts 1/4/7)

Read directly from `app.outpero.com/assets/*`:

```
value:    rates.sarvam_per_min      →  ₹3/min
standard: rates.smallest_per_min    →  ₹5/min
premium:  rates.cartesia_per_min    →  ₹7/min
```

Also present: `ai_per_use`, a `provider` field on voices, `voice_id`, and billing fields
`runway_days` / `daily_burn_inr`.

**★ This inverts an earlier assumption.** Premium is **Cartesia**, not a premium Sarvam voice —
and **Sarvam is their *cheapest* tier**. A third vendor appears that we had not tracked:
**Smallest.ai** at ₹5. *(Smallest's public rate reads ~$0.09/min of generated audio — too vague
to reconcile; not built upon.)*

> ⚠ **RETRACTED: "Outpero self-orchestrates / pays no platform fee."** Inferred from their
> security page and mid-call failover, and stated far more confidently than the evidence
> supported. **Sarvam, Smallest and Cartesia are all three on Bolna's published supported-TTS
> list** — a vendor trio matching a rented orchestrator's provider menu is at least as
> consistent with *being that orchestrator's customer*. **Treat their orchestration layer as
> UNKNOWN**; no cost or strategy conclusion rests on it.

**Method limit worth remembering:** a client bundle can *never* settle this — calls run over
PSTN, never through the browser. Confirmed absent from their bundle: livekit, twilio,
daily.co, agora, webrtc. Only `getUserMedia`/`MediaRecorder` for the in-browser "Talk"
feature. *(An early "daily" hit was the billing field `daily_burn_inr` — a false positive.)*

---

## Not scraped (judged low value)

The live "Talk to an employee" browser feature · the Swara 5-question onboarding run · global
Instant Leads / Train Employees pages · Settings & account · Billing Transactions/Usage/GST
tabs · ~15 remaining docs pages · Cookie Policy · their city-SEO blog play.
