# Calevate — India GTM & Sales Playbook

**Status:** working sales playbook for the founder. First version 30 Aug 2026.
**Not a pricing contract and not legal advice.** Every product claim here is backed by a
shipped surface (cited `file:line`); every number is either a real config value in this
repo or is marked as *the buyer's own input*. Where a figure is per-deal, it says so rather
than inventing one — same discipline as the marketing site (hard rule 11,
`docs/POSITIONING-QUALIFICATION-LAYER.md §6`).

This governs how we **sell**, not how the product behaves. It changes no code and no price.

---

## 0. The one-line strategy

> **Sell inbound reception first, to one vertical, on a free pilot. Prove it on their own
> calls. Expand to outbound once they trust the leads table.**

Everything below is the reasoning and the scripts behind that sentence.

---

## 1. Who we sell to first

### 1.1 Pick ONE vertical and go deep

We ship four seeded extraction templates (`scripts/seed.py:103`): **clinic, real estate,
insurance, education**. Do **not** spread across them at launch. One vertical repeated means
the agent prompt, the extraction schema, the objection answers and the case study all
compound with every client instead of resetting.

Ranked by *pain × ability-to-pay × short sales cycle × how fast we can prove ROI*:

| Rank | Vertical | Why it wins first | Ideal first buyer |
|---|---|---|---|
| **1** | **Real estate** (Hyderabad: Gachibowli, Kondapur, Financial District) | Highest ticket — one saved lakhs/crores deal pays for a year. **Speed-to-lead is the whole game** and a human physically cannot call a fresh Meta/portal lead in seconds; our webhook→dial can. Owner-operator decides in one meeting. | A **1–5 agent brokerage** already spending ₹20–50k/mo on lead ads and losing half to slow follow-up. |
| **2** | **Clinics / dental / diagnostics / IVF** | Constant **missed inbound** at lunch, after 8pm, Sundays — each miss is a patient who dialled the next clinic. High recurring call volume = steady minutes = steady revenue. | A **3–6 doctor clinic or small chain** with one overwhelmed receptionist. |
| 3 | Insurance agents (LIC / health) | Outbound-follow-up heavy — but DLT/DND-sensitive, so the first sale is harder. Fast-follow, not first. | — |
| 4 | Education (coaching / admissions) | Real pain but **seasonal** (admissions spikes). Time it to the season. | — |

**Default recommendation: start with real estate, keep clinics as the close second.** Both
map cleanly onto capabilities we already ship (§3).

### 1.2 The buyer inside the business (personas — `docs/BRD.md §3`)

- **P2 Client Owner** — the one who signs. **Buys outcomes**, not technology: "no missed
  calls", "qualified leads". Pitch to this person.
- **P3 Client Staff** — works the Leads table daily. Their buy-in kills or saves the
  renewal: show them the CRM makes their day easier, not that it replaces them.
- **P4 Caller** — speaks Telugu/Hindi/mixed, expects a natural, honest, fast call.

---

## 2. The GTM lever most founders miss: lead with **inbound**

Our own compliance docs hand us a fast "yes":

- **Inbound reception can go live *without* DLT Telemarketer registration** — it needs only
  the client's number + the engine + the legal pages
  (`docs/legal/LEGAL-OPS-PLAYBOOK.md`). We can be live in **days**.
- **Outbound campaigns need the full PE–TM DLT chain**, which is a client-side **1–2 week**
  onboarding (they register as Principal Entity and bind our Telemarketer ID). The campaign
  launch gate literally blocks a dispatch until that chain is Active
  (`apps/api/campaigns/service.py:283`).

So the motion is:

1. **Phase 1 — Inbound.** "Let me answer your missed calls this week." Fast to yes, fast to
   value, no compliance homework for the client.
2. **Phase 2 — Outbound.** Once the leads table has earned their trust, upsell instant
   speed-to-lead callback and bulk campaigns — and *then* walk them through the one-time DLT
   setup, which now feels worth it because they've already seen results.

Selling outbound first means asking for a two-week compliance setup **before** they've seen
a single lead. Don't.

---

## 3. What we can honestly promise (every claim is a shipped surface)

Nothing in a pitch should claim a capability that isn't in the tree. These are:

| Promise to the buyer | Shipped surface |
|---|---|
| Every call answered — nights, weekends, lunch, in Telugu | Inbound receptionist, `docs/BRD.md §4` scope 1 |
| A web/portal lead gets called back in seconds | `apps/api/ingest/service.py:1` webhook-in → compliance gate → outbound; dispatch at `:395` |
| The gap between the enquiry and the dial is measured on every one | `apps/api/core/alerting.py:611` `record_speed_to_lead(...)`, called on all four exits |
| Each call lands as a CRM row with **the fields you chose** | `packages/shared/.../extraction.py:105` schema; `apps/api/crm/columns.py:16` — the extraction schema *is* the Leads table |
| Leads come back marked new→contacted→interested→hot→won→lost | `apps/api/crm/schemas.py:29` fixed status enum |
| A ready-to-book lead pings you within ~2 minutes | `apps/workers/pipeline.py:135` hot-lead triggers → owner alert (`docs/FLOWS.md §6`) |
| Your dashboard reads it back as a funnel (Calls → Connected → Qualified) | `apps/api/crm/performance.py:3` |
| Recording + transcript + AI summary + timestamped moments attached | `apps/workers/pipeline.py`, `moments.py` |
| The agent always answers truthfully if asked "are you an AI / is this recorded?" | server-enforced `TRUTHFUL_ANSWER_DIRECTIVE`, `docs/SECURITY-COMPLIANCE.md §2.0` |

### The framing that makes it land: **the qualification layer**

(Adopted positioning — `docs/POSITIONING-QUALIFICATION-LAYER.md`.)

> Calevate qualifies the **whole** list; your people close only the **warm** subset.

Not "replace your telecaller" (a six-minute sales call has no cheaper substitute). Instead:
*where does a salesperson's hour go — prospecting, or closing?* We move it to closing.

---

## 4. The pitch — sell the outcome, per vertical

Open with the buyer's pain in their words. Tech comes only if they ask.

**Clinic owner:**
> "How many calls does your front desk miss after 8pm, at lunch, on Sundays? Each one is a
> patient who called the next clinic. Calevate answers every call in Telugu, books the slot,
> and it's in your dashboard by morning — for less than one telecaller costs."

**Real-estate broker:**
> "When a lead drops from your Meta ad at 11pm, how fast does someone call it? Calevate calls
> in seconds, in Telugu, asks budget, location and timeline, and only the serious ones reach
> your phone. You stop paying agents to chase dead numbers."

**The 20-second "what is it":**
> "An AI phone agent for your business. It answers and makes calls in Telugu, captures every
> enquiry as a lead with the details you care about, and hands the hot ones straight to you."

---

## 5. How to convert — lower the risk of "yes"

1. **Free / low-cost pilot on their real calls.** We ship a `trial` tier and prepaid credits
   (`apps/api/billing/credit_packs.py`, `billing/ai_quota.py:202`). Point their number at
   Calevate for 1–2 weeks, inbound-only, and **let the leads table fill up in front of
   them.** A filling dashboard out-sells any slide.
2. **Show, don't claim.** Play a real recording. Open the ROI calculator and enter *their*
   numbers — telecallers at **₹18–25k/mo each** (`docs/BRD.md:22`) vs our **₹5/min**
   (`credit_packs.py:4`). Because they typed the inputs, they can't argue with the output.
3. **Land small, expand.** Inbound first; outbound + campaigns as phase 2 (§2).
4. **Quality process is the trust wedge.** Our real competitors are DIY self-serve platforms
   and no-code resellers (`docs/BRD.md:22`). Our edge: *India-native, managed for you,
   Telugu-first, with per-client regression testing so the agent doesn't drift off-script* —
   something a reseller cannot show.

---

## 6. Pricing — the one-pager to say out loud

**Structure** (plans are config rows `{setup_fee, monthly_fee, included_min, overage_rate,
hard_cap_min, hard_cap_spend}` — `docs/TRD.md:1131`):

- **Setup fee** — funds the build of *their* agent (KB, script, extraction schema, testing).
- **Monthly retainer** — covers the fixed base and includes a minutes bucket.
- **Overage** — **₹6–8/min band** beyond the bucket (`docs/TRD.md:1507`).
- **List / self-serve rate — ₹5.00/min**, 1 credit = ₹1 (`credit_packs.py:4,12`).
- **Prepaid credits, no monthly floor** (`docs/TRD.md:859`) + a **hard spend cap** so the
  client can never be surprised by a bill.

> The exact setup fee and retainer are **set per deal** — the docs deliberately keep them as
> config, not a fixed sticker (`docs/TRD.md:1510`). Anchor them against what the client
> already spends on telecallers, and recover your build cost in the setup fee + retainer, not
> in a scary per-minute headline (`docs/TRD.md:1522`).

**How to frame it:** one always-on agent that never sleeps, against a ₹20k telecaller who
works one shift and takes leave. The retainer *is* the "salary"; the difference is it answers
at midnight.

---

## 7. Objection handling

| They say | You say |
|---|---|
| "Will it actually sound natural in Telugu?" | "Let's not argue about it — I'll run it on your real calls for two weeks. You listen to the recordings and decide." (We do **not** quote a Telugu-accuracy number — it's still being tuned, D-36. The pilot *is* the proof.) |
| "Is recording people even legal?" | "The agent tells the caller it's an AI and that the call is recorded, at the start — those notices are built in and can't be silently switched off, and it always answers honestly if a caller asks. It's built for Indian DPDP/TRAI rules." (`docs/SECURITY-COMPLIANCE.md §2`) |
| "It's too expensive." | Open the ROI calculator with their numbers. Never defend the price in the abstract — let their own arithmetic answer. |
| "I'll just hire another telecaller." | "For a receptionist workload, sure — but your closer's alternative isn't a cheaper closer. Let the AI qualify the whole list; your people spend their hours only on the warm ones." (`POSITIONING-QUALIFICATION-LAYER.md §2`) |
| "What if it says something wrong?" | "Every client gets a per-client regression test suite — the agent is tested against real transcripts before it ever picks up, and re-tested when it changes. Resellers can't show you that." |
| "Can it call my old leads too?" | "Yes — that's phase 2. It needs a one-time telecom registration (DLT) first, which takes about a week. Let's get inbound live now and turn that on once you've seen the leads come in." |

---

## 8. Two honesty rules that protect your credibility

These are not optional — breaking them is how a founder loses a technical buyer:

1. **Never quote conversion stats.** No "391% more conversions", no "7× more likely". Our
   own site *refuses* these because none is verifiable (`POSITIONING-QUALIFICATION-LAYER.md
   §6`, enforced by `publicLanding.test.tsx`). Give the buyer arithmetic on **their** numbers
   instead — undisputable, and stronger.
2. **Never claim a Telugu-accuracy figure.** It's UNMEASURED (D-36). That's *why* the pilot
   is the sales tool — you prove it on their calls rather than promising a number.

---

## 9. The first-10-clients motion

1. Narrow to **one vertical** in AP/TS.
2. Warm outreach through the founder's own network first — not cold.
3. Offer a **free inbound pilot** (1–2 weeks).
4. Screenshot the **filled leads table** as case study #1.
5. Ask every happy client for **2 referrals in the same vertical.**
6. Repeat in the same vertical until the agent, schema and pitch are sharp — *then* consider
   vertical #2.

Because there is no client in production yet, **client #1 is the whole roadmap right now**
(`docs/ROADMAP.md` — "client #1 needs beat platform polish"). Treat the first pilot as the
product's real first test, not a demo.

---

## 10. What this playbook deliberately does NOT do

- **No price moved.** ₹5/min list rate and TRD §10 are untouched — this is a sales document.
- **No US / foreign motion.** India-only remains frozen (`LEGAL-OPS-PLAYBOOK.md`); the US
  path is a different telecom + legal machine we have not built (see the US-exposure analysis
  in `docs/legal/comet-legal-research.md` Part G).
- **No invented benchmark.** Every figure is a repo config value, a cited product surface, or
  the buyer's own input. When a number is per-deal, it says so.
