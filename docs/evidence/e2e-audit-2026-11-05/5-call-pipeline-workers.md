# Lane 5: call pipeline and workers (backend only)

Phase 1 audit, 5 Nov 2026. Read-only: no code was changed. Scope: engine webhooks
(`apps/voice-runtime`), the post-call pipeline and every worker job around a call, the outbox
and its dispatcher, arq registration and routing, crons, deploy ordering, and the detection
heuristics that turn a transcript into owner-visible findings.

How this was checked: by reading the code at the commits named below, reading the installed
arq 0.28.0 source (`.venv/Lib/site-packages/arq/worker.py`), reading `git log` for when each
job and migration arrived, and one regex probe run in Docker (`python:3.12-slim`, patterns
copied verbatim from the code; script at
`C:/Users/jumes/AppData/Local/Temp/claude/a50a3f0a872c1724/0c51a750-0b23-4950-961e-84972febca40/scratchpad/audit/5-call-pipeline-workers/re_probe.py`).
No production database, Redis or log was read; where a finding's production impact needs
one, the VPS command to settle it is given.

---

## 1. Map

### 1a. Webhook intake (voice-runtime)

| What | Where | What it is for |
|---|---|---|
| `POST /…/{engine}` receiver | `apps/voice-runtime/webhook_routes.py:621` `engine_webhook` → `_receive_signed` :782 | Admit a ThinnestAI delivery, ack under 500 ms |
| Signature / freshness / keying | `apps/voice-runtime/signed_intake.py` (`delivery_signature_matches`, `delivery_is_fresh`, `keyed_event`) | v2 HMAC over `<delivered-at>.<body>`, 5 min window, dedupe on body `id` |
| Event → job routing | `signed_intake.py` `SIGNED_INTAKES` | `call.completed`/`call.analysed` → `ingest_engine_event`; `contact.opted_out` → `ingest_engine_opt_out`; `lead.captured`/`conversation.escalated` → `ingest_engine_notice`; `call.problem` → `ingest_engine_problem`; `contact.erased`/`byok.changed` → `ingest_engine_workspace_event` |
| Fast-path dedupe (Redis) | `webhook_routes.py:437` `_fast_path_seen`, :491 `_remember_fast_path` | Skip Postgres for a body already settled |
| Durable dedupe + enqueue | `webhook_routes.py:945` `settle`, :1040 `_claim_and_enqueue` | Inbox claim, forensic `webhook_deliveries` row, arq enqueue, mark enqueued, one transaction, under `durable_deadline_s` |
| Ack measurement | `webhook_routes.py` `measured`, `_ack`, `WEBHOOK_ACK` | `X-Ack-Ms` + metric on every exit |
| Endpoint repair sweep | `apps/workers/engine_webhooks.py:155` `reconcile_engine_webhooks` | Re-enable switched-off endpoints, ask for re-sends |
| Execution poller (truth) | `apps/workers/pipeline.py:5870` `reconcile_executions`, :5693 `reconcile_outstanding_calls` | Settle calls whose webhooks never arrived |

### 1b. Post-call pipeline (`apps/workers/pipeline.py`)

| Step | Where | What it is for |
|---|---|---|
| Ingest | `ingest_engine_event` :496 | Upsert the call row from the delivery, queue the pipeline |
| Pipeline entry | `run_post_call_pipeline` :904 → `_run_post_call_stages` :1283 | All post-call stages for one call |
| Truth read / wait for transcript | :1295-1336 | Re-read the engine; Retry while an answered call has no turns |
| Recording copy (parallel) | `_recording_copy_stage` :1230 | Copy recording to our storage |
| Vendor document archive | `_archive_engine_document` :1154 | Keep the raw vendor record (object storage) |
| Hand-over settle | :1380 `settle_handoff` | Book a call-back when a transfer reached nobody |
| Forwarding test claim | :1393 `claim_inbound_call` | Forwarded-number test calls |
| Call timeline | :1412 `call_timeline.request_call_timeline` | Per-turn timings job |
| Transcript + redaction | `_persist_transcript` :2174 | `text` + `text_redacted` |
| Spoken opt-out | :1432 `detect_opt_out` (`apps/api/compliance/optout.py`) | Suppression before extraction |
| Spoken WhatsApp consent check | :1442 `check_spoken_consent` | Verify an agent-reported opt-in |
| Disclosure / recording notice evidence | :1466-1486 | Was the AI sentence / recording notice spoken |
| Extraction (Sarvam) | `_extract_stage` :1783; prompt `packages/shared/src/calevate_shared/extraction.py:678` `build_extraction_prompt` | Lead fields, summary, headline, next_step, next_step_by, outcome_tag, goal_reached/goal_reason, business_outcome, callback request, moments |
| Knowledge gaps | :1512 `gap_service.record_call_gaps` → `apps/api/insights/detection.py` `detect_gaps` | "Questions to answer" list |
| Call mistakes | :1528 `call_mistakes.mistakes_in` → `apps/api/agents/turn_checks.py` | "Mistakes on real calls" (D-949) |
| Call reading | `_record_reading` :2882 | Summaries, headline, next step |
| After-call call-back | :1565 `book_requested_callback` (`apps/workers/after_call_callbacks.py`) | Book the call-back the caller asked for |
| Outcome / business outcome | `_record_outcome` :3095, `_record_business_outcome` :3185 | Derived outcome, per-business outcome |
| Lead upsert / status / band | `_upsert_lead` :3503, `after_call_status` :3225 | Lead row, hot/warm move |
| Metering | `_meter` :4135 | `usage_events` (money) |
| Engine charge reconcile | :1620 `reconcile_call_charge` | Engine-stated charge vs our meter |
| Hot-lead notify | `_maybe_notify_hot_lead` :5156 | Owner/team alert via outbox |
| Campaign contact resolve | :1667 `resolve_campaign_contact` | Close or re-ladder the dial |
| Follow-ups, CRM fan-out, after-call actions, save-number | :1681-1735 | Outbox rows, once per call |
| Late-erasure re-file | :1749 `refile_erasure_for_late_records` | DPDP |
| Language pass | `queue_language_pass` :3040 | English turns and missing summary, by its own job |
| Stall alarm | `apps/workers/dispatcher.py` `report_stalled_pipeline` | Completed calls owed extraction after `PIPELINE_STALL_AFTER` |

### 1c. Jobs around a call, after the call

| Job | File | Queue | Notes |
|---|---|---|---|
| `caller_memory_distil` cron | `apps/workers/caller_memory_distil.py` | default | Model distils facts per completed call into caller memory |
| `recheck_call_quality` | `apps/workers/call_quality_recheck.py` | **bulk** | D-970 one-off re-read of gaps and two mistake kinds, queued by migration `a7d3e9c1f570` |
| `extraction_reread` | `apps/workers/extraction_reread.py` | default | Re-read calls whose model reading failed |
| `call_language` / language pass | `apps/workers/call_language.py` | default | English for turns and summary |
| `run_after_call_actions` | `apps/workers/client_actions.py` | default | Client's after-call actions |
| `callbacks` dispatch | `apps/workers/callbacks.py` | default | Rings booked call-backs |
| `qa_sampling`, `moments`, `hot_facts` (`recompute_hot_facts` is bulk) | `apps/workers/*.py` | mixed | Owner insights |

### 1d. Outbox, dispatcher, arq

| What | Where | What it is for |
|---|---|---|
| Outbox write | `reliability/service.enqueue_outbox`, `enqueue_outbox_once` | Side effect committed with the domain write |
| Claim | `reliability/service.py:555` `claim_outbox_batch` | Lease + attempt bump on its own connection; filters to `jobs` (5149588aa) |
| Unknown-job DLQ | `reliability/service.py:621` `_dead_letter_unknown_jobs` | Pending > `OUTBOX_UNKNOWN_JOB_GRACE` (30 min, :86) for a job this release does not run → `failed` |
| Exhausted-claim DLQ | `reliability/service.py:654` `_dead_letter_exhausted_claims` | |
| Publish | `apps/workers/dispatcher.py` `dispatch_outbox` | Every 10 s and `run_at_startup=True` (`settings.py` `CRON_JOBS[0]`) |
| Mark published + scrub payload | `reliability/service.py:680` `mark_outbox_published` | `payload = '{}'` in the same UPDATE |
| Consumer guard | `apps/workers/outbox_consumer.py` `consume_outbox_once`; `reliability/service.py:737-773` | Skip a re-run of a consumed message; stamp `consumed_at` on success |
| Replay | `reliability/service.py:1111` `replay_dead_letters`, `apps/api/ops/routes.py:1016` | Replays `status='failed'` only |
| Routing | `apps/api/core/queue.py` `BULK_JOBS`, `queue_for` | `arq:bulk` vs default |
| Registration | `apps/workers/settings.py` `FUNCTIONS` (:393), `BULK_FUNCTIONS` (:771), `CRON_JOBS`, `WorkerSettings` (:2148), `BulkWorkerSettings` (:2227) | Main worker registers every job; bulk worker only `BULK_JOBS`; crons only on main |
| Registered set handed to the dispatcher | `settings.py:1970` `startup` | `ctx[REGISTERED_JOBS]` = main worker's `FUNCTIONS` names |
| arq terminal-warning alerter | `settings.py:1907` `ARQ_TERMINAL_MESSAGES` | "function not found" → `job_function_not_registered` (severity `page`, `core/alarm_severity.py:639`) |
| Wiring guard | `scripts/check_job_wiring.py` (reads migrations too, :354) | Every enqueued name is registered |

### 1e. Deploy

| Step | Where |
|---|---|
| Build → migrate (+seed) → redis up → swap `workers`, `workers-bulk`, `api`, `voice-runtime` in that order | `scripts/vps-deploy.sh:1405-1455`, `run_migrations` :944 |
| Worker swap waits `SETTLE_S` (30 s) watching restarts, no health signal | `wait_settled` :1043 |
| Worker drain on SIGTERM: 45 s (`job_completion_wait`) | `settings.py` `WorkerSettings` |

---

## 2. Findings

Severity per BRIEF: P0 breaks money/law/data or a core client flow; P1 wrong/broken with a
workaround; P2 confusing/slow/fragile; P3 polish.

### The outbox row from migration `a7d3e9c1f570`: the cause

**Root cause (from code; production log not read).** `recheck_call_quality` is a new job and
a new member of `BULK_JOBS`, both added today in 6b0abc5d1 (`git log -S'"recheck_call_quality"'`).
The sequence on the VPS:

1. Migration runs while the OLD release runs. The old dispatcher's `REGISTERED_JOBS` (5149588aa)
   lacks the name, so the row stays `pending`. This part works as designed.
2. `swap workers` (`vps-deploy.sh:1453`) starts the NEW main worker. Its `startup`
   (`settings.py:1970`) sets `REGISTERED_JOBS` from the new `FUNCTIONS`, which contains
   `recheck_call_quality`, and `dispatch_outbox` runs immediately (`run_at_startup=True`).
3. The dispatcher claims the row and enqueues it with `_queue_name=queue_for(job)` =
   `arq:bulk` (`core/queue.py:97`, :176). It marks the row `published` and scrubs its payload
   (`reliability/service.py:713-718`).
4. `arq:bulk` is still read by the OLD `workers-bulk` container: the deploy only swaps it after
   `workers` has stayed up for `SETTLE_S` = 30 s plus the recreate (`vps-deploy.sh:1043-1065`,
   :1453). The old bulk worker's `BULK_FUNCTIONS` has no `recheck_call_quality`.
5. arq 0.28.0 `Worker.run_job` (`.venv/Lib/site-packages/arq/worker.py:531-534`):
   `function %r not found` → `job_failed(...)`, result kept, job removed from the queue. No
   retry. The wrapped function never ran, so `consumed_at` stays NULL.
6. Nothing re-publishes a `published` row. The hand-queued row later ran because by then
   `workers-bulk` was on the new image.

The 5149588aa filter checks "does MY release register this name", using the main worker's
set, but the consumer of a bulk job is a different process on a possibly different release.
The comment at `vps-deploy.sh:1427-1429` ("Both workers before api, so the bulk queue has a
reader before a new api starts routing jobs onto it") covers the api as a producer and misses
the new main worker's own dispatcher.

To confirm on the VPS (ids and timestamps only):

```bash
sudo -u postgres psql -d calevate -c "SELECT id, status, job_id, created_at, published_at, consumed_at, last_error FROM outbox_messages WHERE job = 'recheck_call_quality' ORDER BY created_at;"
```

```bash
cd /var/www/calevate && docker compose -p calevate -f compose.prod.yml logs --since 24h workers-bulk 2>&1 | grep -E "not found|recheck_call_quality" | head -20
```

The second should show `function 'recheck_call_quality' not found` from the old bulk
container if this account is right.

### Findings table

| ID | Sev | Where | What happens (observed or read) | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| L5-01 | **P0** | `scripts/vps-deploy.sh:1453`; `apps/workers/settings.py:1970`; `apps/api/core/queue.py:176`; `apps/workers/dispatcher.py` `dispatch_outbox` | Any outbox message for a job that is new to `BULK_JOBS` in a release, and pending at swap time, is published by the new main worker onto `arq:bulk` while the old bulk worker still reads it, and is dropped as "function not found". Today's `recheck_call_quality` row is this case. Same exposure for every future bulk job queued by a migration, by `queue_upgrade_on_start`, or by any user action in the ~30-40 s window | The dispatcher only publishes a job when the worker that will consume it, on its queue, runs this release (or the bulk worker is swapped first and producers wait for it) | Sequence above; arq `worker.py:531-534`; `git log` 6b0abc5d1 | Truthful system; BRIEF "deploy-time cleanup job never ran" |
| L5-02 | **P0** | `apps/workers/caller_memory_distil.py:253` (`SELECT c.id, c.agent_id, c.from_e164`), :510 (`phone = row[2]`); `apps/api/agents/service.py:4308-4322` (outbound row stores OUR number in `from_e164`); `service.py:3884` `_recall_for_dial` (recalls by the dialled number) | For an OUTBOUND call the distiller files the callee's facts under `calls.from_e164`, which for outbound is the business's own calling number (`service.py:4318-4320` "Our number when we chose it"). There is no `direction` anywhere in the distiller or `compliance/caller_memory.py`. Result: (a) every outbound callee's notes pile into one subject, the business's number; (b) recall for the next dial looks up the callee's number and finds nothing, so memory never works for an outbound agent; (c) a DPDP erasure by the callee's phone (`_active_handle(tenant_id, phone_e164)`, `compliance/caller_memory.py:502`) cannot find facts filed under the business's number | Subject = the other party: `from_e164` on inbound, `to_e164` on outbound, the same rule the pipeline already uses (`pipeline.py:1538-1540`, `_party_e164(snapshot.from_e164 if direction == "inbound" else snapshot.to_e164)`) | Code read; production impact needs `SELECT direction, caller_memory_state, count(*) FROM calls GROUP BY 1,2` (command in §4) | Law (DPDP erasure), data |
| L5-03 | **P1** | `reliability/service.py:713-718` (`payload = '{}'` on publish); `outbox_consumer.py`; no reader of `consumed_at IS NULL` in `apps/` (`grep consumed_at`) | A message that is `published` but never consumed (dropped by arq, exhausted retries, or a non-Retry exception) is invisible and unrecoverable: no metric or alarm counts `published AND consumed_at IS NULL`, replay only takes `status='failed'` (`replay_dead_letters`, :1111), the payload is already gone, and an `enqueue_outbox_once` `dedupe_key` (migrations `b7e3d9a2c5f1`, `queue_upgrade_on_start`) blocks queueing it again | A reconciler that finds published, unconsumed rows past a deadline, alarms, and either re-publishes (payload kept until consumed, then scrubbed) or dead-letters them as `failed` with the payload intact | Code read | Truthful system, reliability (BACKEND-PATTERNS §4) |
| L5-04 | **P1** | `claim_outbox_batch` filter by NAME (`reliability/service.py:555-616`); deploy migrates before swap (`vps-deploy.sh:949-962`) | A migration that queues a job that ALREADY exists, in a release that also changes that job's code, is claimed by the OLD dispatcher in the migrate→swap window and run by the OLD worker with the OLD logic, then stamped `consumed`. The new logic never runs for that message. Candidates by history: `c8e2f4a6b913` (D-887, 25 Oct) queued `refresh_field_reason` in the same commit (a20332e89) that changed `apps/workers/field_reason_refresh.py`; `e962a4c1d7b3` (2 Nov) queued `strip_retired_example_lines`, a job new in that commit, before the 5149588aa filter existed, so the old worker dropped it as "function not found" (the `name_core_details` failure 5149588aa describes) | Messages carry the release (or migration revision) that queued them and are claimed only by a dispatcher at or past it | `git show --stat` a20332e89, d812edb6c; production outcome UNVERIFIED (command in §4) | Reliability |
| L5-05 | **P1** | `apps/api/insights/detection.py:124-131` `_QUESTION_RE`, :336 `caller_asked`; `apps/api/agents/turn_checks.py:1076-1080` `_CALLER_ASKS` | The D-970 fix stops only the exact "I will try." The question test still fires on: any English `what/when/where/how` anywhere in the line; Telugu question words matched as substrings with no word boundary (`ఎలా` inside `ఎలాగైనా` "somehow", `ఎక్కడ` inside `ఎక్కడో` "somewhere"); and `kavali` ("I want"). Probe results (verbatim patterns, Docker): `ఎలాగైనా ట్రై చేస్తాను` → asks=True; `ఎక్కడో చూసాను, ట్రై చేస్తా` → True; `I will try when I get time` → True; `ok I will try what you said` → True; `naaku help kavali ante cheptanu` → True; `I will try.` → False. Each, followed by an agent line mentioning WhatsApp, becomes an "unanswered question" on the owner's list | A gap needs a real question to the business. Deciding that from a hand list is the wrong tool for Telugu; the question/deflection judgement should come from the post-call model reading that already runs (the extraction call can return "questions the agent could not answer" with the caller turn index), with the string match kept only as a cheap pre-filter, if at all | `re_probe.py` output above | Truthful UI (rule 6); founder's "I'll try" report |
| L5-06 | **P1** | `apps/api/insights/detection.py:94-107` `_DEFERRED_RE` | Any agent reply containing `whatsapp`, `send you`, `send it`, `call you back`, `get back to you` after a "question" is a `deferred_channel` gap, whatever the business. For Rytu Khata, sending the app link on WhatsApp IS the answer; probe: `Sure, I'll send you the link on WhatsApp now.` matches. The module says the list is "the Outpero signal verbatim" (:92) | Whether a channel hand-off is a deflection depends on the business (its capability profile / script says what it sends on WhatsApp). Derive it per business, or let the model judge "answered vs deferred" | Code read; probe | Rule 1 (nothing hardcoded per business); `no-competitor-wording` memory |
| L5-07 | **P1** | `apps/api/agents/turn_checks.py` (228 lines with Telugu/Devanagari, e.g. :203, :216-235, :248, :290-302, :415-443, :559-598, :859-892, :959-1012, :1076-1128); `apps/api/insights/detection.py:76-212, :244-302` (romanised Telugu/Hindi); `apps/workers/call_language.py:104-109`; `apps/workers/extraction.py:1239-1275` (OfflineExtractor negation/asking lists); `packages/shared/src/calevate_shared/extraction.py` prompt (`"కాల్ బ్యాక్"`, `"malli call cheyyandi"`, `"house kavali ani chepparu"`, `"Mee peru cheppandi"`, `"Book cheyala leda cancel cheyala?"`, `"ledu", "vaddu", "kaadu"`…); `apps/api/compliance/optout.py:356` | Telugu and Hindi words are hand-written in code across every heuristic that judges a real call. The founder-owned data file exists (`packages/shared/src/calevate_shared/spoken_style.json`, with the admin overlay `spoken_style.install_published`) and none of these lists live there. Also: the romanised lists cannot see Telugu-script transcripts at all, and the script lists cannot see romanised ones | Word lists move to founder-owned data (a `caller_words`/`turn_words` section beside `spoken_style.json`, reviewed on Ops > Spoken style), or the judgement moves to the model reading. Note: `compliance/optout.py` is a compliance surface; moving its list needs the compliance lane's sign-off, not a silent swap | Grep counts in §3 | Founder rule 2 |
| L5-08 | **P1** | `apps/workers/caller_memory_distil.py:208-232` `_SYSTEM_PROMPT`, :301-338 `within_scope` | The scope guard that enforces "never remember money or health" is an English substring list (`price`, `cost`, `medicine`, `patient`…). The prompt never asks for English notes, so a Telugu call can yield a Telugu note (e.g. a price or a medicine named in Telugu) that passes the guard and is read back on the next call | Ask for notes in English (as the extraction prompt does for summaries) AND check the language of each note; refuse a note not in English letters | Code read | Founder scope decision on caller memory; DPDP |
| L5-09 | **P2** | `apps/workers/pipeline.py:1512-1549` | Knowledge-gap and call-mistake stages run inline, before the outcome, lead upsert and metering (:1590-1617), with no isolation. A deterministic exception in `turn_checks`/`detection` (a bad regex, an unexpected turn shape) fails the whole job on every retry: no lead and no `usage_events` for that call until a code fix | Owner insights run after money and lead, or in their own job, so their failure cannot hold up the meter (hard rule 7) | Code read | Hard rule 7 ordering; reliability |
| L5-10 | **P2** | `apps/workers/call_quality_recheck.py:32-42` | No `Retry` and no error handling: one DB blip or lock timeout ends the job on its first attempt (arq retries only `Retry`/`CancelledError`, `settings.py` `retry_jobs` comment). With L5-03 the payload is already scrubbed, so it cannot be replayed | `raise Retry(defer=…)` on transient errors, as `qa_sampling` does | Code read | Reliability |
| L5-11 | **P2** | `apps/workers/dispatcher.py` `dispatch_outbox` (`job_id or "deduped"`), `core/queue.py` `enqueue` (INFO `job_deduped`) | When arq refuses the id because a RESULT for the same message id exists (an earlier run that failed, e.g. L5-01's "not found"), the dispatcher marks the row `published` with `job_id='deduped'` and logs only INFO. The receiver has the same blind spot and at least warns (`webhook_routes.py:1006-1024`); the dispatcher does not | Treat `deduped` on an outbox message as "already ran or already failed": look up the arq result or `consumed_at`, and warn/alarm when neither shows success | Code read | Truthful system |
| L5-12 | **P2** | `apps/voice-runtime/webhook_routes.py:1006-1024` | `webhook_claimed_without_job`: a fresh claim whose enqueue arq refused (result key still present) is marked enqueued with no job behind it, WARNING only. For `call.*` the execution poller repairs it; for `contact.opted_out`, `lead.captured`, `conversation.escalated`, `call.problem`, `contact.erased`, `byok.changed` there is no poller | Alarm (not just log) for non-call events, or key those jobs so a refused id means "already ran successfully" | Code read | Hard rule 5 (DNC/opt-out propagation) |
| L5-13 | **P2** | `apps/workers/business_copy.py:775-793` `queue_upgrade_on_start` | Runs in the NEW main worker's startup; its walk queues `generate_business_copy` (bulk) while the OLD bulk worker still runs. If the old code has the job, it writes copy with the old prompt and stamps the message consumed; the daily walk repairs it within a day | Same fix as L5-01 | Code read | Reliability |
| L5-14 | **P2** | Rollback via `vps-deploy.sh --checkout` | Jobs already on a Redis queue for functions the older release lacks are dropped "not found" (paged). Pending outbox rows go to `failed` after 30 min and are replayable; queued arq jobs are not | Document in `runbooks/deploy-failed.md`; same consumer-capability check as L5-01 | Code read | Reliability |
| L5-15 | **P2** | `packages/shared/src/calevate_shared/extraction.py` `build_extraction_prompt` | Business-specific examples in the prompt every client's calls go through: headline `"Asked if chilli is in stock; wants a call back today"` (a shop), `"house kavali ani chepparu"` → "They said they want a house" (real estate), `"Book cheyala leda cancel cheyala?"` (bookings), and "our AI receptionist" for an agent that may be an outbound caller | Neutral examples, or examples built from the agent's own business profile | Code read | Rule 1, rule 2 |
| L5-16 | **P2** | `apps/api/insights/detection.py:137-212` `_TOPICS`, :244-302 `_STOPWORDS` | Fixed list of eleven "SMB" topics (pricing, refunds, warranty, delivery, timings, location, stock, bookings, offers, payment, documents) with Telugu/Hindi triggers. The capability filter (`_TOPIC_NEEDS`) removes some per business, but the vocabulary itself is one generic retail/service view | Topic names from the business's own data (script, knowledge, capabilities), or from the model | Code read | Rule 1, rule 2 |
| L5-17 | **P2** | `apps/workers/after_call_callbacks.py`; prompt `callback_requested` rules in `calevate_shared/extraction.py` | An outbound call-back is booked from the model's reading alone (no consent row, by design, :26-29), default next day at the call's hour. The prompt counts "said they would talk again later" as a request, which includes a caller saying they will call | The extraction rule should separate "call me back" from "I'll call you"; whether an auto-booked call-back needs recorded consent under TRAI's 2024-25 commercial-communication rules is UNVERIFIED here (not researched this session) | Code read | Rule 7 (verify), outbound etiquette |
| L5-18 | **P3** | `apps/workers/caller_memory_distil.py:208-216` | Prompt calls the agent "a business's AI receptionist" and uses clinic/booking examples ("asked about weekend timings", "booked for Saturday morning") | Neutral wording that covers outbound agents | Code read | Rule 1 |
| L5-19 | **P3** | `apps/api/agents/call_mistakes.py:338-376` | `recheck_call_mistakes` calls `mistakes_in(turns, language="")`; the pipeline passes the agent's language (`pipeline.py:1533`). Harmless for the two kinds it deletes today; a trap if `RECHECKED_KINDS` grows | Pass the agent's language | Code read | Consistency |
| L5-20 | **P3** | `WorkerSettings.job_completion_wait = 45`; bulk jobs run up to `WORKER_JOB_TIMEOUT_S` (300 s) | A deploy cancels a running bulk job; arq re-queues it (`worker.py:624-626`) and increments `job_try`; three deploys during one long job exhaust it with only `job_retries_exhausted` (severity `attention`) | Accept, or give bulk a longer grace in `compose.prod.yml` | arq source | Reliability |

Not findings (checked and sound): signed intake (v2 HMAC, delivered-at freshness, event-id
keying, agent and workspace mismatch refusals); the ack deadline and its non-ack on timeout;
`consume_outbox_once` wraps every registered function; `check_job_wiring` reads migrations;
`BULK_JOBS` refuses to boot on an unregistered name; the post-call extraction stays on Sarvam
(`GEMINI_EXTRACTION_DEFAULT = False`, `extraction.py:293`); gap quotes are built from
`redact(turn.text)` only.

---

## 3. Research notes

- **arq behaviour** (primary source: installed arq 0.28.0, `.venv/Lib/site-packages/arq/worker.py`,
  read 5 Nov 2026): a job whose name is not in the worker's `functions` is failed at once
  (:531-534) with no retry; only `Retry`, `RetryJob` and `CancelledError` are retried
  (:612-626); every other exception finishes the job (:627-634). The result key outlives the
  job for `keep_result` and blocks the same job id (`core/queue.py` docstring).
- **Idempotent consumer / transactional outbox**: the repo already cites
  microservices.io "Idempotent Consumer" (`reliability/service.py:733`). The same pattern
  family treats "published but not acknowledged by the consumer" as a state to reconcile,
  which is the gap in L5-03. Not re-fetched this session.
- **Mixed-version deploys**: the standard answer is that a producer must not route work to a
  queue until a consumer of the new version is reading it (expand-then-contract applied to
  job names). Our deploy already applies expand/contract to the schema (`vps-deploy.sh:949-962`)
  but not to job names on the bulk queue. Not re-fetched this session; the fix in §4 does not
  depend on an outside source.
- **Hand-written word counts** (rg over `apps/**/*.py`, Telugu U+0C00-0C7F or Devanagari
  U+0900-097F, 5 Nov 2026): `turn_checks.py` 228 lines, `call_purpose.py` 31, `call_mistakes.py` 1,
  `detection.py` 1 (plus 17 romanised hits), `extraction.py` (workers) 14 romanised,
  `calevate_shared/extraction.py` 8 romanised, `call_language.py` 7 romanised. Many are in
  comments; the regex and frozenset lines listed in L5-07 are code.
- Telugu false positives in L5-05 were verified by running the code's own patterns, not
  reasoned about.

---

## 4. Proposed fixes, grouped by files (no two groups share a file)

**G1. Bulk queue release safety (L5-01, L5-13, L5-14).** Files: `apps/workers/settings.py`
(`bulk_startup` writes its registered job names and release sha to a Redis key with a TTL
refreshed by the worker; `startup` unchanged), `apps/workers/dispatcher.py` (for a job where
`queue_for(job) == BULK_QUEUE`, publish only if that key lists the job; otherwise leave it
pending), `scripts/vps-deploy.sh` (swap `workers-bulk` BEFORE `workers`, and fix the
ordering comment at :1425-1430), tests in `tests/bulk_queue_test.py`. Either half alone closes
today's case; both together also cover jobs removed from bulk.

**G2. Published-but-unconsumed reconciliation (L5-03, L5-10, L5-11).** Files:
`apps/api/reliability/service.py` (keep the payload until `consumed_at` is set, scrub it in
`mark_outbox_consumed`; a `sweep_unconsumed_outbox` that finds `published AND consumed_at IS NULL`
past a per-job deadline for wrapped jobs, alarms, and returns them to `pending` with the
attempt budget, so arq's job-id dedupe and `consume_outbox_once` make a re-run safe),
`apps/workers/outbox_consumer.py` (scrub on consume), `apps/workers/call_quality_recheck.py`
(`Retry` on transient errors), `apps/api/core/alarm_severity.py` (new code). Note the scrub
change re-opens the D-170 credential-in-payload window until consumption; `deliver_auth_email`
should stay scrubbed at publish (it already keeps no result) and be excluded from the sweep.
Check with the security lane before moving the scrub.

**G3. Release-stamped outbox messages (L5-04).** Files: an alembic migration adding
`outbox_messages.min_release` (nullable), `apps/api/db/migration_offline.py` helper that
migrations use to stamp it, `reliability/service.claim_outbox_batch` (skip rows whose
`min_release` is newer than the dispatcher's). Then re-queue through a new migration for any
lost one-offs found by the queries below.

**G4. Caller memory subject and scope (L5-02, L5-08, L5-18).** Files:
`apps/workers/caller_memory_distil.py` (select `direction, from_e164, to_e164`; subject is the
other party; prompt asks for English notes, neutral wording; refuse non-Latin notes),
plus a data migration that re-files or deletes memory rows written from outbound calls (needs
the handle derivation in `compliance/caller_memory.py`, read-only for this group) and tests.
Erasure semantics: deleting the mis-filed rows is the safe default; ask the founder before
re-filing.

**G5. Gap and mistake detection (L5-05, L5-06, L5-16, L5-19).** Files:
`apps/api/insights/detection.py`, `apps/api/insights/service.py`, `apps/api/agents/call_mistakes.py`,
`packages/shared/src/calevate_shared/extraction.py` (an `unanswered_questions` key in the
reading, each with the caller turn index and whether the agent deferred, judged against this
business) and the pipeline stage that reads it. Then a recheck job like D-970 to clear the
false rows. Golden-transcript fixtures need Telugu cases (founder-supplied words).

**G6. Word lists out of code (L5-07, L5-15).** Files: `packages/shared/src/calevate_shared/spoken_style.json`
(new founder-owned sections), `calevate_shared/spoken_style.py` loader, `apps/api/agents/turn_checks.py`,
`apps/workers/call_language.py`, `apps/workers/extraction.py` (OfflineExtractor), the
extraction prompt examples. `compliance/optout.py` only with the compliance lane. Large; can be
done one heuristic at a time, each behind its existing tests.

**G7. Pipeline stage order (L5-09).** File: `apps/workers/pipeline.py` only: move STEP 3c and
3c' after STEP 5b (or into their own job via `enqueue_outbox_once`), wrapping each so a failure
alarms without failing the meter.

**G8. Non-call webhook events with no job (L5-12).** File: `apps/voice-runtime/webhook_routes.py`
(alarm on `claimed and job_id is None` for non-`INGEST_JOB` routes). Hard rule 3: keep it a
non-blocking `alert()`.

**G9. After-call call-back rule (L5-17).** File: `calevate_shared/extraction.py` prompt text for
`callback_requested`; research TRAI/DPDP position first.

### VPS commands to measure what has already been lost

```bash
sudo -u postgres psql -d calevate -c "SELECT job, status, count(*) AS n, count(*) FILTER (WHERE consumed_at IS NULL) AS unconsumed, min(created_at) AS first_at FROM outbox_messages WHERE status = 'published' GROUP BY job, status HAVING count(*) FILTER (WHERE consumed_at IS NULL) > 0 ORDER BY unconsumed DESC;"
```

```bash
sudo -u postgres psql -d calevate -c "SELECT job, created_at::date AS day, status, job_id = 'deduped' AS deduped, (consumed_at IS NOT NULL) AS consumed, count(*) FROM outbox_messages WHERE job IN ('refresh_field_reason','strip_retired_example_lines','name_core_details','write_starter_steps','recheck_call_quality','upgrade_business_copies') GROUP BY 1,2,3,4,5 ORDER BY 2,1;"
```

```bash
sudo -u postgres psql -d calevate -c "SELECT direction, caller_memory_state, count(*) FROM calls GROUP BY 1,2 ORDER BY 1,2;"
```

(Pruning: `retention.prune_reliability_tables` removes published outbox rows after 90 days, so
rows older than that cannot be checked.)

---

## 5. What I could not check, and why

- Production rows, Redis keys and container logs: not reachable from this lane; commands above.
- Whether the founder received the `job_function_not_registered` page today: alert delivery
  is not observable from the repo.
- `apps/workers/retention.py` (4,454 lines), `moments.py`, `qa_sampling.py`,
  `extraction_reread.py`, `call_timeline.py`: registration and existence checked, logic not
  audited line by line.
- Headline / next_step / goal reason / lead band: prompt text read (L5-15); their downstream
  rendering belongs to the dashboard lanes.
- TRAI position on auto-booked call-backs (L5-17): not researched this session, marked
  UNVERIFIED.
- No test suite was run (BRIEF: phase 1, and the suite is about 2 h on this machine).
