# What removing the Pipecat engine would touch (measured 13 Oct 2026)

The founder asked (13 Oct 2026) what deleting everything that exists only for `ENGINE=pipecat`
would remove: our Pipecat voice worker and its Pipecat Cloud hosting, Vobiz/Plivo telephony on
our side, our own voice legs (Gnani, Cartesia direct, Sarvam TTS remnants), the Pipecat worker
API and the in-call model leg of our own loop. **Nothing has been deleted.** This file records
the measurement so a removal, or a rebuild, can start from it. The founder's condition: the
removal must not affect any other Calevate behaviour.

Counts were taken with `wc`/`grep` on commit `85bf6084` plus the uncommitted test pruning of
13 Oct. "EST" marks a reading of sections, not a line-exact count.

## 1. Stays, because the ThinnestAI engine uses it

- `apps/api/worker/engine_actions.py` and `engine_lookups.py`: ThinnestAI's in-call actions and
  caller lookups.
- `apps/voice-runtime/signed_intake.py`: ThinnestAI's signed webhooks. Hard rule 3 still binds
  voice-runtime.
- `apps/api/engine/hosted_platform.py`: imports ThinnestAI's limits (17 importers).
- Cartesia through ThinnestAI's own-key voice (Studio): `agents/hosted_voices.py`,
  `agents/studio_voices.py`.
- Sarvam's first post-call extraction pass; the Azure OpenAI dashboard assistant.
- The `fake` engine (tests).
- The `clear`/`studio` rung vocabulary, `credit_lots` rate columns and billing (both engines).
- `CONFIDENTIALITY_RULE` and the truthful-answer block in `calevate_shared/engine.py` (the prompt
  half of D-674). Only `PromptLeakGuard` in the voice worker is Pipecat-only.

## 2. Code

### 2.1 Directories and files that exist only for Pipecat (exact line counts)

| Part | Lines |
|---|---|
| `apps/voice-worker` | 12,604 |
| `apps/api/engine/{pipecat,cartesia,carrier,carrier_pacing,vobiz,plivo_carrier}.py` | 5,184 |
| `apps/voice-runtime/carrier_{auth,events,routes}.py` | 1,762 |
| `apps/workers/carrier_{events,recordings}.py` | 1,862 |
| `apps/api/worker/routes.py` (`/v1/worker/**` for our worker) | 353 |
| **Total** | **21,453** |

Not whole files, although they look it (see §2.4):
- `apps/api/worker/service.py` (2,111) and `tools.py` (742): `worker/engine_actions.py:114-123` imports `refuse_wrong_engine`, `OPTOUT_DONE_SAY`, `CallLocator`, `ToolCall`, `book_callback_for`, `cancel_callback_for`, `record_opt_out_for` and `request_handoff_unplaced`, which serve ThinnestAI opt-out, call-back and hand-over. `POSTCALL_DEDUPE_PREFIX` and `REMETER_DEDUPE_PREFIX` are imported by `workers/pipeline.py:174`, `campaign_dispatch.py:144` and `remetering.py:73`. These move before the rest goes.
- `apps/api/engine/carrier_pacing.py` (312): `engine_concurrency_cap` (130-140, `thinnest_max_concurrent_calls`), `outbound_line_pool`, `LINES_BUSY_RULE` and `ENGINE_LINE_HORIZON` are ThinnestAI dial limiting. About 140 lines stay; `await_dial_slot`, `PACING_*`, `dials_through_our_carrier`, `RING_LINE_HORIZON` and `DialPacingTimeoutError` go.

Engine files whose ownership was not yet checked: `trial_line.py` (30), `recording_source.py`
(46), `document.py` (77), `forwarding_probe.py` (77). `forwarding_probe.py` builds ThinnestAI's
`overrides.callInstructions`, so it is at least partly shared.

For scale: application Python is about 405,000 lines (`apps/api` 282,864, `apps/workers` 50,038,
`packages` 20,642, `scripts` 34,691, `apps/voice-runtime` 3,648, `apps/voice-worker` 12,604).

### 2.2 Pipecat-only code inside shared modules

151 non-test files in `apps`, `packages` and `scripts` mention a Pipecat-only name (pattern:
pipecat, vobiz, voice_worker, plivo_carrier, TtsModel, voice_offer, timbre, gnani,
engine.carrier, carrier_pacing, in_call_llm). Most mentions are in `core/settings.py` (71),
`billing/rates.py` (67), `calevate_shared/config.py` (60), `calevate_shared/engine.py` (56),
`agents/voices.py` (54), `agents/gnani_voices.py` (41), `scripts/check_model_lifecycle.py` (30),
`scripts/check_deploy_env.py` (29), `calevate_shared/model_lifecycle.py` (27),
`agents/service.py` (22), `ops/config_catalog.py` (22), `calevate_shared/carrier.py` (21),
`calevate_shared/worker_api.py` (21). The per-file classification is §2.4.

Dependencies only the worker needs (`apps/voice-worker/pyproject.toml`): `pipecat-ai[sarvam,
websocket]==1.10.0`, `pipecat-gnani==0.5.12` and their tree (onnxruntime, Silero/smart-turn
models). `pyproject.toml` import-linter contracts name `apps.api.engine.{cartesia,pipecat,
vobiz,plivo_carrier}`.

### 2.3 Tests

- 66 test files named for Pipecat, Vobiz, the carrier, Cartesia, the voice worker, TTS or
  Plivo: 27,612 lines, 982 test functions, of about 10,900 in the suite (before the 13 Oct
  pruning). Not every one is Pipecat-only: `cartesia_*` and `tts_*` files may test Studio
  pricing on ThinnestAI; each needs checking.
- Files whose name says `worker_` are partly the ARQ workers, not the voice worker
  (`worker_platform_config_test.py` is ARQ).
- `apps/web/tests/legalVendorNames.test.ts:74,78` requires "Vobiz" in the sub-processor register
  and bans "Vobiz" and "Pipecat" in public text.

### 2.4 Per-file classification of shared modules

Read-only trace of the 151 files and their callers. File lengths and line ranges are exact;
"removable" totals for partial files are estimates.

**Totals**

| Class | Lines |
|---|---|
| Whole files in the 151 (20 files) | 7,548 (exact) |
| Whole files found while tracing (6) | 2,044 (exact) |
| Partial files in the 151 | ~9,640 (EST) |
| Partial lines in files outside the 151 | ~900 (EST) |
| Removable only after other decisions (below) | ~1,700 (EST) |
| Comment lines that go stale | ~280 (EST) |

Overall, with §2.1: about **41,600 lines removable** (21,453 + 9,592 exact, ~10,540 estimated).
On top of that, part of `worker/service.py` and `tools.py` can go once the shared functions move,
and ~1,700 lines more depend on decisions. Against about 405,000 lines of application Python, that
is roughly 10-11%.

**Whole files**

| File | Lines | Callers outside the delete set and what they need |
|---|---|---|
| `agents/gnani_voices.py` | 200 | none |
| `agents/voice_admission.py` | 526 | only whole files |
| `agents/voice_routes.py` | 771 | `main.py:123` mount. Client `agents/panels/delivery.tsx:63-64` and admin `prompt/sections/voice.tsx:83-84` read `GET /v1/agents/voices` (`selectable`, `note`) on ThinnestAI: replace with the engine catalogue. Copilot `console_reads.py:691-720, 906-913`, `console_actions.py:1723-1728, 1836`. `check_list_bounds.py:495`. |
| `agents/config_versions.py` | 486 | `check_compliance_invariants.py:360, 1063` |
| `ops/voice_curation_routes.py` | 706 | `main.py:230`; admin `ops/voices/page.tsx` (Pipecat branch) |
| `agents/transfer_providers/{base,fake,plivo,vobiz}.py` | 576 | only inside the package |
| `compliance/carrier_application.py` | 853 | The dial and launch gate (`compliance/service.py:89-94, 598-666, 1205-1218`, `campaigns/service.py:81, 1154-1158`), the client readiness screen (`legal/readiness.py:47, 53, 340, 376-406`), `agents/service.py:4557-4574`, `number_supply.py:73, 177`, `retention.py:3395, 3566`, `storage.py:920-1022` |
| `compliance/carrier_application_routes.py` | 534 | `main.py:160-165`; admin `kyc/CarrierApplicationPanel.tsx`, `KycScreen.tsx`, `lib/api/admin.ts:1486-1561`, `lib/api/kyc.ts:347-552` |
| `calevate_shared/carrier_token.py` | 99 | `worker_api.py:52, 922-958`, `core/settings.py:1094-1100` |
| `crm/live_speaking.py` | 270 | `crm/routes.py:40, 287-317` (`GET /v1/calls/{id}/speaking`); admin and client `callSpeaking.ts`, `CallDetailScreen.tsx`, `liveCallPanel.tsx`, `CopilotPanel.tsx` (always "no speaker" on ThinnestAI) |
| `kb/pack_vectors.py` | 386 | `kb/pack.py:100` |
| `calevate_shared/knowledge_pack.py` | 402 | `kb/service.py:1899` builds the pack on every publish; `kb/delivery.py` drives client `KnowledgeDelivery.tsx`/`KnowledgeScreen.tsx` and admin `KnowledgeDeliveryPanel.tsx`. Those go or are replaced together. |
| `workers/call_finalise.py` | 332 | `workers/settings.py:111, 371`; alarm key `alarm_severity.py:962` |
| `workers/pack_gc.py` | 330 | `workers/settings.py:232, 1303-1308` |
| `scripts/measure_turn_detection.py` | 263 | a test |
| `scripts/pipecat_build_context.py` | 106 | a test; `pipecat-worker-setup.sh:797` |
| web `kyc/CarrierApplicationPanel.tsx` | 338 | `KycScreen.tsx` |
| web `components/voicePicker.tsx` | 370 | `voice.tsx:7`, `voiceCards.tsx:21` |
| outside the 151: `agents/handoff_execution.py` | 489 | only `worker/tools.py` |
| `scripts/deploy/pipecat-worker-setup.sh` | 887 | `scripts/vps-deploy.sh:740-775` (~35 lines) |
| web `VoiceCatalogue.tsx`, `AddVoiceDrawer.tsx`, `voiceColumns.tsx`, `panels/voiceCards.tsx` | 668 | |

**Partial files (EST removable lines)**

- **Voice and TTS:**
  - `voice_offer.py` ~570. Keep `tts_price_is_billable`, the price-reader install and default, and `cartesia_credential_installed` (136-203, 244-262).
  - `voices.py` ~400-550. Keep `CurationState`, `ARRIVAL_CURATION_STATE`, `VoiceOrigin`, `voice_tier`, `voice_tier_of_provider`, `get_voice`, `speech_for_voice_id`, `voice_id_of`.
  - `voice_curation.py` ~470. Keep `count_live_agents_by_engine_voice`. The copilot callers in `admin_actions.py:601-667`, `admin_tools.py`, `step_labels.py:56` go.
  - `voice_sync.py` ~450. Keep the hosted arm (304-314).
  - `publishing.py` ~258 (543-571, 1687-1911, 124-130).
  - `llm_models.py` ~70 (263-335 only).
  - `model_price_routes.py` ~40-80; `model_pricing.py` ~70; `pricing_snapshot.py` ~25.
  - `rates.py` ~546: Plivo card 1266-1534, Vobiz card 1535-1603, the owned-carrier floor, and the Gnani per-character block. Its callers in `tts_speaking_rate.py`, `spend_routes.py` and `config_routes.py` change too.
  - `model_lifecycle.py` ~56-155; `languages.py` ~10 plus comments; `check_model_lifecycle.py` ~157 (455-611); `check_docs_drift.py` ~10.
- **Carrier, telephony and hand-over:**
  - `agents/service.py` ~440:
    - in-call own-key model block 793-1079 (287);
    - the own-speech arm 1172-1184;
    - `retire_agent_carrier_bindings` 1736-1765 (with `lifecycle.py:81, 786`);
    - carrier spellings, line accounting, pacing and the carrier-application check.
  - `agents/models.py` ~240: `AgentConfigVersion`, `AgentConfigAttestation`, `PipecatAgent`, `PhoneNumber.carrier_binding_id`.
  - `transfer_providers/registry.py` ~120. Keep `transfer_platform_note`, `transfer_blocked_reason`, `PLATFORM_CANNOT_TRANSFER` and `CARRIER_LIMITED_TRANSFER_NOTES` (`handoff_routes.py:56`).
  - `handoff.py` ~32; `compliance/service.py` ~80; `compliance/models.py` ~140; `legal/readiness.py` ~55; `admin/routes.py` ~25.
  - `vendor_http.py` ~14 plus comments. `is_line_limit` and `carrier_lines_busy` are shared.
  - `calevate_shared/carrier.py` ~150. Keep `NumberProvider`, `ENGINE_NUMBER_PROVIDER` and `CALLBACK_SECRET_PARAM`; `CARRIERS` feeds CHECK constraints.
  - `campaigns/routes.py` ~6; `number_supply.py` 2.
  - `retention.py` ~105 (carrier erasure arms).
  - `storage.py` ~125. Keep `copy_recording`, which ThinnestAI recordings use (`pipeline.py:1044-1056`).
  - `workers/settings.py` ~50; `pipeline.py` ~95 (the import at 174 moves); `campaign_dispatch.py` ~15; `callbacks.py` 2.
- **Settings, config and gates:**
  - `core/settings.py` ~242.
  - `calevate_shared/config.py` ~257: Pipecat, Plivo, Vobiz, carrier, Gnani and Sarvam-STT fields, and the `EngineName` members `pipecat` and `cartesia`. Each removed field needs a `RETIRED_ENV_KEYS` entry, or an existing `.env` fails `extra="forbid"`.
  - `config_catalog.py` ~131 (`number_provider` and `carrier_concurrency` need a new scope).
  - `secret_probes.py` ~137, with `POST /v1/ops/carrier/probe`, `ratelimit.py:393`, `ConfigStatus.tsx` and `opsSecrets.ts`.
  - `platform_config.py` ~85; `alarm_severity.py` ~60 (about 30 codes); `config_routes.py` ~15.
  - `ratelimit.py` ~12. Keep `Rule("/v1/worker/**")`.
  - `config_controls.py` 2; `check_deploy_env.py` ~150; `check_env_parity.py` ~70.
  - `check_public_routes.py` 121. Keep 590-628 (ThinnestAI).
  - `check_compliance_invariants.py` ~80; `check_subprocessor_coverage.py` ~14.
- **Shared engine, worker API, KB, CRM and billing:**
  - `worker_api.py` ~760. Keep the tool models `engine_actions.py:69-76` uses.
  - `calevate_shared/engine.py` ~110 plus comments; `kb/pack.py` ~590; `crm/models.py` ~185; `db/registry.py` ~140; `billing/models.py` ~120; `engine/fake.py` ~75; `engine/__init__.py` 26; `billing/service.py` ~32.
  - `compliance/deletion.py` ~70 and `tenant_erasure.py` ~25 are client-facing erasure-certificate text, so changing them moves `limitations_version`.
  - `ingest/service.py`: one import moves.
- **Web:**
  - `ConfigStatus.tsx` ~37; `ops/voices/page.tsx` ~95 (keep `HostedVoicesScreen`).
  - `prompt/sections/voice.tsx` ~140 (keep 132-151); `NumbersScreen.tsx` ~175; client `panels/delivery.tsx` ~60 (keep 119-126).
  - `schema.d.ts` ~690, regenerated.
  - Outside the 151: `lib/api/admin.ts` ~76, `kyc.ts` 206, `opsVoices.ts` ~200 (keep `useRefreshVoiceCatalogue`), `voices.ts` ~75, `numbers.ts` ~57, `opsSecrets.ts` ~14, `voiceFacts.ts` ~49, `KycScreen.tsx` ~15.
- **Also outside the 151:**
  - `transfer_providers/__init__.py` ~35; copilot callers ~120; `secret_routes.py` ~50; `healer/health.py` ~6.
  - `pyproject.toml` ~30: the workspace member, the `forbidden_modules` entries, the mypy overrides and the pytest `pythonpath`.
  - `uv.lock`: the worker's pipecat, onnxruntime and numpy tree.
- **Legal text** (a version bump and re-acceptance): `subprocessors.ts` ~50-60, `privacy.ts` ~40-70, `legal/catalogue.py` ~30, `versions.ts`.
- **Marketing:** `solutions/page.tsx:131-156` justifies published claims by `PIPECAT_CAPABILITIES`; on ThinnestAI `in_call_handoff=True`, `transfer=False` and `knowledge_base=True`, so those claims need re-grounding.

**Shared dependencies that must stay (evidence)**

- **ThinnestAI in-call actions:**
  - `worker/tools.*_for` and `worker/service.refuse_wrong_engine` (`engine_actions.py:114-123`);
  - the `worker_api` tool models (`:69-76`);
  - `actions/in_call.run_in_call_action` (`:84, 632`);
  - the `/v1/worker` prefix in `loadshed.py:79`, `ratelimit.py:294` and `rbac.py:710`.
- **ThinnestAI dial limiting:** the engine half of `carrier_pacing.py` (130-157), called from `agents/service.py:4114-4127, 4226, 4336-4359` and `campaign_dispatch.py:137, 373, 594`. `engine/vendor_http.py`.
- **Billing and post-call:** `POSTCALL_DEDUPE_PREFIX` and `REMETER_DEDUPE_PREFIX`.
- **Studio:**
  - `voice_offer.tts_price_is_billable` and its reader;
  - the Cartesia price attestation (`pipeline.py` meters Studio `tts_kchars`; `engine_charges.py:57`);
  - `voices.voice_tier_of_provider` (`tts_volume.py:70`) and `voices.voice_tier` (`pipeline.py:3542`);
  - `CartesiaPlan`, `CARTESIA_PLANS` and `_worst_marginal_tts` (the Studio cost floor `rates.py:2837`);
  - `cartesia_api_key`.
- **Voices and rungs:**
  - `voices.get_voice`, `speech_for_voice_id` and `voice_id_of` (`agents/service.py:1159-1160, 3153`);
  - `count_live_agents_by_engine_voice`;
  - the hosted arm of `sync_voice_catalogue`;
  - `VoiceTier`, `VALUE_VOICE_TIER` and `PREMIUM_VOICE_TIER` (`engine_minutes.py:105-125`).
- **Copilot, extraction, OCR and the dashboard model:**
  - all of `llm_models.py`;
  - the Azure, Gemini, platform-model, tier and Sarvam settings;
  - the LLM half of `model_lifecycle` and its check;
  - `check_model_residency`.
- **Numbers and hand-over:**
  - `ENGINE_NUMBER_PROVIDER` and `NumberProvider`;
  - `CALLBACK_SECRET_PARAM`;
  - from `agents/service`: `carrier_of_provider`, `outbound_number_provider`, `_hold_engine_line`, `provision_number` and `route_inbound_numbers`;
  - `transfer_platform_note` and `transfer_blocked_reason`;
  - from `handoff`: `spec_for`, `on_duty`, `spoken_line_for` and `india_handoff_number`.
- **Recordings, erasure and alarms:**
  - `storage.copy_recording`;
  - `tenant_of_pipecat_ref` and `processor_erasure.OWN_RUNTIME_ENGINES` (the ThinnestAI erasure path, `retention.py:2988, 3744, 3776`);
  - the alarm codes `carrier_dial_precondition_failed` and `carrier_lines_busy`.

**Tables and columns only the Pipecat path writes** (kept; dropped in a later release, hard rule 8)

- **Tables:**
  - `pipecat_agents`, `pipecat_kb_objects`;
  - `agent_config_versions` and `agent_config_attestations` (append-only);
  - `call_metering_refusals` (append-only);
  - `call_engine_latency`;
  - `carrier_compliance_applications`.
- **Columns:**
  - `calls.carrier_call_id`, `calls.carrier`, `calls.carrier_recording_id`, `calls.carrier_recording_deleted_at`, `calls.knowledge_state`;
  - `phone_numbers.carrier_binding_id`;
  - `agents.knowledge_pack_sha256` and `agents.knowledge_pack_recorded_at` (written on every engine, consumed only by the worker and `kb/delivery.py`).
- **Usage units:** `stt_min`, `llm_ktok_in` and `llm_ktok_out` (only `worker/service.py`); `tts_kchars` is also written for Studio and stays.

Pre-existing, not part of the removal: the ORM CHECK at `agents/models.py:1020` (`provider IN CARRIERS`, vobiz/plivo) does not match migration `a3d9e6f1c204`, which widened the database CHECK to include `'thinnest'`.

**Not classified (decision needed)**

1. **Cost floors.** `rates.py` owned-runtime cost floors and the Cartesia all-in functions (1604-2630, ~310), with the `config_routes.py` cost-model blocks (~260) and `SpeakingRateNotice` (58). The ops rate-card console renders them, and `SELF_SERVE_COST_FLOOR_INR_PER_MIN` is still the refusal floor.
2. **TTS volume and speaking rate.** `tts_volume.py`, `tts_speaking_rate.py` and their platform rows: whether Studio on ThinnestAI writes them is not determined.
3. **Pipecat-era parts of `engine.py`.** The latency budget (~449), LLM traps (~170), Sarvam STT constants and the `ModelConfig` in-call fields. Removing those fields changes config digests, and the fake engine exercises them.
4. **The number-buy path.** `number_supply.py`, `provisioning.py` and the `number_catalog` buy path run only on the fake engine.
5. **Partly shared settings.** `openai_api_key`, `carrier_concurrency`, `number_provider` and `EngineName` (the last reaches a database constraint).
6. **Historical rows.** Rows from the founder's Vobiz test calls may hold `pipecat:` refs or carrier columns. Removing the carrier erasure arms would leave them with no erasure path. The database was not queried.
7. **Legal and erasure-certificate wording.** A compliance decision.
8. **The engine-latency screen.** It is engine-generic, but nothing on ThinnestAI writes latency.
9. **`check_docs_drift.py` TRD §10.1 parsers.** 10-200 lines, depending on the doc edits.

## 3. Docs

### 3.1 Whole files

| File | Lines |
|---|---|
| `docs/PIPECAT-MIGRATION.md` | 1,286 |
| `runbooks/vobiz-first-live-call.md` | 537 |

`PIPECAT-MIGRATION.md` also holds shared material to move before deleting it: §1.3 (118-162,
`unit_cost_paid` as a sum of legs), §8.4-8.6 (629-765, our Postgres knowledge store, Supermemory,
`kb_chunks`), §10.4 (1106-1178, embedding cost). 127 code files cite it by name; none opens it.
`vobiz-first-live-call` is cited in 7 code files; `docs/evidence/{vobiz,pipecat,gnani,worker-http}`
in 29.

### 3.2 Sections in other docs (EST)

47 files outside `docs/evidence` mention Pipecat or Vobiz: 30,911 lines, 1,081 matching lines.
About 1,600 lines are Pipecat-only and about 950 are mixed (rewrite, not delete).

| File | Pipecat-only (EST) | Mixed, rewrite (EST) |
|---|---|---|
| `docs/DEPLOYMENT.md` | ~542 (§12 intro, §12.1-12.6 at 1702-2231, and 13, 748-749, 933-935, 1290, 1530, 2377-2378) | ~31 (§12.7 ThinnestAI, 2232-2262, sits under the Pipecat heading) |
| `docs/TRD.md` | ~300 (§3 280-315, 118-124; rows 18, 20, 24; §5 565-577; §8 1236-1244; §9 1301; Gnani/Bulbul parts of §10.1 1482-1854) | ~150 |
| `CLAUDE.md` | ~190 (67-87, 108-141, 209-244, 309-316, 328-331, 752, 766-867) | ~200 (11-66, 88-107, 142-208, 245-308, 352-356, 389-412, 832-842, 848-851) |
| `docs/AGENTS.md` | ~85 (53-101, 126-146, 222-229, 233-236, 377) | ~50 (7-50, 102-125, 147-160, 237-243, 250) |
| `runbooks/first-deploy.md` | ~125 (§9a 494-568, 49-80, 282-300, 326) | ~5 |
| `docs/FLOWS.md` | ~70 (233-299, 91-93) | ~45 (397-414, 426, 586-588, 591-675, 753, 813) |
| `docs/legal/SUBPROCESSOR-REGISTER.md` | ~61 (rows 36, 37, 39, 41, 45, 47; 85-100, 131-147, 213-226, 242-249) | ~40 (rows 44, 46, 48; 101-130, 153-212, 227-241) |
| `runbooks/alarm-index.md` | ~48 (518-560, 74, 76, 101, 113) | ~10 (recording rows 536-545) |
| `docs/OPERATIONS.md` | ~20 gate rows, 12, 15, 28-29, 300-309 | ~5 |
| `docs/SECURITY-COMPLIANCE.md` | ~20 (1110-1124, 1174) | ~25 |
| `docs/BRD.md` | ~15 | ~70 (§6 194-362, R-02, R-10, A-1, A-6) |
| `docs/THINNEST-INTEGRATION.md` | ~11 (Pipecat column of the table at 52-62) | ~10 (35, 181, 217, 338, 348) |
| `docs/ROADMAP.md` | ~10 (21-41, 322-327) | ~25 (320-348) |
| `docs/DATA-MODEL.md` | 0 until the tables are dropped (hard rule 8) | ~70 (289-297, 311-316, 412-422, 830-852, 1346-1387, enum at 224) |
| `docs/SURFACES.md` | ~9 (712-720) | ~6 |
| `docs/README.md`, `README.md`, `DEV-SETUP.md`, `PLATFORM-CONFIG.md` and small runbook lines | ~25 | ~40 |

Stays as history: the ROADMAP decision log (655 lines, 650 rows, 109 mention Pipecat or Vobiz),
`PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md`, `RESEARCH-DISCIPLINE.md`, `docs/vendor/bolna/*`.
Plivo in `SECURITY-COMPLIANCE.md:228,243` and `LEGAL-OPS-PLAYBOOK.md` §10.9 is ThinnestAI's
upstream carrier, and "Exotel/Plivo/Vobiz" in the legal playbook and briefs is the generic
client-held-number carrier class: neither is the Pipecat path.

### 3.3 Mixed places that must be rewritten, not deleted

- **Rollback.** `runbooks/thinnest-first-live-call.md:315` rolls back by setting the engine to
  `pipecat`; `runbooks/auto-healer.md:59`; `THINNEST-INTEGRATION.md:35,181,338` and
  `CLAUDE.md:62-63`, `AGENTS.md:46-48` say `ENGINE=pipecat` "must stay unchanged". Removing
  Pipecat leaves no second engine.
- **Hard rules.** Rule 2 lists `apps/voice-worker` as a vendor home (`CLAUDE.md:389-412`,
  `AGENTS.md:250`); rule 3 still binds voice-runtime (`CLAUDE.md:413-417`).
- **D-674.** `CLAUDE.md:832-842`, `848-851`, `AGENTS.md:237-243`, `SECURITY-COMPLIANCE.md`
  §6.1 1218-1278 (1251-1262 is the `PromptLeakGuard` half).
- **Compliance text.** `SECURITY-COMPLIANCE.md:53-58` (recording is Vobiz's), 319-323 (D-666),
  406 (cross-border row), 1209 (threat-model row).
- **Public legal pages** (`apps/web/src/lib/legal`). No page names Vobiz, Pipecat or Gnani
  (`subprocessors.ts` `named: []` except payments, messaging and client integrations), but they
  describe our own call program and carrier in general words: `subprocessors.ts` (rows 58-279,
  body 535-1068), `privacy.ts` (555-1242), `dpa.ts` (125-627). Changing them bumps versions in
  `versions.ts`, which feed acceptance records in `apps/api/legal/`.
- **Sub-processor register is read by code**: `scripts/check_subprocessor_coverage.py:76` and
  `apps/web/tests/legalVendorNames.test.ts:24,74,78`.
- **Recording retention**: `CLAUDE.md:313`, `AGENTS.md:226`, `FLOWS.md:280-288`,
  `runbooks/object-lifecycle.md:117-120`, `alarm-index.md:536-545` (`carrier_recording_*`
  alarms; whether ThinnestAI raises any is not checked), `THINNEST-INTEGRATION.md:61`.
- **Erasure**: `FLOWS.md:586-588`, `runbooks/processor-erasure.md:21-22` (`telephony` and
  `voice_engine` processor rows).
- **Shared machinery explained through Pipecat**: `THINNEST-INTEGRATION.md:217` (client actions
  also on `/v1/worker/...`), 348 (`X-Agent-Secret`), `runbooks/client-actions.md:7`,
  `DEV-SETUP.md:164-165`.
- **Pricing**: TRD §10 preamble 1305-1330 and §10.1 1482-1854 (the Cartesia band and speaking-rate
  measurement also price Studio on ThinnestAI), BRD §6 194-362, `FLOWS.md:753,813`,
  `CLAUDE.md:88-107`.
- **Schema docs**: `DATA-MODEL.md` ranges above.
- **DEPLOYMENT** §12.7 (ThinnestAI config under the Pipecat heading); `first-deploy.md:557-560`.

### 3.4 OPERATIONS gates that exist only for Pipecat (15)

Gate 3 (Telugu quality, "Applies to ENGINE=pipecat only"; ThinnestAI's equivalent is T-6), 55
(Vobiz callback signing), 56 (Gnani commercials), 57 (Pipecat Cloud billing), V-1 to V-11
(193-207). Gates 47, 58, 59, 9, 12, 13 and 26 are shared or Bolna-era and stay.

### 3.5 Evidence and vendor mirror (history)

- `docs/evidence`: 55 of 121 files mention the terms (26,107 lines). 14 are entirely about
  Pipecat, Vobiz or Gnani (8,316 lines): `pipecat-api-surface-2026-09-13.md` (2,683),
  `vobiz-integration-plan.md` (911), `vobiz-api-contract.md` (634),
  `carrier-plivo-vs-exotel-2026-09-16.md` (555), `pre-build-blockers-2026-09-13.md` (525),
  `pipecat-cloud-bringup-2026-09-16.md` (493), `carrier-caller-identity.md` (485),
  `gnani-evaluation-2026-09-06.md` (444), `inbound-end-to-end-hunt-2026-09-21.md` (376),
  `kb-under-an-engine-we-run-2026-09-13.md` (368),
  `orchestrator-commercial-and-carrier-2026-09-13.md` (283),
  `orchestrator-livekit-vs-pipecat-2026-09-12.md` (280), `worker-http-contract.md` (140),
  `carrier-pricing-concurrency-2026-09-17.md` (139). Mixed: `inbound-concurrency-audit-2026-09-21.md`,
  `per-minute-cost-model-2026-09-21.md`, `engine-replacement-comet-2026-09-06.md`.
- `vobiz-findings/mirror/`: 492 files, 8,405,569 bytes, 89,630 lines of Markdown.

## 4. How a removal would be made safe

1. Tag the last commit that has the engine, so it is one checkout away.
2. Delete file by file, checking every importer (§2.4) against §1.
3. Keep database tables and columns; drop them in a later release (hard rule 8).
4. Rewrite the §3.3 places; retire the §3.4 gates; a decision row like D-639 (Bolna).
5. Prove it: ruff, mypy, `lint-imports`, every CI gate, and the full test suite on the result.
