"""How loud each alarm is — the one thing `alert()` never asked (D-591).

WHY THIS FILE EXISTS. `core/alerting.py` had good delivery machinery and no sense of
proportion: every code was mailed, so an evening of four ordinary deploys, one browser
extension and one already-diagnosed FX outage put thirty-odd messages in the founder's
inbox beside the single one that mattered (`kb_detach_failed`'s family — an operational
failure worth reading). Their instruction was exact: *"I need to see about failures in
admin panel only. I want high priority things only through mail."*

The defect was never the throttling. `ALERT_REPEAT_INTERVAL_S` and the token bucket both
work; they bound HOW OFTEN a code is sent and had nothing to say about WHETHER it should
be. An inbox where `signal_received` on a deploy looks identical to `razorpay_money_
unapplied` is an inbox nobody reads, which is the same outage as no alerting at all.

THE VOCABULARY IS THREE RUNGS, and each is defined by what the reader is expected to DO
rather than by how bad it sounds — a severity nobody can act on differently is a label,
not a routing decision:

* **`page`** — *wake a human now.* Money moved and did not land, a statutory or TRAI
  deadline is breached, data is unrecoverable or unreachable, a credential is unusable, or
  a whole client (or the whole platform) has stopped working. **This rung, and only this
  rung, sends email.** There is one operator and no incident console, so the test for
  membership is literally "would Sri want the phone to buzz at 3am for this".
* **`attention`** — *an operator should look at this today.* A real failure, bounded: one
  call, one client, one sweep, one retryable leg. It is recorded, it is on
  `/admin/ops/alerts`, and it is not mailed. This is where the overwhelming majority of
  genuine failures live, and calling it "low priority" would be wrong — it is the rung the
  founder asked to see *in the admin panel*.
* **`record`** — *expected, or somebody else's noise.* A normal deploy's SIGTERM, a
  visitor's browser extension tripping CSP, an unauthenticated stranger posting a bad
  signature, a caveat on another alarm's count. It still gets a row, because "how often
  does this actually happen" is a question worth being able to answer, and because an
  absent trail is how a code quietly becomes a lie.

THE DEFAULT IS `page`, AND THAT IS THE SAFE DIRECTION — fail loud, not closed. An
unclassified code is one somebody has just added, and the two possible mistakes are not
symmetric: a new alarm mailed when it should not have been costs one message and a
one-line diff, while a new alarm silently demoted to a console row nobody has learned to
watch costs the outage it was written for. `scripts/check_alarm_wiring.py` makes the
default unreachable in a green tree — every raised code must have an entry here AND the
same word in its `runbooks/alarm-index.md` row — so the fallback is a backstop for the
window between someone writing `alert("CORE_LOGIC", "new_thing")` and CI telling them.

THIS MAPPING IS THE SOURCE OF TRUTH AND THE INDEX CHECKS AGAINST IT, not the other way
round. `alert()` reads it on the SIGTERM path and inside voice-runtime's 500ms ack budget,
so it has to be a dict lookup in a loaded module; parsing a markdown table there is not
available at any price. The index still has the column, because the operator reading it at
3am needs to know whether silence means "nothing is wrong" or "it did not mail" — and the
guard fails the build when the two disagree, so the document cannot drift into a
comfortable lie.
"""

from __future__ import annotations

from typing import Literal, get_args

#: Ordered loudest-first, which is the order every reader wants and the order
#: `/admin/ops/alerts` sorts by.
Severity = Literal["page", "attention", "record"]

SEVERITIES: tuple[Severity, ...] = get_args(Severity)

#: What an unclassified code gets. See the module docstring: loud, not closed.
DEFAULT_SEVERITY: Severity = "page"

#: The one rung that leaves the building. A frozenset rather than an `== "page"` in
#: `alerting._dispatch`, so "which severities mail" is one fact with one name that a test
#: can assert and a future rung (an SMS tier, say) does not have to hunt for.
EMAILED_SEVERITIES: frozenset[Severity] = frozenset({"page"})

#: Every alarm code this platform can raise, and how loud it is.
#:
#: The contested entries carry their reason inline. The uncontested ones do not, because a
#: comment restating "outbox_dead_letter is serious" is noise — the runbook row is the
#: place that explains what a code means, and this file's only job is the routing verdict.
ALARM_SEVERITY: dict[str, Severity] = {
    # ── `_unusable_hmac_key`'s four callers (core/settings.py). A signing key that cannot
    # be resolved does not degrade a feature, it STOPS one — and the audit chain is the
    # one whose absence is a compliance fact rather than an inconvenience: no tamper-proof
    # record is being written while it is down. All four page.
    "audit_chain_not_configured": "page",
    "idempotency_not_configured": "page",
    "copilot_proposals_not_configured": "page",
    "impersonation_not_configured": "page",
    # ── The four the widened scan surfaced last, all real single codes.
    # HARD RULE 5, AND IT PAGES. `require_call_compliance_floor` refuses a dial that would
    # place a call with NO truthful-answer rule on it. Reaching this means the invariant
    # that "no column, config row or client-authored script can withdraw it" has nowhere
    # to live for that dial — the same class as the drift codes above, not a config nit.
    "engine_compliance_floor_absent": "page",
    # voice-runtime's own refusals. `attention`: the ack path shed a webhook or a tool
    # call, which the poller reconciles (TRD §5 makes the poller the truth and the webhook
    # a hint) — but a RUN of them is the queue being down, which is what the board shows.
    "tool_queue_unavailable": "attention",
    "webhook_claim_unavailable": "attention",
    "body_read_timeout": "record",
    # ══ THE `ProblemError` CLASS, WHICH THE FIRST PASS OF THIS FILE MISSED ENTIRELY ══
    #
    # `core/errors.py` turns EVERY 5xx `ProblemError` into an alarm — its handler calls
    # `alert(exc.failure_stage, exc.code, ...)` and `failure_stage` DEFAULTS to
    # `ROUTE_HANDLER`. So a refusal raised with `kind="transient"` and no `failure_stage=`
    # argument is an emailing alarm that looks like ordinary error handling at the call
    # site, and `check_alarm_wiring`'s shape-3 scan only saw the ones that name the stage
    # explicitly. 44 codes were in that blind spot, unclassified and therefore `page` by
    # the fail-loud default.
    #
    # **THE FOUR THAT WERE ACTIVELY MAILING THE FOUNDER ARE THE POINT.** `rate_limited`
    # fires on every throttled request, `too_many_attempts` on every throttled login,
    # `service_load_shed` and `platform_maintenance` on every shed request — the highest
    # -volume refusals in the product, each one an email. That is a self-inflicted denial
    # of service on the one inbox that has to stay readable, and it is why "only high
    # priority by mail" could not be delivered by classifying the `alert()` call sites
    # alone.
    #
    # ── record: a REFUSAL WORKING AS DESIGNED. The caller was told, correctly, and there
    # is nothing for an operator to do. A wall of these on the console is a signal
    # (someone is hammering us); one of them is not.
    "rate_limited": "record",
    "too_many_attempts": "record",
    "service_load_shed": "record",
    "signup_load_shed": "record",
    "platform_maintenance": "record",
    "signup_disabled": "record",
    "signup_unavailable": "record",
    "ai_paused_platform_wide": "record",
    "admin_ai_paused_platform_wide": "record",
    "meta_lead_retrieval_deferred": "record",
    "copilot_interrupted": "record",
    "copilot_confirm_unavailable": "record",
    "recording_unavailable": "record",
    "delivery_body_unavailable": "record",
    "qa_report_unreadable": "record",
    "kb_upload_unavailable": "record",
    "calendar_oauth_failed": "record",
    "config_key_vanished": "record",
    # The FAKE engine's own refusals. They cannot fire in production at all — the fake is
    # the test double — and classifying them keeps the registry exhaustive rather than
    # carrying an exemption nobody would revisit.
    "engine_agent_missing": "record",
    #
    # ── attention: SOMETHING IS MISCONFIGURED OR A VENDOR IS MISBEHAVING. Nobody is
    # woken, and the operator sees it on the board next time they look, which is the
    # right latency for "a capability is off" — it was already off yesterday.
    "kb_detach_failed": "attention",
    "engine_capability_absent": "attention",
    "engine_capability_unverified": "attention",
    "engine_not_configured": "attention",
    "engine_number_not_linked": "attention",
    "engine_number_purchase_unusable": "attention",
    "engine_caller_id_not_configured": "attention",
    "engine_publish_not_applied": "attention",
    "number_provisioning_not_configured": "attention",
    "number_resale_not_authorized": "attention",
    "payments_not_configured": "attention",
    "voice_check_unavailable": "attention",
    "voice_check_incomplete": "attention",
    # A DIAL WE COULD NOT CONFIRM — the call may or may not have been placed, so it is
    # not "nothing happened". `attention` rather than `page` for `unhandled_exception`'s
    # reason: one is a blip the poller reconciles, and a run of them is an outage that
    # the engine codes above are already paging for.
    "dial_unconfirmed": "attention",
    # The generic 500 body. Same argument as `unhandled_exception`, which this file
    # already classifies `attention`: a real outage is a WALL of these, legible on a
    # board and illegible in an inbox.
    "internal_error": "attention",
    #
    # ── page: MONEY THAT DOES NOT RECONCILE, OR CREDENTIALS THE PLATFORM CANNOT READ.
    # The payment pair is the same argument `razorpay_money_unapplied` gets: a figure the
    # provider and our ledger disagree about is money owed to somebody, and it cannot be
    # corrected in place (hard rule 4).
    "payment_order_amount_mismatch": "page",
    "refund_amount_mismatch": "page",
    # Not every payment code pages: these are the provider being unreachable or refusing,
    # which is a retry and a client who sees an honest failure, not money in limbo.
    "payment_provider_unreachable": "attention",
    "payment_provider_rejected": "attention",
    "payment_order_unreadable": "attention",
    "refund_rejected": "attention",
    "refund_unreadable": "attention",
    # A SECRET THE PLATFORM CANNOT UNWRAP is every BYOK leg down at once and no way to
    # publish, dial or extract until a human restores the key. `platform_secret_unreadable`
    # already pages; these are the same failure one layer down.
    "platform_kek_unusable": "page",
    "platform_secret_corrupt": "page",
    "platform_secret_unwrappable": "page",
    # ── The voice path ────────────────────────────────────────────────────────
    # A FLEET-WIDE vendor outage: dials, publishes and the poller are all down at once.
    "engine_error_spike": "page",
    # Its own index row says "individually routine; it feeds `engine_error_spike`" — so
    # the spike is the alarm and this is the input. Mailing both means mailing the same
    # outage ten times before the one that means something arrives.
    "engine_unreachable": "record",
    "engine_rejected": "attention",
    "engine_rate_limited": "attention",
    "engine_bad_response": "attention",
    # HARD RULE 5. A live agent running a script we did not publish is an agent whose
    # AI-disclosure and recording-notice lines are not ours — the invariant that "no
    # column, config row or client-authored script can withdraw it" is exactly what has
    # been withdrawn. Not a config nit.
    "engine_agent_drift_detected": "page",
    "handoff_destination_unknown": "attention",
    "handoff_brief_channel_absent": "attention",
    "handoff_agent_unmapped": "attention",
    "handoff_unresolved": "attention",
    # Same reason as the drift alarm and one step worse: a vendor-side semantic route
    # answers a caller FROM A STATIC STRING without consulting the model, so
    # `compose_engine_prompt`'s appended truthfulness sentences cannot run at all.
    "engine_agent_semantic_routes_present": "page",
    # Speech config drift, not truthfulness drift: a language entry brings its own voice
    # or transcriber. Wrong, visible, and it says nothing untrue to a caller.
    "engine_agent_multilingual_speech_override": "attention",
    # A client's number answers nobody. Their whole inbound product is off.
    "engine_inbound_binding_failed": "page",
    "agent_published_answering_no_number": "attention",
    # Money AND service: a client out of credit keeps taking calls nothing can bill, or a
    # client who has just paid stays refused.
    "inbound_credit_cutover_failed": "page",
    # A standing statement about this deployment's engine rather than an event. It is the
    # same sentence every time and it will never stop being true until the engine changes.
    "inbound_cutover_unsupported": "record",
    # Hard rule 5 again, at its sharpest: an agent PROVEN to be running a prompt we did
    # not write cannot be taken off the air. The last enforcement step has failed.
    "inbound_truthful_answer_silence_unsupported": "page",
    # The expected tail after an offboarding: somebody is still ringing a withdrawn
    # number. Nothing is broken and nothing can be done.
    "engine_agent_route_withdrawn": "record",
    "number_bought_but_not_recorded": "page",
    "number_rented_but_unrecorded": "page",
    "number_recorded_but_not_held": "page",
    # Money, but a CATALOGUE gap rather than a movement: the recurring cost is unpriced
    # until somebody fills it in, and no client is debited wrongly in the meantime.
    "number_rental_price_missing": "attention",
    "number_rentals_incomplete": "attention",
    "engine_agent_unmapped": "attention",
    # The call has NO ROW: no lead, no transcript, no usage event. Unrecoverable.
    "engine_ingest_abandoned": "page",
    # Every client's live agent is unwatched, so hard rule 5's "verified against the
    # engine on every drift sweep" has stopped being true platform-wide.
    "engine_drift_sweep_abandoned": "page",
    "engine_kb_drift_detected": "attention",
    "kb_drift_sweep_abandoned": "attention",
    # The vendor has raised compliance flags against OUR account. Unanswered, that ends in
    # a suspended account and every client's calls stopping at once.
    "engine_violation_open": "page",
    "engine_violation_sweep_incomplete": "attention",
    "engine_violation_sweep_abandoned": "attention",
    # The alarm `core/alerting.py`'s own docstring names as "the alarm the whole system
    # exists to raise".
    "postcall_pipeline_stalled": "page",
    # One call with no lead, no extraction and no usage event — the thing the client pays
    # for, gone, with no retry left. Rare and terminal, which is what earns the rung.
    "post_call_abandoned": "page",
    "recording_copy_failed": "attention",
    # Hard rule 7: a call metered with no attested price for the voice it spoke.
    "cartesia_call_without_attested_tts_price": "page",
    "call_billable_without_cost": "page",
    "engine_cost_implausible": "page",
    "engine_llm_ttft_degraded": "attention",
    "calls_never_finished": "attention",
    # Bookkeeping caveats on another alarm's number ("this count is a FLOOR"), not
    # findings of their own.
    "outstanding_probe_incomplete": "record",
    "outstanding_probe_budget_exhausted": "record",
    "call_duration_negative": "attention",
    "reconciliation_fetch_failed": "record",
    "reconciliation_probe_incomplete": "record",
    "reconciliation_listing_incomplete": "attention",
    "engine_listing_window_too_wide": "attention",
    # THE BIG RED SWITCH FAMILY, AND ALL OF IT PAGES. Outbound was halted — by an
    # operator, or by a regulator's complaint — and these five each say some version of
    # "dials the vendor already holds may still go out". A halt nobody can prove landed is
    # the one failure in this product that can put calls on the phones of people who asked
    # not to be called, which is a TRAI matter and not an engineering one.
    "dial_recall_unstopped": "page",
    "dial_recall_incomplete": "page",
    "dial_recall_impossible": "page",
    "dial_recall_abandoned": "page",
    "dial_recall_not_queued": "page",
    # The same argument, per number, on the DNC path.
    "dnc_recall_undetermined": "page",
    "dnc_recall_incomplete": "page",
    "dnc_recall_abandoned": "page",
    # No outbound line exists at all: NO campaign on the platform can dial.
    "outbound_pool_empty": "page",
    "dispatch_tick_overrun": "attention",
    "dispatch_tick_overlap": "attention",
    "dispatch_budget_starved": "attention",
    # ── Compliance and consent ────────────────────────────────────────────────
    # A campaign generating opt-outs at 10%+ is the shape a TRAI complaint comes from.
    "campaign_complaint_spike": "page",
    # The fast path failed and the POST-CALL pass is the backstop that still runs. A
    # suppression that is late by one pipeline is not a suppression that did not happen.
    "in_call_optout_unresolved": "attention",
    "in_call_optout_agent_unmapped": "attention",
    "in_call_optout_unattributable": "attention",
    "opt_out_unattributable": "attention",
    "in_call_callback_unresolved": "attention",
    "in_call_callback_agent_unmapped": "attention",
    "in_call_callback_unattributable": "attention",
    "caller_memory_distil_worklist_failed": "attention",
    # A retention policy that would delete below the regulatory floor. Statutory.
    "retention_below_trai_floor": "page",
    "retention_sweep_truncated": "attention",
    "retention_sweep_incomplete": "attention",
    "copilot_distil_worklist_failed": "attention",
    "copilot_transcript_sweep_failed": "attention",
    "kb_gloss_worklist_failed": "attention",
    # DPDP §12: the statutory clock has already run out.
    "erasure_requests_overdue": "page",
    "processor_erasure_overdue": "page",
    "erasure_probe_deadline_exhausted": "attention",
    # The audit chain is the evidence a regulator is shown. A missing link is not
    # re-creatable later.
    "action_audit_unrecorded": "page",
    # An offboarding erasure that reported success and erased nothing.
    "tenant_erasure_mark_failed": "page",
    # ── Leads, notifications, integrations ────────────────────────────────────
    # Nobody can reset a password or accept an invitation — and it is the SAME transport
    # this alert travels on, so a systemic failure here is also the alerting path warning
    # about itself.
    "auth_email_exhausted": "page",
    # The lead is in the CRM and on the client's screen; what failed is one notification.
    # Loud in the console, not in the inbox.
    "hot_lead_notification_exhausted": "attention",
    "hot_lead_no_channel": "attention",
    "account_notice_exhausted": "attention",
    "account_notice_no_channel": "attention",
    "account_notice_tenant_missing": "attention",
    "account_notice_unknown_event": "attention",
    "closure_sweep_incomplete": "attention",
    "hot_lead_whatsapp_exhausted": "attention",
    "hot_lead_whatsapp_rejected": "attention",
    "campaign_escalation_exhausted": "attention",
    "campaign_escalation_rejected": "attention",
    "campaign_escalation_unrecordable": "attention",
    "outbound_webhook_exhausted": "attention",
    "delivery_body_not_retained": "attention",
    "meta_page_token_invalid": "attention",
    "meta_leads_retrieval_denied": "attention",
    # Unauthenticated, from anywhere on the internet, with no credential. The class
    # `core/alerting.py`'s docstring already singles out as free to raise.
    "meta_signature_rejected": "record",
    "meta_batch_over_cap": "attention",
    # ── The reliability path ──────────────────────────────────────────────────
    # arq accepted work for a job name no worker registered AND DROPPED IT. This is deploy
    # skew silently eating side effects.
    "job_function_not_registered": "page",
    # The generic terminal every `Retry` ends at. The jobs whose failure matters have
    # their own code above; mailing the catch-all too would mail each of them twice.
    "job_retries_exhausted": "attention",
    # Two of the three alarms `core/alerting.py` says this whole path exists for.
    "outbox_dead_letter": "page",
    "outbox_queue_unreachable": "page",
    # The unauthenticated edge. Named in `core/alerting.py`'s docstring as fireable "from
    # anywhere on the internet with no credential"; a stranger must not be able to choose
    # when the founder's phone buzzes.
    "webhook_source_rejected": "record",
    "webhook_payload_too_large": "record",
    "webhook_unkeyable": "attention",
    "webhook_body_timeout": "record",
    "webhook_ack_slow": "attention",
    "webhook_claim_timeout": "attention",
    "webhook_payload_mismatch": "attention",
    "tool_source_rejected": "record",
    "tool_payload_too_large": "record",
    "tool_call_unkeyable": "attention",
    "tool_enqueue_timeout": "attention",
    "tool_body_timeout": "record",
    "tool_ack_slow": "attention",
    # ── Money and platform state ──────────────────────────────────────────────
    # THE FOUNDER'S 26-MESSAGE THREAD, and the two rungs above it. D-589 gave FX a
    # three-rung ladder; `fx_source_degraded` says the ladder WORKED (a lower published
    # rung served), and `fx_rate_stale` says every rung is old and costs are converting at
    # the documented fallback. Nothing is broken in either case, no client is billed
    # wrongly, and the condition lasts as long as a vendor's feed is down — which is
    # precisely the shape that must never be an email.
    "fx_source_degraded": "record",
    "fx_rate_stale": "attention",
    "fx_pull_silent": "attention",
    "fx_pull_failed": "attention",
    # The refusal WORKED: an implausible rate was rejected and the previous one still
    # applies. This is the guard reporting a catch, not a loss.
    "fx_rate_implausible": "attention",
    "voice_catalogue_empty": "attention",
    "voice_catalogue_sync_failed": "attention",
    # Payments cannot be verified at all, so money is arriving and nothing is crediting it.
    "razorpay_webhook_unconfigured": "page",
    # Unauthenticated internet noise, same class as `webhook_source_rejected` — and the
    # one `core/alerting.py` names by hand.
    "razorpay_webhook_bad_signature": "record",
    "razorpay_unknown_tenant": "page",
    # THE ONE THE BRIEF SINGLES OUT: a client was debited and their wallet did not move.
    "razorpay_money_unapplied": "page",
    # The order exists at the provider and not here: the client can pay into a void.
    "topup_attempt_not_recorded": "page",
    "topup_settlement_silent": "page",
    "topup_settlement_scan_incomplete": "attention",
    # The backstop that would otherwise FIND `topup_settlement_silent` is itself down, so
    # a client's money can now go missing unobserved.
    "topup_settlement_sweep_abandoned": "page",
    "rate_card_notice_fanout_budget_reached": "attention",
    "rate_card_notice_no_billing_email": "attention",
    "wallet_alert_no_billing_email": "attention",
    # Money NOT collected, from a known list of tenants, re-runnable.
    "setup_fees_unissued": "attention",
    # The cap doing exactly its job. One client's outbound stopped, by their own configured
    # ceiling — a thing to see on a screen, not to be woken for.
    "tenant_spend_capped": "attention",
    # The 80% heads-up. It will fire for every healthy growing account, by design.
    "tenant_spend_cap_approaching": "record",
    # Dashboard AI is now off for EVERY tenant.
    "ai_platform_brake_tripped": "page",
    "ai_platform_brake_near": "attention",
    # Money leaking a fraction of a rupee at a time, per assist. Real, and not a 3am
    # problem: `usage_events` keeps the evidence and the price can be back-applied.
    "ai_assist_unmeterable": "attention",
    "ai_assist_unknown_provider": "attention",
    "kb_gloss_unmeterable": "attention",
    "kb_ocr_unmeterable": "attention",
    "admin_ai_assist_unmeterable": "attention",
    "admin_ai_assist_unknown_provider": "attention",
    # The KEK cannot decrypt this deployment's credentials: no vendor call can be made.
    "platform_secret_unreadable": "page",
    # "Informational, and deliberately loud" — and the loud half stays, one rung down. It
    # fires on a rare deliberate act that is already in `audit_log`, and its real value is
    # as a tripwire somebody reads, which a console row serves.
    "platform_secret_set": "attention",
    "platform_config_never_loaded": "attention",
    "platform_config_stale": "attention",
    # An operator is standing at the console doing this on purpose.
    "maintenance_drain_forced": "attention",
    "maintenance_voice_unsupported": "record",
    "maintenance_voice_incomplete": "attention",
    "maintenance_notice_exhausted": "attention",
    "maintenance_notice_no_channel": "attention",
    "maintenance_notice_unknown_kind": "attention",
    # ── Identity, auth and the request edge ───────────────────────────────────
    # One 500. The family is broad (one fingerprint per exception class), and a real
    # outage reads as a WALL of these on `/admin/ops/alerts` — which is legible — rather
    # than as a bucket-emptying storm in an inbox, which is not.
    "unhandled_exception": "attention",
    "client_ip_unresolved": "attention",
    # THE FOUR DEPLOYS. See `docs/ROADMAP.md` D-591 and the note in `core/bootstrap.py`:
    # a handler only ever runs on SIGTERM/SIGINT, and both are an orchestrator or a person
    # asking this process to stop. The restarts that are NOT ordinary — OOM, a hard crash,
    # SIGKILL — never reach this handler at all, so nothing here can distinguish a deploy
    # from an incident because every signal that reaches it IS an orderly stop.
    "signal_received": "record",
    # It happened in a VISITOR'S browser. Extension-scheme reports are already dropped
    # before this fires (`security/routes.py`), and what survives is a CDN, a proxy or our
    # own policy being narrow — a console-screen problem, found by reading a page.
    "csp_violation": "record",
    # ── Quality ───────────────────────────────────────────────────────────────
    "qa_sample_draw_failed": "attention",
    "qa_sample_draw_truncated": "attention",
    "trial_erasure_blocked": "attention",
    "trial_sweep_truncated": "attention",
    "trial_sweep_failed": "attention",
    "qa_sample_draw_abandoned": "attention",
    "kb_digest_content_refused": "attention",
    "kb_digest_undelivered": "attention",
    "kb_digest_sweep_abandoned": "attention",
    # ── The host backup chain ─────────────────────────────────────────────────
    # THE RULE FOR THIS WHOLE SECTION: `page` when the answer to "can we restore this
    # database tonight" is NO or UNKNOWN, `attention` when the answer is still yes and
    # something around it is degraded. An unknown is not softer than a no — the night you
    # need the backup is not the night to find out.
    "basebackup_failed": "page",
    # Storage grows; the index row says recoverability is unaffected.
    "basebackup_prune_failed": "attention",
    "base_backup_stale": "page",
    "no_base_backup": "page",
    "backup_list_failed": "page",
    "backup_list_unparseable": "page",
    "archiver_failing": "page",
    "archiver_never_succeeded": "page",
    "archive_stale": "page",
    # Keeps growing and the cluster stops accepting writes.
    "pg_wal_backlog": "page",
    "wal_chain_broken": "page",
    # UNVERIFIED, not broken: the base backups exist and restore to their own timestamps.
    # What is unproven is point-in-time recovery across the archive.
    "wal_verify_failed": "attention",
    "wal_verify_unparseable": "attention",
    # Nothing on this host can back anything up, and nothing here can check.
    "walg_unavailable": "page",
    "health_db_unreachable": "attention",
    "health_pg_wal_unreadable": "attention",
    "backup_health_gap": "attention",
    # Not scheduled, not armed, not firing: three spellings of "that backup will not run".
    "backup_timer_missing": "page",
    "backup_timer_inactive": "page",
    "backup_timer_not_firing": "page",
    # The index row opens "Backups are healthy". What failed is the dead man's telemetry.
    "backup_heartbeat_undelivered": "attention",
    "offsite_pgdump_failed": "page",
    # A dump far smaller than last night's is the shape an RLS-FILTERED dump takes — an
    # offsite copy that exists, restores, and is missing most of the fleet's data.
    "offsite_dump_shrank": "page",
    "offsite_encrypt_failed": "page",
    "offsite_upload_failed": "page",
    "offsite_readback_failed": "page",
    "offsite_digest_mismatch": "page",
    # Redis holds in-flight jobs, not the record of anything. Losing tonight's copy loses
    # a queue, not a customer.
    "offsite_redis_missing": "attention",
    # THE META-ALARMS, and they page for the reason nothing else in this file does: they
    # say THE ALERTING PATH ITSELF IS BROKEN. Mailing them may well fail too — the host
    # relay and the Python transport are different legs, so it may well not — and the cost
    # of trying is one message against the cost of a silent pager.
    "alert_delivery_failed": "page",
    "alert_delivery_unconfigured": "page",
    # ── Schedules and certificates ────────────────────────────────────────────
    # Expiry takes down every hostname this product is served from, for every client, at
    # once. It fires daily for up to 21 days, which used to make it noise; the onset/clear
    # transition in `core/alerting.py` now mails it once per episode.
    "tls_certificate_expiring": "page",
    # We cannot read our own certificate: either nginx is down or we are blind to the row
    # above until the day it stops working.
    "tls_certificate_unreadable": "page",
    "campaign_schedule_expired": "attention",
    "campaign_schedule_unparseable": "attention",
    "campaign_schedule_kind_unknown": "attention",
    "campaign_recurrence_unreadable": "attention",
    "campaign_recurrence_skipped": "attention",
    # A SUPERSEDED vendor credential is still live at the engine beside the new one. A
    # rotation that did not rotate is a security finding, not a config nit.
    "engine_credential_not_replaced": "page",
    # Our margin, not a client's wallet: the engine is charging for synthesis we already
    # pay Cartesia for. Per call, re-derivable from `usage_events`, and correctable.
    "engine_billed_byok_tts": "attention",
    "cartesia_voice_incomplete": "attention",
    "engine_kb_document_missing": "attention",
    "engine_kb_agent_config_required": "attention",
    "engine_kb_ambiguous_source": "attention",
    "engine_kb_processing_failed": "attention",
    "engine_kb_processing_timeout": "attention",
    "engine_kb_listing_incomplete": "attention",
    "engine_kb_account_listing_incomplete": "attention",
    "engine_kb_orphans_detected": "attention",
    "kb_orphan_sweep_abandoned": "attention",
    "kb_embed_unmeterable": "attention",
    "kb_embed_unusable_response": "attention",
    # THE SCHEMA CONTRADICTS THE DEPLOYMENT: the column is not as wide as the vectors this
    # deployment buys, so NO knowledge can be embedded for anybody until a migration runs.
    # Its twin ends the whole caller sweep.
    "kb_embed_width_mismatch": "page",
    "caller_embed_width_mismatch": "page",
    "kb_embed_worklist_failed": "attention",
    "caller_embed_unusable_response": "attention",
    "caller_embed_unmeterable": "attention",
    "caller_embed_worklist_failed": "attention",
    # Rows of caller data that a DPDP erasure structurally CANNOT reach. An erasure that
    # reports success and leaves personal data behind is the worst shape a §12 failure has.
    "caller_subject_key_unreachable": "page",
}


#: CODE FAMILIES — a severity for a code built at runtime rather than typed.
#:
#: Two `ProblemError` sites compose their code from a value they do not know until they
#: fail: `core/errors.py` relays an unhandled `HTTPException` as `http_{status_code}`, and
#: `workers/extraction.py` names an assist refusal `assist_{reason}`. Neither can be
#: enumerated — `http_` alone spans every 5xx a dependency can return — so an exact-match
#: registry could never cover them, and they sat in `DEFAULT_SEVERITY`'s fail-loud arm.
#:
#: A PREFIX TABLE RATHER THAN A PATTERN LANGUAGE. Matching is longest-prefix and nothing
#: else: no globs, no regexes, no ordering subtleties to reason about at 3am. The exact
#: table always wins, so a single member of a family can still be lifted or lowered on its
#: own merits without touching this.
ALARM_SEVERITY_FAMILIES: dict[str, Severity] = {
    # The generic HTTP relay. `internal_error`'s argument, one layer out: a real outage is
    # a WALL of these, which is legible on a board and illegible in an inbox.
    "http_": "attention",
    # The dashboard-AI capability ladder refusing — no credential, no attested price, the
    # disclosed fallback declined. The client was told honestly and an operator installs a
    # key when they next look; nobody is woken to paste one.
    "assist_": "attention",
}


def severity_of(code: str) -> Severity:
    """This code's severity — exact entry first, then its FAMILY, then the default.

    The family arm exists for codes composed at runtime (`http_502`, `assist_no_credential`)
    which an exact table cannot enumerate; see `ALARM_SEVERITY_FAMILIES`. Longest prefix
    wins so a narrower family can be carved out of a wider one later without re-ordering
    anything, and the exact table always beats both — lifting one member of a family on its
    own merits stays a one-line change.
    """
    exact = ALARM_SEVERITY.get(code)
    if exact is not None:
        return exact
    best: tuple[int, Severity] | None = None
    for prefix, severity in ALARM_SEVERITY_FAMILIES.items():
        if code.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), severity)
    return best[1] if best is not None else DEFAULT_SEVERITY


def is_emailed(severity: Severity) -> bool:
    """Does this rung leave the building?"""
    return severity in EMAILED_SEVERITIES


__all__ = [
    "ALARM_SEVERITY",
    "ALARM_SEVERITY_FAMILIES",
    "DEFAULT_SEVERITY",
    "EMAILED_SEVERITIES",
    "SEVERITIES",
    "Severity",
    "is_emailed",
    "severity_of",
]
