# Positioning: Calevate as the qualification layer

**Status:** adopted, 25 Aug 2026. Governs the marketing site only
(`apps/web/src/app/page.tsx` section 03, `apps/web/src/components/marketing/roiCalculator.tsx`,
`apps/web/src/lib/roi.ts`). It changes no product behaviour and no price.

---

## 1. The problem this replaces

The homepage ROI calculator compared **Calevate at the published self-serve rate against
hiring telecallers, on the same calls**. That comparison is honest for a receptionist
workload — the default call length there is two minutes, and a two-minute call is an
enquiry being written down.

It stops being honest as the call gets long, and at the top of the slider it loses. At
200 calls/day × 6-minute calls it showed four telecallers at ₹1,48,000/month against
Calevate at ₹1,56,000/month, and the buyer was invited to conclude that hiring wins.

The defect is not the arithmetic — the arithmetic was right. The defect is that the two
sides were **never alternatives**. A six-minute call is a sales conversation, and nobody's
alternative to their closer is a cheaper closer. The comparison compared a closer to a
per-minute agent and got the answer that comparison deserves.

## 2. The framing that is like-for-like

The split every sales organisation already runs: **one person qualifies, another closes.**

- **Stage 1 — Calevate qualifies the whole list.** Every inbound enquiry and every name on
  the owner's list gets a short first call, quickly, and comes back categorised with
  structured fields captured.
- **Stage 2 — humans close only the qualified subset.** The owner's salespeople spend their
  expensive conversations only on leads that are already warm.

What moves is not the cost of a telecaller. It is **where a salesperson's hours go** —
from prospecting to closing. The remaining gate becomes how fast the owner can service the
demand that has been qualified for them.

## 3. What was built

### `apps/web/src/lib/roi.ts`

- `TWO_STAGE` — two new benchmarks: `qualifiedPct` (default 30, range 5–100) and
  `qualifyMinutes` (default 2, range 0.5–5). **Neither is sourced and both say so**: they
  are assumptions about the buyer's own list, which nobody outside it can know. They are
  sliders for that reason, exactly as the telecaller benchmarks are.
- `computeTwoStage(inputs)` — **composed from `computeRoi`, not re-derived.** Option A is
  `computeRoi(inputs)`; option B's first stage is `computeRoi({…, avgMinutes: qualifyMinutes})`
  read for `calevatePaise`; option B's second stage is `computeRoi({…, callsPerDay: qualified})`
  read for `humanTotalPaise`. One cost model at three volumes, so the two sides of the
  comparison cannot drift into disagreeing about what a telecaller costs. Money stays
  integer paise throughout (module header doctrine, hard rule 7's reasoning).
- `humanMinutesReleased` — `triagedAwayPerMonth × avgMinutes`. This is the argument.

### The worked example the buyer now sees

200 calls/day · 26 working days · 6-minute human conversations · business hours ·
30% qualified · 2-minute first call, on the shipped defaults:

| | |
|---|---|
| **A. Your people work the whole list** | 4 salespeople · **₹1,48,000/mo** |
| B. Calevate's first call to all 5,200 | ₹52,000/mo |
| B. Your 2 salespeople, on the 1,560 qualified conversations | ₹74,000/mo |
| **B. Together** | **₹1,26,000/mo** |
| **Difference** | **₹22,000/mo**, and 4 salespeople → 2 |
| 3,640 calls a month never reach a person | ≈**364 hours** of selling time |

Pinned to the paise in `apps/web/tests/roi.test.ts` ("the worked example the page shows")
and end-to-end through the rendered component in `apps/web/tests/publicLanding.test.tsx`.

### It can lose, and says so

At `qualifiedPct = 100` there is nothing for a first call to filter, so option B is option
A plus a qualification bill: `deltaPaise` goes to **−₹52,000** and the verdict prints *"the
two-stage funnel costs ₹52,000.00 more a month, not less … if that is really your list,
your team should keep calling it."* Guarded by
`roi.test.ts::"goes NEGATIVE when everything on the list is worth a conversation"` and
`publicLanding.test.tsx::"says so plainly when the two-stage funnel costs MORE"`.

### Input surface: three additions, all progressively disclosed

The founder has twice said the calculator must not exhaust the buyer. The mode is a
two-option `radiogroup` at the top; the two extra sliders exist **only** when the two-stage
mode is chosen. In the default (head-to-head) mode the input surface is unchanged.

At `avgMinutes >= 4` in head-to-head mode the verdict card adds one line pointing at the
two-stage mode — the page names the mismatch rather than showing a losing number in
silence.

## 4. Vocabulary adopted, and the evidence class of each source

**Every host that would have been a primary source is egress-blocked in this sandbox**
(re-measured 25 Aug 2026: `hbr.org`, `en.wikipedia.org`, `blog.hubspot.com`, `ebq.com`,
`coldlytics.com` all return `EGRESS_BLOCKED` at the proxy on `WebFetch`). What was actually
read this session is **search-result excerpts**, not the pages behind them. Under hard
rule 11 that is REPORTED, not VERIFIED — good enough to borrow a *word* from, never good
enough to borrow a *number* from.

So: the terms below are used as vocabulary; **no factual claim rests on any of them**, and
none of them appears as an assertion on the page.

| Term | Used on the page as | Read from (25 Aug 2026) | Class |
|---|---|---|---|
| SDR / AE split ("one person qualifies, another closes") | plain-language body copy, no acronym | search excerpts, e.g. <https://ebq.com/make-the-sdr-ae-model-work-for-you/>, <https://salesroads.com/leadership/sdr-vs-ae/> | REPORTED (excerpt only; page blocked) |
| Lead qualification · MQL → SQL | the two-stage model's shape | <https://blog.hubspot.com/sales/sales-qualified-lead>, <https://marketing.techinformed.com/insights/mql-hql-sql-bant-guide/> | REPORTED |
| BANT (Budget/Authority/Need/Timing) | **not used in copy** — the shipped extraction fields (budget, timeline, urgency) already are this, per-vertical | <https://www.coldlytics.com/glossary/bant-framework> | REPORTED |
| Speed-to-lead / lead response time | "the gap between the form and the dial is timed on every one" | <https://www.callpage.io/blog/posts/speed-to-lead>, <https://www.leandata.com/blog/speed-to-lead-speed-is-the-key-to-lead-conversion/> | REPORTED; the *mechanism* is ours and shipped (§5) |
| Top-of-funnel triage · human-in-the-loop augmentation | "This is not your team replaced. It is the part of their day that was never selling." | <https://research-hub.g2.com/sales-marketing-ai-study>, <https://mountainise.com/blog/ai-sales-orchestration-human-in-the-loop/> | REPORTED |
| Sales capacity / productivity per rep | expressed as the buyer's own arithmetic (hours released), never as a benchmark | — | ours, computed |

**Register note.** The audience is Telugu-first SMB owners in AP/TS, not a B2B SaaS
buying committee. The concepts are used; the acronyms are not printed. A clinic owner
does not search for "MQL".

## 5. Shipped capabilities backing each claim

Nothing on the page claims a capability that is not in the tree today.

| Claim on the page | Shipped surface |
|---|---|
| Every enquiry and every name gets the first call | `apps/api/ingest/service.py:1` — "Instant lead callback: webhook-in → lead → compliance gate → outbound (FLOWS §4)"; `apps/api/ingest/service.py:395` dispatches. Bulk lists: `apps/api/campaigns/service.py:1` (draft → launch gate → dispatch → retries). |
| The gap between the form and the dial is timed | `apps/api/core/alerting.py:611` `record_speed_to_lead(seconds, outcome=…)`, called on all four exits of `ingest/service.py` (:368, :379, :390, :406). **The page states the measurement, not a duration** — see §6. |
| Each call lands as a row with the fields you asked for | `packages/shared/src/calevate_shared/extraction.py:79` `ExtractionField` / `:105` `ExtractionSchemaSpec`; `apps/api/crm/columns.py:16` — "The extraction schema IS the Leads table's column list (TRD §7 (c))"; one registry, one resolver, screen and CSV mirrored. |
| The lead comes back marked | `apps/api/crm/schemas.py:29` — `LeadStatus = Literal["new","contacted","interested","hot","won","lost"]`, a fixed enum (D-21). |
| Someone who wants to book reaches you as an alert | `apps/workers/pipeline.py:135` `HOT_LEAD_FIELD_TRIGGERS` (`urgency ∈ {emergency,urgent}`, `intent ∈ {buy,book}`) → `:2496 _maybe_notify_hot_lead` writes `status='hot'` and enqueues once through the outbox; FLOWS §6 targets the owner within 2 minutes. |
| Your dashboard reads it back as a funnel | `apps/api/crm/performance.py:3` (Calls → Connected → Qualified), `:46` `QUALIFIED_STATUSES = ("contacted","interested","hot","won")`, `:16` — Qualified is lead-level, so three calls that qualify one lead are one outcome. |
| The audio is attached / moments timestamped | already on the page before this change (`apps/workers/pipeline.py` pipeline order, `moments.py`). |
| The BRD already promised this | `docs/BRD.md:12` — "qualifies leads … extracts structured data into a built-in CRM, and hands hot leads to humans"; `docs/BRD.md:28` — "speed-to-lead determines conversion, and manual dialing cannot call a fresh web/Meta lead within seconds"; `docs/BRD.md:65` — hot-lead notifications. The positioning is not new; the marketing site had simply never made it the argument. |

**Partial, therefore excluded from client-facing copy:**

- **Meta Lead Ads as a named source.** `apps/api/ingest/meta.py` is built, but its module
  header records that `developers.facebook.com` was blocked and that one real delivery
  end-to-end is still an OPERATIONS §2 gate. The page says "a web enquiry", never "your
  Facebook leads".
- **Knowledge-gap insights** (`apps/api/insights/`) are shipped but are about the agent's
  gaps, not lead qualification. Not claimed here.
- **Extraction quality in Telugu** is UNMEASURED (D-36, task #87). No accuracy word appears
  — `publicLanding.test.tsx` bans them page-wide.

## 6. Claims deliberately REFUSED

Each of these is in circulation, each would have made the section punchier, and each is
absent because it could not be verified to a primary source this session.

| Refused | Where it came from | Why refused |
|---|---|---|
| "391% more conversions when you call in the first minute" | surfaced in the speed-to-lead search excerpts (callpage / leadangel / kixie) | No primary source. The figure is attributed onward to a study nobody in the chain links to a readable original; it is the exact defect class hard rule 11 exists for (a REPORTED number laundered by repetition). |
| "7× more likely to reach a decision maker if you respond within an hour" (Oldroyd/HBR, 2,241 companies) | same excerpts | `hbr.org` is egress-blocked here (measured 25 Aug 2026, `EGRESS_BLOCKED` at the proxy). Not read ⇒ not stated. |
| "The average B2B company takes 42 hours to respond to a lead" | same excerpts | Unsourced in every excerpt; also a US B2B figure being aimed at Indian SMBs. |
| "85% of organisations are automating top-of-funnel work" | G2 research excerpt | Page not read; a percentage on a landing page is a claim, and the page bans stray percentages outside the calculator for this reason. |
| "One SDR manages 400–500 enriched leads a month" | search excerpt | Unsourced, and it would have set the calculator's per-agent default — a benchmark reaching arithmetic is exactly where an unverified number does damage. |
| "Calls every enquiry **instantly**" | tempting shorthand for `record_speed_to_lead` | We measure the gap; we do not publish a figure for it, and no client is in production to have measured. `publicLanding.test.tsx` bans "instantly" page-wide. The card says the gap is **timed**, which is true and checkable. |
| Any conversion-rate lift from qualification | the whole genre | We have never measured one. The page instead gives the buyer arithmetic they drive themselves — the existing house style of this calculator, and stronger than a borrowed statistic because they cannot dispute their own inputs. |

`publicLanding.test.tsx::"the qualification-layer section"` enforces the absence: no
percentages, no `Nx` multiples, no "study/research/survey/on average", no
"more conversions". A future session cannot quietly reinstate one.

## 7. What did NOT change

- **No price moved.** `CALEVATE_PAISE_PER_MIN` is still 500 paise, still tracking
  `self_serve_inr_per_min`. TRD §10 is untouched. This is a marketing surface only.
- **The head-to-head comparison survives** and remains the default, because it is the
  honest one at the calculator's default two-minute call.
- **The page's no-price rule** is unchanged: prices appear only inside
  `[data-roi-calculator]`, still scoped by `textOutsideCalculator`.
- **The honest-verdict doctrine** is unchanged and now covers both modes from one set of
  branches (`baseline` / `delta` / `close`), so neither mode can grow a friendlier rule
  than the other.
