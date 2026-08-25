# Per-minute cost-reduction evaluation — where the money is and what actually moves it

**Lane: cost. Written 25 August 2026 (UTC).** Commission: produce a grounded evaluation of
how to reduce Calevate's cost per talk-minute, component by component, weighed against the
hard constraints (India-only, Telugu-first, Sarvam speech per D-36, Bolna engine per D-31,
Azure OpenAI `eastus2` per D-449/D-456). This lane wrote **one file, this one**, and touched
no code, no other doc, and did not run git.

**The discipline applied throughout is hard rule 11.** A cheaper option that cannot speak
Telugu, or that reverses a founder decision, is flagged as such and is not counted as a
saving. Every outside-world number carries its evidence class and its source at the point of
use. Two vendor hosts I would have read first-hand are egress-blocked from this container and
were **re-measured blocked this session** (`docs.sarvam.ai`, `azure.microsoft.com` — both
returned `EGRESS_BLOCKED` on WebFetch on 25 Aug 2026), so several vendor figures are carried
as the repo's own dated reads rather than as a fresh first-party read, and are labelled
accordingly. `WebSearch` is reachable but returns third-party search summaries, which are
**REPORTED**, never a first-party read — one of them this session repeated a claim the repo
has specifically found to be false (§7).

---

## Evidence-class legend (as this repo uses it)

| Class | Means |
|---|---|
| **VERIFIED-VENDOR-DOCS** | the vendor's own page/spec, read this session from the hash-pinned `bolna-findings/` mirror (page + line cited) |
| **VENDOR-PUBLISHED** | the vendor's own page, read first-hand by a **named, dated** past session but not re-readable here (host egress-blocked) |
| **VERIFIED-DASHBOARD** | a founder screenshot of a live vendor console — one panel, not a contract |
| **REPORTED** | a third-party tracker or a search summary; corroborates, never satisfies hard rule 7 |
| **ESTIMATE** | a repo-internal modelling assumption (e.g. pilot gate 12) |
| **UNKNOWN** | not verifiable from here; names what a human must confirm |

A repo-internal number (a constant, a TRD row, a prior lane) is a **CLAIM**, not evidence.
Where a figure below is our own cost model quoting itself, it says "our cost model states X
(file:line)" and is **REPORTED**, not independently verified.

---

## 0. Headline

| # | Finding | Class | Lever owner |
|---|---------|-------|-------------|
| A | Current all-in cost is **₹3.43–4.28/call-min** (our cost model, TRD §10.1); the founder-approved margin floor constant is **₹3.70** (`rates.py:609`); client price ₹5.00, `MIN_GROSS_MARGIN` 0.20. | REPORTED (our model) | — |
| B | **The engine platform fee is the single largest component** (~₹1.5–1.84/min, ~40–48% of the BYOK-legs-plus-fee total) and is the biggest lever — but its magnitude is **UNVERIFIED as a commercial term** (pilot gate 12). | ESTIMATE / VERIFIED-DASHBOARD | **founder** (invoice + negotiation) |
| C | **TTS is the largest BYOK leg** (₹1.08–1.62/min). The one verified saving on it is **Bulbul v2** — half the per-char rate, and the ONLY Sarvam TTS on Bolna's bundled preferred list (`bulbul:v2` is listed, `bulbul:v3` is NOT). | VERIFIED-VENDOR-DOCS | **founder** (reverses the single-tier voice decision) |
| D | **No Western TTS is a saving**: Deepgram Aura cannot speak Telugu at all; Cartesia Sonic can but is **not cheaper** than Sarvam; ElevenLabs Telugu-on-Flash is unconfirmed. The Telugu gate eliminates the "cheaper TTS" search. | REPORTED | — |
| E | **LLM is the smallest leg (₹0.10–0.24/min); optimising it moves pennies.** `gemini-2.5-flash-lite` is already offered and ~₹0.03–0.05/min cheaper; Sarvam-LLM is free but costs the Azure residency posture. | VERIFIED-VENDOR-DOCS / REPORTED | in-repo config (marginal) |
| F | **Volume/enterprise pricing exists** on Bolna ("$600+ top-ups get a lower effective per-minute rate"; enterprise custom rates). This is the cleanest verified path to move the biggest component. | VERIFIED-VENDOR-DOCS | **founder** (negotiation) |

---

## 1. Our current per-minute cost, from our own cost model

All figures in this section are **REPORTED** — they are what this repository's own cost model
states, not an independent verification. TRD §10 is dated "verified July 2026; re-verify
quarterly" and its §10.1 rate card is dated Aug 2026.

### 1.1 The two anchor numbers

- **Margin floor:** `SELF_SERVE_COST_FLOOR_INR_PER_MIN = Decimal("3.70")`
  (`apps/api/billing/rates.py:609`). Its own comment classes it **ESTIMATE (pilot gate 12),
  founder-approved for margin modelling** and states it is TRD §10.3's launch blend
  (≈₹3.26–3.76/min) taken at ₹3.70. It reaches no bill (hard rule 7); it is the number the
  credit-pack margin guard checks every pack against (`billing/credit_packs.py`).
- **Client price:** `self_serve_inr_per_min = Decimal("5.00")`
  (`packages/shared/src/calevate_shared/config.py:1109`), one voice quality → one rate. Its
  comment states a "founder-accepted ~22–30% gross margin against an all-in cost of roughly
  ₹2.89–4.28/call-minute (TRD §10.1)".
- **Margin invariant:** `MIN_GROSS_MARGIN = Decimal("0.20")`
  (`apps/api/billing/credit_packs.py:64`). At ₹5.00/min, 20% margin ⇒ **cost must stay
  ≤ ₹4.00/min**. At the ₹4.28 ceiling the margin is already below 20% — the ceiling is
  carried deliberately (TRD §10.1, "thin at the ceiling").

### 1.2 Cost breakdown per talk-minute (BYOK, rented engine)

Decomposition and per-leg figures from TRD §10.1's rate card (lines 1122–1170) and the
functions in `billing/rates.py`:

| # | Component | Per talk-minute | Derivation | Class |
|---|---|---|---|---|
| (a) | **Voice engine / Bolna platform fee** | **~₹1.5–1.84** (target ≤₹1.50) | flat bundled rate is $0.06/min = ₹5.52 decomposed voice-agent 3.5¢ + telephony 0.5¢ + **platform 2.0¢ ≈ ₹1.84**; BYOK removes the voice-agent 3.5¢ | **VERIFIED-DASHBOARD** (2.0¢ panel, D-423) over **VERIFIED-VENDOR-DOCS** (bundle) |
| (b) | **Speech — STT (Sarvam Saaras)** | **₹0.50** | ₹30/hr ÷ 60 (`tts`-sibling; TRD §10.1:1124); `tts_cost_inr`/`tts_rate_inr_per_char` are the TTS half | VENDOR-PUBLISHED (D-35, 11 Aug 2026) |
| (b) | **Speech — TTS (Sarvam Bulbul v3)** | **₹1.08–1.62** | ₹30/10,000 chars = ₹0.003/char (`TTS_INR_PER_10K_CHARS`, `rates.py:79`) × **360–540 chars/min** (unmeasured, pilot gate 12) | rate VENDOR-PUBLISHED; char-count **ESTIMATE** |
| (c) | **Language — Azure OpenAI `gpt-4o-mini`** | **₹0.10 (1m) / ₹0.16 (5m) / ₹0.24 (10m)** | `llm_cost_inr_per_minute(minutes, model="gpt-4o-mini")` over `REFERENCE_CALL` (`rates.py:482,492`); $0.15/$0.60 per 1M tok; grows with duration (§6.1 resends whole convo) | VERIFIED-VENDOR-DOCS (Azure card, 23 Aug 2026, `engine.py:_AZURE_PRICE_EVIDENCE`) |
| (d) | **Telephony** | **₹0.35–0.50** | Exotel/Vobiz-class estimate | **UNVERIFIED / ESTIMATE** (TRD §10.1:1160) |
| | **All-in (rented engine)** | **₹3.43–4.28** (₹4.36 at 10m; ₹4.56–4.77 on the `gpt-4.1-mini` switch) | floor = v3+Sarvam-LLM low + telephony low + fee; ceiling = v3+`gpt-4o-mini` high + telephony high + fee (TRD §10.1:1162–1171) | REPORTED (our model) |

**Two facts about (a) and (c) that decide what is worth optimising.** (i) The Bolna platform
fee is the single largest component and the only one that is neither a token rate nor a
character rate — it is a flat per-minute fee (`bolna-findings/mirror/pages/pricing/call-pricing.md`,
"A flat per-minute fee charged by Bolna on top of your provider costs"). (ii) The LLM leg
is the smallest, and `llm_cost_inr_per_minute` is not billed at all on a BYOK leg — the
engine pays and reports nothing, and the truth is an Azure invoice per subscription
(`rates.py:160–169`, TRD §10.1:1133–1143). **The LLM leg is where the least money is; the
platform fee and TTS are where the money is.**

---

## 2. Lever analysis, per component, with primary sources

### 2.1 Voice engine / Bolna platform fee — the biggest component, the biggest lever

**What it is.** VERIFIED-VENDOR-DOCS: Bolna's flat rate is "**$0.06/min (₹5.52/min)** at
standard wallet tiers" and it bundles ASR + LLM + TTS
(`bolna-findings/mirror/pages/pricing/preferred-models.md`). The bill is "the sum of five
components across three parts … Voice AI processing (STT + LLM + TTS), telephony charges, and
a Bolna platform fee" (`.../pricing/call-pricing.md`). The platform fee itself is
**observed at 2.0¢/min ≈ ₹1.84** on a founder dashboard panel (VERIFIED-DASHBOARD, D-423) —
one screen, not a commercial term; the target is ≤₹1.50 and the true fee is **pilot gate 12,
UNVERIFIED** (TRD §10 comparison table, line 1061).

**Levers, ranked:**

1. **BYOK — already adopted, and it is a real saving, not merely a residency move.**
   VERIFIED-VENDOR-DOCS: "When you bring your own keys (BYOK), Bolna does not charge for
   those components. You only pay your providers directly, plus Bolna's platform fee"
   (`call-pricing.md`, "How can I reduce my Voice AI costs?"). This deletes the bundled
   voice-agent 3.5¢/min and replaces it with our own (cheaper) Sarvam + Azure bills. D-423
   corrected an earlier lane that had called the cost case for BYOK "dead"; it is not — BYOK
   on our stack is cheaper. **This is banked, not a new lever.**

2. **Volume / annual commitment — verified to exist, magnitude UNKNOWN.**
   VERIFIED-VENDOR-DOCS: "Larger wallet top-ups (e.g. $600+) get a lower effective per-minute
   rate as a volume discount — the preferred model bundle itself is the same across tiers"
   (`preferred-models.md`, Note), and enterprise custom pricing is offered
   (`enterprise@bolna.ai`, `call-pricing.md`). **This is the cleanest verified path to move
   the single largest component**, but no committed rate is published — a founder must
   negotiate it and read the resulting invoice (pilot gate 12).

3. **Self-hosting the orchestrator — a decision reversal, break-even ~2k min/month.**
   D-31 rents the engine; TRD §10.5 is the standing plan ("build for the switch, do not build
   the switch"). Self-orchestrated cost is modelled at **≈₹2.20–3.14/min** (BYOK legs +
   telephony + ~₹0.15–0.30/min compute, no platform fee — TRD §10.1:1192–1202). The delta
   from the rented engine is "≈₹0.9–1.5/min, which is simply the platform fee". At launch
   volume, monthly floors dominate (TRD §10 D-32 rule), so this only pays back above the
   ~2k min/month break-even the doc already states. **FOUNDER / architecture decision, not an
   adapter's** — reverses D-31.

4. **Alternative engines — none beats Bolna on the Telugu + India-DLT + BYOK constraint
   set.** TRD §10's normalised comparison (lines 1059–1066): LiveKit Cloud is region-verified
   Mumbai but a **$50/mo Ship floor dominates** at launch volume (₹4.40/min @1k min); Vapi is
   "$0.05/min on top of model spend" and **US/EU only (+230–260ms hairpin)**; Cartesia Line
   is bundled ($0.06/min), **cannot host D-36's Sarvam stack** (Ink 2 / Sonic are fixed, no
   swap interface — first-party Line SDK README, `github.com/cartesia-ai/line`), and was
   **eliminated on telephony** (no DLT-registered Indian number). **No verified engine
   saving under the constraints.**

### 2.2 Speech / TTS — the largest BYOK leg, and the only real per-leg saving

**TTS is ₹1.08–1.62/min — bigger than STT + LLM combined.** So the TTS per-character rate and
the (unmeasured) character-count assumption are the two biggest per-leg levers.

**Lever 1 — Bulbul v2 (Sarvam's own value tier). The single biggest VERIFIED per-leg
saving, and it is a founder quality reversal.**

- VERIFIED-VENDOR-DOCS: Bolna's bundled preferred TTS list is
  `eleven_turbo_v2_5`, `eleven_flash_v2_5`, `eleven_v3_conversational`, **`bulbul:v2`**,
  `sonic-3`, `sonic-3.5`, `sonic-preview` (`preferred-models.md`, TTS tab). **`bulbul:v3` is
  NOT on it.** So D-36's default voice (v3) falls OFF the flat rate onto variable usage
  billing, while v2 is the one included.
- The v2 per-char rate: D-35 read the Sarvam card live on 11 Aug 2026 and found **Bulbul v2
  live at half the v3 rate** (TRD §10.1:1026–1028, carried as **REPORTED** — `sarvam.ai` is
  egress-blocked and was re-measured blocked this session). If v2 is ~₹15/10,000 chars, the
  TTS leg roughly halves to **≈₹0.54–0.81/min**, a saving of **~₹0.54–0.81/min** (~15–20% of
  all-in) — the largest single verified lever below the platform fee.
- **BUT** the single-tier voice decision (superseding D-36/D-35/D-34) *withdrew the v2 rung*
  deliberately: `TTS_INR_PER_10K_CHARS` is now one scalar and `TtsTier`/`billable_tier` were
  deleted (`rates.py:1–17,62–79`). Restoring v2 is a **founder quality reversal**, not an
  in-repo change, and the repo has already declined to make it on price alone (bolna
  evidence, Finding F). It also needs a **Telugu ear-test** at the pilot (TRD §252, §10.1) —
  a cheaper voice that degrades Telugu is not a saving.

**Lever 2 — the character-count assumption (360–540 chars/min). The biggest *uncertainty*,
not a lever we control.** TRD §10.1 states plainly this ratio "is the single biggest lever on
the TTS line and is a pilot measurement (gate 12)"; Indic scripts can run denser and push
cost toward/past the ceiling (config.py:1100–1102). **This can only move by measurement, and
it can move cost the wrong way.** Not a saving — a risk to size at the pilot.

**Lever 3 — Western TTS alternatives. Eliminated by the Telugu gate and by price.** Telugu
support is the gate, and it fails for the cheap options:

- **Deepgram Aura — cannot speak Telugu.** REPORTED (search, 25 Aug 2026): Aura/Aura-2 TTS
  supports English, Spanish, German, French, Dutch, Italian, Japanese only. (Deepgram's
  Telugu product is STT, a different service.) **Excluded — cannot meet Telugu-first.**
- **Cartesia Sonic — speaks Telugu, but is not cheaper.** REPORTED (search, 25 Aug 2026:
  `cartesia.ai/languages/telugu`, Sonic-3.6 Indic coverage incl. Telugu) and corroborated in
  repo (TRD §10 "Sonic 3 across the top 9 Indic languages incl. Telugu"). But TRD §10's
  like-for-like table prices Cartesia Sonic at **≈₹2.7–3.0/1,000 chars ≈ ₹1.0–1.6/call-min**
  vs Sarvam Bulbul v3 at **₹3.00/1,000 chars** — i.e. **the same order, not cheaper**, and
  Cartesia's own SDK cannot be run through Bolna as a Sarvam substitute anyway. **No saving.**
- **ElevenLabs Flash/Turbo v2.5 — Telugu on the fast models is unconfirmed.** REPORTED
  (search, 25 Aug 2026): Flash v2.5 lists 32 languages and Telugu is not clearly among them;
  a Telugu marketing page exists but may route to Multilingual v2, not Flash. And ElevenLabs
  is a premium per-char vendor — no evidence it undercuts Sarvam. **Not a verified saving.**

**Honest conclusion on TTS:** the Telugu-first constraint (D-36) means the only credible TTS
saving is *within Sarvam* (the v2 value tier), which is a founder quality reversal, not a
vendor swap. Every Western swap either can't speak Telugu, isn't cheaper, or can't run on the
engine.

### 2.3 Speech / STT — already cheap, no worthwhile lever

STT is ₹0.50/min (Saaras, ₹30/hr). `saaras:v2.5`/`saaras:v4` are on Bolna's bundled preferred
ASR list (VERIFIED-VENDOR-DOCS, `preferred-models.md`); `saaras:v3` is not, so a version pin
decides bundling (bolna evidence, Finding F). Deepgram `nova-2`/`nova-3` are also bundled and
support Telugu STT, but D-36 chose Saaras for Telugu **code-mixed** quality — the deciding
factor, not price, and the delta is at most a few paise/min. **No worthwhile lever.**

### 2.4 LLM — the smallest leg; optimising it moves pennies

The LLM leg is ₹0.10–0.24/min on the default and is **not metered by the engine** on BYOK.
Verified prices (per 1M tokens):

- `gpt-4o-mini` (default): $0.15 in / $0.60 out (VERIFIED-VENDOR-DOCS, `engine.py`
  `_AZURE_PRICE_EVIDENCE`, azure.microsoft.com East US 2 card read 23 Aug 2026; the mandated
  **Regional Standard** deployment is +10% ⇒ $0.165/$0.66, the residency cost, paid on
  purpose — `rates.py:139–143`).
- `gemini-2.5-flash-lite`: $0.10 in / $0.40 out — **cheaper than the default on both legs**,
  already an offered leg, safe on a phone call (the engine sends `thinking_budget=0`, which
  Google documents works on 2.5 flash/-lite; **Gemini 3.x is the trap** — "do not support
  full thinking-off", can return dead air, so every `gemini-3.*` is `selectable=False`,
  CLAUDE.md + `engine.py:833–850`). Class: repo carries it **verified=False** (ai.google.dev
  egress-blocked) but corroborated by a reachable Vertex page (multi-provider lane §2) and by
  search this session (REPORTED). Saving vs default: **~₹0.03–0.05/min** at five minutes.
- Sarvam 105B: **free per token** — the cheapest possible LLM. But an in-call return needs
  `provider: "custom"` (credential path retired gate 16c put in doubt) and it **loses the
  Azure residency/DPA posture** the whole D-410/D-449 chain exists to hold. Saving ~₹0.16/min,
  bought at the cost of the residency argument. **Not recommended as a cost move.**
- **Excluded on safety, not price:** `gpt-5.x` models reject `temperature: 0.1` at agent
  create (the GPT-5 trap, `ModelConfig.llm_traps`); a "cheaper" model that 500s on call setup
  is not a saving. `gpt-5.4-mini` is also the *dearest* thing offered ($0.75/$4.50), so this
  is moot for cost.

**LLM conclusion:** the only free-and-safe LLM lever is defaulting agents whose plan allows
it to `gemini-2.5-flash-lite`, saving pennies per minute. It is real but small, and the
surcharge already floors at zero for it (`is_surchargeable_llm_model`, `rates.py:705`) so it
cannot be mis-billed. **Do not chase the LLM leg for savings — it is the smallest.**

---

## 3. Synthesis — achievable floors and what each unlocks

The all-in floor is dominated by (a) the platform fee and (b) the TTS leg. Holding STT
₹0.50, LLM ₹0.16 (5-min `gpt-4o-mini`), telephony ₹0.40:

| Scenario | Platform fee | TTS | All-in (5-min) | Margin @ ₹5.00 | Notes |
|---|---|---|---|---|---|
| **Today (as modelled)** | ₹1.84 (observed) | ₹1.35 (v3, mid) | **≈₹4.25** | ~15% | at/near the ceiling; below the 20% invariant |
| Today at the **target** fee | ₹1.50 | ₹1.35 (v3) | **≈₹3.91** | ~22% | the number the ₹3.70 floor and ₹5.00 price were struck on |
| **+ Bulbul v2** (founder reversal) | ₹1.50 | ₹0.68 (v2, mid) | **≈₹3.24** | ~35% | biggest per-leg saving; needs Telugu ear-test |
| **+ enterprise fee** (negotiated) | ₹1.00 (illustrative, UNKNOWN) | ₹1.35 (v3) | **≈₹3.41** | ~32% | magnitude unverified — founder negotiation |
| **+ v2 + enterprise fee** | ₹1.00 (UNKNOWN) | ₹0.68 (v2) | **≈₹2.74** | ~45% | both founder actions stacked |
| **Self-orchestrated** (phase 2) | ₹0 + ~₹0.25 compute | ₹1.35 (v3) | **≈₹2.66** | ~47% | reverses D-31; break-even ~2k min/mo |

Illustrative fee figures marked UNKNOWN are placeholders to show *sensitivity*, not claims —
the ₹1.00 enterprise fee is not a quoted rate.

**What this unlocks for pricing.** The ₹3.70 floor constant (`rates.py:609`) and the
`MIN_GROSS_MARGIN` 0.20 invariant together cap any committed-bundle rate at **cost ÷ 0.80**.
Two verified-or-founder levers move the floor:

- If the platform fee lands at its ≤₹1.50 **target**, the floor is already ~₹3.91 all-in and
  the ₹3.70 constant is slightly optimistic — the credit-pack guard's own sensitivity note
  (`rates.py:604–608`) says exactly this: at the top of the band the deepest packs dip under
  20% and must come down. **No repricing possible until the fee is a real invoice number.**
- If **Bulbul v2** returns, the floor drops to **≈₹3.24/min** even at the target fee, which
  would let the ₹3.70 constant fall to ~₹3.30 and support a committed-bundle rate around
  **₹4.10–4.30/min** at a healthy >20% margin (v2's Telugu quality permitting).
- The two stacked (v2 + negotiated fee) reach **≈₹2.74/min**, which is where an aggressive
  committed rate near **₹3.50/min** becomes margin-safe.

**The lever ranking is therefore: (1) platform fee, by size; (2) TTS→v2, by verified
magnitude; (3) LLM, by pennies.** But by *what a session can act on now*, the order inverts —
see §4.

---

## 4. Ranked recommendation

**Do now (in-repo, no external blocker):** essentially nothing on cost is safely in-repo. The
one marginal in-repo move is defaulting eligible agents to `gemini-2.5-flash-lite` (saves
~₹0.03–0.05/min, safe, already offerable, surcharge floors at zero) — but it is pennies on the
smallest leg and is a product/plan choice, not a pure cost fix. **The honest finding is that
the two real levers are both founder/commercial, not code.** Do not manufacture an in-repo
"saving" by touching the ₹3.70 floor or the margin invariant — that is forbidden
(`rates.py` docstring; editing the coverage/margin baselines is a hard-rule violation).

**Needs a founder / commercial action (named):**

1. **Read the Bolna invoice and negotiate the platform fee** (pilot gate 12). The fee is the
   largest component and the only VERIFIED-VENDOR-DOCS lever with published upside (volume +
   enterprise tiers). Closes: a Bolna account with funds + a signed volume/enterprise term.
2. **Decide the TTS rung: Bulbul v2 vs v3** (reverses the single-tier voice decision), gated
   on a **Telugu ear-test at the pilot**. Biggest per-leg saving (~₹0.54–0.81/min). Closes: a
   founder quality decision + pilot gate 12's character-count and quality measurement.
3. **Confirm the Azure Regional-Standard premium and the telephony rate** against real
   invoices (gate 20c; telephony is UNVERIFIED). These size, not reduce, the cost.

**Phase-2 / architecture (reverses D-31):** self-orchestrate to drop the platform fee once
volume clears ~2k min/month (TRD §10.5). Not now; not a code task this session.

---

## 5. Constraints that killed candidate "savings" (so they aren't re-proposed)

- **Deepgram Aura TTS** — no Telugu. Fails Telugu-first (D-36).
- **Cartesia Sonic TTS** — Telugu yes, but same-order price as Sarvam and cannot run as a
  Sarvam substitute on Bolna; Cartesia Line eliminated on Indian DLT telephony.
- **ElevenLabs Flash/Turbo** — Telugu-on-fast-model unconfirmed; premium vendor, no price
  advantage.
- **OpenAI direct / `gpt-5.x`** — dearer and/or GPT-5 temperature trap; no Indian inference
  (D-448/D-449 — that ground is now spent, but price and safety still exclude them for cost).
- **Sarvam-LLM in-call** — free, but forfeits the Azure residency/DPA posture and uses an
  unverified `custom` credential path.
- **Alternative engines (Vapi/LiveKit/Cartesia Line/Retell)** — each fails on at least one of
  latency-to-India, Indian DLT telephony, monthly floor at launch volume, or inability to
  host the Sarvam stack (TRD §10 comparison table).

---

## 6. What I could NOT verify, and why

- **Sarvam's current published rates first-hand.** `docs.sarvam.ai` and `sarvam.ai` are
  egress-blocked and were **re-measured blocked this session** (WebFetch → `EGRESS_BLOCKED`,
  25 Aug 2026). The ₹30/10,000-char v3 rate and the "v2 = half v3" figure are carried from
  D-35's dated live read (11 Aug 2026, VENDOR-PUBLISHED) and corroborated only by third-party
  search (REPORTED). **Closing this needs a first-party read or a Sarvam invoice.** In
  particular, **v2's exact current rate is unverified** — the ~50% saving in §2.2 assumes v2
  is ~₹15/10,000 and must be confirmed before it is priced.
- **Azure's current `gpt-4o-mini` / `gpt-4.1-mini` list and the Regional-Standard premium.**
  `azure.microsoft.com` is egress-blocked (re-measured blocked this session). The
  $0.15/$0.60 and +10% figures are the repo's own dated read (23 Aug 2026). A search summary
  this session returned an unreliable, contradictory "regional $1.21/$4.84" figure — **not
  used**. The premium is confirmed against a real invoice at gate 20c, not here.
- **The Bolna platform fee as a commercial term.** Only VERIFIED-DASHBOARD (one 2.0¢/min
  panel) + the ≤₹1.50 target exist; the committed/enterprise rate is UNKNOWN pending a
  founder negotiation and invoice (gate 12).
- **Telephony rate.** ₹0.35–0.50/min is an UNVERIFIED estimate (TRD §10.1); needs a real
  Exotel/Vobiz invoice.
- **The TTS character count per Telugu minute.** 360–540 chars/min is unmeasured (pilot gate
  12) and is the single biggest swing on the largest BYOK leg — it can move cost the wrong
  way. Needs the pilot.

---

## 7. A hard-rule-11 note this session actually hit

My web search for Gemini pricing returned a confident summary stating *"Google is retiring
Gemini 2.5 Flash-Lite on October 16, 2026."* **CLAUDE.md records that exact claim as WRONG**
— the 16 Oct 2026 date belonged to *preview snapshots*, the GA ids carry no announced
shutdown, and it propagated out of this repo's own `model_lifecycle.py` as if it were fact
(hard rule 11's founding example; `GEMINI_DEFAULT_LLM_RETIRES` and its CI test were deleted).
So the search summary is repeating the retracted claim. It is recorded here as **REPORTED and
specifically contradicted by the repo's own correction**, and is **not** treated as a reason
to avoid `gemini-2.5-flash-lite` on cost grounds. This is the trap the rule exists for: a
plausible date, authoritative-sounding, wrong.

---

## 8. Sources

**VERIFIED-VENDOR-DOCS (hash-pinned mirror, read this session):**
`bolna-findings/mirror/pages/pricing/preferred-models.md` (flat $0.06/min = ₹5.52; volume
discount at $600+; bundled model lists incl. `bulbul:v2` not `bulbul:v3`);
`bolna-findings/mirror/pages/pricing/call-pricing.md` (five-component bill; BYOK removes the
component charge; flat per-minute platform fee).

**Repo cost model / decisions (REPORTED — repo-internal claims):**
`apps/api/billing/rates.py` (`:79`, `:139–169`, `:482`, `:492`, `:567–586`, `:609`);
`apps/api/billing/credit_packs.py:64`;
`packages/shared/src/calevate_shared/config.py:1109`, `:1100–1102`;
`packages/shared/src/calevate_shared/engine.py` (`_AZURE_PRICE_EVIDENCE` ~`:1040–1050`,
`LLM_MODELS` `:1151+`, Gemini traps `:833–850`);
`docs/TRD.md` §10 / §10.1 / §10.5 (lines 972–1202);
`docs/evidence/bolna-executions-cost.md` (Findings E/F, D-423 decomposition);
`docs/evidence/llm-multi-provider-2026-08.md` (Gemini Developer-API price corroboration).

**REPORTED (third-party search, 25 Aug 2026):**
- [Sarvam API pricing (search summary)](https://docs.sarvam.ai/api-reference-docs/pricing) — ₹30/10,000 chars Bulbul v3 (host egress-blocked; not read first-hand)
- [Deepgram Aura TTS models](https://developers.deepgram.com/docs/tts-models) — Aura languages exclude Telugu
- [Cartesia Telugu TTS](https://www.cartesia.ai/languages/telugu) — Sonic supports Telugu
- [ElevenLabs supported languages](https://help.elevenlabs.io/hc/en-us/articles/13313366263441-What-languages-do-you-support) — Flash v2.5 Telugu unconfirmed
- [pricepertoken — Gemini 2.5 Flash-Lite](https://pricepertoken.com/pricing-page/model/google-gemini-2.5-flash-lite) — $0.10/$0.40 per 1M tok (and the retracted retirement claim, §7)
- [Azure OpenAI pricing](https://azure.microsoft.com/en-us/pricing/details/azure-openai/) — host egress-blocked; search figure unreliable, not used

**Egress-blocked this session (re-measured 25 Aug 2026):** `docs.sarvam.ai`,
`azure.microsoft.com`, `www.cartesia.ai`, `developers.deepgram.com`, `help.elevenlabs.io` —
all returned `EGRESS_BLOCKED` on WebFetch, so no vendor pricing/docs page was read first-hand
this session; the hash-pinned Bolna mirror is the sole first-party vendor source available
here.
