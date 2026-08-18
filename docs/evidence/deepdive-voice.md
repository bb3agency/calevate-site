# Deep dive — the voice path and the engine seam (18 Aug 2026)

Scope: `apps/voice-runtime/**`, `apps/api/engine/**`, `packages/shared/**` (the
`VoiceEngine` protocol and the normalized `CallEvent`/`TranscriptTurn`), both real
adapters plus the two fake profiles, the conformance suite, the in-call tool endpoint,
and the post-call pipeline where it meets engine data.

Deliberately NOT re-covered, because a prior pass cleared them and this one confirmed
nothing had moved: voice-runtime's five hard-rule-3 obligations, the post-commit
fast-path key, the reliability triad, the kill switch, the explicit HTTP timeouts, and
D-181's pre-dial intent ordering. See `audit-reliability.md` and `audit-correctness.md`.

**Every claim below is labelled PROVEN (by running something) or REASONED (read only).**

---

## Fixed

### F-1 — The poller certifies a call as finished on the strength of a summary (PROVEN)

`apps/workers/pipeline.py::_expected_artifacts` decides what a call was OWED by reading
the engine's own record: no cost in the snapshot ⇒ no usage row expected, no transcript
in the snapshot ⇒ no transcript expected. That inference is sound for `get_execution`
and **unproven for the snapshot the poller actually holds**, which comes from
`list_executions` — and the contract itself calls those rows summaries
(`VoiceEngine.get_execution`: "the poller's listing rows are summaries").

Nothing anywhere requires a listing row to be as rich as a fetch:

* the Protocol's `list_executions` clause is entirely about COMPLETENESS of the listing
  (pagination), never about the richness of a row;
* whether a listing row carries `total_cost`/`cost_breakdown` and the transcript blob is
  a **vendor behaviour nobody has verified** (D-31/D-32);

  > **CORRECTION, D-350.** This bullet originally read "Bolna publishes no OpenAPI spec,
  > so whether `GET /executions` rows carry ..." — and it was wrong on both halves. Bolna
  > DOES publish an OpenAPI 3.1 document (`docs/vendor/bolna/hosted-oas.md`), and there is
  > no `GET /executions` collection to ask about: the listing is per agent,
  > `GET /v2/agent/{agent_id}/executions` (D-353). The finding this bullet supports
  > SURVIVES both corrections, which is why it is corrected in place rather than struck.
  > The spec declares the listing's `data[]` as `AgentExecution` — the identical schema
  > `GET /executions/{execution_id}` returns — so on paper a row is a full execution. What
  > a schema cannot say is whether the server POPULATES the expensive fields on a list
  > response, and a nullable-everywhere schema is exactly how a server that omits them
  > still validates. The gate stands.
* the conformance suite cannot fail on it, and this was checked rather than assumed:
  `FakeEngine.list_executions` builds its rows with the same `_snapshot_from` as
  `get_execution`, and the Bolna stub's `GET /executions` branch returns whole
  `BOLNA_COMPLETED` documents (`conftest.py`). Both adapters therefore make listing rows
  and fetches indistinguishable — which is exactly the assumption at issue.

**The consequence if the premise is wrong** is silent and total for one population: a
completed call whose pipeline died (Redis refused the enqueue, the worker was killed, the
ladder ran out) on an agent with **no extraction schema** and a tenant with **no
subscribed CRM endpoint** implies nothing from a summary row, so `_pipeline_settled`
answers `settled`, the poller never comes back, and the call is never transcribed, never
metered, never invoiced — with no alert anywhere. `report_stalled_pipeline` cannot see it
either: it asks only `EXTRACTION_OWED_SQL`. D-31 appoints this poller the guarantee of
record; for that shape it would have guaranteed the status line and nothing else, which is
verbatim the defect `tests/poller_guarantee_test.py` was written to close one layer up.

**PROVEN**: `tests/poller_guarantee_test.py::test_a_summary_listing_row_does_not_certify_a_call_as_finished`
stages a completed call whose pipeline was lost, ages it past the stall window, and hands
the poller a listing row stripped of cost and transcript while `get_execution` still holds
both. Before the fix: `repaired=[]`, no alert, call permanently unmetered. After: one
`unfinished_pipeline` repair.

**Fix**: `_pipeline_settled` confirms an EMPTY expectation set against the authenticated
read before believing it, and only there. Three conditions bound the cost:

| condition | what it excludes |
|---|---|
| `not expected` | the row carried neither cost nor transcript — a healthy call under a rich listing never reaches the line |
| `not any(present.values())` | the database holds no artefact either — a call whose pipeline ran is answered from its own rows, with no vendor request at all |
| `late` | past `PIPELINE_STALL_AFTER`; the 30-minute window then admits the execution about three more times, so a genuinely silent call costs a handful of reads in its whole life rather than one per tick |

A failing read PROPAGATES: `reconcile_executions` counts it `unreached` and says so in
`reconciliation_probe_incomplete`, which already reports repairs as a floor. Swallowing it
would answer `settled` on no evidence, which is the defect.

**What closes the unknown, by name**: OPERATIONS §2 gate 6, which needs a Bolna account.
If a real listing row turns out to be fetch-quality the confirmation is belt-and-braces
and stays; it cannot be reasoned away from here.

### F-2 — `end_call` had no contract, and the adapters disagreed underneath it (PROVEN)

`VoiceEngine.end_call` was a bare `...` in the Protocol — no docstring, no stated
semantics — and the conformance suite had **no clause for it at all**. Underneath:

* `BolnaEngine.end_call` → `POST /executions/{id}/stop`, whose 404 `_request` turns into
  `engine_rejected`;
* `CartesiaEngine.end_call` → `POST /agents/calls/{id}/end`, same;
* `FakeEngine.end_call` → looked the id up, found nothing, **returned None**.

So the whole pipeline running offline (DEV-SETUP §3) reported a hang-up that never
happened. Same shape as the `get_execution` divergence P2.6 found and the `transfer` one
D-93 found, surviving on the one method with no clause to catch it.

**The right answer is RAISE**, and it is argued rather than picked: this method's caller
is a control plane — an operator or a cost guard stopping a live call — and its one
observable failure is saying it worked. Silence there puts "call ended" on a screen while
the caller is still connected and the minutes are still billed. Deliberately NOT
`delete_agent`'s idempotent answer, whose caller is a compensation path an absent object
already satisfies.

**PROVEN**: the new clause
`contract_test.py::test_ending_a_call_the_engine_does_not_hold_is_reported` was run
against the tree three times — it failed for `bolna` and `cartesia` first (their stubs
answered 200 to every id), and, with the stubs made stateful, failed for `fake` and
`fake-restricted` under a restored no-op `end_call`. All four pass with the fix.

**Also fixed, and it is the interesting half**: both vendor stubs answered `/stop` and
`/end` with 200 regardless of id, so the clause could only ever be failed by the fixture
— the exact defect the KB stub's own docstring refuses ("a stub that answered every
DELETE with 200 would let an adapter that never detaches anything sail through"). They are
now stateful, and each carries a MARKED ASSUMPTION: nothing published says what either
vendor returns for a call it is not running, 404 is inferred from the REST default their
GET routes are documented to give, and pilot gate 2 is where it stops being an assumption.
What the fixture proves is OUR mapping — that the adapter surfaces a refusal rather than
swallowing it.

`end_call` has one caller in the tree (`scripts/pilot/concurrency.py`); this is a contract
defect, not a live incident.

### F-3 — `_persist_transcript` rewrote half a turn (PROVEN)

The upsert was `ON CONFLICT (call_id, idx) DO UPDATE SET text, text_redacted`, so a
re-drive whose transcript differed at an index rewrote **what** was said and kept **who**
said it, **which language** it was in and **when**. It also left any turn past the end of
the new transcript in place. Both halves produce a row nobody spoke.

**It is reachable through our own parser, not only through a fickle vendor.** Bolna sends
one prefix-tagged blob and `bolna.parse_transcript` indexes turns by POSITION, counting as
lost "an unprefixed line arriving BEFORE any turn exists". Two fetches that disagree about
the opening line are therefore off by one for the whole call, and every turn inherits the
other reading's speaker. `speaker` is not cosmetic: the extractor is speaker-aware — which
is why `fake.SAMPLE_TURNS` had to be rewritten so the CALLER asks to book — and a
mis-attributed turn is how a call becomes a hot lead nobody asked for. It also drives the
client's transcript view and the QA sample.

**PROVEN**:
`tests/pipeline_partial_failure_test.py::test_a_re_driven_transcript_replaces_a_turn_rather_than_half_of_it`
persists a three-turn reading then a two-turn one that is off by one. Before the fix the
call ended as `[(0,'caller','namaskaram'), (1,'agent','naaku appointment'), (2,'caller','sare')]`
— every speaker wrong and an orphan tail. After: exactly the second reading, `lang`
carried.

**Fix**: refresh every column, and delete what this reading does not claim — matched
against the indices actually written rather than `idx >= len(turns)`, because contiguity
is a property of today's parsers and not of `TranscriptTurn` (`idx` is only `ge=0`). An
EMPTY new transcript still returns early and deletes nothing: one read coming back with no
turns is not evidence that the turns we hold are wrong. `transcript_turns` is tenant-scoped
and is NOT in `db.registry.APPEND_ONLY_TABLES`, so the delete is a correction, not a
rewrite of evidence — verified against the constant, and `make guardrails`' ledger check
passes.

### F-4 — D-182 left two voice-runtime tests asserting the number it changed (PROVEN)

`db/session.get_engine` sets `max_overflow=MAX_NESTED_CONNECTIONS - 1` (= 1) and argues
at length why zero self-deadlocks a pool holding only depth-2 tasks. Two tests in
`tests/voice_runtime_ack_budget_test.py` still asserted the superseded `0`:
`test_a_warm_receiver_opens_no_new_database_connections_under_load` and
`test_the_pool_is_sized_with_no_single_use_overflow_and_a_bounded_wait`.

**PROVEN, and PROVEN to be upstream rather than mine**: both fail on
`origin/claude/app-building-session-r1v5j9` as merged — `git show` on that ref has the
test asserting `_max_overflow == 0` beside a `session.py` whose own docstring says "WHY
THE OVERFLOW IS 1 AND NOT 0 (D-182)". Nothing in this dive touches `db/session.py`. Lint,
mypy and `make guardrails` were all green over it; only pytest saw it.

**Fix**: the property is restated where the number can move rather than pinned to a
literal. The churn test now asserts connections opened are bounded by the pool's OWN valve
(twelve deliveries through a two-connection pool may open at most one; a restored
`max_overflow=10` produces twelve), and the configuration test asserts
`_max_overflow == MAX_NESTED_CONNECTIONS - 1` — the same constant
`scripts/check_session_nesting.py` bounds nesting by, so the pair D-182 created can no
longer drift apart. The test is renamed to match what it now says.

---

## Cleared — looked at, found sound

* **The 100ms in-call budget** (REASONED, plus D-109's measurements re-read). It IS
  measured: `tool_ack_ms` is its own series via `TOOL_ACK`, the endpoint is
  `POST /tools/v1/{engine}/opt-out`, and CI asserts the MECHANISM (zero DB round trips,
  exactly one enqueue) rather than a wall clock. The breach ALERT fires at 500ms, not
  100ms, and that is stated where it happens (`webhook_routes.TOOL_ACK`) with D-109's
  argument for why a wall-clock CI assertion on a shared runner measures the runner. Not
  a finding; the budget is instrumented and its enforcement question is argued, not
  forgotten.
* **The <500ms webhook ack path** (REASONED). Walked every call in `_receive` for a
  blocking wait: `client_ip` is pure `ipaddress`; `verify_source` is two dict lookups plus
  `parse_source_ip_allowlist`, which is `lru_cache`d on the string and reached through
  `get_settings`, also cached; `alert()` writes a log record and a bounded `queue.Queue`
  handed to a daemon thread — the SMTP send never touches the loop, and `_admit` takes its
  lock NON-BLOCKING; `_server_span` returns before the opentelemetry import when tracing is
  off; the body read is bounded in bytes AND time; the durable section is under
  `asyncio.timeout`. `tests/voice_runtime_import_surface_test.py` boots the service in a
  fresh interpreter and reads `sys.modules`, which is what keeps the lazy-import claim
  honest. Nothing new here.
* **The normalized-model boundary** (PROVEN by grep across `apps/**` and `apps/web/src`).
  Searched for vendor field names and vendor status strings (`no-answer`, `balance-low`,
  `call-disconnected`, `total_cost`, `extracted_data`, `rag_id`, `user_data`,
  `recipient_phone_number`, `latency_data`, `synthesizer`, `transcriber`) outside
  `apps/api/engine/`. Every hit is prose in a comment or docstring; the frontend's status
  literals are all OUR `CallStatus` vocabulary. `webhook_deliveries.event_type` carries the
  vendor's raw status string by design (a forensic row, SEC-COMP §4), which is stated where
  it is written.
* **The truthful-answer floor** (PROVEN by grep + the conformance suite + the compliance
  guardrail). `TRUTHFUL_ANSWER_DIRECTIVE` has no writer; `compose_engine_prompt` is the
  only producer and all three adapters call it; the only `AgentConfig(...)` construction
  outside tests is `agents/service._to_config`, and the A/B arm path
  (`_variant_config`) `model_copy`s it and recomposes the opening rather than substituting
  a sentence; `verification.judge` scores `TRUTHFUL_ANSWER_MARKER` separately from the
  script (arguing the vendor-truncation case) and refuses the publish on a proven absence;
  the drift sweep re-reads it. `make guardrails` reports "3 adapters composing the
  truthful-answer rule they cannot switch off". Per-call `CallContext.fields` reach Bolna's
  `user_data`, which is rendered into the client's script — i.e. BEFORE the appended
  directive — so the precedence sentence still stands over lead-derived text.
* **Adapter divergence, the rest of it** (PROVEN by running the suite). `get_agent`,
  `get_execution`, `detach_kb`, `transfer`, `provision_number`, the capability descriptor
  and the webhook method are each pinned by a clause, and 132 cases pass across four
  subjects. `end_call` was the gap (F-2).
* **Recording that never arrives** (REASONED). `_copy_recording_once` returns
  `none_offered` and the recording is deliberately NOT in `_expected_artifacts`, with the
  argument written out: a vendor link that has expired must not block the repair of a
  missing lead.
* **Out-of-order status delivery** (REASONED). `_upsert_call_row`'s conflict clause
  refuses to move a terminal row backwards, and the inbox is keyed on the TRANSITION rather
  than the execution, so `completed` is not swallowed by an earlier `queued`.

---

## Found, not fixed

* **`call-disconnected` maps to our `completed` while `_TERMINAL_RAW` excludes it**
  (PROVEN by reading `bolna._STATUS_MAP` and `_TERMINAL_RAW` together). One snapshot can
  therefore report `terminal=False` with `status="completed"`, and `CallEvent.is_terminal`
  would answer True for the same event. **Inert today**: `snapshot.terminal` is read only
  by pilot scripts and tests, and `CallEvent.is_terminal` has no caller at all in the tree.
  `billable_ready` — the flag the pipeline actually gates on — is `raw_status ==
  "completed"` and is correct. Left alone deliberately: changing either side is a change to
  a status mapping that nothing consumes, and inventing a consumer to justify it would be
  the worse edit. Recorded here so the next reader does not have to re-derive that the
  contradiction is harmless.
