# PLAN — Credit lots with per-lot rates, and a second voice tier (Cartesia)

**Status: IN PROGRESS — Phase A and Phase C (partial) started 7 Sep 2026; decisions §0 all taken.** This document is the guide for the implementation and is
kept current as each phase lands (a phase is marked DONE here with the commit that landed
it). It was written on 7 Sep 2026 from three read-only maps of the tree, each claim below
cites the file and line it was read from, and anything not verified is marked UNKNOWN.
Decision-log entry on landing: **D-547** (next free id after D-546, `docs/ROADMAP.md:786`).

The founder's decisions that fix the shape (7 Sep 2026): credits are sold in packs; a
bigger pack means a **cheaper minute**, delivered as a **falling rate, not bonus credits**;
the rate falls **faster for the Cartesia voice** than for Sarvam; the voice tier is chosen
**per agent**; credits **never expire**; each purchase's terms are **frozen on that
purchase** and spent **oldest-first**; a **₹2,000 pack** exists with Cartesia at ₹8.00.

---

## 0. Decisions — TAKEN (founder, 7 Sep 2026): every recommendation below is adopted

The founder took every recommendation in this table on 7 Sep 2026 ("you choose all the
recommended and best things for these and continue"). The table is kept so the reasoning
travels with the decision. Q1 is resolved by construction rather than by a list: the Cartesia
catalogue is BUILT FROM CARTESIA'S OWN VOICES API (`GET /voices`, the endpoint our ops probe
already hits — `ops/secret_probes.py:145-157`), filtered to Telugu / Hindi / Indian English,
and the exact field names come from the Cartesia research report commissioned the same day;
until that report lands, Phase C ships the catalogue SHAPE and refuses a Cartesia publish
with a named reason (§4.C.3).

| # | Question | Recommendation | Why it matters |
|---|---|---|---|
| Q1 | **Which Cartesia voices?** The voice library is behind login at `play.cartesia.ai/voices` (egress-blocked here; count and ids UNKNOWN). Need: voice id, display name, gender, language, for Telugu / Hindi / Indian English — at least two Telugu. | You list them; I do not invent ids. | The catalogue (`agents/voices.py`) is built from ids, and an id that does not exist publishes an agent that 422s. |
| Q2 | **Existing balances.** Every wallet today is one number plus bonus rows. On migration each becomes ONE opening lot. At what rates? | Sarvam ₹5.00 / Cartesia ₹7.00 (the ₹5,000-pack card). Nobody today was sold a Cartesia minute, so no promise is broken; anybody with a bigger balance was sold it at ₹5.00 flat, so ₹5.00 is exactly what they bought. | A migration that invents a better rate than the one sold is a gift; one that invents a worse one is a breach. |
| Q3 | **Free-amount top-ups.** `MIN_TOPUP_INR = 100` still allows any amount (`payment_routes.py:181`). Keep them? If kept, what rates does ₹3,400 get? | Keep; a free amount takes the rates of the **largest pack whose price ≤ the amount** (₹100–4,999 → ₹2,000-pack rates; ₹5,000–9,999 → ₹5,000-pack rates, etc.). Simple, monotone, and a client who tops up ₹4,999 is not punished. | Removing free amounts breaks `tests/topup.test.tsx:380` and a documented flow; a rate rule for them has to exist either way. |
| Q4 | **Grants, trial credit, refunds-as-credit.** Operator grants (`credit_routes.py:167`), trial credit, and pack-bonus rows written before this change: which rates? | List rates (₹2,000-pack tier: 5.00 / 8.00). A gift is spent at the standard price. | Otherwise a ₹50,000 grant would be a cheaper minute than a ₹50,000 purchase. |
| Q5 | **Overdraft.** The wallet already goes negative on a call (`service.py:941`, `allow_negative=True`). Under lots, which rate prices the overdraft minutes? | The rate of the lot that ran out. The next purchase repays the overdraft first, then opens its lot. | Telecom prepaid does this; it needs no new state beyond a signed balance, which we already have. |
| Q6 | **Founding-client promotion** (first pack of any size at ₹25,000-pack rates, 60 days). Build it as an operator-applied, audited **lot rate override** ("sell this lot at pack X's rates"), or leave it to manual grants? | Build the override — one admin route, audited, with the pack it borrows from named on the lot. Manual grants cannot express "cheaper minute". | It is also the mechanism for any negotiated deal later, so it is not promo-only code. |
| Q7 | **Runway on the wallet screen.** One balance can no longer print one "minutes left". Show both voices? | "About N minutes on the Sarvam voice, M on the Cartesia voice", lot by lot, cheapest lot first. | `prepaid_minutes_left` (`service.py:279`) is the runway today and divides one balance by one rate. |
| Q8 | **Refund of a partly spent lot.** Refund policy §3 refunds "unused credit … less anything you owe" (`refunds.ts:128-130`). Under lots: unspent credits refund at ₹1 face value regardless of the lot's rate? | Yes — credits are rupees; the rate was a price for minutes, not a discount on the rupee. | Keeps the Refund Policy true without rewriting it. |
| Q9 | **New-agent default voice.** | Sarvam. Cartesia is chosen, never inherited. | A default that costs the client more per minute must be a choice they made. |
| Q10 | **The Cartesia availability rule** (two clinics on Startup; the third triggers the grant/Scale decision). Enforce in code (refuse the third Cartesia agent until an operator lifts a cap) or keep it an operator practice? | Enforce: an operator-set `cartesia_agent_cap` platform setting, default 2, refusing the picker with a named reason. Silent overspend is the failure this exists for. | Without it the third clinic silently forces ₹26,312/month. |

---

## 1. What exists today, and what actually changes

The maps found more already built than the conversation assumed. Read this before the phases.

**Already live and staying:**
- **Credit packs** — `apps/api/billing/credit_packs.py` (catalogue `:154-158`: 2,000 / 5,000 / 10,000 / 25,000 / 50,000 with bonus 0/3/5/7/8%), served by `GET /v1/billing/topups/packs` and the unauthenticated `GET /v1/public/rate-card` (`payment_routes.py:430-484`, D-545), response models `CreditPackOut`/`CreditPacksOut` (`:296-330`). The top-up screen is already pack-first (`apps/web/src/app/c/[slug]/billing/TopUp.tsx`, `lib/api/billing.ts:94-103`).
- **A margin floor on every pack** — `MIN_GROSS_MARGIN = 0.20` (`rates.py:915`), `test_every_pack_holds_the_gross_margin_floor` (`tests/credit_packs_test.py`).
- **Dated list rates** — `platform_list_rates` (append-only, D-492; `billing/list_rates.py:60-131`), written only from the ops console (`ops/config_routes.py:683-718`).
- **The ledger** — `credit_ledger` (`alembic/versions/f170dbce6f47`), INSERT-only, per-tenant `pg_advisory_xact_lock` in `record_entry` (`billing/service.py:233-397`), `balance_after` denormalised, unique `(tenant_id, reason, ref)`.
- **`cartesia_api_key` as an installable platform secret** with a live probe (`ops/secret_probes.py:145-157`), alongside `sarvam_api_key`.
- **"Credits never expire"** — already published (`pricing/page.tsx:141`), contradicted by no Terms clause (`lib/legal/terms.ts`, `refunds.ts` — read in full).
- **Cartesia on Bolna** — first-class provider, `sonic-3.5` recommended (`bolna-findings/mirror/pages/providers/voice/cartesia.md:58-66`); credential store takes ONE entry named `CARTESIA` (`providers.md:146-150`).

**What changes:**
1. The pack discount moves from **bonus credits** (a second `bonus` ledger row, `payments.py:1155-1212`) to **two per-minute rates carried by the lot the pack creates**.
2. A **`credit_lots`** table is added; every credit-adding ledger row opens or tops up a lot; every debit consumes lots oldest-first at the lot's rate for the agent's voice tier.
3. A **second voice tier** (Cartesia `sonic-3.5`) enters the catalogue, the adapter, the credential store, the publish read-back, the picker, and the price.
4. The **₹15,000 pack** is added; the ladder becomes 2k / 5k / 10k / 15k / 25k / 50k.
5. The rate card, wallet, usage, runway, margin panel, pricing page, ROI calculator, Terms §6.1, and the docs all say the new thing.

**What does NOT change:** `₹1 = 1 credit`; the pack ids and the two pack endpoints; the ledger's append-only trigger and lock; D-492's rule that a closed month is never re-priced (it becomes true by construction — see §2.4); Model B (the client owns the number); the ₹5.00 Sarvam list rate on the smallest pack.

---

## 2. Domain model

### 2.1 Definitions
- **Credit**: ₹1 of prepaid value. Never expires.
- **Pack**: a catalogue row — `pack_id`, `amount_inr`, `sarvam_inr_per_min`, `cartesia_inr_per_min`. Static, bounded (`check_list_bounds` already pins the two pack endpoints as bounded by `PACK_CATALOGUE` being static, `scripts/check_list_bounds.py:286-292`).
- **Lot**: the credits one purchase (or grant, or migration) created, with the two rates frozen at creation. `credits_total`, `credits_remaining`, `sarvam_inr_per_min`, `cartesia_inr_per_min`, `source` (`topup` | `grant` | `bonus_legacy` | `migration` | `override`), `pack_id` (nullable), `override_of_pack_id` (nullable, Q6), `opened_at`.
- **Voice tier**: `sarvam` | `cartesia`, a property of the AGENT (`agents.voice_tier`, derived from the chosen voice's provider — never stored separately from the voice, §4.3).
- **Card**: the pack table in force at an instant. Dated: a new card applies to lots opened after its `effective_from`; existing lots are untouched (D-492 extended, §2.4).

### 2.2 The final card (from the founder's sign-off, 7 Sep 2026)

| pack_id | Amount | Sarvam ₹/min | Cartesia ₹/min |
|---|---|---|---|
| `starter` | ₹2,000 | 5.00 | 8.00 |
| `growth` | ₹5,000 | 5.00 | 7.00 |
| `scale` | ₹10,000 | 4.85 | 6.75 |
| `plus` | ₹15,000 | 4.70 | 6.50 |
| `pro` | ₹25,000 | 4.60 | 6.25 |
| `max` | ₹50,000 | 4.50 | 6.00 |

Floors that bind these numbers, from `billing/rates.py` and the plan arithmetic recorded in `docs/evidence/cartesia-tts-verification-2026-09-06.md`: the Sarvam worst-case cost is ₹4.12/min (fee 1.76 + STT 0.50 + LLM 0.24 + Bulbul 1.62), so no Sarvam rate may go below it — `MIN_GROSS_MARGIN` is re-pointed to check BOTH rates of every pack (§4.1). The Cartesia rate has no per-minute cost floor because its TTS cost is a monthly plan; the floor for it is the platform-wide minute count (§4.6).

### 2.3 Invariants (each becomes a test)
1. `SUM(credit_lots.credits_remaining) == wallet balance` for every tenant, when the balance is ≥ 0. A negative balance means every lot is at 0 and `overdraft_inr = -balance`.
2. A debit consumes from the lot with the smallest `opened_at` that has `credits_remaining > 0`, and splits across lots when one runs out; each split part is priced at ITS lot's rate for the call's voice tier.
3. A lot's two rates never change after creation. (No UPDATE path exists for them; the table's mutable columns are `credits_remaining` and `closed_at` only, enforced by trigger — §3.1.)
4. Overdraft minutes are priced at the rate of the last lot consumed (Q5). The next credit-adding entry reduces the overdraft first.
5. Every `usage` ledger row records, in `meta`, the lot splits it drew: `[{lot_id, credits, minutes, inr_per_min, voice_tier}]`. The month's statement and the margin panel are re-derivable from those rows alone (D-492/D-458 kept).
6. A pack's `cartesia_inr_per_min` is never below its `sarvam_inr_per_min`; both fall monotonically with `amount_inr` across the card.
7. An agent's voice tier is a pure function of its chosen voice's `provider`; there is no way to hold a Cartesia voice and a Sarvam tier.

### 2.4 What "dated" means now
Today: every call is priced at `self_serve_rate_at(month_pricing_instant(month))` (`workers/pipeline.py:2544-2557`). After: the dated card prices **lots at the moment they are opened**; the debit reads the lot. `platform_list_rates` gains rows per `(pack_id, voice_tier)` rather than one `self_serve_inr_per_min` — same table, same append-only rule, same console writer (§4.5). "Raise prices later" = record a new card; nothing already sold moves. This is also the sentence Terms §6.1 gains (§4.8).

---

## 3. Data model and migrations (hard rules 1, 4, 8)

### 3.1 `credit_lots` — new table (migration `<rev>_credit_lots`)
```
credit_lots(
  id uuid PK, tenant_id uuid NOT NULL FK organizations ON DELETE RESTRICT,
  source text NOT NULL CHECK (source IN ('topup','grant','bonus_legacy','migration','override')),
  pack_id text NULL, override_of_pack_id text NULL,
  credits_total NUMERIC(12,4) NOT NULL CHECK (credits_total > 0),
  credits_remaining NUMERIC(12,4) NOT NULL CHECK (credits_remaining >= 0 AND credits_remaining <= credits_total),
  sarvam_inr_per_min NUMERIC(12,4) NOT NULL CHECK (> 0),
  cartesia_inr_per_min NUMERIC(12,4) NOT NULL CHECK (>= sarvam_inr_per_min),
  ledger_entry_id uuid NOT NULL UNIQUE FK credit_ledger(id),   -- the row that opened it
  opened_at timestamptz NOT NULL, closed_at timestamptz NULL,
  created_at, updated_at)
```
- RLS: ENABLE + FORCE, strict `tenant_isolation` for every verb (the repo-wide shape — NOT the `OR <guc> IS NULL` form that `f2b91c47e0a3` just corrected on `kb_uploads`). Cross-tenant zero-rows test in the same migration's test file.
- Not append-only — `credits_remaining` and `closed_at` mutate — so it is NOT added to `APPEND_ONLY_TABLES`. Instead a trigger `credit_lots_terms_frozen` refuses any UPDATE that changes a column other than `credits_remaining`, `closed_at`, `updated_at` (invariant 3). `scripts/check_ledger_immutability` is not the checker for this; a new `tests/credit_lots_terms_frozen_test.py` is.
- Index `(tenant_id, opened_at, id) WHERE closed_at IS NULL` — the FIFO scan.
- Registered in `apps/api/db/registry.py` (`TENANT_TABLES`; `check_rls_coverage` refuses an unregistered tenant table).
- `credit_ledger` is UNCHANGED in shape (INSERT-only; hard rule 4). New `usage` rows carry the lot splits in `meta.lots` (invariant 5); new credit rows carry `meta.lot_id`.

### 3.2 `platform_list_rates` — extended, not replaced
Rows keyed `rate_key = 'pack:<pack_id>:<voice_tier>'` beside the existing `self_serve_inr_per_min` (`list_rates.py:58`). The old key stays readable for the transition (§10). `record_list_rate` (`:104-131`) is reused; a new `record_card(card)` writes all twelve rows in one transaction under one `effective_from`.

### 3.3 Agents — no new column
`voice_tier` is derived from the chosen voice's `provider` (`agents/voices.py:280` gains a second Literal member). Storing it twice would let them disagree; invariant 7.

### 3.4 Migration of live balances (Q2)
One-shot data migration in the same revision: for every tenant with `balance_after > 0` on its newest ledger row, open one lot `source='migration'` at the Q2 rates, `credits_total = credits_remaining = balance`, linked to a new zero-delta `adjustment` ledger row whose `meta.kind = 'lot_migration'` so the ledger records that lots began here. Negative balances open no lot (overdraft, Q5). Reversible: the downgrade deletes `credit_lots` and the marker rows; the ledger balance is untouched because no delta was written. Two-step deprecation (hard rule 8): the `bonus` reason and `_grant_pack_bonus` stop being WRITTEN in this release and are removed in the next (§10).

### 3.5 TTS price attestation (hard rule 7)
Today `tts_chars` usage rows write `qty = 1` and `unit_cost_paid = CostBreakdown.tts_inr`, the ENGINE's reported synthesizer leg cost (`workers/pipeline.py:2500-2520`, `engine/bolna.py:5487`). Under a BYOK Cartesia plan the engine's synthesizer figure is expected to be zero (we pay Cartesia, not Bolna) — **UNKNOWN until gate 51 (§9)**. So the Cartesia leg needs its own attested cost seam:
- `TtsPriceAttestation` beside `LlmPriceAttestation` (`rates.py:494`), operator-attested in the same ops panel (`ops/model_pricing.py`), value = the plan's marginal rate per 1,000 characters (Startup: ₹4,312 / 1.25M = ₹3.4496/1k, recorded as such with its evidence class).
- `qty` = agent characters spoken, counted from OUR transcript turns (the same measurement `billing/tts_speaking_rate.py` already makes), NOT from the vendor.
- `unit_cost_paid` = attested rate × qty. The plan fee itself is recorded once a month as a platform cost row (the `platform_ai_usage` shape) so the margin panel shows both the attributed cost and the true plan spend, and their difference is the plan's unused allotment.
- Until a Cartesia price is attested, `offerable_voices()` (§4.3) refuses the Cartesia tier with `NO_ATTESTED_PRICE_REASON` — the exact rule `offerable_models()` applies to an LLM (`agents/llm_models.py:452-476`).

---

## 4. Backend phases

Order is by dependency. Each phase ends with its tests green standalone and the ratchet's `ledgers-and-money` area at zero uncovered (`scripts/check_coverage_ratchet.py:410-428`, `tests/fixtures/coverage_baseline.json`).

### Phase A — the card: per-pack rates, two voices, ₹15,000
Files: `billing/credit_packs.py`, `billing/rates.py`, `billing/payment_routes.py`, `billing/list_rates.py`, `ops/config_routes.py`, tests.
1. `CreditPack` gains `sarvam_inr_per_min`, `cartesia_inr_per_min`; loses `bonus_pct`/`bonus_credits` (kept on the wire as deprecated zero fields for one release — §10). `PACK_CATALOGUE` becomes the §2.2 table; `plus` (₹15,000) added.
2. `CreditPackOut` gains the two rates and `talk_time_minutes` becomes a pair (`sarvam_minutes`, `cartesia_minutes`); `CreditPacksOut.list_rate_inr_per_min` stays (= `starter.sarvam`), `from_inr_per_min` becomes `from_sarvam_inr_per_min` + `from_cartesia_inr_per_min`. The OpenAPI snapshot is regenerated (`check_openapi_fresh --write`, then `pnpm -C apps/web gen:api`).
3. `MIN_GROSS_MARGIN` check runs for `sarvam_inr_per_min` against `SELF_SERVE_COST_FLOOR_INR_PER_MIN` (`rates.py:895`, re-derived without telephony — the client pays Plivo, D-474) and for `cartesia_inr_per_min` against the ex-plan floor plus the plan-per-minute at the platform-wide break-even count (§4.6). Invariant 6 asserted.
4. `platform_list_rates` gains the twelve `pack:*:*` keys; `record_card` writes them; the ops console's rate write (`config_routes.py:683-718`) becomes a card write with a preview of every margin before commit.
5. `rates.py` module prose (`:1-24, 65-70, 103, 778`), `credit_packs.py` prose (`:1-46, 130-158`), `voices.py:14` — rewritten; `scripts/check_docs_drift.py` §4b gains the second TTS rung so TRD §10.1 and `rates.py` are compared on both.

### Phase B — lots and the FIFO debit
Files: `billing/models.py`, `billing/service.py`, `billing/lots.py` (new), `workers/pipeline.py`, `billing/payments.py`, `billing/credit_routes.py`, `billing/ai_quota.py`, `compliance/service.py`, migration, tests.
1. `billing/lots.py`: `open_lot(session, tenant_id, *, credits, rates, source, pack_id, ledger_entry_id)` and `consume(session, tenant_id, *, minutes, voice_tier, call_id) -> list[LotSplit]`. Both run INSIDE the caller's transaction and INSIDE the existing per-tenant advisory lock (`service.py:233-248`); `consume` reads open lots FIFO with `FOR UPDATE`, decrements with a CAS `UPDATE ... WHERE credits_remaining = :seen` (BACKEND-PATTERNS §5), closes a lot at zero.
2. `record_entry` (`service.py:305-397`) is not changed; a new `record_usage_from_lots` wraps it: computes the rupee delta as the SUM of splits, writes one `usage` row with `meta.lots`, and the overdraft part (if any) priced at the last split's rate (Q5). Idempotency is the existing `(tenant_id,'usage',call_id)` unique (`service.py:917-935`) — a replay finds the row and makes no second consumption.
3. `workers/pipeline.py:2496-2662`: the call's `minutes` and the agent's `voice_tier` (from the call's `tts_voice`, already stamped at `:2485`) go to `record_usage_from_lots`; `prepaid_billed_inr(minutes, self_serve_rate)` (`rates.py:1062`) is no longer the price of a self-serve call — it survives only for the `bonus_legacy`/trial paths and is deleted in §10.
4. Every credit-adding writer opens a lot in the same transaction: Razorpay capture (`payments.py:1109-1116`, rates from the pack or Q3 rule for a free amount), admin top-up and restatement (`credit_routes.py:819, 1222` — a restatement adjusts the lot's `credits_total` and `credits_remaining` by the same delta, never its rates), grants (`credit_routes.py:1388`, Q4 rates), trial credit. `_grant_pack_bonus` (`payments.py:1155-1212`) is retired (§10).
5. Overdraft repayment: a credit-adding entry on a negative balance first books `min(credits, overdraft)` as repayment (no lot), then opens the lot with the remainder (Q5).
6. `credits_exhausted` (`compliance/service.py:392-440`) is unchanged (balance ≤ 0). `prepaid_minutes_left` (`service.py:279-301`) becomes `runway(tenant) -> {sarvam_minutes, cartesia_minutes}` summed lot by lot (Q7).
7. `ai_quota.py:1189-1196` debits the same wallet in rupees, not minutes: it consumes lots FIFO at face value (₹1 = 1 credit), no rate. Documented in the lot split as `voice_tier = NULL`.
8. Tests (each a file, per BACKEND-PATTERNS §9): FIFO order; a split across two lots priced at two rates; a debit larger than all lots (overdraft, priced at the last lot's rate); repayment then lot open on the next top-up; replay makes no second consumption; a lot's rates cannot be updated (trigger); cross-tenant zero rows; invariant 1 after a randomised sequence of top-ups and debits; the migration opens one lot per positive balance and none for a negative one.

### Phase C — the Cartesia voice tier
Files: `agents/voices.py`, `agents/voice_routes.py`, `agents/verification.py`, `engine/bolna.py`, `agents/llm_models.py` (pattern) → `agents/voice_offer.py` (new), `core/platform_config.py`, `packages/shared/.../engine.py`, `packages/shared/.../model_lifecycle.py` (or a TTS twin), tests + conformance.
1. **Catalogue**: `TtsModel = Literal["bulbul:v3", "sonic-3.5"]`; `Voice.provider: Literal["sarvam","cartesia"]`; Cartesia entries from Q1 with `voice_id_for()` unchanged in shape (`"sonic-3.5:<voice_id>"`). `sonic-3` is deliberately NOT in the catalogue (Bolna: use 3.5 in production, `cartesia.md:66`; a sunset of 20 Oct 2026 for `sonic-3` is REPORTED by Comet from `docs.cartesia.ai` and is NOT on Bolna's page — recorded as REPORTED, not asserted). The `_NOTE` at `voices.py:306` stops hardcoding ₹30/10k.
2. **Offerability**: `offerable_voices()` mirrors `offerable_models()` (`llm_models.py:452-500`): a Cartesia voice is offered only when `cartesia_api_key` is installed (`secret_probes.py:145`), a Cartesia price is attested (§3.5), AND the `cartesia_agent_cap` (Q10) is not exceeded — each refusal a named reason the picker renders. `GET /v1/agents/voices` (`voice_routes.py:230`) returns the reason per unavailable voice, never a shorter list.
3. **Adapter**: `_synthesizer_config` (`bolna.py:536-570`) gains a per-provider shape; the Cartesia `provider_config` field names are **ABSENT from the pinned mirror** (OAS `Synthesizer.provider` enum is `[polly, elevenlabs, deepgram, styletts]`, `create.md:640-644`, already narrower than what ships) — so the Cartesia block is written as the best reading of `cartesia.md` and **fails LOUD at publish (422 → `engine_rejected`) until gate 50 (§9) records the real shape**. No guess is silently sent.
4. **Credential**: `set_llm_credential` (`bolna.py:4593-4677`) is `require_capability("llm")`-gated; a `set_tts_credential` twin installs the ONE `CARTESIA` entry (`providers.md:146-150`). `Settings` gains `bolna_tts_credential_name` (`applies: live`, default `CARTESIA`) beside `bolna_llm_credential_name` (`platform_config.py:548`).
5. **Publish read-back**: `verification.py:169-304` diffs the SPEAKER only; it now diffs `tts_provider` and `tts_model` too (`_agent_models`, `bolna.py:2500-2521`, already reads them back), so a Cartesia agent that the engine holds as Sarvam is `voice_applied=False`. `AgentSnapshot.holds_speech("tts")` (`engine.py:3150-3164`) returns `(provider, model, voice)` for the TTS leg.
6. **Lifecycle**: `check_model_lifecycle` is LLM-only and closed (`scripts/check_model_lifecycle.py:118-126`). A `TTS_MODEL_LIFECYCLE` table with the same `retirement_stance` field is added for `bulbul:v3` and `sonic-3.5` (both "vendor announced nothing", class VERIFIED-VENDOR-DOCS from the mirror), and the checker gains the second table rather than a second script.
7. **Conformance**: `packages/shared/tests/engine_conformance/contract_test.py:79-85,1263` pin one TTS model; extended to require both adapters (bolna, fake) to round-trip both providers.
8. `voice_tier(agent)` helper = provider of its voice; the pipeline stamps `meta.tts_tier` with it (`pipeline.py:2484` currently the constant `"premium"`; `BASE_OVERAGE_RUNG`/`_RUNGS` (`service.py:1190-1197`) are re-pointed to `("sarvam","cartesia","")`).

### Phase D — Cartesia metering and the margin panel
Files: `billing/rates.py`, `ops/model_pricing.py`, `workers/pipeline.py`, `billing/service.py` (margin SQL), `billing/attribution.py`, `billing/cost_unit.py`, `crm/schemas.py` (`UsagePanelOut`), tests.
1. §3.5's `TtsPriceAttestation`, ops attestation panel entry, and `tts_price_is_billable("cartesia")`.
2. Pipeline: for a Cartesia call, `tts_chars` row `qty` = agent characters from transcript, `unit_cost_paid` = attested rate × qty; for a Sarvam call the existing engine-leg figure stays (its own attestation question is gate 7, `docs/OPERATIONS.md:88`, unchanged).
3. Monthly `cartesia_plan` platform cost row (operator-attested amount, once per IST month) so the spend board shows plan spend vs attributed.
4. `calling_revenue_inr` (`service.py:2194-2231`) takes the lot splits' sum instead of `(minutes × one rate)`; `_ROW_TIER_SQL` (`:1233`) reads the new tier spellings; `UsagePanelOut` gains `sarvam_minutes`, `cartesia_minutes`, and their charges, still with NO total computed in the browser (D-458).

### Phase E — the public rate card and API shapes
Files: `billing/payment_routes.py`, `apps/web/src/lib/api/rateCard.ts`, OpenAPI snapshot, `tests/public_rate_card_test.py`, `tests/list_bounds_guard_test.py`.
1. `GET /v1/public/rate-card` returns both rates per pack; still bounded by the static catalogue; still `public, max-age=60`.
2. `isRateCard` (`rateCard.ts:125-143`) validates the new fields as money strings; `cheapestPack` becomes per-voice.

### Phase F — Terms and the legal register
Files: `apps/web/src/lib/legal/terms.ts` §6.1, `refunds.ts` §1/§3 wording, `versions.ts`, `apps/web/tests/legal.test.tsx`, `tests/legalRegister.test.ts`, `tests/legal_agreements_test.py`.
1. §6.1 gains: *"Each purchase of credit is priced at the per-minute rates shown for that purchase when you made it, for the voice each agent uses. Those rates apply to that purchase's credit until it is spent, and a later change to our rate card does not change them. Credit does not expire. Credit is spent oldest purchase first."* — the founder approves the wording before the version bump.
2. §6.1's *"not the rate your credit balance is drawn down at"* (`terms.ts:326`) and Refunds §1 (`refunds.ts:56-59`) are reworded to the plural ("the rates").
3. ⚠ `mergewt/` is a stale worktree holding duplicate legal files and tests; nothing is edited there.

---

## 5. Frontend phases

Ownership for parallel lanes is by directory; the pricing page and the wallet hub are separate lanes.

### F1 — Wallet hub (`apps/web/src/app/c/[slug]/billing/**`)
- `TopUp.tsx`: the pack cards show **two rates per pack** and two talk-time figures; the "Extra credit" column goes (`pricing/page.tsx:188` has the same column). A free amount shows the rule from Q3 in words before the Razorpay button.
- `WalletHero.tsx` / `CreditsTab.tsx` / `OverviewTab.tsx`: balance stays rupees; runway becomes the Q7 pair; a new **Lots** list (open lots, oldest first, each with its two rates and remaining credits) — the sentence a client reads is *"3,200 credits at ₹4.70 / ₹6.50, then 2,000 at ₹5.00 / ₹8.00"*.
- `WhatCallsCost.tsx:26-53,132`: "one voice, one rate" and its rationale are rewritten around the two voices; `UsageTab.tsx:154-223`: the legacy "reduced rate (NULL on every plan)" pair is replaced by Sarvam/Cartesia minutes and charges from `UsagePanelOut`.
- `TransactionsTab.tsx`: a `usage` entry expands to its lot splits.
- Tests to re-point: `tests/topup.test.tsx:380-564`, `tests/credits.test.tsx:205-626`, `tests/spend.test.tsx:301-531`, `tests/billingHub.tsx`.

### F2 — Pricing page, homepage, ROI (`apps/web/src/app/pricing`, `/`, `/roi`, `components/marketing/**`)
- `pricing/page.tsx`: the stale header doc (`:20-52`) goes; the lede prints both "from" rates; the pack table has both rate columns; `METERED[1]` (`:70-77`, "two voice tiers, a plan can quote them") is rewritten for the per-agent meaning; `PLAN_SHAPE` (`:100-105`) likewise.
- Provenance test (`tests/marketingPages.test.tsx:200-241`): `fromCard` is extended to both rate fields per pack — the rule (every ₹ figure on the page must be one the API sent) is unchanged. Fixture `tests/fixtures/rateCard.ts:17-30` gains `plus` and the second rate.
- ROI calculator (`components/marketing/roiCalculator.tsx`, `lib/roi.ts:173-212`): gains a voice choice; `calevatePaisePerMin` is fed from the chosen voice's rate on the chosen pack; `tests/roi.test.ts:31-53` re-pointed.

### F3 — Agent voice (admin picker + client display)
- Admin: `admin/tenants/[tenantId]/agents/[agentId]/prompt/page.tsx:1116-1176` (`VoicePanel`) groups voices by provider, shows each voice's per-minute rate on the client's OPEN lots (cheapest first), and renders the `offerable_voices` refusal reason for an unavailable Cartesia voice. Copy at `:1143` rewritten.
- Client: `c/[slug]/agents/panels/publishing.tsx:136-198` (`VoiceFacts`) shows the tier and its rate; `:138-139` rewritten.
- `lib/api/voices.ts:4,68-82` types regenerate; `tests/agentVoice.test.tsx:15,73,190-450`, `tests/agentDetail.test.tsx:122,348,352` re-pointed.

### F4 — Admin console
- `admin/ops/ConfigPanel.tsx`: the list-rate write becomes a card editor with a margin preview per cell (Phase A.4); `ModelPricingPanel.tsx` gains the Cartesia TTS attestation row (Phase D.1).
- `admin/tenants/[tenantId]/credits/page.tsx`: grants and restatements show the lot they open/adjust; the Q6 override control ("sell at pack X's rates"), audited.
- `admin/spend/page.tsx`: Cartesia plan spend vs attributed; the "TTS speaking rate — measured" card now feeds `qty` for Cartesia rows (Phase D.2).

---

## 6. Documents to update (in the same commits as the code they describe)

| Document | What changes |
|---|---|
| `docs/TRD.md` §10 | `:1365-1367, 1468-1469, 1488-1500` "one voice quality, one rate" → two tiers, per-lot rates; §10.1's TTS table gains the Cartesia rung; `:1305` Cartesia "eliminated as orchestrator" stays, with a new line that it is ADOPTED as a TTS vendor; the rate card table (§2.2) replaces the ₹5.00 sentence. `check_docs_drift` §4b/§4e must pass on both rungs. |
| `docs/BRD.md` | `:104-114, 192, 206-209` pricing rationale → the pack card; R-10 (`:264`) still describes v2 as a lever — rewritten. |
| `docs/DATA-MODEL.md` | `:617-653` `credit_ledger` section gains `credit_lots` (§3.1) and the `meta.lots` shape; the balance derivation sentence gains invariant 1. |
| `docs/FLOWS.md` | Has NO billing/top-up flow today (grep confirmed). A new "Buy credit → lot → call → debit" flow section, with the overdraft and repayment branches. |
| `docs/OPERATIONS.md` §2 | Gate 12 (`:94`) (h) TTS speaking rate now also feeds Cartesia `qty`; new gates 50–52 (§9). |
| `docs/ROADMAP.md` | **D-547** (this plan) — supersedes the un-numbered "single-tier voice decision" cited at `rates.py:3`, `TRD:1365`; extends D-492 (rates per lot) and D-545 (card shape). |
| `docs/BUILD-LOG.md` | One entry per phase landed. |
| `docs/SECURITY-COMPLIANCE.md` | Nothing on pricing; only the sub-processor list gains Cartesia (already present in `lib/legal/subprocessors.ts`? — `:125-126` lists Sarvam; Cartesia's entry, data-handling terms from `cartesia-tts-verification-2026-09-06.md` §A5, is added in Phase F). |
| `apps/api/billing/credit_packs.py`, `rates.py`, `agents/voices.py` prose | Rewritten in Phase A/C (the docstrings are the doc for those modules). |
| `CLAUDE.md` | No pricing sentence to fix (grep confirmed); the Sarvam/"one voice" paragraph in the header is about the SPEECH posture, not price, and is left. |

---

## 7. Tests and guards that will break, and what re-points them

Backend (`tests/`): `credit_packs_test.py:58-354` (ladder, "five rupees", bonus-once → per-lot rates, margin on both), `self_serve_list_rate_test.py:205-459` (one rate per month → one CARD per instant), `public_rate_card_test.py`, `client_rate_billing_test.py:97-228`, `margin_prepaid_revenue_test.py`, `plan_tier_split_test.py`, `tts_tier_metering_test.py:37-211` (tier spellings), `tts_rate_card_drift_test.py:60-103` (second rung), `money_walk_test.py:125`, `cost_partition_test.py:86`, `margin_cost_definition_test.py:46,110`, `llm_model_surcharge_test.py:180,530`, `spend_attribution_test.py:162`, `wallet_test.py`, `billing_surfaces_test.py`, `response_shape_test.py`, `money_wire_quantization_test.py`, `agent_voice_test.py:242-541` ("one voice quality" assertion), `list_bounds_guard_test.py`, `packages/shared/tests/engine_conformance/contract_test.py:79-85,1263`, `absent_tenant_answer_test.py` (every new route joins `BODIES`).
Guards (`scripts/`): `check_rls_coverage` (new table registered), `check_ledger_immutability` (unchanged set), `check_list_bounds` (rate card still static), `check_docs_drift` §4b/§4e (two rungs), `check_model_lifecycle` (TTS table), `check_openapi_fresh` (snapshot), `check_half_wired` (every new column read), `check_metadata_columns`, `check_raw_sql` (the FIFO SQL is literal-derived).
Web (`apps/web/tests/`): listed per F1–F4 above, plus `legal.test.tsx`, `legalRegister.test.ts`.
Ratchet: `ledgers-and-money` at ZERO uncovered — every FIFO branch, every overdraft branch, every refusal reason in `offerable_voices`, tested; no `# pragma: no cover` on any of it.

---

## 8. Sequencing and parallel lanes

```
A (card)  ──►  B (lots + debit)  ──►  D (Cartesia metering)  ──►  E (rate card wire) ──► F (Terms)
                 │                        ▲
                 └──► C (voice tier) ─────┘        Frontend F1..F4 start after E's OpenAPI snapshot.
```
- A and C are independent of each other and can run as two lanes; B depends on A (rates on the pack); D depends on B and C; E on A+D; the frontend on E's regenerated types.
- File ownership for lanes: A = `billing/credit_packs.py, rates.py (constants), payment_routes.py, list_rates.py, ops/config_routes.py`; C = `agents/voices.py, voice_routes.py, verification.py, engine/bolna.py, agents/voice_offer.py, shared engine.py + lifecycle`; B = `billing/lots.py, service.py, models.py, payments.py, credit_routes.py, ai_quota.py, workers/pipeline.py, migration`.
- One gate run (`make db-reset && make redis-reset && make coverage-ratchet`) at the end of each merged phase, never in parallel lanes (hard rule 10).

---

## 9. Operations gates this plan opens (live Bolna + Cartesia account; not code)

| # | Question | Why it blocks |
|---|---|---|
| 50 | (exists) graph-agent read-back — unchanged. | — |
| 51 | **Does a BYOK Cartesia call's `cost_breakdown.synthesizer` read 0 on Bolna, and is `synthesizer_characters` populated?** One call, read the execution. | Decides whether §3.5's transcript-counted `qty` is the only source (expected) or the vendor's count is usable. |
| 52 | **The Cartesia `provider_config` field names on `POST /v2/agent`** — voice id key, model key, language handling. Absent from the pinned mirror. One CREATE with the Phase C block; record the 200 or the 422 body. | Until recorded, every Cartesia publish fails loud by design (Phase C.3). |
| 53 | **Cartesia concurrency under load**: 10 simultaneous Cartesia agents speaking, Startup plan (5 contexts) — count 429s. | The tier's availability rule (Q10) is set from this, not from the vendor's rule of thumb. |
| 25 | (exists) `/inbound/setup` with a Plivo `phone_number_id` — unchanged, still the one unverified link in the number chain. | — |

---

## 10. Two-step deprecation and rollback (hard rule 8)

- **Release 1 (this plan):** `bonus` ledger reason stays in the CHECK and `CREDIT_REASONS`; nothing writes it. `bonus_pct`/`bonus_credits` stay on the wire as `0`, marked deprecated in the OpenAPI description. `self_serve_inr_per_min` stays readable (`= starter.sarvam`) so every old reader keeps working; `Settings.self_serve_inr_per_min` stays as the fallback `list_rates.py:96-97` uses.
- **Release 2:** remove the deprecated wire fields, `_grant_pack_bonus`, `prepaid_billed_inr`'s single-rate path, and the `bonus` reason from the CHECK (migration with downgrade).
- **Rollback of release 1:** the migration's downgrade drops `credit_lots` and the marker rows; the ledger and every balance are untouched because lots never wrote a delta; the previous release's debit path re-prices new calls at `self_serve_inr_per_min`, which still resolves. Lots opened between upgrade and rollback lose their frozen rates — the rollback runbook says so (`runbooks/deploy-failed.md` §4 gains the sentence).

---

## 11. Definition of done

- A clinic buys a ₹15,000 pack and sees 3,191 Sarvam minutes / 2,307 Cartesia minutes and two rates on its wallet; a second ₹2,000 pack appears BEHIND it with its own rates.
- A call on a Cartesia agent debits FIFO at the oldest lot's Cartesia rate, splits across lots when one runs out, and the ledger row shows the splits.
- A wallet driven negative is repaid by the next top-up before a new lot opens.
- The public rate card shows both rates per pack and every ₹ figure on the marketing pages comes from it (the provenance test unchanged in spirit).
- The admin can attest the Cartesia price, install the key, see Cartesia voices become offerable, pick one for an agent, publish, and the read-back diffs provider, model and voice.
- The margin panel shows Sarvam and Cartesia minutes, revenue by lot splits, attributed Cartesia TTS cost and the plan fee side by side.
- Terms §6.1 states the lot promise and the version register carries the bump.
- `make coverage-ratchet` green with `ledgers-and-money` at zero; every guard in §7 green; D-547 in ROADMAP; TRD/BRD/DATA-MODEL/FLOWS/OPERATIONS updated in the same commits.
- Gates 51–53 filed in OPERATIONS §2 and NOT claimed as done.
