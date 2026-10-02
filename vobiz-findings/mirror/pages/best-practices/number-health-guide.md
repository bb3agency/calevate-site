> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Number Health Guide

> Keep your caller-ID (DID) numbers healthy for high-volume outbound voice - pickup/answer rate, pacing & CPS, repeat-dial limits, ring time, inbound ratio, a day-by-day warm-up schedule, and the anti-patterns that get numbers marked Spam Likely. Based on ~9 months of real call records.

*Keeping your caller-ID (DID) numbers healthy for outbound voice campaigns.*

Based on \~9 months of real call-detail records across thousands of high-volume numbers (79-, 80-, 22- and 11-series). All example numbers are anonymized.

<Info>
  **Monitor these metrics programmatically** with the [Number Health Dashboard API](/docs/account-phone-number/get-number-health) - it returns each number's `status`, spam flag, answer rate, and call metrics (total/answered calls, answer rate, minutes, avg duration) with a daily time series.
</Info>

## 1. What "Number Health" Means - and Why It Matters

Every number you dial from (your DID / caller-ID) builds a **reputation**. A **healthy** number reliably reaches real people and holds a normal answer rate for months. An **unhealthy** number gets silently throttled, sent to voicemail, or stamped **"Spam Likely"** on the screen - and once that happens, almost nobody answers. The number is effectively dead, even though you can still dial from it.

### The two ways you get marked spam

There are exactly two, and they are very different:

1. **A human reports you.** Someone didn't ask for the call, doesn't recognise the number, and taps *"Report Spam."* This is about **permission and relevance** - calling people who never opted in, for things they don't care about.

2. **The operator's algorithm flags you - and this one hurts far more.** Long before any human complains, the **carrier's own detection system** is watching *how* you dial. It isn't reading your script; it's asking one question: **does this number behave like a person, or like a machine?** A machine gives itself away instantly - **thousands of calls in a few seconds**, zero-to-full-volume on day one, **no warm-up, no history**. The algorithm flags that pattern *preemptively*, and it kills **far more numbers** than human reports ever will.

**This guide is about beating the second one.** The whole strategy reduces to a single principle:

<Tip>
  **A high number reputation is about mimicking human behaviour.** Warm up like a human, pace like a human, move on like a human, show up at human hours, and build a reputation like a human.
</Tip>

**Why it matters commercially:** a burned DID wastes spend (you pay to dial numbers nobody answers), decays your list, and can taint your wider sending reputation. Warming and resting numbers *before* they burn is far cheaper than rehabilitating a flagged one.

***

## 2. The Core Health Metrics - every factor, and what "good" looks like

### 2.1 Pickup rate (answer rate) - your #1 gate

**What it is:** answered outbound calls ÷ total outbound calls.
**Why it matters:** it's *the* outcome that tracks health. Healthy numbers hold their answer rate for months; burned ones collapse to \~5% while still dialing. A `< 15%` reading catches essentially every bad number.
**How much to expect (be realistic):**

* On a decent, consented list, a healthy number holds **\~25–35%** (our fleet median ≈ 27%).
* Genuinely good numbers reach **40–53%** - but that's rare (under 3% of numbers clear 50%).
* **≥ 25–30% = green. 15–25% = watch. `< 15%` = burned, pause it.**

<Note>
  **Reality check:** "green" means a *durable* \~30%, not 70%. If someone promises 70% on cold bulk dialing, be sceptical.
</Note>

### 2.2 Average call duration (total, including unanswered)

**What it is:** average length of *all* call attempts (answered + unanswered).
**Why it matters:** it's the duration metric that actually **correlates with health**. A *falling* total duration means more calls are ringing out or being rejected - an early sign the list or number is going bad.
**Benchmark:** **≥ 35s green · 25–35s watch · `< 25s` red** (≈ 0s means the calls never connect at all - an unreachable/blocked list).

### 2.3 Answered talk time - important to understand, but NOT a health KPI

**What it is:** average length of *answered* calls only (real conversations).
**Why it's here:** so you **stop using it as a reputation signal.** It reflects your *script and list-fit* (a business metric), not your carrier standing. In the data it's \~identical between healthy and burned numbers (\~32–36s) and has near-zero correlation with pickup. A number can hold great 40-second conversations while its reputation quietly collapses.
**Use it for:** measuring agent/script performance and list quality - **not** for deciding if a number is healthy. Do not put it in your health formula.

### 2.4 Ring time - and how to *increase* it

**What it is:** how long the call rings before it's answered or dropped.
**Why it matters (counter-intuitive):** **short ring is the danger sign, not long ring.** Numbers with sub-5-second average ring have the *worst* pickup - it means callees (or their spam-filters) are rejecting/auto-dropping you instantly, a classic spam-flag fingerprint. A healthy 20–30s ring is normal.
**Benchmark:** **≥ 20s green · 5–20s watch · `< 5s` red.**
**How to increase ring time (fix short ring):**

* **Set your ring timeout to \~25–30 seconds** - give the callee time to actually pick up; don't hang up at 5–8s.
* **Turn off aggressive answering-machine detection (AMD)** or tune it - over-eager AMD clips calls early and manufactures fake "short rings."
* **Stop premature auto-hangups** in your dialer.
* If ring time is *already* short across the board, that's usually the **list/number being rejected**, not a config issue - pause and investigate.

### 2.5 Pacing - the two dials you must control

This is where most numbers live or die. Pacing has **two** components:

**(a) Calls per day (per number).** How much one number dials in a day.

**(b) Time between calls (the dial rate / CPS).** How fast you fire them - the single loudest "machine" signal.

**Pace-value guide - good / acceptable / bad:**

| Dial rate (gap between calls) | ≈ CPS | Verdict | What happens |
| - | - | - | - |
| 1 call every **60–90s** | \~0.01 | 🟢 **Excellent** | Reads fully human. The healthiest numbers open here. |
| 1 call every **2–15s** (`< 1/sec`) | `< 1` | 🟢 **Good** | Safe for steady-state on any list. |
| **1–5 calls/sec** | 1–5 | 🟡 **Acceptable only on a large, *fresh* list** | Survivable short-term, but shortens the number's life. |
| **5–10+ calls/sec** | `> 5` | 🔴 **Bad** | Burst signature. Fast carrier flagging. A number that hit \~10/sec was **dead in 4 days.** |

| Calls per day (per number) | Verdict |
| - | - |
| \~500–1,500/day | 🟢 **Healthy** (fleet median ≈ 1,000) |
| 1,500–3,000/day | 🟡 **Acceptable ceiling** |
| 3,000–10,000/day | 🟡 **Risky** - spread across more numbers |
| `> 40,000/day` | 🔴 **Burnout** - dies in days |

**Practical translation:** **1,000 calls spread across an 8-hour business day = \~2 calls a minute, roughly one every 30 seconds.** That's the sweet spot - high daily volume, but a human-looking rate.

### 2.6 Repeat-dial rate - your #1 *leading* indicator

**What it is:** total calls ÷ distinct numbers dialed (how many times, on average, you hit the same person).
**Why it matters:** it's the **strongest single predictor** of a number going bad. Healthy numbers dial each contact **\~1–2.5×** and move on; numbers that get flagged hammer a small list **20–55×**. Low-repeat numbers hold \~35% pickup; high-repeat ones fall to \~21% and keep dropping.
**Benchmark:** **1.0–2.5 green · 3–5 watch · ≥ 6 red.**
**Control:** dedupe your list, cap per-contact retries at **\~3**, and **never keep re-dialing a number that doesn't answer.**

### 2.7 Inbound-to-outbound ratio - the trust signal most people ignore

**What it is:** the share of the number's traffic that is *inbound* (calls it receives) vs *outbound* (calls it makes).
**Why it matters:** a number that *only ever dials out and never receives a call* looks like a pure machine to carriers. A number that also **receives** calls - return calls, callbacks, genuine two-way traffic - looks like a real business line. Two-way numbers earn more trust and hold their reputation longer.
**Recommendation: aim for roughly a 10–15% inbound-to-outbound ratio.** In practice that means **enabling inbound routing** on your dialing DIDs so people can call back, publishing the number where customers will use it, and welcoming return calls instead of dead-ending them.

<Note>
  Most bulk dialers run their numbers 100% outbound - which is exactly why so many get flagged. Adding even 10–15% inbound is a cheap, powerful way to look human.
</Note>

### 2.8 Tenure - how long a number lasts, and what to expect

**What it is:** how many days a number has been in healthy service.
**Why it matters:** longevity is the *reward* for good behaviour, not a cause of it. A well-run number stays healthy for **months** - on the flagship 79/80 pools, run properly, **well past 180 days** (see §3 below). But **tenure alone proves nothing** - a badly-run number can survive 80+ days at 5% pickup while being commercially dead. Always read tenure **together with** the trailing-7-day pickup.
**Benchmark:** a healthy number should give you **several months of productive life** before it needs a rest. Plan to **rest and rotate before you burn**, not after.

### Master benchmark table

| Metric | 🟢 GREEN (healthy) | 🟡 YELLOW (watch) | 🔴 RED (act now) |
| - | - | - | - |
| **Pickup / answer rate** | ≥ 25–30% | 15–25% | `< 15%` (burned ≈ 5%) |
| **7-day pickup vs lifetime** | ≥ 80% of lifetime | 70–80% | `< 70%` & falling |
| **Repeat-dial (calls/contact)** ⭐ | 1.0–2.5 | 3–5 | ≥ 6 (spam 20–55) |
| **Avg total duration** | ≥ 35s | 25–35s | `< 25s` (≈0s = dead list) |
| **Ring time** | ≥ 20s | 5–20s | `< 5s` (fast rejections) |
| **Calls/day per number** | \~1,000 | 3,000–10,000 | `> 40,000` |
| **Dial rate (CPS)** ⭐ | `< 1 CPS` (60–90s gap) | 1–5 CPS | `> 5 CPS` (burnout) |
| **Inbound : outbound** | \~10–15% inbound | `< 5%` inbound | 0% (pure one-way blaster) |
| **Answered talk time** | *Business metric - not a health signal* | - | - |

***

## 3. Which Numbers Should You Use? Start with the 79- and 80-series

Yes - the series you pick genuinely matters, and if you're running serious outbound we point you straight at our **79- and 80-series** numbers. They're our flagship pools: the deepest, the most established, and the best supported, dialed by more successful high-volume programs than any other series. When someone glances at their screen, a 79/80 caller-ID reads as a normal, familiar, human number - which is exactly the first impression you want.

Here's how the series stack up for serious, high-volume outbound:

| Series | Answer rate | Healthy lifespan\* (run properly) |
| - | - | - |
| **79** | \~34% | **\~201 days** |
| **80** | \~31% | **\~183 days** |
| **22** (Mumbai) | \~13% | \~120 days |
| **11** (Delhi) | \~13%† | \~90 days |

*\*Healthy lifespan = how long the number keeps answering when warmed and paced the way this guide describes.*
*†The 11-series can answer well on individual numbers but sits on a very small pool, so per-number results vary widely and it's hard to source at scale.*

**The verdict:** 79/80 answer in a strong **\~31–34%** band - but the decision isn't really made on answer rate. It's made on **lifespan, pool depth, and reliability**, and that's where 79/80 win decisively. A well-run 79/80 number keeps answering for the better part of a year, and there are plenty of them to source; the smaller pools simply can't match that at scale.

Here's the payoff - the thesis of this whole guide in one line:

<Tip>
  **Utilized properly - warmed and paced the way this guide describes - a 79- or 80-series number stays healthy for months, not weeks.** In our data, disciplined 80-series numbers have run well past 200 days and kept answering; run with the same care, 79-series numbers reach comparable multi-month lifespans (\~180–200 days when they're truly looked after).
</Tip>

The numbers that die in a fortnight aren't dying because of their prefix - they're dying because they were blasted from day one. Give a 79/80 number the human treatment - a gentle warm-up, a call every 30–90 seconds, each contact dialed once or twice, wide fresh lists, a little inbound traffic - and it becomes a durable engine that runs for the better part of a year. **Start with the proven pool (79/80), then run it like a human.** That's the combination that lasts.

***

## 4. Proven Healthy Patterns (what the winners actually did)

The long-lived, high-pickup numbers all shared the same behaviours:

1. **They ramped - they never blasted from day one.** They opened with tens-to-low-hundreds of calls and climbed over 1–2 weeks. (The best number opened its first hour at **\~6 calls, one every \~90 seconds**, every number unique, and grew \~1.1–2× a day.)
2. **They paced sustainably** - around **1,000 calls/active-day**, never tens of thousands.
3. **They spread across the day** - 6+ active hours (some 13–24), like a real room of agents, not a 20-minute burst.
4. **They dialed wide and fresh** - hundreds-to-thousands of *distinct* numbers a day, each dialed only \~1–2×.
5. **They held a durable answer rate** (\~27–39%) that stayed steady instead of spiking then collapsing.
6. **They lived long *because* of the above** - several months of healthy service (the best-run 79/80 numbers well past 200 days).

<Note>
  **Ramp caveat:** ignore the inflated pickup you'll see in a number's first few days (it's a tiny-sample artifact - 5 calls, 3 answered = "60%"). Judge health only once you're dialing hundreds a day.
</Note>

***

## 5. Anti-Patterns (what kills a number)

### 🔴 Act immediately

* **Repeat-dial hammering (≥ 6 calls/contact).** The #1 killer. One flagged number dialed just 8,717 people **346,254 times** at 3.9% pickup. Stop re-dialing non-answers.
* **Answer rate below 15%.** Below 10% the number is effectively burned. Pause it and clean the list.
* **Burst velocity (tens of thousands of calls/day, or `> 5 CPS`).** A number that opened at \~55,000 calls/hour crashed from 100% → 17% and **died in 4 days.**

### 🟡 Watch and intervene early

* **Trailing-7-day pickup falling below \~70–80% of its lifetime average** for several days - decay in progress. (One number slid 18% → 2% over 90 days this way.)
* **Total average duration dropping below \~25s** - rising rejected/unanswered calls.
* **Ring time under 5s** - fast rejections.
* **A number reused across many unrelated campaigns** - dilutes reputation.

### The two failure modes

* **Slow burn:** perfectly normal volume, quietly decaying pickup, because the list is small and over-dialed. *Volume looks fine; repeat-dial and pickup expose it.*
* **Fast blast:** explodes to huge volume from a standing start, gets flagged, dies within days.

### ❌ Do NOT rely on these as health signals

* **Answered talk time** - identical between healthy and burned numbers.
* **Long ring time** - long ring is *fine*; short ring is the danger.
* **Raw volume or tenure alone** - a number can dial "normal" volume for 90 days and still be dead.

***

## 6. Your Warm-Up Schedule - day by day, with expected results

Per number, on a decent list answering \~30%:

| Day | Calls to make | Expect answered | Goal |
| - | - | - | - |
| **Day 1** | **50** | \~15 | Exist quietly; every call to a unique number |
| **Day 2** | **100** | \~30 | Double, no more |
| **Day 3** | **250** | \~75 | Confirm the list is answering |
| **Day 4** | **500** | \~150 | Build track record |
| **Day 5** | **750** | \~225 | Approach cruising speed |
| **Day 6–7** | **1,000** | \~300 | Reach & hold steady volume |

**Week 1: \~3,650 calls → \~1,100 answered, and a number carriers now trust.**

**Steady state (week 2+):** hold \~1,000 calls/day → **\~300 pickups/day, \~9,000/month**, for several months - well past 180 days on a well-run 79/80 number = **tens of thousands of answered calls per number over its life** - then rest and reuse.

**Scaling formula:** `answered wanted per day ÷ 0.30 ÷ 1,000 = numbers you need`.
→ Want **15,000 pickups/day?** Run **\~50 warmed numbers**, not one screaming one.

***

## 7. The Client Checklist - DO and DON'T

### ✅ DO

* **Warm up.** Start at \~50 calls day 1; grow \~1.5–2× daily to \~1,000/day over 1–2 weeks.
* **Pace under 1 CPS** on new numbers - one call every 30–90 seconds. Never exceed 5 CPS.
* **Cap daily volume \~1,000/number.** Need more? Add numbers, not intensity.
* **Keep repeat-dial at 1–2×.** Dedupe lists; cap per-contact retries at 3.
* **Dial wide and fresh** - hundreds-to-thousands of distinct numbers, spread over 6+ hours.
* **Stay in business hours.**
* **Enable inbound** on your DIDs - aim for \~10–15% inbound-to-outbound; two-way numbers look human.
* **Set ring timeout to 25–30s** and tune AMD so you don't manufacture short rings.
* **Watch the 7-day pickup trend** - the earliest warning sign.
* **Dedicate each number to one use-case**, and let its good history compound.
* **Rest and rotate *before* a number burns**; keep replacements warming in the background.

### ❌ DON'T

* **Don't blast from day one** - no thousands of calls on days 1–3.
* **Don't exceed \~5 CPS** - burst velocity is the fastest way to die.
* **Don't re-dial the same people 5, 10, 40 times.**
* **Don't run one number at tens of thousands of calls/day.**
* **Don't call at odd hours.**
* **Don't run pure 100%-outbound** with zero inbound if you can avoid it.
* **Don't chase call duration** as a health metric - it won't warn you.
* **Don't rotate numbers to dodge flags** - carriers detect the swapping and penalize it. Fix the *behaviour* (pacing + list), not the number.
* **Don't judge a fresh number by its first few days' pickup** - it's a tiny-sample mirage.
* **Don't keep pushing volume through a number showing 2+ red flags** - pause and clean.

### 🎛️ Auto-guardrail (for your ops team)

Auto-quarantine any number tripping **≥ 2** of: `pickup < 15%` · `repeat-dial ≥ 6` · `7-day pickup < 0.8× lifetime` · `total duration < 25s`. Auto-suspend at **≥ 3**. You can pull these signals per number from the [Number Health Dashboard API](/docs/account-phone-number/get-number-health).

***

## The one line to remember

<Tip>
  **Making calls is easy. Making *millions* of calls without getting marked spam is a craft - and the craft is to dial like a human at scale.** Warm up, pace yourself, move on, show up at human hours, and let each number build an honest reputation. Do that, and your numbers don't just survive the algorithms - they earn the pickup.
</Tip>

*All behavioural thresholds are drawn from \~9 months of real call records across the 79/80/22/11-series fleets. Health is driven by dial behaviour - pacing, repeat-dial restraint, destination spread, and two-way traffic - not by how long your answered calls last.*


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.