<!-- EVIDENCE CLASS: MIXED, stated per row. Nothing in this file is a vendor quote for the
     carrier leg, and the carrier leg is the question this file was written to answer.

     Read §0 first. The headline is not a number: it is that the per-minute cost model in
     `apps/api/billing/rates.py` contains NO CARRIER LEG AT ALL, deliberately (D-474,
     Model B), so every margin figure in this repository is the margin BEFORE the cost of
     the phone call itself. Whether that is right depends on a commercial decision the
     founder has not yet restated for the Pipecat architecture.

     Exotel's per-minute rate is UNKNOWN. It is not published, and `exotel.com` is
     egress-blocked from this container — measured twice, two ways, 21 Sep 2026 (§4.4). No
     competitor rate, blog range or reseller figure is substituted for it anywhere below.
     §5's sensitivity table is the deliverable: it is built so the founder reads the answer
     off it the moment Exotel replies with a rupee number. -->

# Per-call-minute cost model, and what a Plivo → Exotel move changes (21 Sep 2026)

## §0 The three answers, up front

1. **The carrier leg is absent from the cost model.** `apps/api/billing/rates.py:1201-1205`
   states it in as many words: *"NO TELEPHONY LEG, on either floor (D-474, Model B). The
   client buys the connection on their own carrier account (Exotel/Plivo/Vobiz), is the
   subscriber of record and is billed the per-minute carrier rate by that carrier — Calevate
   supplies, rents and bills no number."* Every cost floor, every pack margin and every
   break-even in this repository is therefore **ex-telephony**. That is a deliberate decision
   and not an oversight — but §4.1 shows it is now in tension with the architecture the code
   actually implements, and that tension is the founder's to resolve, not an engineer's.
2. **Per call-minute, all legs we DO model, the total is ₹2.5241–₹3.1491 on the `clear`
   rung and ₹3.5413–₹4.7099 on the `studio` rung** (§3). Both exclude the carrier.
3. **Exotel's per-minute rate is UNKNOWN** (§4.4), and the break-even carrier rate that
   makes each rung's cheapest sold minute exactly zero-margin is **₹0.8509/min on `clear`
   at ₹4.00** and **₹0.7901/min on `studio` at ₹5.50** (§6). Those two numbers are the ones
   to hold Exotel's quote against.

---

## §1 What a call-minute is made of — enumerated from the code, not from memory

Entry point: `apps/api/billing/rates.py::_ex_tts_cost_inr_per_min` (`:1307-1320`) and
`ex_tts_cost_inr_per_min_at` (`:1817-1836`), which between them define the three legs both
voice rungs share, plus one TTS leg per rung.

| # | Leg | Constant / function | ₹ per call-minute | Evidence class, **as the code states it** |
|---|---|---|---|---|
| 1 | Engine / runtime container | `ENGINE_PLATFORM_FEE_USD_PER_MIN` `rates.py:1266` = $0.01/min × `COST_MODEL_USD_INR` `:1291` (₹95) | **₹0.95** | **VERIFIED-VENDOR-DOCS** — Pipecat Cloud published "$0.01/min active", cited at `docs/evidence/engine-replacement-comet-2026-09-06.md:93,103,122`. ⚠ Billing **granularity UNKNOWN** (`rates.py:1243-1246`): no page read states the rounding unit for an active minute. ⚠ Also **UNKNOWN what an "active minute" covers** — `apps/voice-worker/voice_worker/meter.py:22-24,44-49`: connected time only, or container start/teardown too |
| 2 | STT (Sarvam Saaras, transcribe + translate) | `STT_INR_PER_HOUR` `rates.py:253` = ₹30.00/hr ÷ 60 | **₹0.50** | **VENDOR-PUBLISHED** — Sarvam dashboard Model Catalogue, read by the founder 27 Aug 2026 and relayed (`rates.py:236-244`). NOT fetched here; `sarvam.ai` is egress-blocked. ⚠ Vendor billing granularity **UNKNOWN and not imputed** (`rates.py:1169-1180`), so this leg is a **floor** on real cost |
| 3 | In-call LLM | `llm_cost_inr_per_minute(minutes, model=)` `rates.py:949` | **₹0.1021** (1-min call) … **₹0.2411** (10-min call), at `gpt-4o-mini` | **ESTIMATE over a VENDOR-PUBLISHED list price.** The curve is quadratic in call length (full history resent every turn, TRD §6.1), so a "₹/min" here is a blended average. ⚠ Converted at `LIST_PRICE_USD_INR` = ₹95.66 (`rates.py:470`), whose own class the code marks **REPORTED, NOT READ** (`:439-447`) — `www.rbi.org.in` is egress-blocked. ⚠ Prices the **full resend with no cache discount** (gate 42) |
| 4a | TTS — `clear` rung (Gnani Timbre v2.5) | `TTS_INR_PER_10K_CHARS` `rates.py:153` = ₹27.00/10k chars × `TTS_ASSUMED_CHARS_PER_CALL_MINUTE` `:169` (360–540) | **₹0.9720 – ₹1.4580** | Price: **VENDOR-PUBLISHED** — `app.gnani.ai/voice/pricing`, read by the founder 19 Sep 2026 with a screenshot (`rates.py:108-114`); host unreachable here. Character band: **ESTIMATE, explicitly unmeasured** (TRD §10.1, pilot gate 12) |
| 4b | TTS — `studio` rung (Cartesia Sonic 3.5) | `CARTESIA_MARGINAL_TTS_INR_PER_10K_CHARS` `rates.py:2156` = ₹57.20/10k at ₹88/$ (Pro plan $65 per 1M credits, marginal/overage) × 360–540 | **₹2.0592 – ₹3.0888** | Plan inputs **VENDOR-PUBLISHED** (Tinmaz correspondence, 9 Sep 2026, `docs/evidence/cartesia-tts-verification-2026-09-06.md` ADDENDUM 3); the Scale plan's fee/allotment are **REPORTED and deliberately excluded** (`rates.py:1802-1808`). It is a **subscription**, so there is no per-character price inside the allotment at all — only a marginal rate past it |
| 5 | **Carrier (PSTN + media streaming)** | **NONE — no constant, no function, no leg** | **₹0.0000 modelled** | **ABSENT BY DECISION (D-474, Model B)** — `rates.py:1201-1205`. See §4 |
| 6 | Number rental | `apps/api/billing/number_rental.py` — a monthly `usage_events` row, `unit_type='number_rental'`, `qty = 1 month` | **Not a per-minute cost at all**; amortises (see §4.3) | **Vendor quote at purchase** (`phone_numbers.monthly_rental_usd`), converted at the live FX rate each month (`number_rental.py:26-35`). ⚠ Written only for numbers this platform rents (D-537); under Model B a client's own number produces no row |
| 7 | Recording storage | **not modelled anywhere** | — | **UNKNOWN.** A repo-wide search for a storage-cost leg on the money path returns nothing. Object-storage bytes are a real cost and no line item exists for them |
| 8 | Dashboard AI assists | `ai_assist_ktok_in/out`, `PLATFORM_ABSORBED_UNIT_TYPES` `billing/models.py:220` | — | Deliberately **not** per call-minute: platform-absorbed, excluded from every client-facing rupee (D-127 G-3) |
| 9 | Reserved warm capacity | `ENGINE_RESERVED_INSTANCE_USD_PER_MIN` `rates.py:1274` = $0.0005/min ⇒ $21.60/instance/month | **deliberately ₹0 in any floor** | **VERIFIED-VENDOR-DOCS**, but it is a **fixed** cost of standing up the platform; folding it into a per-minute floor needs a utilisation figure nobody has measured (`rates.py:1234-1242`) |

### §1.1 Which of these may legally reach a bill today

Hard rule 7 is enforced structurally, not by a flag. Status as of this reading:

* **`clear` rung TTS — NOT BILLABLE.** `tts_rate_inr_per_char()` raises `UnattestedTtsRateError`
  until an operator attests an invoice; `agents/voice_offer.tts_price_is_billable` refuses
  every Gnani voice, so the whole rung is unsellable. **One attestation in the ops console
  unblocks it** (`docs/PIPECAT-MIGRATION.md` §6 step 9). The published ₹27 is a catalogue
  figure and has no path to `unit_cost_paid` (`rates.py:129-136`).
* **`studio` rung TTS — billable only via `TtsPriceAttestation`** (`ops/model_pricing`). The
  ₹57.20/10k in the model is the vendor's overage rate, pre-filled into the attestation form
  **greyed and never billable** (`rates.py:2150-2155`).
* **LLM — billable on exactly two grounds** (`rates.py::llm_price_is_billable` `:819`): an
  operator attestation, or a catalogue price whose evidence is `verified=True`. The Azure
  figures are verified; **Gemini's and OpenAI-direct's are `verified=False`**, so those legs
  cannot be billed until attested.
* **STT and engine fee — these are COST-MODEL figures, not bills.** What actually reaches
  `usage_events` for STT is the engine's own reported leg cost divided by billable seconds
  (`workers/pipeline.py:2563`), never `STT_INR_PER_HOUR` (`rates.py:1157-1168`).
* **Carrier — see §4.2.** The ledger unit exists and is priced from the carrier's own CDR;
  nothing in production supplies one.

---

## §2 Method and rounding

All arithmetic below is `Decimal`, matching `rates.py` (hard rule 7: NUMERIC, INR, never
floats). Leg figures are exact; **only the presented totals are rounded, to 4 decimal places
— `MONEY_Q`, the storage precision of `usage_events.unit_cost_paid` (`NUMERIC(12,4)`)**, with
`ROUND_HALF_UP` (`rates.py:274,284`). Percentages are rounded to 1 dp at presentation only.

Every total is quoted as a **range**, because two inputs are bands rather than points:
`TTS_ASSUMED_CHARS_PER_CALL_MINUTE` (360–540 chars of agent speech per call-minute) and the
LLM leg's dependence on call length (1 min → 10 min).

Two FX rates appear, and they are different facts and must not be collapsed:
`COST_MODEL_USD_INR` = ₹95 (the cost model's strike, founder-stated 14 Sep 2026,
`rates.py:1291`) and `CARTESIA_EVIDENCE_USD_INR` = ₹88 (the rate the Cartesia evidence file
was written at, which freezes the pack-card refusal threshold, `rates.py:2100-2129`).

---

## §3 The total, per rung, per call-minute (NO CARRIER LEG)

### `clear` rung — Gnani Timbre v2.5

```
                           LOW  (1-min call, 360 chars/min)   HIGH (10-min call, 540 chars/min)
engine (Pipecat, $0.01×95)      0.9500                             0.9500
STT   (₹30/hr ÷ 60)             0.5000                             0.5000
LLM   (gpt-4o-mini)             0.1021                             0.2411
TTS   (₹27/10k × 360 | 540)     0.9720                             1.4580
                               ───────                            ───────
                         TOTAL  ₹2.5241 /min                       ₹3.1491 /min
```

The high end is exactly `SELF_SERVE_COST_FLOOR_INR_PER_MIN`, confirmed by evaluating the
module: **₹3.1491**.

> ⚠ **A STALE FIGURE IN THE SOURCE, FOUND WHILE CHECKING THIS.** `rates.py:36` and `:1213`
> still narrate this floor as **₹3.3111** ("0.95 + 0.50 + 0.2411 + 1.62"), and the module
> docstring's margin claim ("17.2% at a flat ₹4.00 against a ₹3.3111 floor") is computed from
> it. The constant itself is correct and self-deriving; what is stale is the prose, left
> behind when `TTS_INR_PER_10K_CHARS` moved ₹30 → ₹27 on 19 Sep 2026 (₹1.62 → ₹1.4580 on the
> TTS row). The true margin at ₹4.00 is **21.3%**, i.e. *above* the 20% target, not below it.
> **Not corrected here — this pass is read-only outside this file.**

### `studio` rung — Cartesia Sonic 3.5 (marginal, i.e. past the plan allotment)

At `CARTESIA_EVIDENCE_USD_INR` = ₹88 (the frozen refusal basis):

```
                           LOW                                HIGH
engine ($0.01×88)               0.8800                             0.8800
STT                             0.5000                             0.5000
LLM                             0.1021                             0.2411
TTS (₹57.20/10k × 360 | 540)    2.0592                             3.0888
                               ───────                            ───────
                         TOTAL  ₹3.5413 /min                       ₹4.7099 /min
```

The high end is exactly `CARTESIA_COST_FLOOR_INR_PER_MIN` = **₹4.7099**.

> ⚠ **A SECOND STALE FIGURE.** `rates.py:2100-2102` and `cartesia_cost_floor_inr_per_min_at`'s
> docstring (`:1911`) still say this floor is **₹5.5899 at ₹88**. It is not, and has not been
> since D-592 halved the engine fee from $0.02 to $0.01/min: at ₹88 the engine row fell
> ₹1.76 → ₹0.88, so the three shared legs fell ₹2.5011 → ₹1.6211 and the floor with them,
> ₹5.5899 → ₹4.7099 (the worst marginal TTS half, ₹3.0888, is unchanged). The claim that "at
> ₹95.66 the live floor is ₹6.0120 and the founder's own ₹6.00 max rung is under it" is
> likewise stale — recomputed at ₹95 the live floor is **₹5.0256**, and the ₹7.00 top rung
> clears it. **Not corrected here.**

At `COST_MODEL_USD_INR` = ₹95 the same computation gives **₹3.7751 – ₹5.0256**.

**Studio is a subscription, so the marginal figure is not the cost at every volume.** Blended
all-in cost per call-minute at ₹88, from `cartesia_cost_inr_per_call_minute`: ₹6.0211 at 100
call-min/month, ₹4.0499 at 200, ₹4.4459 at 500, ₹4.5779 at 1,000, ₹3.5043 at 2,500. It is
**not monotonic**, because the cheapest plan changes underneath it. Below roughly 150
call-minutes a month the real cost is *higher* than the ₹4.7099 floor.

### The weakest input in both sums

`TTS_ASSUMED_CHARS_PER_CALL_MINUTE`. TRD §10.1 calls it unmeasured in its own words
(`rates.py:156-158`), it is worth ₹0.49/min of spread on `clear` and ₹1.03/min on `studio`,
and **Indic character density is the named risk that the true count sits ABOVE 540**, which
would make both floors wrong in the expensive direction. `billing/tts_speaking_rate.py`
replaces it once ~20 real calls exist. **No real call has ever been placed on this product
(BLOCKER-1).**

---

## §4 THE CARRIER LEG

### §4.1 What the code assumes today — plainly

**There is no carrier constant, and the carrier leg is absent from the cost model by
decision.** `rates.py:1201-1205`, quoted verbatim in §0.1. The decision is D-474 "Model B":
the client is the subscriber of record on their own carrier account, so the per-minute PSTN
charge is the CLIENT's cost and folding it into our floor "would defend our margin with a
rupee we never pay". The same block names Plivo's **₹0.38/min** explicitly as *the client's*
cost, not ours.

⚠ **THAT PREMISE IS IN TENSION WITH THE ARCHITECTURE THE CODE NOW IMPLEMENTS, AND THE
TENSION IS COMMERCIAL, NOT TECHNICAL.** Three things in this tree point the other way:

* `apps/voice-worker/voice_worker/carrier.py:1-7` — "the only place in this repository that
  knows the carrier is Plivo" — is written for **one Plivo account that Calevate holds**, and
  `PLIVO_AUTH_ID`/`PLIVO_AUTH_TOKEN` are **our** env credentials, not per-tenant ones.
* `apps/api/agents/transfer_providers/registry.py:63` hard-codes `_CARRIER_OF_ENGINE =
  {"pipecat": "plivo"}` — one carrier for the whole engine, not one per tenant.
* `docs/evidence/carrier-pricing-concurrency-2026-09-17.md` concludes that **none of Plivo,
  Exotel or Vobiz has a documented self-serve way to run Model B at all** (client's own
  pre-existing DLT number hosted on our trunk): Vobiz blocks it outright, Plivo's claim is
  US-shaped (RespOrg), Exotel is silent. Its own words: *"this is the single biggest open
  question in this whole report, bigger than any per-minute rate."*

**If Calevate ends up holding the carrier account — which is what the code is built for —
then the carrier minute is OURS, and every margin figure in this repository is overstated by
the carrier rate.** §5 and §6 are written so that outcome can be priced the instant it is
decided. This file does not decide it: the founder does.

### §4.2 Is the carrier cost metered anywhere? — Yes, and no producer is wired

Traced end to end:

* **The ledger unit exists.** `telephony_s` is the first entry in `CLIENT_BILLED_UNIT_TYPES`
  (`apps/api/billing/models.py:171`) and is the unit every client-facing minute is billed off
  (`billing/service.py:2570,3402`).
* **On the old rented-engine path it is written** from the engine's own reported network
  charge: `apps/workers/pipeline.py:2561` — `("telephony_s", duration_s,
  _unit_price(cost.network_inr, duration_s))`. That is Bolna's charge to us, not a rate card.
* **On the owned-runtime (Pipecat) path it is written from the CARRIER'S OWN CDR**:
  `apps/voice-worker/voice_worker/meter.py:780-793` builds the `telephony_s` row with
  `qty = carrier.connected_seconds` and `unit_cost_inr` derived from `carrier.charge_inr`.
  There is **no rate constant** — the charge is an input, and the module says why
  (`meter.py:19-20,42-47`): *"No runtime signal: this is not ours to witness"*, and metering
  the billable quantity against our own clock is explicitly rejected.
* **Missing it REFUSES rather than writing zero.** `CarrierFactsMissingError`
  (`meter.py:249-257`) — *"Do NOT substitute the worker's own session duration: the carrier
  billed the minute and is the authority."*
* ⚠ **AND NOTHING IN PRODUCTION CONSTRUCTS A `CarrierCdr`.** A repo-wide search finds it
  built only in `tests/voice_worker_meter_test.py:117,197`. `carrier.py:57` lists *"every
  carrier REST call except the hangup — placing a call, **listing a CDR**, binding a number"*
  among the UNKNOWNs, refused by name. **So the carrier leg is a half-wired seam: the
  ledger row, the refusal and the reconciliation are built; the CDR ingestion is not.**
  `lifecycle.py:262-270` confirms the design — the ledger for a call is settled later, from
  the CDR, against the `call_id` already written.

Number rental (`billing/number_rental.py`) is separately and correctly metered as a monthly
`usage_events` row, and it is **not** in the per-minute floor.

### §4.3 What would actually change, Plivo → Exotel

Beyond the per-minute rate, from sources read for this pass:

| What changes | Plivo (today) | Exotel | Class |
|---|---|---|---|
| **Per-minute PSTN rate** | ₹0.38/min India domestic, in and out | **NOT FOUND — see §4.4** | Plivo figure is **VENDOR-PUBLISHED (third-party read)** — `docs/evidence/carrier-pricing-concurrency-2026-09-17.md`, Plivo's India voice pricing page, read by a research agent. Not read from here |
| **Bidirectional streaming surcharge** | ₹0.00 — included free per Plivo's own India SIP page | **NOT FOUND**; AgentStream is excluded from every published Exotel plan and its rate is not published | Same file, §7 addendum of `carrier-plivo-vs-exotel-2026-09-16.md`. **This is the single largest unknown after the PSTN rate** — it stacks on top (on Vobiz it is +₹0.06/min, +16%) |
| **Billing increment** | **Contradiction inside Plivo's own docs** — "30-second pulse" on the India pricing page vs explicit 60/60 on the billing-concepts page. Unreconciled | **NOT FOUND**; per-second after a minimum/plan pulse is stated, values not | See §4.5 — an increment is a multiplier on the rate and can matter as much as the rate |
| **Billing trigger** | Explicit: billed **from answer**, not from ringing | May start **at ringing** for connect-to-number flows | Exotel side is **THIRD-PARTY/REPORTED** and would need confirming |
| **Monthly number rental** | ₹200/mo | ~₹499/mo Exophone — **third-party / prior console session, not an official figure** | At 1,000 billed min/mo that is ₹0.20/min vs ~₹0.50/min; at 500 min/mo, ₹0.40 vs ~₹1.00 |
| **Plan / platform fee** | None for Pay-As-You-Go up to ₹2,00,000/mo usage | Published bundles Dabbler ₹9,999/5mo, Believer ₹19,999/11mo, Influencer ₹49,499/11mo — **all of which explicitly exclude AgentStream**. Whether the Voice/streaming product can run without one is **NOT FOUND** | **VENDOR-PUBLISHED** for the ladder. At 1,000 billed min/mo, Dabbler's ₹4,999 rental component amortises to **≈₹1.00/min** — roughly the entire modelled headroom |
| **GST** | 18% added on Indian invoices | 18% added on Indian invoices | Same both sides. Every figure in this file is **ex-GST**. If Calevate is GST-registered the carrier's 18% is input tax credit and does not change the cost model; if it is not, the effective carrier cost is the rate × 1.18. **Which applies is a business fact this file does not assert** |
| **Minimum commitment** | None on PAYG | **NOT FOUND** — KYC-gated | |
| **Concurrency** | 50 concurrent + 2 CPS free on India PAYG, per account | Starter ≈10, "notify us above 20", sales-gated past that; per-unit price NOT FOUND | Not a per-minute cost, but it caps revenue per account |
| **Programmatic hangup** | **Implemented** — `pipecat/serializers/plivo.py:184` DELETEs `https://api.plivo.com/v1/Account/{auth_id}/Call/{call_id}/` | **NOT IMPLEMENTED** in the pinned wheel: `pipecat/serializers/exotel.py` (171 lines) has no REST call and no hangup path at all | **VERIFIED-VENDOR-SDK** — pipecat-ai 1.10.0 as installed, read 21 Sep 2026. **This is a COST item**: a leg we cannot terminate keeps billing both carrier minutes and Pipecat active minutes |
| **Caller identity on the stream** | **Absent** — Pipecat's Plivo branch populates only `stream_id`/`call_id` (`pipecat/runner/utils.py:257-262`) | **Present** — the Exotel branch populates `from`, `to`, `account_sid` and `custom_parameters` (`:264-272`) | **VERIFIED-VENDOR-SDK**, same reading. Exotel is strictly better here, and it retires the workaround in `apps/voice-runtime/carrier_routes.py` |
| **Wire format** | 8 kHz μ-law (`serializers/plivo.py:139-163`) | 8 kHz PCM (`serializers/exotel.py:44-49,104-112`) | **VERIFIED-VENDOR-SDK**. No cost effect; a resampler change only |
| **Our code that must change** | — | `voice_worker/carrier.py` (the one module that knows the carrier), `agents/transfer_providers/registry.py:63`, a new `transfer_providers/exotel.py`, `compliance/carrier_application.py:115` (`CARRIER = "plivo"`), `compliance/models.py:147` (`CARRIER_APPLICATION_CARRIERS = ("plivo",)`) | Read this session |
| **Multi-tenant compliance model** | Plivo publishes a Reseller mode with one compliance application per client | **NOT PUBLISHED** | `carrier-plivo-vs-exotel-2026-09-16.md` §4 ranks this **above price** for a product whose second client is a regulatory event |

### §4.4 The Exotel rate: **UNKNOWN**, measured

**Measured from this container, 21 Sep 2026, two independent ways, both refused:**

```
curl --max-time 25 https://exotel.com/pricing      → CONNECT tunnel failed, response 403
curl --max-time 25 https://www.exotel.com/pricing  → CONNECT tunnel failed, response 403
curl --max-time 25 https://exotel.com/             → CONNECT tunnel failed, response 403
curl --max-time 25 https://my.exotel.com/          → CONNECT tunnel failed, response 403
curl --max-time 20 https://docs.exotel.com/        → CONNECT tunnel failed, response 403
curl --max-time 20 https://developer.exotel.com/   → CONNECT tunnel failed, response 403
curl --max-time 20 https://support.exotel.com/     → CONNECT tunnel failed, response 403
```

The fetch tool returns `EGRESS_BLOCKED` for `exotel.com` on the same URL. **`exotel.com` is
egress-blocked from this container.**

Independently of egress: **the rate is not published to anyone.** A research agent with
browser control logged into `my.exotel.com` on 17 Sep 2026 with live credentials and called
the Account API directly; the account returned `Trial`, `KycStatus: notstarted`, and **no
plan, rate or billing data is exposed pre-KYC through either the console or the API** —
confirmed two independent ways (`carrier-pricing-concurrency-2026-09-17.md`, "Access actually
achieved"). That same report's Exotel column is labelled **blog midpoints, estimates, "do not
quote"**, and its own header says so.

**Therefore: EXOTEL PER-MINUTE RATE = UNKNOWN.** No figure is carried forward into §5 or §6.
The figures in circulation and why each is refused:

* ₹0.80–1.00/min (Exotel's own "Migrating from Twilio" blog) — a **marketing blog, not a rate
  card**, and the blog states it as a *market range*, not as Exotel's tariff.
* ₹0.85–1.50 outbound / ₹0.30–0.50 inbound — **THIRD-PARTY** "typical mid-volume contract
  rates", GST treatment and pulse unstated.
* ₹0.42–1.68/min SIP — from an Exotel blog about *self-hosted alternatives*, **not attributed
  as Exotel's own price**.

A figure that later turns out to match is still not a source (`rates.py:116-121` records the
same lesson costing this repository a day).

### §4.5 The increment is a multiplier, and it belongs in any quote

If a carrier bills a **60-second round-up** (Vobiz's confirmed behaviour; one of the two
readings of Plivo's own docs), the cost of a *call*-minute is the rate times
`ceil(duration) / duration`. On a 1.5-minute mean call that is **×1.333**; on a 2.5-minute
mean call, **×1.200**; on a 4.5-minute mean call, **×1.111**. A ₹0.80/min rate at 60-second
round-up on 1.5-minute calls is an effective **₹1.0667 per call-minute** — one full
sensitivity row worse than the quoted rate. **Ask for the rate AND the increment AND the
trigger, or the quote cannot be compared.** (Mean call duration on this product is itself
unmeasured — no call has been placed.)

---

## §5 Sensitivity — the table to read the answer off

Carrier leg added to the modelled floor. `clear` uses the worst-case floor ₹3.1491 (at
₹95/$); `studio` uses the frozen ₹4.7099 (at ₹88/$) and, in brackets, ₹5.0256 (at ₹95/$).
All ex-GST. All **per call-minute**; multiply the carrier column by §4.5's factor first if
the quote carries a round-up.

| Carrier ₹/min | `clear` all-in | `studio` all-in (@₹88 / @₹95) |
|---|---|---|
| **₹0.00** (today's model) | **₹3.1491** | **₹4.7099** / ₹5.0256 |
| **₹0.30** | **₹3.4491** | **₹5.0099** / ₹5.3256 |
| **₹0.50** | **₹3.6491** | **₹5.2099** / ₹5.5256 |
| **₹0.80** | **₹3.9491** | **₹5.5099** / ₹5.8256 |
| **₹1.20** | **₹4.3491** | **₹5.9099** / ₹6.2256 |
| ₹0.38 (Plivo's published India rate, for reference) | ₹3.5291 | ₹5.0899 / ₹5.4056 |

Low-end (best-case) variants, using §3's LOW column — 1-minute calls at 360 chars/min:
`clear` = ₹2.5241 + carrier; `studio` = ₹3.5413 + carrier (@₹88).

---

## §6 Margin against what we sell — and the break-even carrier rate

**What we sell** (`apps/api/billing/credit_packs.py:217-249`, the approved card): six credit
packs, **`clear` flat at ₹4.00/min on every pack**, **`studio` from ₹7.00/min (₹2,000 pack)
down to ₹5.50/min (₹50,000 pack)**. `Settings.self_serve_inr_per_min` remains an
operator-settable list rate (`billing/list_rates.py:86,154`); the card is the static one since
D-547. `MIN_GROSS_MARGIN` is **20%** (`rates.py`), and the guard **refuses below cost** and
only **reports below target** (`rate_margin`, `rates.py:2447`).

### `clear` at ₹4.00/min

| Carrier ₹/min | All-in cost | Margin ₹/min | Margin % |
|---|---|---|---|
| ₹0.00 | ₹3.1491 | ₹0.8509 | **21.3%** |
| ₹0.30 | ₹3.4491 | ₹0.5509 | 13.8% |
| ₹0.50 | ₹3.6491 | ₹0.3509 | 8.8% |
| ₹0.80 | ₹3.9491 | ₹0.0509 | 1.3% |
| ₹1.20 | ₹4.3491 | −₹0.3491 | **−8.7%** |

> **BREAK-EVEN CARRIER RATE, `clear` at ₹4.00: ₹0.8509/min.** Above that, every `clear`
> minute loses money. It falls below the 20% target at **₹0.0509/min** — i.e. essentially any
> carrier cost at all puts the `clear` rung below target.

### `studio`, at the cheapest (₹5.50) and dearest (₹7.00) rungs, marginal cost @₹88

| Carrier ₹/min | All-in cost | Margin @₹5.50 | Margin @₹7.00 |
|---|---|---|---|
| ₹0.00 | ₹4.7099 | ₹0.7901 (14.4%) | ₹2.2901 (32.7%) |
| ₹0.30 | ₹5.0099 | ₹0.4901 (8.9%) | ₹1.9901 (28.4%) |
| ₹0.50 | ₹5.2099 | ₹0.2901 (5.3%) | ₹1.7901 (25.6%) |
| ₹0.80 | ₹5.5099 | −₹0.0099 (**−0.2%**) | ₹1.4901 (21.3%) |
| ₹1.20 | ₹5.9099 | −₹0.4099 (−7.5%) | ₹1.0901 (15.6%) |

> **BREAK-EVEN CARRIER RATE, `studio`: ₹0.7901/min at the ₹5.50 rung; ₹2.2901/min at the
> ₹7.00 rung.** At ₹95/$ those become **₹0.4744** and **₹1.9744** — the FX rate alone moves
> the cheapest rung's break-even by ₹0.32/min.

### What this means against the unknown

The whole published Exotel *range* in circulation (₹0.80–1.50 outbound) sits **at or above
both cheap rungs' break-even**. That is a reason to get the real number, not a reason to
believe the range: it is blog and third-party material and is refused under hard rule 11. But
it does tell the founder what to watch for — **the decision hinges on whether Exotel quotes
below or above roughly ₹0.79/min**, and on whether the AgentStream surcharge (**UNKNOWN**)
stacks on top of it.

⚠ **And none of the above carries number rental.** Adding Exotel's reported ≈₹499/mo Exophone
at 1,000 billed minutes a month is a further **≈₹0.50/min**, which on its own exceeds both
cheap rungs' entire remaining headroom. At 10,000 min/mo it is ₹0.05. **This is a ramp
problem, and the ramp is the month we start in.**

---

## §7 UNKNOWNS — what must be obtained from a human or a vendor

Nothing below can be closed from inside this container. Each names the exact question.

1. **UNKNOWN — Exotel's per-minute India PSTN rate, in and out, ex-GST.** Closes with:
   *"Quote your INR ex-GST per-minute rate to Indian mobile and to landline, inbound and
   outbound, at 1,000 AND at 10,000 minutes/month."* `exotel.com` is egress-blocked here and
   the figure is KYC/sales-gated to everyone.
2. **UNKNOWN — Exotel's AgentStream / bidirectional streaming rate.** Excluded from every
   published plan. *"What is the per-minute charge for bidirectional media streaming, as a
   separate line item, and does it stack on the PSTN rate?"*
3. **UNKNOWN — Exotel's billing increment and billing trigger.** *"What is the pulse (1s /
   30s / 60s), is there a minimum billable duration, and does billing start at ringing or at
   answer?"* §4.5 shows this is worth up to 33% of the rate.
4. **UNKNOWN — Exotel's monthly number rental by series (including 140/160) and any setup
   fee**, as an official figure rather than a console recollection.
5. **UNKNOWN — whether the Exotel Voice/streaming product requires one of the published
   plan bundles** (Dabbler/Believer/Influencer), which would add a fixed monthly that
   amortises to ≈₹1.00/min at launch volumes.
6. **FOUNDER DECISION, not a vendor question — does Calevate hold the carrier account, or
   does the client?** D-474 Model B says the client; `voice_worker/carrier.py` and
   `transfer_providers/registry.py:63` are built as though we do; and no carrier documents a
   self-serve path for Model B. **Until this is answered, "our margin" has two different
   values and §5 is the map between them.**
7. **UNKNOWN — mean call duration on this product.** No real call has ever been placed
   (BLOCKER-1). It is the multiplier in §4.5 and the x-axis of the LLM leg's quadratic.
8. **UNKNOWN — `TTS_ASSUMED_CHARS_PER_CALL_MINUTE`**, the 360–540 band, unmeasured by TRD
   §10.1's own admission. Worth ₹0.49/min on `clear` and ₹1.03/min on `studio`. Closes with
   ~20 real calls through `billing/tts_speaking_rate.py`, not with a vendor.
9. **UNKNOWN — what a Pipecat Cloud "active minute" covers, and its rounding unit.**
   (`meter.py:22-24`.) Closes with one Pipecat Cloud invoice against calls of known duration.
10. **UNKNOWN — Sarvam's STT billing granularity.** Closes with one Sarvam invoice line
    against a request of known duration. Until then the ₹0.50 STT row is a floor.
11. **REPORTED, not confirmed — `LIST_PRICE_USD_INR` = ₹95.66**, the rate the whole LLM
    catalogue is struck at; `www.rbi.org.in` is egress-blocked and no session can re-fetch it.
    It reaches `unit_cost_paid` for dashboard assists (`rates.py:439-447`). Closes with an
    operator-attested strike rate — a founder pricing decision.
12. **NOT ATTESTED — the `clear` rung cannot be sold at all today.** One `TtsPriceAttestation`
    in the ops console unblocks every Gnani voice. This is ours, not a vendor's, and per the
    repo's own tempo rule it is not a "later".
13. **HALF-WIRED — no production path supplies a `CarrierCdr`,** so on the owned-runtime path
    the `telephony_s` leg refuses rather than settling. Closes with the carrier's CDR-listing
    API, which is itself among `carrier.py:57`'s refused-by-name unknowns.
14. **UNKNOWN — recording/object-storage cost per call.** Not modelled anywhere in this tree.
15. **UNKNOWN — GST posture.** Every figure here is ex-GST. Whether the carrier's 18% is
    recoverable as input tax credit depends on Calevate's registration status, which this file
    does not assert.

---

## §8 Two stale figures in `apps/api/billing/rates.py`, reported not fixed

This pass is read-only outside this file. Both are prose, not constants — the constants
re-derive correctly — but both are quoted in the module docstring as margin claims and will be
repeated by the next reader.

* `rates.py:36-40` and `:1211-1215`: `SELF_SERVE_COST_FLOOR_INR_PER_MIN` narrated as **₹3.3111**
  with a ₹1.62 TTS row. It is **₹3.1491** with a ₹1.4580 TTS row, since ₹30 → ₹27 on 19 Sep 2026.
  The docstring's "17.2% at a flat ₹4.00 … below the 20% target" is therefore wrong in the
  product's favour: the true margin is **21.3%**, above target.
* `rates.py:2100-2102`, `:1911`, `:2122-2126`: `CARTESIA_COST_FLOOR_INR_PER_MIN` narrated as
  **₹5.5899 at ₹88** (and "₹6.0120 at ₹95.66"). It is **₹4.7099 at ₹88** (₹5.0256 at ₹95),
  since D-592 halved the engine fee $0.02 → $0.01/min. The consequent claim that the ₹6.00 /
  ₹7.00 top rung is under water is no longer true.

Both were found by evaluating the module rather than reading its comments, which is the
difference hard rule 11 is about.
