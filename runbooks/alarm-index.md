# Alarm index — every code that can reach a phone

You were paged. The subject line is `[calevate/<env>/<service>] <code>`. Find the code
here: what it means in one line, and where to go next.

**This file is checked, not curated.** `scripts/check_alarm_wiring.py` derives the alarm
vocabulary from the tree — every `alert()` call, every `ProblemError` carrying a
`failure_stage` (which `core/errors.py` relays into `alert()` verbatim), every `*_code`
field on an ack meter, and every alarm the host backup chain emits in shell — and fails CI
in **both** directions: a row here with no call site behind it, and a code that can page
somebody with no row here. It is in `make guardrails` and in CI.

**Read the stage first.** `ROUTE_HANDLER` = something arrived and was refused;
`CORE_LOGIC` = a decision inside the app; `OUTBOX_DISPATCH`/`WORKER_*` = the reliability
path; `PROCESS_RESTART` = a service going down; `HOST_BACKUP` = the host chain, outside
every Python process (OPERATIONS §4).

**Noise bounds apply to all of them.** One page per `stage:code` per 15 minutes, 20/hour
globally with a burst of 6; suppressed and dropped counts ride the next delivery
(`apps/api/core/alerting.py`). "Happened once" and "still broken, 199 times" look
different — read the `note:` lines.

## Alarm codes

### The voice path — calls, campaigns, the engine

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `engine_error_spike` | CORE_LOGIC | The voice platform failed 10+ requests in 5 minutes (5xx, or no answer at all). Dials, publishes and the reconciliation poller are all affected. | `runbooks/calls-stopped.md` §9. Check the vendor's status page; the poller (D-31) is the guarantee of record, so calls already placed are not lost. Nothing to replay. |
| `engine_unreachable` | CORE_LOGIC | One request to the voice platform got no answer (DNS, TCP, TLS, timeout). Individually routine; it feeds `engine_error_spike`. | Only actionable in bulk — wait for the spike alarm or read `platform_engine_health`. |
| `engine_rejected` | CORE_LOGIC | The voice platform refused one request (4xx/5xx). Usually OUR request being wrong: a bad agent config, a wrong path, an unknown id. | Search logs for `engine_error` with the same `route`, and read the two fields on it: `status` and **`vendor_error`**, the vendor's own integer code from their error envelope — that is the value to quote at their support desk, and it is the only part of their body we keep (the human `message` quotes our request back at us, hard rule 6). If it follows a publish, the agent is not live. **On a DIAL, the status decides what happened to the contact**: 400/401/403/404 are documented refusals of the request, so no line was seized, the `calls` row is closed `failed` and the campaign contact keeps its retry ladder (`dial_not_placed` in the log); anything else could not rule out a ringing phone, so the contact is settled terminally and the client is escalated to (`campaign_dial_unconfirmed`). A burst of 401s is a revoked `BOLNA_API_KEY` and every campaign on the platform is stalled behind it. |
| `engine_rate_limited` | CORE_LOGIC | The vendor throttled us past our retry ladder. Nothing is lost; the caller sees a transient error. | Only act if sustained: it means concurrency above what the account allows. |
| `engine_bad_response` | CORE_LOGIC | A 2xx from the voice platform whose body is not JSON — a WAF page, a CDN interstitial, a proxy error. | Vendor-side or edge-side. Retry is safe; if it persists, the account or the region is being interfered with. |
| `engine_agent_drift_detected` | WORKER_STALL | A client's live agent is running a script we did not publish (D-123). Someone edited it in the vendor console. | `runbooks/agent-engine-drift.md`. **Do not re-publish blindly** — the vendor-side edit may be the correct emergency change. |
| `engine_transfer_leg_unhandled` | CORE_LOGIC | **An execution arrived carrying a `transfer_call_data` leg — the caller was handed to a human — and nothing in this repo models that leg.** The transferred call is a SECOND object at the vendor with its own recording, its own cost and its own hangup: none of it is copied, retained, reachable by erasure, or metered. `BOLNA_CAPABILITIES.transfer` is False, so the only way this happens is somebody enabling the Transfer Call tool on a published agent in the vendor console — no deploy required, and the drift sweep proves the PROMPT, not the tool list. | Two problems, in this order. **(1) DPDP:** a recording of a caller exists at the vendor that our erasure path cannot reach — note the execution id from the alert against its tenant before anything else. **(2) Money:** that leg is billed and unmetered (hard rule 7). Find the agent through `engine_agent_routes`, have the tool removed at the console, and `runbooks/agent-engine-drift.md` for the console-edit conversation. **Capture the payload as an adapter fixture while it exists** — it is the only real `transfer_call_data` anyone here has seen, and OPERATIONS §2 gate 18 needs one. Adopting transfer deliberately is a design decision (a second recording to copy, retain and erase; a second cost to meter; an unanswered disclosure question at the handoff), never a flag flip. |
| `engine_agent_semantic_routes_present` | CORE_LOGIC | **A read-back of a live agent carries vendor-side `routes` — semantic routes that answer a caller from a STATIC STRING without consulting the model.** The vendor's layer is `{route_name, utterances, response, score_threshold}`, matched on similarity of what the caller said (default 0.85). Hard rule 5's truthful-answer floor lives in the system prompt, and every instrument we have (publish read-back, `verification.judge`, the half-hourly drift sweep) scores the PROMPT — so anything a route matches never reaches the directive, including "am I talking to an AI?". Nothing in this tree sends `routes`; they were added in the vendor console. Raised from the publish read-back and from every drift sweep. The detail carries the agent ref, the route count and up to five operator-authored route names (never utterances or responses — that is caller conversation, hard rule 6). | Treat as a compliance incident, not a config drift: a published agent can be denying it is an AI while its prompt reads back perfect. Find the agent through `engine_agent_routes` and read the named routes in the vendor console. **A route that could plausibly match an AI-disclosure or recording question must be removed before anything else** — until it is, the agent can answer a caller untruthfully and no check here will say so. Then `runbooks/agent-engine-drift.md` for the console-edit conversation, which is the same one. Adopting routes deliberately would need the disclosure floor proven to survive them (every route's response composed with the same floor); today nothing here can prove that. |
| `engine_inbound_binding_failed` | CORE_LOGIC | **The voice platform was not told which agent answers a client's number.** Our `phone_numbers.agent_id` says the receptionist is assigned; the engine does not know it, so an incoming call reaches whatever the vendor console was last set to, or nothing. The alert names the agent id, the number's ROW id (never the number), what was intended (answer / stop answering) and the refusal code. | `engine_number_not_linked` means the number was never connected to the voice platform account — an onboarding step a person does, not an error to retry. `engine_rejected` means the vendor refused the binding: check **OPERATIONS §2 gate 25**, which is open on whether that route accepts a non-Twilio Indian number at all. Either way the number is not answering; until it is fixed the client's inbound line is dark, and re-publishing the agent retries it. |
| `engine_agent_route_withdrawn` | WORKER_TERMINAL | An event arrived for an agent whose routing was WITHDRAWN — an offboarded client whose number is still pointed at the voice platform. The only other symptom is a stranger ringing it. | Release the number with the telephony provider and remove the agent at the engine. Nothing else in the system can discover this. |
| `engine_agent_unmapped` | WORKER_TERMINAL | The engine sent an event for an agent reference no row of ours knows. The call cannot be attributed to a tenant. | Check `engine_agent_routes`; usually an agent deleted on the vendor side, or a stale publish. |
| `engine_ingest_abandoned` | WORKER_TERMINAL | The post-call event could not be ingested after every retry. The call has no row. | `runbooks/calls-stopped.md`. The 10-minute reconciliation poller is what recovers it; if it does not, the execution is unreadable at the vendor. |
| `engine_drift_sweep_abandoned` | WORKER_TERMINAL | The half-hourly drift sweep failed every attempt. **Every client's live agent is unwatched until it succeeds.** | `runbooks/agent-engine-drift.md` §1. Credentials or vendor availability. |
| `engine_kb_drift_detected` | WORKER_STALL | Live agents hold knowledge on the voice platform that is not what was approved here. | `runbooks/kb-out-of-sync.md`. |
| `kb_drift_sweep_abandoned` | WORKER_TERMINAL | The KB drift sweep failed every attempt; published knowledge is unwatched. | `runbooks/kb-out-of-sync.md` §1. |
| `engine_violation_open` | WORKER_STALL | **The voice platform has raised compliance flags against our account and nothing has been submitted against them.** Their word, not ours: "content policy, regulatory, or fraud". The detail names how many, how many tenants they touch, the age of the oldest, and up to five violation ids. | `runbooks/engine-violations.md`. This is the one alarm in this family only a person can clear — evidence submission is manual and the vendor publishes no deadline, so treat the age in the detail as the urgency. |
| `engine_violation_sweep_incomplete` | WORKER_DELIVERY | The violations listing could not promise it saw everything (page cap, a stuck `has_more`, or a missing one). **The open count in the other alarm is a FLOOR, not a total.** | `runbooks/engine-violations.md` §3. Re-read the list by hand in the vendor console before concluding the account is clean. |
| `engine_violation_sweep_abandoned` | WORKER_TERMINAL | The hourly compliance-flag sweep failed every attempt. The platform's flags are unwatched until it succeeds. | `runbooks/engine-violations.md` §3. Credentials or vendor availability — the same two causes as `engine_drift_sweep_abandoned`. |
| `postcall_pipeline_stalled` | WORKER_STALL | Calls ended more than ten minutes ago and still owe an extraction. The 2-minute lead SLO is being missed now. | `runbooks/campaign-stall.md`; check worker liveness and queue depth at `/healthz/ready`. |
| `post_call_abandoned` | WORKER_TERMINAL | One call's post-call pipeline exhausted its retries. No lead, no extraction, no usage event for that call. | Re-drive by the poller, or investigate the call id in the alert. |
| `recording_copy_failed` | WORKER_DELIVERY | The call recording could not be copied into our storage. The call is otherwise intact. | Object storage credentials or bucket policy. The vendor's copy expires — act before it does. |
| `call_billable_without_cost` | WORKER_TERMINAL | The engine says the execution was billable and the adapter could not read a cost. We are being charged for something we cannot meter. | Money: reconcile against the vendor invoice. `runbooks/topup-payments.md` for the billing side. |
| `engine_cost_implausible` | CORE_LOGIC | One call metered at a per-minute cost orders of magnitude away from what a minute costs (band ₹0.10–₹100/min; a real call is ₹0.5–6/min). **The row is already written** — this alarm is about a number that landed, not one that was refused. | `runbooks/vendor-cost-unit.md`, which carries the whole sequence and what NOT to do. In short: read the ratio in the detail — **near 100** is the minor-unit assumption (`_MINOR_UNITS_PER_MAJOR` in `engine/bolna.py`), **near 90** is the currency one (a rupee figure multiplied by the USD rate) — settle it against one vendor invoice line (OPERATIONS §2 gate 7), fix the constant, then restate the rows already metered with `uv run python -m scripts.correct_cost_unit` — `usage_events` is append-only, so the repair is a compensating row and never an edit. Do not change the divisor on a hunch. |
| `calls_never_finished` | WORKER_TERMINAL | The outstanding-call sweep found calls the engine will never say more about — **never transcribed, never metered, never invoiced**, and invisible to the stall report because a lost terminal webhook leaves the row at `in_progress` rather than `completed`. | `runbooks/calls-stopped.md`. The alert carries the ids; each is a call that happened and has no record. Check the vendor's execution directly before writing them off. |
| `outstanding_probe_incomplete` | WORKER_DELIVERY | Some outstanding calls could not be probed this sweep, so the recovered count is a FLOOR rather than a total. | Transient at first. Sustained means the engine is refusing reads and the guarantee of record (D-31) is degraded. |
| `outstanding_probe_budget_exhausted` | WORKER_DELIVERY | The sweep hit its per-tick vendor-request ceiling and stopped early. **The same tail of the tenant ordering is starved until the incident clears** — the truncation is deliberate and this alarm is what stops it being silent. | Expect it during a large backlog. If it repeats once the engine is healthy, the backlog is bigger than one sweep can drain and needs a manual widening. |
| `call_duration_negative` | WORKER_TERMINAL | The engine reported a negative call duration — a sentinel for "unknown", not a real length. The call is metered at ZERO minutes rather than failing to settle at all. | No action per call: the client is billed for no minutes, which is the safe direction. Repeated = a vendor payload change worth reading (D-251). |
| `reconciliation_fetch_failed` | WORKER_DELIVERY | The poller could not read an execution back from the engine. | Transient at first; sustained means the guarantee of record (D-31) is down. |
| `reconciliation_probe_incomplete` | WORKER_DELIVERY | Some executions could not be probed or re-driven, so the repair count is a FLOOR rather than a total. A sweep that skipped work reports fewer repairs, which reads like a healthy fleet. | Search the worker log for `reconciliation_probe_failed`. Those calls are recoverable only while they stay inside the 30-minute listing window. |
| `reconciliation_listing_incomplete` | WORKER_DELIVERY | A poll could not promise it saw the whole window. Executions inside the gap have no webhook, no repair and no metric. | Widen the window by hand or re-run the poll; treat the gap as calls to check. |
| `engine_listing_window_too_wide` | CORE_LOGIC | **A reconciliation listing asked the engine for more history than it will serve** (7 days, `_LISTING_MAX_WINDOW` in `apps/api/engine/bolna.py`), and the adapter REFUSED rather than quietly narrowing the window — a narrowed window would make `complete=True` a claim about a period nobody agreed to skip. This one is OURS, not the vendor's: no production caller can reach it, because `reconcile_executions` polls a 30-minute window. | Something hand-run asked for too much: a backfill, a script, or new code. Split the request into windows of 7 days or fewer and repeat it to cover the period; never widen the bound (D-414). Nothing was lost and nothing was mis-metered — the listing did not run, so no rows were read and none were skipped. If it fired from a scheduled job, the job is the bug. |
| `dial_recall_unstopped` | WORKER_STALL | **Outbound was halted and one or more dials the voice platform had already accepted could not be pulled back.** The engine's stop route *"cannot stop a call already in progress"*, so a dial that started ringing between the scan and the stop runs to its end. The detail carries the count, the total the scan found, and up to five call ids. | `runbooks/campaign-stall.md` §1. The named calls are ringing or about to; nothing here can stop them, and the poller (D-31) will close their rows normally. What to check is WHY — if the count is most of the batch, the account's concurrency ceiling is far below the outbound pool and the vendor was holding a queue (OPERATIONS §2 gate 31). Re-post the halt to run another pass over anything still queued. **The count cannot yet separate "already ringing" from "the vendor does not know this id"** — the stop route's refusal codes are OPERATIONS §2 gate 35 — so read it as an upper bound on phones that will still ring. |
| `dial_recall_incomplete` | WORKER_STALL | The recall scan hit its 500-dial cap, so the "stopped" count is a FLOOR and more dials may still be queued at the vendor. | Re-post the halt (same confirmation header) to run another pass; the stamp on each recalled dial means a second pass sees only what the first did not reach. A fleet that reaches this cap is one nobody here has sized — read `RECALL_SCAN_LIMIT` in `apps/workers/dial_recall.py` before raising it. |
| `dial_recall_impossible` | WORKER_TERMINAL | Outbound was halted, but the voice platform holds no credentials in this environment, so no queued dial could be recalled. | Only reachable with a named engine and no key — the same condition that stops publishes and the poller. Restore `BOLNA_API_KEY` and re-post the halt. Until then the halt stops NEW dials only. |
| `dial_recall_abandoned` | WORKER_TERMINAL | The recall job failed every attempt. Outbound is halted but dials already accepted by the vendor were not recalled and will ring. | `runbooks/campaign-stall.md` §1. Read the worker log for `dial_recall_run_failed` — the scan and the engine are the two things that can fail this. Re-post the halt to retry once the cause is cleared. |
| `dial_recall_not_queued` | CORE_LOGIC | **The halt landed but its recall job could not be put on the queue** — Redis was unreachable at that instant. The switch IS thrown; the recall never started. | This is the one alarm here that fires from the API rather than a worker, and it is deliberately not a refusal: telling an operator the switch failed when it did not would send them to throw it again. Fix the queue, then re-post the halt to run the recall. |
| `outbound_pool_empty` | WORKER_STALL | The inbound reserve is at or above the total line pool, so no outbound line exists. No campaign can dial. | Config: `INBOUND_RESERVE_RATIO` vs the platform line count (DEPLOYMENT §2a). |
| `dispatch_tick_overrun` | WORKER_STALL | One campaign dispatch tick took longer than its 30-second interval. | Read `dispatch_tick_seconds` for the trend. Sustained = the dispatcher is behind and campaigns dial late. |
| `dispatch_tick_overlap` | WORKER_STALL | The previous tick was still running when the next one started. The lease held, so nothing double-dialled. | Same investigation as `dispatch_tick_overrun`. |
| `dispatch_budget_starved` | WORKER_STALL | **One or more tenants dialled NOTHING this tick because the shared outbound pool ran out before their turn — and the spend order does not rotate, so it will be the same tenants next tick.** The order is `dispatch_scan()`'s `ORDER BY tenant_id`, and `tenant_id` is uuid_v7 (time-ordered), so the tail is the NEWEST clients and the starvation is indefinite, not transient. Every tick still reports a healthy `dialled=N`; this alarm is the only thing that says who got none. The detail carries the pool, the platform-wide active count, and up to five starved tenant ids. | `runbooks/campaign-stall.md` §4a. Read the suppressed counts: once is a busy minute, a sustained repeat is a client dialling zero for as long as it has been firing. There is no floor to raise — we model caps only — so the levers are the pool (`PLATFORM_LINES_TOTAL`, and whether the engine account's real ceiling is higher) and the sliders of the tenants at the HEAD of the order. The durable fix is guaranteed floors plus proportional surplus, which is a plan field and a commercial decision, not a config change. |

### Compliance and consent

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `campaign_complaint_spike` | CORE_LOGIC | Five or more of a campaign's connected calls ended in an opt-out, and that is at least 10% of them. **The campaign has been paused automatically** (FLOWS §5). | `runbooks/dnc-complaint.md` §9. Under TCCCPR five unique complaints in ten days suspends the client's outgoing service — treat this as the last cheap moment. Resuming re-pauses while the 24h window still holds the spike. |
| `in_call_optout_unresolved` | WORKER_TERMINAL | A caller asked to be left alone mid-call and the fast path could not resolve the execution. The post-call transcript pass is the backstop. | `runbooks/dnc-complaint.md`. Confirm the suppression landed; the gap is a window in which a campaign can still dial. |
| `in_call_optout_agent_unmapped` | WORKER_TERMINAL | An in-call opt-out arrived for an agent reference no row of ours knows, so no tenant owns it. | Suppress the number by hand from the ops DNC screen. |
| `in_call_optout_unattributable` | WORKER_TERMINAL | An in-call opt-out with no usable caller number to suppress. | Same: find the call and add the number by hand. |
| `opt_out_unattributable` | WORKER_TERMINAL | The post-call transcript pass detected an opt-out on a call with no usable number. | Same as above, from the call record. |
| `retention_below_trai_floor` | WORKER_TERMINAL | A tenant's retention policy would delete records earlier than the regulatory floor allows. The sweep refused. | `docs/SECURITY-COMPLIANCE.md` §4. Fix the policy row; do not relax the floor. |
| `retention_sweep_incomplete` | WORKER_TERMINAL | Some tenants did not complete tonight's retention sweep. Their expired recordings, transcripts and leads are still held. | Re-run the sweep. A DPDP obligation missed by a night is a fact to record. |
| `erasure_requests_overdue` | WORKER_STALL | A DPDP erasure request has passed its deadline and is still not executed. | `docs/SECURITY-COMPLIANCE.md` §4; execute it by hand from the ops screen. |
| `erasure_probe_deadline_exhausted` | WORKER_DELIVERY | The overdue-erasure walk ran out of its time budget and stopped part-way through the fleet. **`overdue_erasures=0` from that tick means "none among the tenants it reached", not "none".** The starved tail is stable (the directory is ordered by tenant id), so the same tenants are skipped every hour until this is acted on. | Not a longer deadline — the next stop after it is arq's `job_timeout`, and past that the alarm stops running entirely. The walk costs one session per organization because `deletion_requests` is FORCE-RLS'd; the fix is a cross-tenant probe. |
| `tenant_erasure_mark_failed` | WORKER_TERMINAL | An offboarding erasure ran and `organizations.deleted_at` was not set — so nothing was erased. | Re-run; the mark is the gate the whole erasure hangs off. |

### Leads, notifications, integrations

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `auth_email_exhausted` | WORKER_DELIVERY | A sign-in email — password reset, OTP second factor, or an invitation — failed every attempt. **Somebody is locked out and the screen truthfully told them mail was on its way.** | Check the email transport (`EMAIL_PROVIDER`, `RESEND_API_KEY`, sender-domain verification). The ladder is deliberately tight (10s, 30s) because an OTP expires in ten minutes, so this fires while the person is still watching the screen. |
| `hot_lead_notification_exhausted` | WORKER_DELIVERY | A hot-lead email failed every attempt. The client did not hear about a lead. | Check the email transport (`EMAIL_PROVIDER`, sender domain verification). |
| `hot_lead_no_channel` | WORKER_TERMINAL | A hot lead arrived for a tenant with no billing email and no other channel. Nothing can be delivered. | Fill in the tenant's contact details. |
| `hot_lead_whatsapp_exhausted` | WORKER_DELIVERY | The WhatsApp hot-lead alert failed every attempt. | BSP credentials or template status. Email is the other channel. |
| `hot_lead_whatsapp_rejected` | WORKER_TERMINAL | The BSP refused the WhatsApp alert outright (template, opt-in, number). | Fix the template registration or the opt-in record; retrying will not help. |
| `campaign_escalation_exhausted` | WORKER_DELIVERY | A campaign follow-up message failed every attempt. | `runbooks/campaign-escalation-refused.md`. |
| `campaign_escalation_rejected` | WORKER_TERMINAL | The BSP refused the campaign follow-up. | `runbooks/campaign-escalation-refused.md`. |
| `campaign_escalation_unrecordable` | WORKER_TERMINAL | A campaign contact exhausted its attempts and there is no lead row to record the follow-up on. | Data problem: the contact never produced a lead. Check the ingest path for that campaign. |
| `outbound_webhook_exhausted` | WORKER_DELIVERY | A client CRM webhook failed every attempt and is now dead-lettered. | `runbooks/webhook-delivery-failures.md`; replay with `POST /v1/ops/outbox/replay` after the endpoint is fixed. |
| `delivery_body_not_retained` | WORKER_DELIVERY | The delivered webhook body could not be written to object storage. **The delivery itself succeeded** — only the evidence is missing. | Object storage; no client impact. |
| `meta_page_token_invalid` | ROUTE_HANDLER | A client's Meta page token is dead. Every lead from that source refuses until it is replaced. | Replace the token in the client's integration settings. |
| `meta_leads_retrieval_denied` | ROUTE_HANDLER | The Meta token is alive but not permitted to retrieve leads. | The app's permissions or review status; the client must re-authorize. |
| `meta_signature_rejected` | ROUTE_HANDLER | A Meta webhook arrived with a signature we could not verify. | If sustained, the app secret is wrong; a single one is somebody probing. |

### The reliability path — outbox, inbox, webhooks in

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `job_function_not_registered` | WORKER_TERMINAL | **arq accepted an enqueue for a job name no worker has registered, and dropped it.** The enqueuing code saw success; the side effect never happened. arq logs a warning, retries nothing, and nothing in this repo reads its result keys — so without this alarm the only symptom is an outcome that silently never arrives. | A deploy skew (a producer shipped ahead of its worker) or a rename that missed `WorkerSettings.functions`. `scripts/check_job_wiring` fails the build on this in CI; reaching production means it was bypassed. Re-enqueue after fixing the registration. |
| `job_retries_exhausted` | WORKER_TERMINAL | A job spent its whole retry ladder and arq gave up. This is where every `Retry` ends when the condition never clears, and where a cron cancelled three times at `job_timeout` ends — e.g. the nightly retention sweep gone until tomorrow with only a log line. | Read the job name in the detail and go to that job's own runbook row. The next scheduled tick is the replay for crons; queued jobs need re-enqueuing. |
| `outbox_dead_letter` | OUTBOX_DISPATCH | Messages spent their whole attempt budget and need an operator. | `runbooks/webhook-delivery-failures.md` §3; `POST /v1/ops/outbox/replay`. |
| `outbox_queue_unreachable` | OUTBOX_DISPATCH | The dispatcher could not reach Redis and handed the batch back with a backoff. **Nothing is lost and there is nothing to replay.** | Fix Redis; the next tick drains it. Do NOT replay. |
| `webhook_source_rejected` | ROUTE_HANDLER | An engine webhook arrived from an address outside the allowlist. For an unsigned engine this is the whole authenticity control. | If the vendor renumbered, update `BOLNA_WEBHOOK_SOURCE_IPS` — until then every call waits for the 10-minute poller. Otherwise it is a stranger. |
| `webhook_payload_too_large` | ROUTE_HANDLER | An engine webhook body exceeded the accepted size and was refused. | The poller recovers the call. Repeated = a vendor payload change. |
| `webhook_unkeyable` | ROUTE_HANDLER | A webhook body carried no usable execution id, so it could not be deduplicated or attributed. | The poller recovers the call. Repeated = a vendor payload change. |
| `webhook_body_timeout` | ROUTE_HANDLER | The request body did not finish arriving inside the deadline. | Network, or a sender that opened a request and stalled. |
| `webhook_ack_slow` | ROUTE_HANDLER | The webhook receiver breached its 500ms ack budget. Usually CAPACITY, not a bug. | OPERATIONS §5's triage ladder: flat distribution = add `--workers`; long tail = a dependency. |
| `webhook_claim_timeout` | ROUTE_HANDLER | The receiver hit its 2-second abandon deadline and answered 503. Calls are now waiting on the 10-minute poller. | An incident, not a warning. Same triage, acted on immediately. |
| `webhook_payload_mismatch` | ROUTE_HANDLER | A settled webhook transition was re-delivered with different body bytes. | Recorded, not acted on (the payload is a hint; the poller is truth). Investigate if it repeats. |
| `tool_source_rejected` | ROUTE_HANDLER | An in-call tool call arrived from an address outside the allowlist. | Same as `webhook_source_rejected`, on the in-call path — the agent's opt-out tool is not working. |
| `tool_payload_too_large` | ROUTE_HANDLER | An in-call tool body exceeded the accepted size. | The caller's opt-out may have been missed; the transcript pass is the backstop. |
| `tool_call_unkeyable` | ROUTE_HANDLER | An in-call tool call carried no usable execution id. | As above — check the transcript pass suppressed the number. |
| `tool_enqueue_timeout` | ROUTE_HANDLER | The in-call tool endpoint could not queue its work inside the budget. | Redis. The caller's request is at risk of being dropped. |
| `tool_body_timeout` | ROUTE_HANDLER | An in-call tool request body did not arrive inside the deadline. | Network between the engine and us. |
| `tool_ack_slow` | ROUTE_HANDLER | The in-call tool endpoint breached its 100ms budget (TRD §6.2). | Read `tool_ack_ms`. The in-call experience degrades before anything fails. |

### Money and platform state

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `razorpay_webhook_unconfigured` | ROUTE_HANDLER | A payment webhook arrived and no webhook secret is configured, so it cannot be verified. | Set the secret. Until then top-ups do not credit. `runbooks/topup-payments.md`. |
| `razorpay_webhook_bad_signature` | ROUTE_HANDLER | A payment webhook failed signature verification. | One is somebody probing; a burst after a rotation means the secret is stale. |
| `razorpay_unknown_tenant` | ROUTE_HANDLER | A verified payment names a tenant we cannot find. Money arrived with nowhere to credit it. | `runbooks/topup-payments.md`; reconcile by hand. |
| `setup_fees_unissued` | WORKER_TERMINAL | The one-time setup-fee job failed every attempt for some tenants. Those clients were not charged. | Re-run; the ledger is append-only, so a second successful run is idempotent by key. |
| `tenant_spend_capped` | CORE_LOGIC | **Outbound calling has stopped for one tenant**: this month's usage reached their effective spend cap. Every dial is refused with `rule=spend_cap` and their campaigns read 'running' while dialling nothing. Inbound is unaffected. | `runbooks/calls-stopped.md` §3 (causes 4-6). Clears on the IST month roll, by raising `plans.hard_cap_*`, or by the client raising their own cap. |
| `tenant_spend_cap_approaching` | CORE_LOGIC | A tenant has used 80% of their effective spend cap. At 100% their campaigns stop dialling silently. | Check the campaign and the ceiling before it gets there — the same screens as above. |
| `ai_platform_brake_tripped` | CORE_LOGIC | Platform-wide dashboard-AI spend crossed the brake. **AI help is now paused for every tenant.** Calls, campaigns and leads are unaffected. | Clears on the IST month roll. Releasing sooner is a code change to `PLATFORM_AI_BRAKE_INR`. Find the tenant or loop that spent it. |
| `ai_platform_brake_near` | CORE_LOGIC | Platform-wide dashboard-AI spend passed 80% of this month's brake. | Same investigation, before it stops. |
| `ai_assist_unmeterable` | CORE_LOGIC | A dashboard assist ran and the provider returned no usage metadata, so it could not be metered. | We paid for something we cannot bill or attribute. Check the provider response shape. |
| `platform_secret_unreadable` | CORE_LOGIC | Stored credentials could not be decrypted with this deployment's `PLATFORM_KEK`. | The wrong KEK is deployed. Put the correct one back — do NOT rotate on top of it. |
| `platform_secret_set` | CORE_LOGIC | A platform credential was installed or rotated. **Informational, and deliberately loud.** | If this was not you, treat it as a compromise of the admin realm. |
| `platform_config_never_loaded` | CORE_LOGIC | This process has never read `platform_settings`, so it is running on environment variables alone. | Console changes are not reaching it. Check DB connectivity from that service. |
| `platform_config_stale` | CORE_LOGIC | `platform_settings` could not be re-read; the last known values are still in force. | A console change has not taken. Same investigation. |

### Identity, auth and the request edge

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `unhandled_exception` | ROUTE_HANDLER | An exception escaped every handler and the caller got a generic 500. The exception class is appended to the code. | Always a bug. Find the traceback by the `path` id in the alert. |
| `client_ip_unresolved` | ROUTE_HANDLER | No trusted hop vouched for a caller's address. `audit_log.ip` and per-caller rate limits are degraded. | The edge's real-IP chain (SEC-COMP §5). Usually a proxy config change. |
| `signal_received` | PROCESS_RESTART | A service received SIGTERM/SIGINT and is draining. Expected during a deploy. | Only actionable if unexpected — an unplanned restart is an OOM or a crash loop. |

### Quality

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `qa_sample_draw_failed` | WORKER_DELIVERY | The weekly QA draw failed for some tenants. | Re-run; the draw is reproducible by design. |
| `qa_sample_draw_abandoned` | WORKER_TERMINAL | The weekly draw failed for every tenant after every attempt. **This week's 5% sample is undrawn.** | Re-run before the week closes, or the sample is lost. |

### The host backup chain (`HOST_BACKUP`)

These reach the same inbox through `notify.sh` → `alert-to-app.sh` →
`python -m scripts.host_alert`. They come from the host, as `postgres`, outside every
Python process. Full procedures: `runbooks/backup-heartbeat-silent.md`,
`runbooks/database-restore.md`, `runbooks/backup-restore-drill.md`.

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `basebackup_failed` | HOST_BACKUP | `wal-g backup-push` exited non-zero — no new base backup exists tonight. | `runbooks/database-restore.md`. Every hour without one lengthens restore time. |
| `basebackup_prune_failed` | HOST_BACKUP | Old base backups were not pruned. Storage grows; recoverability is unaffected. | Housekeeping — but a full bucket becomes the first alarm. |
| `base_backup_stale` | HOST_BACKUP | The newest base backup is older than expected. | Find out why the timer stopped producing one; restore time is growing meanwhile. |
| `no_base_backup` | HOST_BACKUP | `wal-g backup-list` returned no base backup with a readable timestamp. **WAL alone cannot be restored.** | The most serious backup alarm. Take a base backup now. |
| `backup_list_failed` | HOST_BACKUP | `wal-g backup-list` failed; we cannot tell whether a base backup exists. | Credentials, network or bucket. Treat as unknown, not as fine. |
| `backup_list_unparseable` | HOST_BACKUP | The newest base backup's timestamp could not be parsed. Backup age is UNKNOWN. | wal-g output shape changed; fix the parser before trusting the age. |
| `archiver_failing` | HOST_BACKUP | `pg_stat_archiver` reports the most recent archive attempt FAILED. WAL is not reaching the bucket. | Point-in-time recovery is degrading right now. |
| `archiver_never_succeeded` | HOST_BACKUP | Archiving has never succeeded on this cluster. | The archive command has never worked. Nothing is recoverable past the last base backup. |
| `archive_stale` | HOST_BACKUP | No WAL segment archived recently — the 15-minute RPO (OPERATIONS §5) is being missed now. | Same investigation as `archiver_failing`. |
| `pg_wal_backlog` | HOST_BACKUP | Unarchived WAL is accumulating in `pg_wal`. If it keeps growing the cluster stops accepting writes. | An outage precursor. Clear the archive path before the disk fills. |
| `wal_chain_broken` | HOST_BACKUP | `wal-g wal-verify` reports a gap or a timeline problem. **Point-in-time recovery across that gap is impossible.** | Take a fresh base backup immediately; the gap is permanent. |
| `wal_verify_failed` | HOST_BACKUP | `wal-g wal-verify` could not run. The archive is UNVERIFIED. | Credentials, network or bucket. Unverified is not verified. |
| `wal_verify_unparseable` | HOST_BACKUP | `wal-verify` returned JSON with no recognisable status. The archive is UNVERIFIED. | wal-g output shape changed; fix before trusting the verdict. |
| `walg_unavailable` | HOST_BACKUP | wal-g or its config is missing on this host, so the destination cannot be checked from here. | The check is blind, which is not the same as the backups being fine. |
| `health_db_unreachable` | HOST_BACKUP | The health check could not read `pg_stat_archiver`; the archiver's state is unknown. | Postgres, or the health check's role. |
| `health_pg_wal_unreadable` | HOST_BACKUP | `pg_ls_waldir` could not be read (needs `pg_monitor`); the disk-fill precursor is unmonitored. | Grant the role. |
| `backup_health_gap` | HOST_BACKUP | The health check did not run for a long stretch and has just resumed. **Backups were unmonitored for that period.** | Check the named nights by hand — nothing else looked at them. |
| `backup_timer_missing` | HOST_BACKUP | A backup timer's unit is not installed on this host. That backup is not scheduled at all. | Install the unit (`infra/backup/README.md`). |
| `backup_timer_inactive` | HOST_BACKUP | A backup timer is not armed. Nothing will trigger that backup. | `systemctl enable --now` the timer. |
| `backup_timer_not_firing` | HOST_BACKUP | A timer is armed but has never fired, or has not fired for longer than its schedule allows. | Being enabled is not the same as having run. Check the unit's last trigger. |
| `backup_heartbeat_undelivered` | HOST_BACKUP | Backups are healthy but the external dead-man heartbeat could not be sent. | `runbooks/backup-heartbeat-silent.md`. The monitor will page on the silence — that is the correct outcome. |
| `offsite_pgdump_failed` | HOST_BACKUP | `pg_dump` exited non-zero; no logical dump exists tonight. | The offsite copy is the one that survives a Cloudflare account event. |
| `offsite_dump_shrank` | HOST_BACKUP | Tonight's dump is far smaller than last night's — suspect an RLS-filtered dump, dropped objects, or a truncated write. | **Do not overwrite the previous dump.** Investigate before the next run. |
| `offsite_encrypt_failed` | HOST_BACKUP | `age` encryption failed; the chain refused to upload plaintext. | Fix the identity/recipient; the refusal was correct. |
| `offsite_upload_failed` | HOST_BACKUP | `rclone` could not upload the encrypted dump to the offsite provider. | Credentials or the provider. No offsite copy tonight. |
| `offsite_readback_failed` | HOST_BACKUP | The dump uploaded but could not be read back. **Treat it as absent.** | An unreadable backup is not a backup. |
| `offsite_digest_mismatch` | HOST_BACKUP | The uploaded dump's digest does not match what was written. | Corruption in transit or at rest. Re-upload and re-verify. |
| `offsite_redis_missing` | HOST_BACKUP | No Redis RDB found to copy; in-flight jobs are not covered tonight. | Lower severity — the queue is rebuildable — but a real gap in the night's coverage. |
| `alert_delivery_failed` | HOST_BACKUP | The host alert command exited non-zero: the alert above reached journald and **nobody else**. | Fix `BACKUP_ALERT_COMMAND` / the email transport, then read journald for what was missed. |
| `alert_delivery_unconfigured` | HOST_BACKUP | No `BACKUP_ALERT_COMMAND` and no relay beside the script; host alerts reach journald only. | OPERATIONS §8's pre-launch gate. Configure it before relying on any alarm above. |

### Schedules and certificates

| Code | Stage | What it means | What to do |
| --- | --- | --- | --- |
| `tls_certificate_expiring` | CORE_LOGIC | The certificate nginx is serving for our public hostnames expires in 21 days or fewer. Certbot renews at 30 days, so renewal has been failing for a week or more. | `runbooks/tls-expiry.md`. All four public surfaces expire together. |
| `tls_certificate_unreadable` | CORE_LOGIC | We could not read the origin's certificate at all — a stopped nginx, a wrong `TLS_ORIGIN_ADDRESS`, a firewall change. | `runbooks/tls-expiry.md` §3. Being unable to see the certificate hides an expiry rather than causing one. |
| `campaign_schedule_expired` | WORKER_TERMINAL | A scheduled campaign start was still blocked 24 hours later; the campaign is back in draft. | Read the blocker rules on the campaign screen and re-schedule. |
| `campaign_schedule_unparseable` | WORKER_TERMINAL | A campaign's schedule carries no offset or is not an ISO-8601 instant. The campaign did not start. | Data problem in `campaigns.schedule`; fix and re-schedule. |
| `campaign_schedule_kind_unknown` | WORKER_TERMINAL | A campaign's schedule names a kind nothing reads. The campaign did not start. | Only `one_time` is implemented (FLOWS §5). |
| `campaign_recurrence_unreadable` | WORKER_TERMINAL | A campaign's repeat rule is not usable. The campaign did not start. | Same. |
| `campaign_recurrence_skipped` | WORKER_STALL | A repeating occurrence came due late and was skipped rather than fired. | Deliberate: a late unrequested call is what generates complaints. Check why the tick was late. |
| `engine_credential_not_replaced` | CORE_LOGIC | The voice platform APPENDED the LLM credential we wrote beside the superseded one instead of replacing it, so it now holds several under one name and chooses between them itself. Which key the in-call model leg authenticates with has stopped being a function of anything we do. | Open the vendor console, delete every entry under that credential name except the newest, and re-run `uv run python -m scripts.probe_bolna_providers` to confirm the store now replaces rather than appends. This also answers an open vendor question: their `POST /providers` documents `added` with no `updated`, so replace-vs-append was never written down — if this fires, it is append. |

## Metric names

Named recorders in `apps/api/core/alerting.py`. They are the vocabulary an SLO rule may
use; nothing else may emit a metric name (the guardrail fails on a direct
`metrics_log.info("metric", ...)`). There is no scraper yet — these are structured log
lines (DEPLOYMENT §8), so "read the metric" means searching them.

| Name | What it measures | Read it when |
| --- | --- | --- |
| `webhook_ack_ms` | The engine-webhook receiver's ack latency, against hard rule 3's 500ms budget. | `webhook_ack_slow` fired, or after a campaign burst. |
| `tool_ack_ms` | The in-call tool endpoint's ack latency, against TRD §6.2's 100ms budget. | `tool_ack_slow` fired. Deliberately a separate series from the above so neither dilutes the other. |
| `inbox_handling_ms` | How long one inbound webhook event sat between being recorded and being handled — the receiver's own half of the reliability triad. | Leads or call records are late and `pipeline_lag_seconds` looks healthy: the delay is upstream of the pipeline, in the inbox. |
| `inbox_lag_seconds` | The age of the OLDEST unhandled inbox event at each dispatch tick. A rising floor means the drain is behind, not that one event was slow. | Read it beside `inbox_handling_ms`: handling fast + lag rising is a throughput problem, both rising is a dependency. |
| `pipeline_lag_seconds` | Hangup → lead visible, per stage. The 2-minute SLO. | `postcall_pipeline_stalled` fired, or a client says leads are late. |
| `speed_to_lead_seconds` | Web form submitted → outbound dial placed. FLOWS §4 targets < 60s. | A client says the instant callback is not instant. |
| `outbox_lag_seconds` | How long a side effect waited in the outbox before dispatch. | Anything downstream looks slow. |
| `outbox_dlq_depth` | How many outbox messages are dead-lettered right now. | `outbox_dead_letter` fired. Read beside the console's `deferred` count — the pair is the diagnosis. |
| `extraction_failures` | Post-call extractions that failed, by reason. | Leads are arriving empty. |
| `reconciliation_repairs` | Calls the poller had to fix, by kind. `missing_call` = a webhook we never got; `unfinished_pipeline` = our own bug. | A rising `unfinished_pipeline` is ours to fix. |
| `reconciliation_listing_incomplete` | Polls that could not promise they saw the whole window, by reason. | Any non-zero value means calls may have gone unseen. |
| `webhook_replay_divergence` | A settled transition re-delivered with different bytes. | Deliberately not an alarm. Investigate a sustained rate. |
| `compliance_blocks` | Dials refused by the gate, by rule. `complaint_spike`, `spend_cap`, `dnc`, `no_consent`, … | A campaign stopped and nobody knows why (`runbooks/campaign-stall.md` §8). |
| `campaign_dials` | Contacts rung per dispatch tick, with how many the gate blocked. | The pair is the signal: 0 dialled with 40 blocked is very different from 0 and 0. |
| `dispatch_tick_seconds` | How long one campaign dispatch tick took, against its 30-second interval. | `dispatch_tick_overrun` or `dispatch_tick_overlap` fired. |
