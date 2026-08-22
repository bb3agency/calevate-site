# Bolna Pilot Scorecard — EVIDENCE ARTIFACT

<!-- GENERATED FILE — do not hand-edit. -->
<!-- Regenerate: uv run python -m scripts.pilot.scorecard --out docs/evidence/bolna-pilot-scorecard.md -->

Gates and pass criteria: OPERATIONS.md §2 (authoritative — this document reports results, it does not restate criteria). Decisions: D-31 (Bolna primary, no fallback engine designated), D-32 (evaluation doctrine). Committed under ENGINEERING-PRACTICES §2 ("evidence artifacts": DR drills, stress runs and vendor scorecards live in the repo).

This file is generated from typed gate results by `uv run python -m scripts.pilot.scorecard --out docs/evidence/bolna-pilot-scorecard.md`. The verdict below is DERIVED from the gate rows — it is not a field anybody can set, and a hard gate that is red or unrun cannot sit under a green headline.

It contains no caller numbers, no transcript text and no recording links, by construction rather than by care: every free-text field is refused at construction if it carries PII or a URL, and the whole rendered document is re-scanned before it is written (hard rules 5 and 6).

---

## VERDICT: NOT RUN — G0 NOT CLOSED

G0 is NOT closed and has not been attempted. Nothing below has been measured. This document is a plan, not evidence.

- Hard gates (10): 10 not run
- Soft gates (3): 3 not run

| Field | Value |
|---|---|
| Engine under test | Bolna |
| Run by | _not recorded_ |
| Window | _not recorded_ |
| Spend | _not recorded_ |

## Hard gates — a red one reopens the engine decision

| # | Gate | How it can be answered | Verdict | Evidence |
|---|---|---|---|---|
| 1 | **Webhook trust** — deliveries arrive only from the documented egress address, the allowlist rejects everything else, execution_id dedupes, and the payload matches Get Execution | automated | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 2 | **Full API provisioning** — agent -> prompt -> number -> call -> execution, by API only; user_data round-trips into the prompt; scheduled_at works | automated | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 3 | **Telugu quality (BYOK)** — names and numbers >=90% correct on a 10-utterance Telugu script over real PSTN, code-mixed handled, and Bulbul V3 selectable | human listening | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 4 | **Real-call latency** — voice-to-voice p50 <= 1.1s and p95 <= 1.8s over 10 PSTN calls, measured by us; first-greeting delay recorded separately; the engine's own latency_data captured and compared against the stopwatch | automated | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 5 | **Telugu turn-taking** — barge-in mid-sentence and end-of-utterance on slow, hesitant Telugu: does it cut callers off, or leave dead air? An orchestration property BYOK does not fix | human listening | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 6 | **Webhook loss behaviour** — kill the receiver mid-call: the call continues, no retry arrives, and the List-Executions poller recovers every missed execution | automated | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 9 | **Compute region + data residency** — where the call actually executes, and India data-residency terms and price IN WRITING (recordings on US storage is a separate fact from compute) | human attestation | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 10 | **Agency model + sub-accounts tier** — multiple end-clients under one account permitted, in writing; and which tier actually includes sub-accounts — the pricing page and the docs disagree, and if the lower tier includes it our tenancy model lands far earlier | human attestation | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 11 | **The humans** — two support threads opened during the pilot, one technical and one commercial: time to first USEFUL answer and the quality of it. This is the gate the previous vendor failed | human attestation | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 12 | **Commercials in writing** — the BYOK platform fee (the single number that decides our unit economics), volume tiers, INR/GST invoicing, price-change notice, export on exit, recording retention and deletion, and whether the built-in KB is billed separately or included — an inference that is currently load-bearing | human attestation | _NOT RUN_ | _no evidence — this gate has not been attempted_ |

## Soft gates — these shape M1 scope, not the engine choice

| # | Gate | How it can be answered | Verdict | Evidence |
|---|---|---|---|---|
| 7 | **Post-call data fidelity** — cost, recording and extracted data present at `completed`; currency confirmed; transcript parses into TranscriptTurn; time-to-completed against the 2-minute lead SLO | automated | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 8 | **KB, campaigns, tools, history** — Telugu retrieval quality and latency in the built-in KB; tool-call p95; a 10-contact batch; whether the KB listing carries the agent linkage and whether deleting a KB clears the agent's reference; history truncation and context caching on BYOK | automated | _NOT RUN_ | _no evidence — this gate has not been attempted_ |
| 13 | **Concurrency ceiling** — our ceiling, the behaviour at the limit (queue or reject, and the error shape), the outbound dispatch rate limit, and the model and trunk ceilings beside it — the effective ceiling is the minimum of all three | automated | _NOT RUN_ | _no evidence — this gate has not been attempted_ |

## The gates no program can answer

Gates 9, 10, 11 and 12 are human-attestation gates and gates 3 and 5 need a human listening to Telugu. They are recorded here separately because they are the ones this company has been burned on: the previous vendor passed a demo and failed diligence (D-31), and gate 11 exists because unresponsive humans were that trap. A PASS on any row below is refused by the result type unless it carries a dated attestation from a written source — a verbal assurance is recordable, and it caps the gate at INCONCLUSIVE.

| # | Gate | Verdict | Attested by | Dated | Source |
|---|---|---|---|---|---|
| 3 | Telugu quality (BYOK) | _NOT RUN_ | — | — | _no source on file_ |
| 5 | Telugu turn-taking | _NOT RUN_ | — | — | _no source on file_ |
| 9 | Compute region + data residency | _NOT RUN_ | — | — | _no source on file_ |
| 10 | Agency model + sub-accounts tier | _NOT RUN_ | — | — | _no source on file_ |
| 11 | The humans | _NOT RUN_ | — | — | _no source on file_ |
| 12 | Commercials in writing | _NOT RUN_ | — | — | _no source on file_ |

## Measured cost model (replaces the estimates in TRD §10)

A blank measured cell means NOT MEASURED. It is never zero: a zero here becomes a wrong unit price in every ledger row we ever write (hard rule 7).

| Leg | Estimated (pre-pilot) | Measured (INR/min) | Source |
|---|---|---|---|
| Platform fee (BYOK) | unpublished; target <= ~INR 1.5/min | _not measured_ | — |
| Sarvam Saaras V3 STT | INR 0.50/min | _not measured_ | — |
| Sarvam Bulbul V3 TTS | INR 0.90-1.40/min (beta pricing) | _not measured_ | — |
| LLM | gpt-4o-mini INR 0.1021 (1 min) - 0.2411 (10 min); gpt-4.1-mini INR 0.2734 (1 min) - 0.6457 (10 min) on Azure OpenAI eastus2 (D-410, where an Azure resource, key and deployment are configured); INR 0.00 on the Sarvam 105B fallback (D-36). Which model runs is `azure_openai_model`, a live switch | _not measured_ | — |
| Telephony | INR 0.35-0.50/min | _not measured_ | — |
| Built-in KB | INR 0 - INFERRED included in the platform fee (D-33) | _not measured_ | — |
| All-in | target INR 3.0-3.6/min | _not measured_ | — |

BYOK legs (STT + TTS + LLM) are identical on every platform and are NOT a decision variable (D-32). Only the platform fee row and gate 4's latency decide.

## Captured artifacts

_None captured._ Gates 1, 2, 4, 7 and 8 each require a payload captured as an adapter conformance fixture; `scripts/pilot/record.py` is what writes them, and it redacts on the way in.

## Parallel asks to Sarvam (not Bolna gates, and they move the cost model more)

- Is the Sarvam LLM's "free per token" permanent, promotional or rate-limited? D-35 read it live from the published rate card; what is unconfirmed is what happens ON OUR ACCOUNT and at the rate-limit ceiling.
- Is Bulbul V3's beta rate committed or introductory? Beta prices move, and D-36 makes v3 the default with v2 as the value tier.
- Convert the plan rate limits (rpm) into concurrent calls at our turn rate, and confirm which plan we need — this is a concurrency input to gate 13, not a price input (D-35).
- Telugu ear test, v3 vs v2, same script and same voice: if v2 is acceptable, the value tier halves the TTS leg (TRD §10.1).

## Open items carried forward

_None recorded._
