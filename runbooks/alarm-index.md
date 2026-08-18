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
| `engine_rejected` | CORE_LOGIC | The voice platform refused one request (4xx/5xx). Usually OUR request being wrong: a bad agent config, a wrong path, an unknown id. | Search logs for `engine_error` with the same route. If it follows a publish, the agent is not live. |
| `engine_rate_limited` | CORE_LOGIC | The vendor throttled us past our retry ladder. Nothing is lost; the caller sees a transient error. | Only act if sustained: it means concurrency above what the account allows. |
| `engine_bad_response` | CORE_LOGIC | A 2xx from the voice platform whose body is not JSON — a WAF page, a CDN interstitial, a proxy error. | Vendor-side or edge-side. Retry is safe; if it persists, the account or the region is being interfered with. |
| `engine_agent_drift_detected` | WORKER_STALL | A client's live agent is running a script we did not publish (D-123). Someone edited it in the vendor console. | `runbooks/agent-engine-drift.md`. **Do not re-publish blindly** — the vendor-side edit may be the correct emergency change. |
| `engine_agent_route_withdrawn` | WORKER_TERMINAL | An event arrived for an agent whose routing was WITHDRAWN — an offboarded client whose number is still pointed at the voice platform. The only other symptom is a stranger ringing it. | Release the number with the telephony provider and remove the agent at the engine. Nothing else in the system can discover this. |
| `engine_agent_unmapped` | WORKER_TERMINAL | The engine sent an event for an agent reference no row of ours knows. The call cannot be attributed to a tenant. | Check `engine_agent_routes`; usually an agent deleted on the vendor side, or a stale publish. |
| `engine_ingest_abandoned` | WORKER_TERMINAL | The post-call event could not be ingested after every retry. The call has no row. | `runbooks/calls-stopped.md`. The 10-minute reconciliation poller is what recovers it; if it does not, the execution is unreadable at the vendor. |
| `engine_drift_sweep_abandoned` | WORKER_TERMINAL | The half-hourly drift sweep failed every attempt. **Every client's live agent is unwatched until it succeeds.** | `runbooks/agent-engine-drift.md` §1. Credentials or vendor availability. |
| `engine_kb_drift_detected` | WORKER_STALL | Live agents hold knowledge on the voice platform that is not what was approved here. | `runbooks/kb-out-of-sync.md`. |
| `kb_drift_sweep_abandoned` | WORKER_TERMINAL | The KB drift sweep failed every attempt; published knowledge is unwatched. | `runbooks/kb-out-of-sync.md` §1. |
| `postcall_pipeline_stalled` | WORKER_STALL | Calls ended more than ten minutes ago and still owe an extraction. The 2-minute lead SLO is being missed now. | `runbooks/campaign-stall.md`; check worker liveness and queue depth at `/healthz/ready`. |
| `post_call_abandoned` | WORKER_TERMINAL | One call's post-call pipeline exhausted its retries. No lead, no extraction, no usage event for that call. | Re-drive by the poller, or investigate the call id in the alert. |
| `recording_copy_failed` | WORKER_DELIVERY | The call recording could not be copied into our storage. The call is otherwise intact. | Object storage credentials or bucket policy. The vendor's copy expires — act before it does. |
| `call_billable_without_cost` | WORKER_TERMINAL | The engine says the execution was billable and the adapter could not read a cost. We are being charged for something we cannot meter. | Money: reconcile against the vendor invoice. `runbooks/topup-payments.md` for the billing side. |
| `calls_never_finished` | WORKER_TERMINAL | The outstanding-call sweep found calls the engine will never say more about — **never transcribed, never metered, never invoiced**, and invisible to the stall report because a lost terminal webhook leaves the row at `in_progress` rather than `completed`. | `runbooks/calls-stopped.md`. The alert carries the ids; each is a call that happened and has no record. Check the vendor's execution directly before writing them off. |
| `outstanding_probe_incomplete` | WORKER_DELIVERY | Some outstanding calls could not be probed this sweep, so the recovered count is a FLOOR rather than a total. | Transient at first. Sustained means the engine is refusing reads and the guarantee of record (D-31) is degraded. |
| `outstanding_probe_budget_exhausted` | WORKER_DELIVERY | The sweep hit its per-tick vendor-request ceiling and stopped early. **The same tail of the tenant ordering is starved until the incident clears** — the truncation is deliberate and this alarm is what stops it being silent. | Expect it during a large backlog. If it repeats once the engine is healthy, the backlog is bigger than one sweep can drain and needs a manual widening. |
| `call_duration_negative` | WORKER_TERMINAL | The engine reported a negative call duration — a sentinel for "unknown", not a real length. The call is metered at ZERO minutes rather than failing to settle at all. | No action per call: the client is billed for no minutes, which is the safe direction. Repeated = a vendor payload change worth reading (D-251). |
| `reconciliation_fetch_failed` | WORKER_DELIVERY | The poller could not read an execution back from the engine. | Transient at first; sustained means the guarantee of record (D-31) is down. |
| `reconciliation_probe_incomplete` | WORKER_DELIVERY | Some executions could not be probed or re-driven, so the repair count is a FLOOR rather than a total. A sweep that skipped work reports fewer repairs, which reads like a healthy fleet. | Search the worker log for `reconciliation_probe_failed`. Those calls are recoverable only while they stay inside the 30-minute listing window. |
| `reconciliation_listing_incomplete` | WORKER_DELIVERY | A poll could not promise it saw the whole window. Executions inside the gap have no webhook, no repair and no metric. | Widen the window by hand or re-run the poll; treat the gap as calls to check. |
| `outbound_pool_empty` | WORKER_STALL | The inbound reserve is at or above the total line pool, so no outbound line exists. No campaign can dial. | Config: `INBOUND_RESERVE_RATIO` vs the platform line count (DEPLOYMENT §2a). |
| `dispatch_tick_overrun` | WORKER_STALL | One campaign dispatch tick took longer than its 30-second interval. | Read `dispatch_tick_seconds` for the trend. Sustained = the dispatcher is behind and campaigns dial late. |
| `dispatch_tick_overlap` | WORKER_STALL | The previous tick was still running when the next one started. The lease held, so nothing double-dialled. | Same investigation as `dispatch_tick_overrun`. |

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

## Metric names

Named recorders in `apps/api/core/alerting.py`. They are the vocabulary an SLO rule may
use; nothing else may emit a metric name (the guardrail fails on a direct
`metrics_log.info("metric", ...)`). There is no scraper yet — these are structured log
lines (DEPLOYMENT §8), so "read the metric" means searching them.

| Name | What it measures | Read it when |
| --- | --- | --- |
| `webhook_ack_ms` | The engine-webhook receiver's ack latency, against hard rule 3's 500ms budget. | `webhook_ack_slow` fired, or after a campaign burst. |
| `tool_ack_ms` | The in-call tool endpoint's ack latency, against TRD §6.2's 100ms budget. | `tool_ack_slow` fired. Deliberately a separate series from the above so neither dilutes the other. |
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
