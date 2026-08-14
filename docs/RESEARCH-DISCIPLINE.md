# Calevate — Research & Evaluation Discipline

How vendor/competitor claims get handled here, and the mistakes already made so they
aren't repeated. Exported from the local rememory store (Aug 2026) so the lessons travel
with the repo instead of living on one machine.

**Why this exists:** we were burned once by a vendor that looked good on paper — ThinnestAI
had a real product, zero real customers, no SLA, and an unresponsive team (retired in D-31).
Decisions here commit a 2-person company's only engineering capacity, so **an unverified
number presented as fact is worse than no number.**

---

## 1. The core rules

**R1 — Verify against first-party sources, and mark verified vs inferred.**
Every number in the docs should be traceable to a vendor's own page, their shipped code, or
our own measurement. Where something is inferred, say so *in the same sentence*.

**R2 — "No claims survived verification" is a coverage gap in the run, NOT a finding about
the option.** If a research pass returns nothing for a candidate, that means the pass
under-covered it. Say so explicitly and go verify directly before publishing any comparison.

**R3 — Vendor latency numbers are marketing until measured on real PSTN.** Bolna publishes an
undefined "<300ms"; a third-party comparison inflated that to "sub-600ms end-to-end" with no
source. Never plan against a vendor figure. Our own p50/p95 come from pilot gate 4.

**R4 — Strip out variables that are identical across options.** Because we are BYOK, Sarvam
rates, Exotel rates, the model-migration cost, and BYOK model *quality* (including Telugu
accuracy) are **not decision variables** — they are constants. Rank only on what actually
differs. *(One exception: turn detection/endpointing is an orchestration-layer property that
BYOK models do not fix.)*

**R5 — Compare like with like.** Vendors price at four distinct layers and the same-looking
number means different things at each:

| Layer | Example |
|---|---|
| Model (STT/TTS/LLM) | Cartesia Sonic ≈ ₹2.7–3.0 / 1k chars |
| Orchestration, **bundled** (vendor's models included) | Cartesia Line $0.06/min · Bolna bundled 6.00¢ |
| Orchestration, **BYOK** (on top of your model spend) | Bolna BYOK (observed 2¢/min) · Vapi $0.05/min |
| Self-orchestrated | ₹0 fee + compute |

Mixing layers produces a **~4× error**. This is not hypothetical — it happened in TRD §10
(a model price was compared against a platform price) and had to be corrected.

**R6 — Never compare on headline per-minute rates.** Always compute **effective ₹/min at a
stated monthly volume**, with fixed monthly costs amortised in. Monthly floors dominate at
launch volume. This applies to **our own marketing copy too**, not just to competitors — we
criticised Outpero for advertising "from ₹3.5/min" while omitting their ₹1,899/mo fee, so we
do not get to do the same thing.

**R7 — An inference stated confidently in conversation is the same error as stating it in a
doc.** Hedging in the artifact and dropping the hedge in chat is not a defence. If it isn't
verified, say so in **both** places.

---

## 2. Mistakes actually made (and corrected)

Recorded because each was caught by the founder, not by me.

| # | The mistake | The correction |
|---|---|---|
| 1 | Reported "zero Bolna claims survived verification" as a footnote, implying weakness | It was a **coverage gap in that research run**. A direct fetch of bolna.ai afterwards surfaced 5 named case studies with metrics that changed the evidence base. → **R2** |
| 2 | Injected "Pipecat is the fallback engine" across seven docs | **No fallback engine is designated.** Engine risk is carried by the VoiceEngine adapter contract + conformance suite. Pipecat appears only in D-02's phase-2 trajectory. Founder correction — do not re-add. |
| 3 | Treated Telugu quality as a platform differentiator | Under BYOK the models are identical across platforms, so it isn't one — **except** turn detection, which is orchestration-layer. → **R4** |
| 4 | Claimed "Outpero self-orchestrates and pays no platform fee" as fact | **Retracted.** It was inferred from their security page + mid-call failover. Their TTS trio (Sarvam/Smallest/Cartesia) exactly matches Bolna's supported-provider list, which is equally consistent with them *being a customer*. Their orchestration layer is **UNKNOWN**. → **R7** |
| 5 | Guessed their premium tier was a cloned Sarvam voice | Their shipped JS says otherwise: `value:sarvam_per_min`, `standard:smallest_per_min`, `premium:cartesia_per_min`. **Sarvam is their cheapest tier.** Read the code before theorising. |
| 6 | Compared Cartesia Line's $0.06 against Vapi's $0.05 as equivalent | Vapi's is an orchestration tax *on top of* model spend; Line's bundles models. **"Appears to" resolved to CONFIRMED (Aug 2026, D-88)**: Line's LLM is BYOK via LiteLLM but Ink 2 (STT) and Sonic 3.5 (TTS) have no swap interface — from Cartesia's own Line SDK README, which is first-party where their docs site is unreachable from our build environment. The lesson survives the confirmation: the error was comparing the numbers before establishing the layer. → **R5** |
| 7 | Amortised Outpero's monthly fee into their effective rate but left **our** fixed costs outside ours | Applied the same rule to ourselves (TRD §10.2) — and it revealed that D-11's ₹6–8/min overage is below true cost under ~5,000 platform min/month. → **R6** |
| 8 | Recorded "Bulbul v2 is discontinued" (D-20) | Wrong — that came from *ThinnestAI's* model listing, not Sarvam's. v2 is live at **half** the v3 price (D-35). Read the vendor's own rate card, not a reseller's. |

---

## 3. Ranking method that worked

When choosing a platform, rank on categories that actually differ — orchestration cost at
launch volume; cost at scale; concurrency headroom and cliff behaviour; India region/latency
physics; what ships vs what we build (in engineering weeks); vendor risk; lock-in/exit cost;
compliance and India ops; data integrity; time to client #1.

**Weighted for a 2-person team pre-client-#1, "time to client #1" and "what ships" outrank
per-minute price.** That is why D-31 selected a rented engine despite a self-orchestrated
stack being ~₹0.9–1.5/min cheaper.

---

## 4. Due-diligence bar for any vendor

Derived from what ThinnestAI failed and Bolna passed:

- **Verifiable customers** — named, with metrics, ideally first-party *and* press
- **Responsiveness** — open two threads (technical + commercial) and time the replies. *This
  is the gate ThinnestAI failed; a good product with unresponsive people is the same trap.*
- **Commercials in writing** — the actual number, not a range in a sales call
- **SLA vs Terms** — check the contract against the marketing. Outpero advertises "99.9%
  Uptime SLA" in three places while Terms §9 disclaims any availability guarantee and §11
  caps liability at 3 months of fees — the same cap that helped disqualify ThinnestAI
- **Exit terms** — data export, deletion with proof, notice period
- **Residency** — where compute *and* storage actually sit

**Applies to us too.** We currently have zero clients. Our "no verifiable customers" critique
of a competitor is only usable once client #1 plus published QA reports exist.

---

## 5. Practical notes

- **Read the shipped bundle.** A competitor's JS revealed their exact tier→vendor pricing map
  when marketing and docs did not. Their legal pages deliberately withhold sub-processor names.
- **Know what a source can and cannot prove.** A client bundle can never reveal a voice
  platform's orchestrator — calls run over PSTN, never through the browser.
- **Watch for self-contradiction.** Outpero's docs say 10 retry attempts; their product UI
  says 3. Their pricing page says a 20-credit signup bonus; their docs say 100. Cite neither
  without re-checking.
- **Some SPAs serve stale text to extractors.** docs.outpero.com returns the previous page's
  body to text extraction — screenshots were required. Verify your tool actually read what
  you think it read.
