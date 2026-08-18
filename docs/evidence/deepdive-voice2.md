# Deep dive 2 — the voice path and the engine seam, re-attacked (18 Aug 2026)

Scope: `apps/voice-runtime/**`, `apps/api/engine/**` and its voice-runtime twin,
`packages/shared/src/**/engine*`, the in-call tool endpoint, the reconciliation poller,
`packages/shared/tests/engine_conformance/**`, and the tests for all of it.

This is the SECOND pass. `docs/evidence/deepdive-voice.md` (D-187) is the first; it was
read before anything here was written, and nothing it covered is re-litigated. What that
pass cleared and this one did not re-open: the five hard-rule-3 obligations of the
receiver, the post-commit fast-path key, the reliability triad, the explicit HTTP
timeouts, `_persist_transcript`'s replacement semantics, and `end_call`'s contract.

**Every claim below is labelled PROVEN (something was executed) or REASONED (read only).**

Environment caveat, stated once: Postgres 5433 and Redis 6380 are shared with six sibling
agents, the database used here is `calevate_replay`, and it currently holds **1,925
tenants** of other suites' residue. Every timing number below is therefore noisy and every
one is reported with its spread. No threshold from this document is asserted in CI.

---

## Fixed

### F-1 — Two adapters, two transport ladders, and no clause that could see the difference (PROVEN) — D-240

`BolnaEngine._request` and `CartesiaEngine._request` were two copies of one ladder, and
the copies disagreed on the two answers that matter most on a failure path. Driven against
the shipped tree with `httpx.MockTransport` (scratch probe, both adapters, same handlers):

| the vendor answers | `bolna` | `cartesia` |
|---|---|---|
| 429 + `Retry-After` | backs off, then `engine_rate_limited` (`transient`, 503, retryable) | `engine_rejected` (`dependency`, 502, terminal) — **no backoff at all** |
| 200, `text/html` (WAF page) | `engine_bad_response` (`dependency`) | **returns a snapshot**: `engine_call_id=''`, `status='failed'`, `raw_status='unknown'`, `cost=None`, `turns=0`, `raw_document=2B` |
| 502 | `engine_rejected` | `engine_rejected` |
| transport failure | `engine_unreachable` | `engine_unreachable` |

Both halves are load-bearing.

**The throttle.** `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` and
`apps.api.agents.service` both dispatch on `engine_rate_limited` by name. Reporting a 429
as `engine_rejected` therefore turns "the vendor is busy" into "this call failed" —
burning a campaign contact's retry budget for a reason that has nothing to do with the
contact, which is verbatim what the OTHER adapter's own comment forbids.

**The unreadable success.** A 200 carrying a WAF challenge, a CDN interstitial or a
truncated document is the ordinary failure mode of an API behind an edge. Answering it
with `{}` does not fail — it INVENTS. Downstream, that snapshot is a completed call
written as `failed`, metered at nothing, archived with `{}` as the vendor's own document,
and read `settled` by the reconciliation poller forever, with no alert anywhere.
`VoiceEngine.get_agent`'s contract clause forbids exactly this shape in words ("a snapshot
for an agent nobody created is a conclusion drawn from nothing that looks like a
measurement"), and `tests/adapter_escaping_exception_test.py` (P2.2) had already found and
closed it — **on one adapter**.

**Why nothing caught it**: the conformance suite's every fixture models a vendor
BEHAVING. `conftest.py`'s stubs are stateful about ids and 404s and nothing else, so no
clause could reach a throttle, a gateway error, a dead socket or an unparseable body.

**Fix.** One ladder in `apps/api/engine/vendor_http.py`; both adapters keep only the
genuinely per-vendor half (their own client, base URL, credential, version pin). Log codes
carry an `engine` label rather than a vendor prefix — `cartesia_request_failed` and
`engine_error` were one event under two greppable names, the same drift D-93 removed from
the receiver's `if engine == "bolna":`.

**Five new conformance clauses**, over a `ladder` fixture that puts one HTTP-speaking
adapter over a transport the clause writes: a retried throttle, an exhausted one, an
unreadable success (WAF page / truncated JSON / whitespace), a vendor error body that must
not reach our caller, and a transport that never answers. A sixth clause derives the
HTTP-speaking set from the roster **by type** and fails if one has no transport recipe, so
a third vendor cannot join with its failure paths unmeasured.

**PROVEN, sabotage.** Restoring the old Cartesia ladder fails exactly three clauses —
`test_a_throttled_vendor_is_retried_rather_than_reported_as_a_failure[cartesia]`,
`test_an_exhausted_throttle_is_transient_rather_than_a_rejection[cartesia]`,
`test_a_success_the_adapter_cannot_read_never_becomes_an_answer[cartesia]` — and no
others; the bolna parametrisations stay green. The saboteur is kept permanently as
`tests/engine_audit_test.py::_DriftedLadder`, because the FakeEngine saboteur harness
cannot reach these clauses (a fake engine has no transport to point anywhere) and a clause
nothing can fail is not a clause. That skip is now explicit in `_conformance_failures`
rather than a `TypeError` counted as a failure.

Conformance suite: **132 → 143 cases**, all green.

### F-2 — The poller's window is anchored to when a call STARTED; its promise is about when a call ENDED (PROVEN) — D-242

`BolnaEngine.list_executions` sends `params={"created_after": since.isoformat()}` and
`reconcile_executions` passes `since = now - 30 minutes`. That is a filter on **creation**.
The guarantee is about **completion**, and the two are the same instant only for calls
shorter than the window.

For a call that runs 40 minutes, `completed` lands roughly 43 minutes after creation
(TRD §5: cost, recording and transcript populate at `completed`, ~2–3 min after
disconnect). Every listing from then on excludes it. Bolna's webhook is at-most-once with
errors swallowed — verified in their OSS delivery code, D-31 — so **one lost delivery on a
long call left it never transcribed, never metered, never invoiced**, and invisible to
everything else in the tree:

* `report_stalled_pipeline` asks `EXTRACTION_OWED_SQL`, which only sees calls already
  recorded `completed`; a lost terminal webhook leaves the row at `in_progress`;
* D-187's `_pipeline_settled` fix — which does catch a completed call whose pipeline died
  — lives entirely inside the listing sweep, so it never gets to run either.

Nothing anywhere said the guarantee of record was bounded by call DURATION. That is the
silent premise D-31/D-32 exist to forbid, sitting under the one mechanism appointed to be
the backstop.

**Fix**: `reconcile_outstanding_calls`, a half-hourly cron at :15/:45 that asks the engine
directly about every call row the pipeline has not finished. Two candidate shapes, in one
query:

1. a row that never reached a terminal status;
2. a row recorded `completed` carrying neither a usage event nor a transcript turn.

`status = 'completed'` bounds the second clause rather than "any terminal status", and
that is what makes it affordable: a `no_answer`, `busy` or `failed` call legitimately has
no cost and no transcript forever, so the wider predicate would make every failed dial in
24 hours a candidate on every sweep. Terminal candidates are then judged by
`_pipeline_settled` rather than re-derived here — that is where "what did this snapshot
imply" was already answered (D-187), and asking it a second way is how the poller starts
re-driving healthy calls.

Bounded four ways: a 10-minute floor (`PIPELINE_STALL_AFTER`), a 24-hour horizon, 50 rows
per tenant, and **200 vendor requests per sweep** — the last alerting when it truncates,
because a sweep that stopped early and said nothing would be a short listing reporting
`complete=True` all over again.

It also produces `calls_never_finished`, which nothing could produce before: a call the
engine still calls unfinished hours later is either burning platform minutes with nobody
watching or an `engine_call_id` that names nothing. There is no repair to count, so it has
to be an alert.

**Why its own cron and not a second phase of the 10-minute tick.** `calls` is FORCE-RLS'd,
so "which tenants hold an unfinished call" can only be asked one tenant session at a time
— the sweep is O(tenants). PROVEN: as a phase of `reconcile_executions`, the poller test
file went from **13s to 51s** against this box's 1,925 tenants, and the fan-out would have
run three times an hour instead of twice. The common case (a short call whose webhook was
lost) is already covered by the listing within ten minutes; this population has been
unfinished for longer than the stall window by definition.

**Rejected alternatives, both recorded in the code:**

* **a wider `created_after`** — 25 hours covers the tail and re-lists a whole day of
  executions, past `_LISTING_MAX_PAGES` (20) for any real fleet. The poller would then
  report `reconciliation_listing_incomplete` on every healthy tick and train the operator
  to ignore the one alarm that says calls are unrecoverable. It also does nothing for a
  call that never completes.
* **an `updated_after` filter** — inventing a freshness parameter has `_next_link`'s exact
  failure mode ("a `?page=` the vendor ignores returns page one forever, which is a silent
  truncation wearing the costume of a fix"). Whether `GET /executions` accepts one is
  OPERATIONS §2 gate 6, and needs a Bolna account.

**NAMED, NOT FIXED**: an exhausted probe budget starves the same tail of the tenant
ordering (ordered by tenant id) until the incident clears or those calls pass the horizon.
A rotating start offset needs durable state to be fair and makes the sweep
non-deterministic to reason about; the truncation ALERTS instead.

**PROVEN, sabotage, in three directions:**

| sabotage | what goes red |
|---|---|
| `reconcile_outstanding_calls` returns before the loop | `..._longer_than_the_listing_window_is_still_recovered`, `..._not_finished_for_hours_is_reported` |
| every terminal candidate forced `settled` | `..._whose_pipeline_died_is_recovered_after_the_window_too` |
| no terminal candidate ever `settled` | `..._does_not_re_drive_a_call_that_owed_nothing` |

Four new clauses in `tests/poller_guarantee_test.py` (24 cases, green). Each scopes the
sweep to its own tenant through `callable_tenants` — the same seam `outbox_dispatcher_test`
drives on the stall alarm — because a fleet-wide sweep on this shared box spends its whole
vendor budget on other suites' residue before reaching the tenant under test.

`callable_tenants` moved from `dispatcher` to `pipeline` (the layer `dispatcher` already
imports) rather than being copied: two sweeps need it, and a second copy would be a second
answer to "which tenants can hold a call".

### F-3 — A stranger's engine name reached an alert field, bounded one function below (PROVEN) — D-243

`webhook_routes._refuse` bounds the `{engine}` path segment before it becomes a metric
label and argues the case at length: "passing it through raw would let anyone who found
the URL mint unbounded label cardinality in the metrics pipeline — a cheap way to hurt the
monitoring of the service they are already probing."

The `alert()` twenty lines above it passed the raw segment through, and so did its twin in
`tool_routes`. **PROVEN** by driving both endpoints with a 414-character path segment
containing a newline, from an unauthenticated caller:

```
webhook status=401 ack=0.5ms   tool status=401 ack=0.3ms
calevate.alert:alert  engine_len=414 'AAAA…\ninjected: yes'      ← the alert record
METRIC webhook_ack_ms provider='unknown'                          ← the label, correctly bounded
METRIC tool_ack_ms    provider='unknown'
```

The ERROR log record is written on EVERY request (the 15-minute suppression governs
delivery, not the log line), from any source address. It is not PII and the log redactor
caps free text at 200 characters, so this is cardinality and operator-facing noise rather
than disclosure — but it is the same value, the same argument, and one of two consumers
was protected.

**Fix**: `engine_intake.engine_label` is the one bounding function; `_refuse` and both
alert call sites use it. The operator loses nothing — the reason string
(`"unknown engine"`) and `source_ip` are both still on the record.

**PROVEN, sabotage**: restoring `engine=engine` in either call site turns
`test_a_strangers_engine_name_reaches_no_alert_field_either` red with the 414-character
value quoted in the failure message.

### F-4 — Hard rule 3's budget had never been measured as a distribution (PROVEN) — D-241

D-109 built a measuring harness for the IN-CALL tool endpoint against TRD §6.2's 100ms and
recorded a full table. The WEBHOOK receiver — whose 500ms budget is the hard rule, and
whose vendor delivers at most once so a slow ack loses the call — had round-trip counts,
deadline tests and no distribution at all.

The instrument moved to `tests/ack_harness.py` (nearest-rank percentile, discarded warm-up,
`asyncio.Barrier` release) and both budget files use it. Two copies of `percentile` is how
two measurements of one service stop being comparable.

---

## Measured

Real handler, real `main.app`, real `verify_source`, real `_read_bounded`, real inbox claim
against real Postgres, real ARQ enqueue against real Redis. Nothing on the path stubbed.
`X-Ack-Ms` is the handler's own `time.perf_counter()` from the route's first line to
`_ack`; the client column is the same request measured from outside through
`httpx.ASGITransport`. Every delivery carries a DISTINCT transition — a repeated one is
answered off the Redis fast path and would measure the cheapest path this endpoint has.

**The webhook receiver, one delivery in flight** (n=40 warm, three consecutive runs):

| run | min | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| 1 | 4.1 | 4.4 | 5.4 | 7.9 | 7.9 |
| 2 | 4.2 | 4.7 | 6.6 | 12.9 | 12.9 |
| 3 | 4.0 | 5.4 | 8.3 | 10.5 | 10.5 |

p50 spread across runs is 4.4–5.4ms, i.e. **±20% run to run on this shared box**. Against
the 500ms budget that is ~1% of it, with the three Postgres statements and two Redis ops
`tests/voice_runtime_ack_budget_test.py` pins as the mechanism.

**A refused delivery (401, source not allowlisted)**, same instrument, n=40:

| min | p50 | p95 | p99 | max |
|---|---|---|---|---|
| 0.1–0.2 | 0.1–0.2 | 0.2 | 0.3 | 0.3 |

**~25× cheaper than an accepted one**, and stable across runs. That number did not exist
before: `_refuse` was written because a rejection storm made `webhook_ack_ms` go silent
rather than spike, and an operator reading that runbook entry had no scale to read the
recovery against.

**The receiver across concurrency widths**, server-measured, released at one event-loop
tick (two runs, same session):

| in flight | 1 | 8 | 24 | 96 |
|---|---|---|---|---|
| p50 ms, run A | 6.0 | 108.2 | 190.7 | 478.9 |
| p95 ms, run A | 6.0 | 131.7 | 197.9 | 505.0 |
| p50 ms, run B | 5.8 | 103.6 | 154.1 | 375.6 |
| p95 ms, run B | 5.8 | 108.2 | 160.9 | 379.8 |

The distribution is FLAT at every width (p50 ≈ max) — D-55's convoy signature: one event
loop, `latency ≈ in-flight ÷ throughput`. Solving from width 96 gives **~200–250 acks/s per
process**, which matches D-55's own figure, and therefore **500ms is reached at roughly
100–125 concurrent in-flight deliveries per process**. At width 96 run A's p95 was 505.0ms
— i.e. the `webhook_ack_slow` alert fires. D-32 records Bolna at 100 concurrent on Pilots
and 250+ in production, so the four-worker deployment D-55 prescribes has a margin of
about 2× and no more. This is a process-count question (DEPLOYMENT §2a), not a handler
question, and it is the same conclusion the tool endpoint reached at a different width.

**The in-call tool endpoint** re-measured on the shared instrument, one call in flight,
n=40: server p50 0.8ms, p95 1.5ms, max 1.9ms; client p50 1.52ms; concurrent width 8 p50
9.9ms. Consistent with D-109's recorded table (p50 1.0 / p95 1.4 at width 1; 6.3 at width
8) and unchanged by this pass. Zero Postgres statements, one enqueue — still asserted as a
mechanism rather than as a clock.

**What is excluded, and cannot be included here** (unchanged from D-109 and restated
because a measurement that drops the slow part is worse than none): the network, the
Cloudflare/nginx edge, uvicorn's socket layer. The engine→us→engine round trip is pilot
gate 8's `custom_function_tool_call_budget`, still NOT RUN, and needs a Bolna account.

---

## Cleared — looked at, found sound

* **Engine isolation, hard rule 2** (PROVEN by grep across `apps/api/**` outside
  `engine/`, `apps/workers/**`, `packages/shared/src/**` and `apps/voice-runtime/**`, plus
  `lint-imports`). Searched for vendor field names (`total_cost`, `cost_breakdown`,
  `recipient_phone_number`, `agent_prompts`, `agent_welcome_message`, `rag_id`,
  `extracted_data`, `user_data`, `latency_data`, `telephony_data`, `agent_call_id`,
  `outbound_calls`, `from_number_id`, `conversation_duration`) and vendor status strings
  (`no-answer`, `call-disconnected`, `balance-low`, `in-progress`, `call-connected`).
  Every hit outside `apps/api/engine/` is prose in a comment or docstring; there are zero
  vendor status literals anywhere else. `execution_id` is OUR key name as well as theirs
  and is used as such. Both import-linter contracts KEPT. **The new
  `engine/vendor_http.py` holds no vendor specifics at all** — the client is passed in.
* **The <500ms ack path, re-walked including every alarm call site** (REASONED + the
  measurement above). Every `alert()` on the receiver path takes `_admit`'s lock
  NON-BLOCKING and does `put_nowait` on a bounded queue; the SMTP send is on a daemon
  thread; `_admit_shared`'s Redis call runs on THAT thread and not on the loop. No new
  heavy import, no synchronous model call, no DB write beyond the inbox claim and the
  forensic row, and both waits that can outlive the caller (`_BODY_DEADLINE_S`,
  `_DURABLE_DEADLINE_S`) still bound. `tests/voice_runtime_import_surface_test.py` boots
  the service in a fresh interpreter and still passes.
* **Deploy coupling** (PROVEN — `tests/voice_runtime_deploy_independence_test.py` and
  `voice_runtime_import_surface_test.py`, green). The one new voice-runtime symbol
  (`engine_label`) lives in `engine_intake` and imports nothing; `vendor_http` is imported
  by the adapters only and is unreachable from this service.
* **A call the vendor says is billable with no cost** (REASONED, and already fixed).
  `_meter` returns 0 and alerts `call_billable_without_cost` when `snapshot.billable_ready`
  is true and no cost could be read (P1.2), naming pilot gate 7. Nothing to add.
* **A duplicate execution** (REASONED). `list_executions` de-duplicates by execution id
  across pages; `_upsert_call` is idempotent on `engine_call_id` (unique) and refuses to
  move a terminal row backwards; the ARQ job id for a re-drive is fixed per execution, and
  the new sweep deliberately reuses the listing sweep's `"reconcile"` key so the two
  mechanisms cannot drive one call twice.
* **A payload that disagrees with the poller** (REASONED). Unchanged and correct: the
  webhook payload contributes only `execution_id`, `raw_status` and an agent-ref HINT;
  `_ingest_stages` prefers the snapshot's ref and reads everything else from the
  authenticated fetch.
* **A body that arrives twice concurrently** (PROVEN — `tests/webhook_storm_test.py`, 10
  cases green, including `test_a_thundering_herd_of_one_transition_claims_exactly_once`
  and `test_the_harness_catches_a_claim_that_is_only_right_sequentially`). The fast path
  is a READ, the durable claim is `INSERT … ON CONFLICT DO NOTHING` plus a CAS on a stale
  lease, and the fast-path key is written only past the commit.
* **A spoofed source and a replayed execution id** (PROVEN — `voice_runtime_security_test`
  and `signing_engine_intake_security_test`, 28 + 5 cases green). `client_ip` reads only
  `CF-Connecting-IP` and only from a trusted peer, fails closed outside `local`, and
  ignores `X-Forwarded-For` entirely; a replay with a rewritten body is absorbed by the
  fast path and COUNTED (`webhook_replay_divergence`).

---

## Found, not fixed

* **`platform_engine_health` fails `scripts/check_rls_coverage`** (PROVEN by running it).
  The table exists in the shared `calevate_replay` database and **does not exist anywhere
  in this worktree** — a sibling agent's migration created it in the database we share.
  Not this dive's to fix, and named here so the next reader does not chase it: on a clean
  database this branch's `check_rls_coverage` has nothing to say.
* **The brief's premise about "new alarm call sites inside both engine adapters" does not
  hold on this tree** (PROVEN by grep). Neither `bolna.py` nor `cartesia.py` calls
  `alert()` or any `record_*` recorder, before or after this pass; the only occurrences of
  "alert"/"health" in them are prose. The health-recording work the brief refers to is
  presumably the sibling's `platform_engine_health` above.
* **`call-disconnected` maps to our `completed` while `_TERMINAL_RAW` excludes it**
  (carried forward from D-187, re-checked because this pass gave `snapshot.terminal` its
  first production consumer). The contradiction is now REACHABLE — `reconcile_outstanding_calls`
  reads `snapshot.terminal` — and the existing mapping is the RIGHT one for that consumer:
  a `call-disconnected` execution has no cost and no transcript yet (TRD §5), so treating
  it as still-outstanding and re-probing next sweep is correct, and treating it as terminal
  would re-drive a pipeline into an empty record. Left alone deliberately, now with a
  consumer that justifies it rather than none that did.
