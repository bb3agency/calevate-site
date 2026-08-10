# Bolna Pilot Scorecard — EVIDENCE ARTIFACT (template; fill during the pilot)

Gates and criteria: OPERATIONS.md §2. Decisions: D-31 (Bolna primary), D-32 (evaluation
doctrine). This file is the committed evidence artifact per ENGINEERING-PRACTICES §2
("evidence artifacts": DR drills, stress runs and vendor scorecards live in the repo).

| Field | Value |
|---|---|
| Run by | |
| Dates | |
| Bolna plan / credits used | |
| Sarvam account tier | |
| Telephony provider + number | |
| Spend (₹) | |

**Verdict: ☐ PASS (D-31 gate closed) ☐ FAIL (engine decision reopens — no fallback engine is designated)**

---

## Hard gates

| # | Gate | Result | Evidence (paste payloads / file refs / quotes) |
|---|---|---|---|
| 1 | Webhook trust — deliveries only from 13.203.39.153, allowlist rejects others, execution_id dedupe, payload == Get Execution | ☐ pass ☐ fail | |
| 2 | Full API provisioning — agent → prompt → number → `POST /call` → `GET /executions/{id}`; `user_data` round-trip; `scheduled_at` | ☐ pass ☐ fail | |
| 3 | Telugu quality (BYOK Saaras V3 + Bulbul V3) — names/numbers ≥90%, code-mixed OK, **V3 selectable** | ☐ pass ☐ fail | |
| 4 | Real-call latency — p50 ≤ 1.1s, p95 ≤ 1.8s over 10 PSTN calls; first-greeting delay recorded | ☐ pass ☐ fail | p50: ___ p95: ___ greeting: ___ |
| 5 | Telugu turn-taking — barge-in + end-of-utterance on hesitant speech (orchestration-layer; BYOK does not fix it) | ☐ pass ☐ fail | |
| 6 | Webhook loss — no retries expected; **poller recovery proven** | ☐ pass ☐ fail | |
| 9 | Compute region + India data-residency terms in writing | ☐ pass ☐ fail | |
| 10 | Agency model in writing + **sub-accounts tier** (Pilots vs Enterprise discrepancy) | ☐ pass ☐ fail | |
| 11 | Support responsiveness — 2 threads, time-to-first-useful-answer | ☐ pass ☐ fail | tech: ___h · commercial: ___h |
| 12 | Commercials in writing — **BYOK platform fee (target ≤ ~₹1.5/min)**, tiers, INR/GST, notice period, export, retention/deletion, **KB billed separately or included?** | ☐ pass ☐ fail | fee: ₹___/min · KB: ☐ included ☐ extra ₹___ |

## Soft gates

| # | Gate | Result | Notes |
|---|---|---|---|
| 7 | Post-call data fidelity — cost/recording/extraction at `completed`, currency, transcript parse, time-to-`completed` vs 2-min SLO | ☐ pass ☐ fail | t→completed: ___ |
| 8 | KB (Telugu multilingual mode) + custom-function budget + batch campaign + H1 history handling | ☐ pass ☐ fail | tool-call p95: ___ms · Telugu KB recall: ___ · history truncated/summarised? ___ · context caching on BYOK? ___ |
| 13 | Concurrency ceiling + dispatch rate limit; Sarvam + trunk ceilings | ☐ pass ☐ fail | platform ___ / model ___ / trunk ___ |

## Measured cost model (replaces estimates in TRD §10)

| Leg | Estimated (pre-pilot) | **Measured** | Source |
|---|---|---|---|
| Bolna platform fee (BYOK) | unpublished; target ≤₹1.5 | | written quote |
| Sarvam Saaras V3 STT | ₹0.50/min | | invoice |
| Sarvam Bulbul V3 TTS | ₹0.90–1.40/min (beta pricing) | | invoice + measured chars/min |
| LLM | **₹0.00 (Sarvam 105B, D-36 default)**; Gemini 2.5 FL fallback ₹0.15–0.20 | | invoice |
| Telephony (Exotel/Vobiz) | ₹0.35–0.50/min | | rate card |
| Built-in KB (`rag_id`) | **₹0 — INFERRED included in platform fee** (D-33) | | written reply, gate 12(g) |
| *(alt)* external KB via custom function | ₹0.02–0.05/min + measured latency cost | | only if gate 8 Telugu fails |
| **All-in** | **target ₹3.0–3.6/min** | | |

BYOK legs (STT+TTS+LLM ≈ ₹1.75–2.30/min) are identical on every platform — they are NOT
a decision variable (D-32). Only the platform fee row and gate 4's latency decide.

## Parallel: Sarvam questions (not Bolna gates)

- ~~Is the Sarvam LLM genuinely free per token?~~ → **ANSWERED 11 Aug 2026 (D-35):** `sarvam.ai/api-pricing` lists **Sarvam 105B and 30B chat LLM as "Free per token."** Removes R-04's forced Gemini-3.x step. Still confirm on-account: is it permanent or promotional, and what happens at the rate-limit ceiling?
- ~~Bulbul V3 pricing~~ → **CONFIRMED ₹30/10k chars; and Bulbul v2 is LIVE at ₹15/10k (half)** — D-20's "v2 discontinued" was wrong. Still ask: is the v3 rate committed or introductory?
- BYOK-tier model concurrency ceiling → **partly answered:** rate limits are 60 rpm (Starter) / 200 rpm (Pro ₹10k) / 1,000 rpm (Business ₹50k). Convert rpm → concurrent calls for our turn rate and confirm which plan we need. → answer:
- **NEW — Telugu ear test, v3 vs v2:** same script, same voice, both models. If v2 is acceptable for Telugu, the value tier costs **₹0.54–0.81/min TTS instead of ₹1.08–1.62** (TRD §10.1). → answer:

## Captured artifacts (commit alongside this file)

- [ ] `fixtures/execution_completed.json` — full Get Execution payload (adapter fixture)
- [ ] `fixtures/webhook_delivery.json` — raw webhook body + headers (proves signing absence)
- [ ] `fixtures/transcript_raw.txt` — prefix-tagged transcript (parser test input)
- [ ] Telugu call recordings + the 10-utterance script used
- [ ] Written commercial reply (email → PDF/markdown)

## Open items carried forward

| Item | Owner | Where it lands |
|---|---|---|
| | | |
