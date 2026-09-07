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

### Phase A — DONE (uncommitted, 7 Sep 2026)

The catalogue is six packs x two rates with `plus` (₹15,000) in the ladder, the margin guard judges each rate against its own re-derived, telephony-free cost floor (Sarvam ₹4.1211 / Cartesia ₹4.3639 — the whole Sarvam column clears cost and sits under the 20% target, deliberately), `platform_list_rates` takes twelve `pack:*:*` rows per card under one `effective_from` written from the ops console behind a margin preview and a refusal, and every deprecated wire field stays at zero for one release.
Files: `billing/credit_packs.py`, `billing/rates.py`, `billing/payment_routes.py`, `billing/list_rates.py`, `ops/config_routes.py`, tests.
1. `CreditPack` gains `sarvam_inr_per_min`, `cartesia_inr_per_min`; loses `bonus_pct`/`bonus_credits` (kept on the wire as deprecated zero fields for one release — §10). `PACK_CATALOGUE` becomes the §2.2 table; `plus` (₹15,000) added.
2. `CreditPackOut` gains the two rates and `talk_time_minutes` becomes a pair (`sarvam_minutes`, `cartesia_minutes`); `CreditPacksOut.list_rate_inr_per_min` stays (= `starter.sarvam`), `from_inr_per_min` becomes `from_sarvam_inr_per_min` + `from_cartesia_inr_per_min`. The OpenAPI snapshot is regenerated (`check_openapi_fresh --write`, then `pnpm -C apps/web gen:api`).
3. `MIN_GROSS_MARGIN` check runs for `sarvam_inr_per_min` against `SELF_SERVE_COST_FLOOR_INR_PER_MIN` (`rates.py:895`, re-derived without telephony — the client pays Plivo, D-474) and for `cartesia_inr_per_min` against the ex-plan floor plus the plan-per-minute at the platform-wide break-even count (§4.6). Invariant 6 asserted.
4. `platform_list_rates` gains the twelve `pack:*:*` keys; `record_card` writes them; the ops console's rate write (`config_routes.py:683-718`) becomes a card write with a preview of every margin before commit.
5. `rates.py` module prose (`:1-24, 65-70, 103, 778`), `credit_packs.py` prose (`:1-46, 130-158`), `voices.py:14` — rewritten; `scripts/check_docs_drift.py` §4b gains the second TTS rung so TRD §10.1 and `rates.py` are compared on both.

### Phase B — lots and the FIFO debit
B1 — DONE (uncommitted, 7 Sep 2026): table, migration, lots.py, tests. B2 (callers) pending Phase A.

Files: `billing/models.py`, `billing/service.py`, `billing/lots.py` (new), `workers/pipeline.py`, `billing/payments.py`, `billing/credit_routes.py`, `billing/ai_quota.py`, `compliance/service.py`, migration, tests.
1. `billing/lots.py`: `open_lot(session, tenant_id, *, credits, rates, source, pack_id, ledger_entry_id)` and `consume(session, tenant_id, *, minutes, voice_tier, call_id) -> list[LotSplit]`. Both run INSIDE the caller's transaction and INSIDE the existing per-tenant advisory lock (`service.py:233-248`); `consume` reads open lots FIFO with `FOR UPDATE`, decrements with a CAS `UPDATE ... WHERE credits_remaining = :seen` (BACKEND-PATTERNS §5), closes a lot at zero.
2. `record_entry` (`service.py:305-397`) is not changed; a new `record_usage_from_lots` wraps it: computes the rupee delta as the SUM of splits, writes one `usage` row with `meta.lots`, and the overdraft part (if any) priced at the last split's rate (Q5). Idempotency is the existing `(tenant_id,'usage',call_id)` unique (`service.py:917-935`) — a replay finds the row and makes no second consumption.
3. `workers/pipeline.py:2496-2662`: the call's `minutes` and the agent's `voice_tier` (from the call's `tts_voice`, already stamped at `:2485`) go to `record_usage_from_lots`; `prepaid_billed_inr(minutes, self_serve_rate)` (`rates.py:1062`) is no longer the price of a self-serve call — it survives only for the `bonus_legacy`/trial paths and is deleted in §10.
4. Every credit-adding writer opens a lot in the same transaction: Razorpay capture (`payments.py:1109-1116`, rates from the pack or Q3 rule for a free amount), admin top-up and restatement (`credit_routes.py:819, 1222` — a restatement adjusts the lot's `credits_total` and `credits_remaining` by the same delta, never its rates), grants (`credit_routes.py:1388`, Q4 rates), trial credit. `_grant_pack_bonus` (`payments.py:1155-1212`) is retired (§10).
5. Overdraft repayment: a credit-adding entry on a negative balance first books `min(credits, overdraft)` as repayment (no lot), then opens the lot with the remainder (Q5).
6. `credits_exhausted` (`compliance/service.py:392-440`) is unchanged (balance ≤ 0). `prepaid_minutes_left` (`service.py:279-301`) becomes `runway(tenant) -> {sarvam_minutes, cartesia_minutes}` summed lot by lot (Q7).
7. `ai_quota.py:1189-1196` debits the same wallet in rupees, not minutes: it consumes lots FIFO at face value (₹1 = 1 credit), no rate. Documented in the lot split as `voice_tier = NULL`.
8. Tests (each a file, per BACKEND-PATTERNS §9): FIFO order; a split across two lots priced at two rates; a debit larger than all lots (overdraft, priced at the last lot's rate); repayment then lot open on the next top-up; replay makes no second consumption; a lot's rates cannot be updated (trigger); cross-tenant zero rows; invariant 1 after a randomised sequence of top-ups and debits; the migration opens one lot per positive balance and none for a negative one.

### Phase C — PARTIAL DONE (uncommitted, 7 Sep 2026): C.1,2,3,4,5,6,7,8-helper; C.3 built to ADDENDUM 3's schema, gate 52 narrowed to hosted-platform acceptance
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

---

# ADDENDUM 1 — What the Cartesia research run settled (7 Sep 2026)

⚠ **THE DELIVERED REPORT IS THE PRICING/COST-REDUCTION RUN, NOT THE API DEEP-DIVE.** It is
the same document already filed at `docs/evidence/cartesia-tts-verification-2026-09-06.md`.
It does NOT contain the request/response schemas, the `provider_config` field names, or the
voices-API shape. **So the two facts that block a Cartesia publish are STILL UNKNOWN**, and
Phase C's fail-loud design (C.3) stands unchanged. What follows is only what it upgraded.

## Now VERIFIED from Cartesia's own docs (was REPORTED)
- **`sonic-3` is deprecated with sunset 20 Oct 2026**, snapshot `sonic-3-2025-10-27`;
  `sonic-2` and `sonic-turbo` share that date; `sonic`, `sonic-english` and
  `sonic-multilingual` were already sunset 1 Jun 2026
  (docs.cartesia.ai/build-with-cartesia/tts-models/api-changes, read 7 Sep 2026).
  → Phase C.1's "sonic-3 is deliberately absent" note upgrades its class from REPORTED to
  VERIFIED, and `TTS_MODEL_LIFECYCLE` (C.6) records the date rather than an absence.
- **`sonic-3.5` snapshot is `sonic-3.5-2026-05-04`, stable, NO announced retirement.** It
  stays our model id.
- **Telugu (`te`) is on the per-snapshot language list** for `sonic-3.5-2026-05-04` (42
  languages) and `sonic-3.6-2026-08-27` (44) — not merely a homepage count.

## New facts that change a design detail
- **`sonic-3.6` is STABLE on Cartesia's side with no retirement date**, while Bolna's page
  calls its `sonic-preview` "Sonic 3.6 (Beta)" and tells you to use `sonic-3.5` in
  production (`bolna-findings/mirror/pages/providers/voice/cartesia.md:58-66`).
  **CONTRADICTION, recorded not resolved.** We send the id BOLNA accepts, so the catalogue
  stays on `sonic-3.5`; `TTS_MODEL_LIFECYCLE` carries both with the disagreement in the
  comment. Revisit when gate 52 runs.
- **Concurrency is counted per unique `context_id`, not per WebSocket or per utterance**,
  and up to 10× the concurrency limit may be open as connections. Exceeding either returns
  **429 with no queueing** — dead air on a live call. Idle WebSocket connections are closed
  after **5 minutes**.
  → This is the evidence behind Q10's `cartesia_agent_cap` (C.2). The cap's docstring cites
  it, and gate 53 (load test) is what sets the number rather than the vendor's
  "one unit ≈ four conversations" rule of thumb.
- **Hinglish code-switching is documented; Telugu-English is NOT** ("absent from docs", not
  "unsupported"). → The voice catalogue's Telugu entries carry that caveat, and the agent
  screen must not promise Telugu-English mixing.
- **Pro Voice Cloning bills 1.5 credits/character**, a 50% premium. → If a cloned voice is
  ever offered, it is a THIRD rate on the pack, not the Cartesia rate. Out of scope here;
  named so nobody assumes parity.
- **Cartesia publishes a caching pattern** — pre-generate stock phrases as raw PCM, cache,
  splice into the live stream; "cached clips skip the API, so those segments are faster and
  free", and the clip must match the live stream's encoding and sample rate exactly
  (docs.cartesia.ai/build-with-cartesia/capability-guides/tts-caching, 21 Jul 2026).
  → This is OUR-side engineering and needs control of the audio stream, which under Bolna
  we do not have. It stays what it was: the graph-agent static node (OPERATIONS gate 50) is
  the only zero-TTS path on this engine. Recorded so the two are not confused.

## Data handling — now enough to write the sub-processor entry (Phase F)
- Privacy policy permits training on submitted content with a **prospective-only opt-out
  form**; **Zero Data Retention is Enterprise-only**, so on our plan retention is governed
  by the DPA rather than by ZDR; DPA is published at `cartesia.ai/legal/dpa`; SOC 2 Type II
  / HIPAA / PCI-DSS / GDPR are asserted with the reports behind a Trust Center request.
- ⚠ The privacy policy states the Services **"are designed for users in the United States
  only and are not intended for users located outside the United States."** That is a real
  clause for an Indian customer and belongs in `/legal/subprocessors` beside the Sarvam
  entry, stated plainly rather than paraphrased.

## Still UNKNOWN, and each still blocks what it blocked before
| # | Unknown | Blocks | Closes by |
|---|---|---|---|
| 1 | Cartesia `provider_config` field names on Bolna's `POST /v2/agent` | any Cartesia publish (C.3 refuses by name) | OPERATIONS gate 52 — one CREATE, record the 200 or the 422 |
| 2 | Telugu voice ids, names, genders | the catalogue's Cartesia entries (C.1 ships the loader EMPTY) | log in to `play.cartesia.ai/voices`, filter Telugu; or the voices API once its shape is known |
| 3 | Overage rate per credit past the allotment | the margin floor's worst case (A.3 uses the plan rate; overage would be dearer) | `cartesia.ai/pricing` FAQ or support@cartesia.ai |
| 4 | Whether a BYOK Cartesia call reports `synthesizer` cost 0 on Bolna | Phase D's `qty`/`unit_cost_paid` seam | OPERATIONS gate 51 |
| 5 | Whether the DPA is self-serve signable on Startup | Phase F's sub-processor entry wording | `play.cartesia.ai/settings` |

---

# ADDENDUM 2 — Two holes the documentation review found in Phase B (7 Sep 2026)

Writing DATA-MODEL and FLOWS against §2.3 and §3.4 exposed two places where the spec did not
say enough to implement. Both are fixed here BEFORE Phase B starts. **These supersede the
sentences they name.**

## 2.1 A `meta.lots` split gets a `kind`, and non-call splits carry no minutes

**The hole**: §2.3 invariant 5 fixes a split as `{lot_id, credits, minutes, inr_per_min,
voice_tier}`, and §4.B.7 says the dashboard-AI quota debit records `voice_tier = NULL` —
without saying what `minutes` and `inr_per_min` hold on such a split. Anything summing
`minutes` across a month's splits would then be adding an unspecified value.

**The fix — an explicit discriminator, not a null anybody has to interpret.** Every split
carries `kind`:

- `kind: "call"` → `{kind, lot_id, credits, minutes, inr_per_min, voice_tier}`. All six keys
  present; `voice_tier` is `"sarvam"` or `"cartesia"`.
- `kind: "ai_assist"` → `{kind, lot_id, credits}`. **`minutes`, `inr_per_min` and
  `voice_tier` are ABSENT, not null.** The dashboard-AI debit buys rupees of assistance, not
  minutes of talk time; there is no rate and no voice, and a key whose null means "not
  applicable" is the tri-state defect `AgentSnapshot.*_readable` exists to avoid.

A reader that totals talk minutes filters `kind == "call"`; one that totals money sums
`credits` across every split regardless of kind. `SUM(credits)` over a row's splits always
equals that row's `delta` (invariant 5 keeps that, unchanged).

## 2.2 A downward restatement floors at zero and the shortfall becomes overdraft

**The hole**: §3.4 says a restatement adjusts a lot's `credits_total` and `credits_remaining`
"by the same delta". Moving both by the same delta preserves `credits_remaining <=
credits_total` — but NOT `credits_remaining >= 0`. A lot of 5,000 with 1,000 left, restated
down by 2,000, would need `credits_remaining = -1,000` and the CHECK would refuse the write.
That is a real production stop, on the path an operator uses to correct a mis-recorded
payment.

**The fix**: a restatement of `-D` on a lot with `R` remaining and `T` total sets
`credits_total = T - D` and `credits_remaining = max(R - D, 0)`, closing the lot when the
remainder is zero. The shortfall `max(D - R, 0)` is **not** absorbed by the lot — it becomes
wallet overdraft, which is a balance-level fact the ledger already carries and which Q5's
rule repays from the next purchase before a new lot opens.

Worked: we recorded ₹10,000, the bank shows ₹8,000, the client has already spent ₹9,000.
`T: 10,000 → 8,000`; `R: 1,000 → 0`; lot closed; wallet balance `1,000 → -1,000`. The client
owes ₹1,000, the next top-up clears it first, and no CHECK is violated. An upward
restatement is the ordinary case: both rise by the delta and the lot may reopen if it had
closed.

**Invariant §2.3.1 already covers the result** ("a negative balance means every lot is at 0
and `overdraft_inr = -balance`") — this addendum says how a restatement gets there. Both
directions, and the CHECK-violating case as a regression test, are Phase B tests.

## Also recorded from the same review
- FLOWS' new billing section is **§11, not §9** — `runbooks/database-restore.md:327` cites
  "FLOWS §9" for the deletion flow, and renumbering would break a runbook a human reads
  during an incident.
- TRD §10.1's Cartesia TTS rung must land in the SAME commit as `billing/rates.py`
  (`check_docs_drift` §4b compares them); the attested figure is the Startup plan's
  **₹3.4496 / 1,000 chars**. Phase A owns both halves.

---

# ADDENDUM 3 — The wire-level answers (7 Sep 2026). C.3 IS NOW BUILDABLE.

The API deep-dive was delivered and it answers the question that had Phase C refusing to
publish. **`_synthesizer_config`'s Cartesia arm stops being a refusal and becomes a block**,
built to the schema below. Three contradictions come with it and each one is a landmine that
must be written into the code, not just noted here.

EVIDENCE: Bolna OSS at commit `ae03977fa2a9ecec3171b45c6cac6d00236b957f` (`enums.py`,
`models.py`, `providers.py`, dated 2026-09-05) and `feac358ee34fb1c17c48227c120e470592f9c0c6`
(`cartesia_synthesizer.py`, 2026-08-21); Cartesia's AsyncAPI spec at
`docs.cartesia.ai/api-reference/tts/websocket` and OpenAPI at `/api-reference/voices/list`.
Class: **VERIFIED-OSS** for everything from the Bolna repo, **VERIFIED-VENDOR-DOCS** for
Cartesia's own specs. ⚠ Whether `platform.bolna.ai` runs that OSS commit is **UNKNOWN** — the
repo is public, no page claims hosted parity. So the block below is built from the OSS
schema and gate 52 narrows from "what are the fields" to "does the hosted platform accept
them".

## 3.1 The Cartesia synthesizer block — build exactly this

`bolna/enums.py:59` → `SynthesizerProvider.CARTESIA = "cartesia"`. `bolna/providers.py` maps
that string to `CartesiaSynthesizer`. `bolna/models.py`:

```python
class StandardVoiceConfig(BaseModel):
    voice: str; voice_id: str; model: str; language: str
class CartesiaConfig(StandardVoiceConfig):
    speed: Optional[float] = 1.0
class Synthesizer(BaseModel):
    provider: str
    provider_config: Union[...] = Field(union_mode="smart")
    stream: bool = False
    buffer_size: Optional[int] = 40
    audio_format: Optional[str] = "pcm"
    caching: Optional[bool] = True
```

So `_synthesizer_config` emits, for a Cartesia voice:

```json
{"provider": "cartesia",
 "provider_config": {"voice": "<display name>", "voice_id": "<Cartesia voice id>",
                     "model": "sonic-3.5", "language": "te", "speed": 1.0},
 "stream": true}
```

The Sarvam arm keeps its current shape. `provider_config` is validated by a `model_validator`
that looks the class up by the provider string, so a wrong key is a 422 at CREATE — which is
why the block is built from the config class rather than from an example.

**`voice` vs `voice_id` is UNKNOWN in semantics** — `StandardVoiceConfig` types both as bare
`str` with no validator visible. We send the catalogue's display name in `voice` and the
Cartesia id in `voice_id`, mirroring what the Sarvam arm already does (`_synthesizer_config`
sends `voice` capitalised and `voice_id` lowercased). Gate 52 records what the platform does
with it.

## 3.2 THREE LANDMINES — each becomes an assertion, not a comment

1. **`CartesiaSynthesizer.__init__` defaults `model="sonic-english"`, a model Cartesia SUNSET
   on 1 Jun 2026.** If our block ever omits `model`, the synthesizer falls back to a dead
   model id. → `_synthesizer_config` must ALWAYS send `model`, and a test asserts the key is
   present and non-empty for every Cartesia voice. Never rely on the default.
2. **The OSS hard-codes `cartesia_version=2024-06-10` in the WebSocket URL**
   (`self.ws_url = f"wss://{host}/tts/websocket?api_key={key}&cartesia_version=2024-06-10"`),
   while Cartesia's current documented version is `2026-08-14`. This is not ours to fix — it
   is inside Bolna — but it explains landmine 3 and it means **we are being served a
   two-year-old Cartesia API version**. Record it; it is a real risk to raise with Bolna and
   a reason a Cartesia feature we read about in current docs may simply not be reachable.
3. **The OSS sends `"voice": {"mode": "id", "id": ...}`; Cartesia's CURRENT schema has no
   `mode` key** (voice is a string id or `{"id": ...}`). Under the pinned 2024-06-10 version
   `mode` was plausibly correct, so this probably works — but "probably" is the word gate 52
   exists to remove. Cartesia's spec says unknown object fields "may be added in future API
   versions", which suggests tolerance and does not promise it.

**None of these three is ours to change.** All three go in the adapter's docstring with their
`repo@commit path` citation, and gate 52's Record list gains them.

## 3.3 Two knobs we now know exist and must decide about
- `Synthesizer.caching: Optional[bool] = True` — Bolna's OWN synthesis cache, defaulted ON.
  We have never set it. If it caches by (text, voice) it is the cheapest possible answer to
  the fixed-greeting cost and it may already be working. **UNKNOWN what it caches or where.**
  → New OPERATIONS gate **54**: on one call, does a repeated identical utterance appear in
  `synthesizer_characters`/cost a second time? This is the same question as gate 49 from a
  different direction, and it is cheaper to answer.
- `Synthesizer.audio_format: Optional[str] = "pcm"` and `buffer_size: 40`. The Cartesia
  synthesizer chooses `pcm_mulaw` at 8 kHz when `use_mulaw` is set, else `pcm_s16le` at its
  `sampling_rate`. We do not set these today for Sarvam either; leave them at default and
  record that the telephony encoding is the engine's choice, not ours.

## 3.4 The voice catalogue can now be built from the API (closes plan §0 Q1's shape)
`GET /voices` (`Cartesia-Version: 2026-08-14`) takes `language`, `gender`
(`masculine|feminine|gender_neutral`), `limit` (1–100), `starting_after`/`ending_before`
cursors, `is_owner`, `include_archived` (default false), `expand[]=preview_file_url`.
Returns `{data: Voice[], has_more, next_page}`.

`Voice` = `{id, name, tagline, description, gender|null, language (DEPRECATED — "prefer
accents[].locale"), accents: [{accent, locale, is_native}], is_pro, status: active|archived,
access: private|public, visibility, created_at, preview_file_url?}`.

→ **C.1's loader takes exactly that shape**, keyed on `id`, displaying `name`, with
`accents[].locale` (not the deprecated `language`) deciding which language a voice serves.
`status == "archived"` voices are excluded. **Telugu's only documented accent id is
`telangana`**; Hindi's are `bagheli` and `standard-hindi`.

**Voice IDS ARE STILL UNKNOWN** — no unauthenticated list exists. Closes by calling
`GET /voices?language=te` with our key once it is installed, which is now a one-command
answer rather than a research question. The catalogue still ships EMPTY until then.
⚠ Also UNKNOWN: whether a voice id is permanently stable, and whether an `archived` voice
still resolves at generation time. Both matter because we store the id on the agent.

## 3.5 Phase D's premise is CONFIRMED, and the Bolna fee is upgraded
Bolna's own pricing page: *"When you bring your own keys (BYOK), Bolna does not charge for
those components. You only pay your providers directly, plus Bolna's platform fee."*
→ The synthesizer leg of a BYOK call is **₹0 from Bolna**, so §3.5's `TtsPriceAttestation`
with a transcript-counted `qty` is REQUIRED, not optional. Gate 51's remaining half is only
whether `synthesizer_characters` is still POPULATED when unbilled.

**The platform fee is now VENDOR-PUBLISHED, not REPORTED**: Bolna's FAQ states
**$0.02/min** for the platform fee, matching the dashboard observation the rate card was
built on (₹1.76 at ₹88). ⚠ Their Preferred Models page states $0.06/min all-in for bundled
models — a different line item, and no Bolna page reconciles the two. Phase A's floor
comment cites the FAQ and records the ambiguity. **Billing granularity for the BYOK fee
remains UNKNOWN** (the 30-second pulse is documented for the Pilot plan only).

## 3.6 Telugu-English code-mixing — now answered as far as it can be
Cartesia's multilingual guide: *"Mixing languages inside a single generation works where it's
common, such as Hindi (Hinglish) and Tagalog (Taglish). Outside those cases the speech may
sound accented."* Telugu-English is **not named**. So it is not "unsupported" — it is
outside the two cases they vouch for, and by their own sentence may sound accented. → The
Telugu voice entries carry that sentence verbatim, and no product surface promises
Telugu-English mixing.

## 3.7 What changes in the phases
- **C.3 becomes a BUILD** (the block above) with the three landmines as assertions. The named
  refusal survives for one case only: a Cartesia voice whose `voice_id` is empty, which is
  what an unpopulated catalogue produces.
- **C.1's loader** is typed to the `Voice` shape above and reads `accents[].locale`.
- **C.6's lifecycle** gains a note that Bolna's OSS default model is a SUNSET id.
- **D** proceeds as written; its premise is confirmed.
- **New gate 54** (Bolna's own synthesizer cache) joins §9.
- Plan §0 Q1 is answered as to SHAPE; the ids remain a one-command lookup after the key is
  installed.

---

# ADDENDUM 4 — Three corrections the build made to this plan (7 Sep 2026, Phase B1)

Implementing §3.1 and §4.B found one place where this document contradicted itself and two
where its API could not be written. All three are now the spec.

## 4.1 The terms-frozen trigger allowlist was self-contradictory (MY ERROR)
§3.1 said the trigger permits UPDATEs to `credits_remaining`, `closed_at`, `updated_at` only.
ADDENDUM 2 §2.2 then required `credits_total` to move on a restatement. **Both cannot hold**;
a restatement would have been refused by the trigger written to §3.1.
**The allowlist is `credits_remaining, credits_total, closed_at, updated_at`.** Frozen: the
two rates, `source`, `pack_id`, `override_of_pack_id`, `ledger_entry_id`, `opened_at`,
`tenant_id`. The trigger compares `to_jsonb(NEW) - allowlist` against OLD's, so **a column
added later is frozen by default** — the safe direction.

## 4.2 `consume()` takes a DEMAND, not a credit count
§4.B.1's signature was `consume(..., credits_wanted, voice_tier, kind)`. A call's demand is
**MINUTES**, and `minutes × rate` cannot be computed before the lots are walked, because the
rate is a property of each lot. So credits-wanted is unknowable at the call site.
**The real shape**: `consume(session, *, tenant_id, demand)` where demand is
`CallDemand(minutes, voice_tier, fallback_inr_per_min)` or `AiAssistDemand(credits)` — the
discriminated type carries `kind` and `voice_tier`, so they are not separate parameters that
could disagree with it. Overdraft is one split with `lot_id=None` at the last consumed lot's
rate, or the fallback when there were no lots at all.
Also: `open_lot`'s `credits` parameter is `credits_inr` — `credits` shadows a builtin and
ruff's A002 is a CI gate.

## 4.3 `FOR UPDATE` is NOT taken, and the reason is the ratchet
§4.B.1 said the FIFO read should be `FOR UPDATE`. It should not. Holding the row locks makes
the CAS **unable to lose**, which turns the retry into an unreachable defensive branch — and
`ledgers-and-money` is a zero-tolerance ratchet area, so an unreachable branch is a failing
gate, not a harmless precaution. BACKEND-PATTERNS §5 puts the guard in the write, and that is
enough here: the per-tenant advisory lock is the serialisation, the CAS is the backstop
against a caller that forgets to take it. A lost race costs one re-read and one retry and
cannot double-spend, because the guard is the value the arithmetic was based on. Eight losses
raise `credit_lots_contended`.

## Recorded from the same lane, for B2
- The data migration must sit inside a `NO FORCE`/`FORCE` bracket on `organizations` and
  `credit_ledger` — `tests/migration_rls_bracket_test.py` enforces it.
- `VoiceTier` is spelled in `lots.py` and `Voice.provider` in `agents/voices.py`;
  `tests/credit_lots_vocabulary_test.py` fails if they drift. B2 reconciles them to one.
- Overdraft REPAYMENT (§4.B.5) is deliberately unbuilt in B1 — it belongs with the callers.
