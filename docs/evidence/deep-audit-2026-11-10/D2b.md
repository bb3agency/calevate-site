# Deep audit D2b (10 Nov 2026): the areas D2 did not reach

Branch `worktree-agent-aea44698ae15c25f1`, on 5c68a0a1b (D2, D3 and D4 merged). No migration.
No wire change: `scripts.check_openapi_fresh` is OK, and the stripped view name and the new
refusal codes do not alter the schema.

## Scope actually read

Five read-only readers covered the area in parallel. I verified every finding below against the
code myself before fixing it, and each fix has a test that failed on the pre-fix source.

**Read in full:**
- `apps/api/ingest/`: graph, lead_policy, meta, models, policy_routes, portals, recorded,
  routes, sealed_secret, service.
- `apps/api/follow_ups/`: definition, models, routes, runner, schemas, service, starters.
- `apps/workers/follow_ups.py`.
- `apps/api/forwarding/`: codes, quiet, routes, save_number, schemas, service, testing.
- `apps/workers/forwarding.py`.
- `apps/api/admin/number_routes.py` and `apps/api/admin/operator_routes.py`.
- `apps/api/admin/account_routes.py` and `apps/api/billing/payment_admin_routes.py`.
- `apps/api/tenancy/`: call_lines, call_line_requests, profile_routes, profile_service,
  profile_wording, routes.
- `apps/api/authn/mobile_number*.py` (D-976).
- `apps/api/campaigns/`: engine_number_purchase, engine_number_routes, number_pricing.
- `apps/api/billing/number_rental.py`.
- `apps/api/crm/`: lens, saved_views, export_tickets, translation.
- `apps/workers/call_translation.py`.

**Read in part:**
- `apps/api/billing/spend_routes.py`.
- `apps/api/authn/operators.py`.
- The `crm/schemas.py` view and lens models.
- The `dispatch_call` refusal ladder in `apps/api/agents/service.py`.
- Pipeline STEP 4 (`_upsert_lead`) and the after-call call-back number in
  `apps/workers/after_call_callbacks.py`.
- `apps/api/billing/reconciliation.py`, the payment and refund passes.

## D2's open item, closed

### D2b-01 (P2, money/availability): a signed Razorpay event naming a tenant we do not have was refused 404

- **Where:**
  - `apps/api/billing/payment_events.py::_require_tenant`, and the dispute path with no tenant.
  - `payment_routes.razorpay_webhook`.
- **Problem:** a signed `payment.captured`, `refund.processed` or dispute event was answered
  404 (`not_found`) after the `razorpay_unknown_tenant` page whenever:
  - the tenant id in its note does not exist here (absent, or erased: `tenant_exists` counts
    `deleted_at` as absent); or
  - a dispute names no tenant at all.

  A redelivery cannot make the tenant appear. Razorpay counts every non-2xx as a failure,
  retries for 24 hours, and "If the webhooks continue to fail for 24 hours, the webhook is
  disabled" (https://razorpay.com/docs/webhooks/best-practices/, read 10 Nov 2026). So one such
  event stops every later top-up, mandate and dispute event.
- **Why no refusal is kept:** D2 left it open in case a non-existent tenant was a forgery
  signal. It is not one. The HMAC has already verified with our webhook secret, so Razorpay
  sent the event. Leaving it a refusal buys retry noise and costs the whole payment feed.
- **What is unverified:** D2 suggested that two deployments sharing one Razorpay account
  could cause this. I could not confirm that every webhook of an account receives every
  event: neither https://razorpay.com/docs/webhooks/ nor the best-practices page says so
  (read 10 Nov 2026). I wrote nothing that depends on it.
- **Fix:**
  - The unknown-tenant refusal has its own code, `payment_tenant_unknown`
    (`payment_events.UNKNOWN_TENANT_CODE`).
  - The receiver acknowledges it the way it acknowledges `payment_tenant_unresolved`: 200
    `status: "unattributed"`, after the existing `razorpay_unknown_tenant` page, with no second
    alarm.
  - The daily reconciliation lists the payment as `payment_tenant_unknown:<id>` (it was
    `not_found:<id>`), and an unknown tenant's refund as `refund:<id>`.
  - Nothing is credited or debited.
- **Tests (each failed before):**
  - `tests/razorpay_events_test.py::test_an_unknown_tenant_alarms_once_and_not_twice` (now 200).
  - `::test_a_refund_for_an_unknown_tenant_is_alarmed_acknowledged_and_writes_nothing`.
  - `tests/self_serve_test.py::test_a_payment_for_an_unknown_tenant_credits_nothing`.
  - `tests/payment_operations_test.py::test_a_dispute_naming_no_client_is_refused_and_alarmed`
    (asserts the new code).

## Findings fixed (each test failed on the pre-fix source)

How the before-state was proven: the ten changed modules were exported from HEAD and mounted
over the worktree. All 15 new or changed test cases failed, and all of them pass on the fix.

### D2b-02 (P1, data loss): a dial the voice platform refused rolled back the lead it had just written

- **Where:** `apps/api/ingest/service.py::ingest_lead`, the `except ProblemError` after
  `dispatch_call`.
- **Problem:**
  - Only person refusals, calling hours and the two line refusals were handled. Every other
    "dial not placed" refusal was re-raised: `engine_rejected` (for example the platform's
    balance or the agent's setup), `engine_rate_limited`, `carrier_dial_precondition_failed`,
    `agent_not_published` and the rest of `DIAL_NOT_PLACED_CODES`.
  - The re-raise rolled back the lead INSERT, contradicting the module's own "THE LEAD ALWAYS
    LANDS".
  - The push receiver (`routes._absorb_push_record`) acks a non-transient refusal with 200 and
    the Meta receiver acks every refusal. So in a window where the platform refused dials,
    every pushed, portal and Meta enquiry was lost with no lead row.
  - `tests/ingest_lines_busy_test.py::test_any_other_refusal_still_propagates` pinned the
    rollback.
- **Fix:**
  - A transient refusal (the platform throttling us) is booked as a call-back due now, like a
    busy line. The call-back tick re-runs the gate and the dial back-off.
  - Every other refusal is recorded like a person refusal and committed: the run ends
    `call_refused` and a "blocked" timeline entry is written.
  - Nothing rang in either case: `dispatch_call` raises `DialUnconfirmedError` whenever the
    phone may be ringing.
  - Client wording was added for the new blocked codes in `crm/attention.BLOCK_REMEDIES`
    (`engine_rejected`, `agent_not_published`, `carrier_dial_precondition_failed`), so no
    wire name or provider reaches the screen.
- **Tests:** `tests/ingest_lines_busy_test.py::test_a_dial_the_platform_refuses_keeps_the_lead`
  and `::test_a_throttled_dial_keeps_the_lead_and_books_the_call_back`. They replace the
  propagation test.

### D2b-03 (P2, availability): rotating a lead source's secret skipped the per-source rule

- **Where:** `ingest/service.py::rotate_secret`.
- **Problem:** rotation minted a random secret whenever none was supplied, and accepted a
  supplied one for any source.
  - A Meta source rotated without the App Secret stored a value Meta never signs with, so
    every delivery failed (401) once the grace ran out, and Meta unsubscribes the Page.
  - A minted source rotated with a secret of the client's installed it and returned
    `secret: null`.
- **Fix:** one helper, `_secret_to_mint`, applies the same `app_secret_required` /
  `app_secret_not_accepted` checks on create and on rotation. Rotation applies them to the
  source it has locked `FOR UPDATE`.
- **Test:** `tests/lead_source_provisioning_test.py::test_a_rotation_takes_a_secret_exactly_where_a_create_does`.

### D2b-04 (P2, availability): giving a test-call number to a client cleared it even when the record was refused

- **Where:** `apps/api/admin/number_routes.py::record_tenant_engine_number`.
- **Problem:** `_release_platform_line` commits `trial_caller_number` /
  `forwarding_test_second_number` = None before `record_engine_number` runs. A refused record
  then left the setting cleared, and free-trial and forwarding test calls stopped platform-wide
  for a number no client got. Refusals that do this include:
  - another client answers the number;
  - the number is already recorded;
  - the client is on a free trial;
  - a series mismatch.

  The error response also skipped the background `propagate`.
- **Fix:**
  - The release returns what it cleared: each key, its value, and the revision after the
    clear.
  - On any failure of the record, each key is put back with an audited conditional write,
    only if nobody has set it since. The route then propagates the change itself.
- **Test:** `tests/engine_numbers_test.py::test_a_refused_record_puts_the_test_line_back`.

### D2b-05 (P2, security): a revoked superadmin could still add an operator mid-request

- **Where:** `apps/api/authn/operators.py::create_operator` and `::reissue_setup_link`.
- **Problem:** the role change and the revocation re-prove "live superadmin" under a row lock
  at the write (`_hold_actor_authority`). Create and resend did not. A create authorised
  before the actor's revocation committed still inserted, and could hand the revoked operator
  a new superadmin account whose setup link goes to a mailbox they still hold.
- **Fix:** both call `_hold_actor_authority` first inside their transaction.
- **Test:** `tests/admin_operators_test.py::test_a_revoked_superadmin_cannot_add_an_operator_or_resend_a_link_mid_request`.

### D2b-06 (P2, wrong person called): a call-ended Follow-up rang the business itself on a hidden-caller call

- **Where:** `apps/api/follow_ups/runner.py::start_for_call`.
- **Problem:** on a forwarded call that showed the business's own number (D-746,
  `calls.caller_id_hidden`), the pipeline files the lead under the call-back number the caller
  gave, or under nobody. The after-call call-back does the same (`_number_to_ring`).
  `start_for_call` took the network number, so a "call back missed calls" Follow-up dialled
  the business's own published number.
- **Fix:** on a hidden-caller call the run's phone is the call's lead's number. With no lead,
  no run starts.
- **Test:** `tests/follow_ups_runs_test.py::test_a_forwarded_call_showing_the_business_number_follows_up_the_real_caller`.

### D2b-07 (P2, race): a start racing a turn-off left live runs under an off Follow-up

- **Where:** `runner.start_run`. Its callers are `service.start_leads`, ingest,
  `start_for_call` and date starts.
- **Problem:** every caller read the Follow-up as live without a lock. `turn_off` locks it
  `FOR UPDATE` and stops live runs, so a start that read "live" before the turn-off committed
  inserted its run after the sweep. The run then:
  - sat `waiting` under an off Follow-up, excluded by the claim, due and orphan scans;
  - stayed counted until `end_overdue`;
  - carried on if the owner turned the Follow-up back on.
- **Fix:** `start_run` re-reads `status = 'live'` under `FOR SHARE`, which waits on
  `turn_off` / `pause`, and returns `not_live` otherwise.
- **Test:** `::test_a_start_that_read_live_before_a_turn_off_committed_starts_nothing`.
- **Known edge:** in `follow_up_call_ended`, `on_call_ended` locks runs before `start_for_call`.
  A turn-off of the same Follow-up at that moment can now deadlock. Postgres aborts one side
  and both are retryable. I judged that acceptable against a run that keeps calling after
  "off".

### D2b-08 (P2, money): deleting a forwarded line during its verification call

- **Where:** `apps/api/forwarding/service.py::delete_line`.
- **Problem:** `forwarding_tests.line_id` is `ON DELETE CASCADE`, so deleting a line while its
  test was placing or ringing removed the test. Then:
  - `settle_test` found nothing, so our legs' `forwarding_test_min` was never metered;
  - the pipeline's claim found no test, so the arrival was billed to the client and filed as
    a lead.
- **Fix:** the delete is refused with 409 `forwarding_test_running` ("Try again in a few
  minutes, once the test ends.") while a test is placing or ringing.
- **Test:** `tests/forwarding_lines_test.py::test_a_line_cannot_be_deleted_while_its_test_is_ringing`.

### D2b-09 (P3, validation): a saved-view name of only spaces got "You already have a view called “”" (409)

- **Where:** `crm/schemas.py`, the `SavedViewIn`, `SavedViewUpdateIn`, `CallSavedViewIn` and
  `CallSavedViewUpdateIn` models.
- **Problem:** the name passed `min_length=1` and was then stripped to "" by the service. That
  broke the table's CHECK, and the blanket `except IntegrityError` reported it as a taken name.
- **Fix:** a `ViewName` type strips before the length check, so the request is a 422.
- **Test:** `tests/lead_saved_views_test.py::test_a_name_of_only_spaces_is_a_validation_error_not_a_taken_name`.

### D2b-10 (P3, money): a contested dispute amount was rounded to the paisa

- **Where:** `billing/payment_admin_routes.py::contest`, `inr_to_paise(to_paise(amount))`.
- **Problem:** `150.005` was contested as 150.01. `0.001` passed `> 0`, rounded to zero and
  was refused in top-up words. This went against `inr_to_paise`'s own rule: refuse, never
  round.
- **Fix:** a sub-paisa amount is refused as `dispute_amount_invalid` before any upload, and
  `inr_to_paise(amount)` is used directly.
- **Test:** two new cases in
  `tests/payment_operations_test.py::test_a_contest_is_refused_before_anything_is_submitted`.

### D2b-11 (P3, error ladder): a billing month at the edge of the calendar was a 500

- **Where:** `billing/plans.py::parse_billing_month`.
- **Problem:** `9999-12` built `datetime(10000, …)`, and `0001-01` fell before year 1 in UTC
  after the IST conversion. A trailing newline also passed `$`. This affected every route that
  takes `month`, including `GET /v1/admin/spend`.
- **Fix:** the pattern is `\A…\Z`, and the year must be between 2000 and 9998.
- **Test:** `tests/plan_effective_dating_test.py::test_a_month_that_is_not_a_month_is_refused`.
  It now goes through `ist_month_window` and adds `9999-12`, `0001-01` and `2026-07\n`.

## NOT FIXED (reported, with why)

**Ingest**

- **P2: Meta leads never get the 30-minute window check, and a re-drive dials under fresh
  consent.**
  - `submission_instant` (`ingest/service.py`) reads only a `submitted_at` answer.
  - Meta's `created_time` goes only into provenance, and a re-driven notification has none.
  - Re-drive candidates have no age bound (`routes.py`, the re-drive query).
  - `_record_dial_consent_granted` stamps consent `now()` + 7 days.
  - Result: a 60-day-old lead recovered by attaching the page token is dialled at once.
  - This is a compliance reading, so it goes to the founder (decision 2).
- **P2: a form with no consent question records a decline.**
  - The decline goes in `consent_ledger` (`_record_dial_consent_declined`), recalls DNC
    dispatch and cancels the person's other call-backs as "consent withdrawn".
  - D-117 intends "never asked" to stop this dial. The side effects on a person who consented
    elsewhere look unintended, so this is founder decision 3.
- **P3: a NUL character in a pushed lead fails the INSERT on every retry.**
  - `/hooks` is exempt from the NUL middleware, and jsonb refuses `\u0000`.
  - The resulting `DataError` is not a `ProblemError`, so the push path answers 500 until
    the sender deactivates the push.
  - Not proven with a test here.
- **P3: the lead-source dry run can say `would_call=True` when "Call new leads" is off.**
  - `routes.test_webhook` carries on when no live follow-up matches; the real path answers
    `follow_up_off`.
  - Display only.
- **UNVERIFIED (P3): a Meta delivery whose provenance differs on a retry for one `leadgen_id`
  raises `webhook_payload_mismatch` for the whole batch.** I did not establish that Meta ever
  does this.

**Follow-ups**

- **P3: a stale-claim re-drive or a pause/resume can be swallowed by arq's job-id dedupe for
  up to an hour.** `drive_follow_up_run` keeps arq's default result window, and the token is
  `wake_at`, which the claim does not change. Recovery is delayed, not lost.
- **P3: a WhatsApp step re-driven after a lead edit is recorded `not_sent:
  idempotency_key_reused` although the message went out.**
- **P3: the subject erasure can race a drive inserting a call-back, leaving that one row's
  real number stored.** The row is never dialled (`callback_still_wanted` cancels it). The fix
  is ordering in `retention._erase_follow_up_runs`, which is another audit's area.
- **P3: the `LIKE key%` booked checks (`runner.on_call_ended`, `_ever_booked`) treat `_` in a
  step id as a wildcard.**
  - Starter ids are `s1`..`s9` and attempts are at most 3, so with generated ids it cannot
    collide.
  - Exact matching (as `cancel_callbacks` does) would remove the class.
- **P3: a call-back cancelled because of a pause reads "moved on". `end_run` can report
  stopping an already-finished run.** Both are wording or a stray event.
- **P3: the hourly start cap is check-then-insert.** Concurrent ingests can exceed
  `starts_per_hour` by the number of concurrent starts.

**Forwarding and numbers**

- **P2: releasing a Calevate number leaves forwarded lines pointing at it `working`.**
  - The number returns to the vendor pool and the client's forwarded callers could reach the
    next renter.
  - It needs a product decision on what to tell the client, and touches the hold and release
    emails. Founder decision 4.
- **P3: a test arrival is billed to the client if the pipeline runs after the test settles.**
  `_OPEN_TEST_SQL` requires `status = 'ringing'`. Matching by window regardless of status
  changes the D-746 claim, so it is reported.
- **P3: a real forwarded call showing the business number inside the 2-minute test window is
  taken as the test.** Possibly by design.
- **P3: the price charged is re-read at record time, not the one quoted.** It differs only if
  an attestation lands mid-purchase, or on a resumed purchase.
- **P3: `delete_line` takes no advisory lock, so two concurrent last deletes may not queue the
  prompt republish. `update_line` 404s on a line whose Calevate number was released.**
- **P3: `campaigns/number_catalog.purchase_number` is unrouted.** Only a test calls it, and
  `workers/number_rental.py` cites it.

**Admin and tenancy**

- **P3: a dispute accepted or contested at Razorpay whose decision write then fails loses the
  operator's audit row.** The provider call comes first.
- **P3: the refund route answers 404 before the step-up check.** It leaks only to an
  `admin:tenants` operator.
- **P3: the same contact id twice in one profile save drops an entry silently**
  (`profile_service.save_contacts`).

**Saved views and translations**

- **P3: saved-view filter value strings and column keys have no per-item length cap**, unlike
  `CapturedFieldFilterIn.value` (200).
- **P3: saved-view names are unique by exact case, but Pip finds them ignoring case.**
- **UNVERIFIED (P3): a lens day of `0001-01-01` may 500.** Not run.
- **P3: an export ticket is spent before the export is built.**
- **P3: two simultaneous "Try again" presses on a translation write two audit rows.**
- **P3: a translation job queued for over an hour can be paid twice** (the stale settle, then
  a second claim).

Checked and sound (not repeated per item): permissions and realms on every route read, tenant
scoping through `tenant_session`, constant-time secret comparison, outbox and job-id dedupe,
IST windows in spend and rental, Decimal money, and logs carrying ids only.

## FOUNDER DECISIONS

1. None needed for D2's question. The unknown-tenant event is now acknowledged. The reason is
   above.
2. Should a Meta lead older than the enquiry window, or recovered by re-drive, be dialled?
   Today it is dialled under a fresh 7-day consent.
3. Should a lead-ad form with no consent question write a consent decline that cancels the
   person's other call-backs, or only refuse this one dial?
4. When a Calevate number is released while a forwarded line points at it, what should the
   client be told, and should the release be refused until the forward is switched off?

## Files outside the brief's area

- `apps/api/crm/attention.py`: three `BLOCK_REMEDIES` sentences for the refusals D2b-02 now
  records.
- `apps/api/billing/plans.py` (D2b-11) and `apps/api/billing/payment_events.py` /
  `payment_routes.py` (D2b-01): billing, which is D2's area.

## Tests and gates run (Docker only)

- The 11 touched test files, then the covering suites:
  - commercial terms, follow-ups (definition, ingest, routes);
  - forwarding (hidden caller, quiet, verification);
  - every `ingest_*` suite, lead ingest, lead-source dry-run, portals and sealed secret;
  - Meta lead ads, number supply, Razorpay e2e, reconciliation listing;
  - saved-views lens, spend attribution, TTS plan fee, error ladder;
  - Pip `follow_up_actions_test` and `lead_actions_test`.
- Before-state: 15 new or changed cases, all failed on the HEAD modules.
- `ruff check` and `ruff format` on every touched file; mypy on the ten modules: clean.
- `scripts.check_raw_sql`: OK. `scripts.check_openapi_fresh`: OK. `lint-imports`: 2 kept.
- Not run, per the brief: the full suite and the coverage ratchet.

## Sources read

- https://razorpay.com/docs/webhooks/best-practices/ (10 Nov 2026): a non-2xx is a delivery
  failure, retried for 24 h, after which the webhook is disabled; 5 s timeout.
- https://razorpay.com/docs/webhooks/ (10 Nov 2026): separate URLs for Live and Test mode.
  Nothing about several webhooks per account or per-webhook filtering.
