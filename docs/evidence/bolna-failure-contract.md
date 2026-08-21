# Bolna's failure contract, against ours

**Date:** 2026-08-21. **Lane:** what happens when their API says NO — the error ladder,
retries, backoff, rate limits, idempotency, timeouts, concurrency admission.
**Subject:** `apps/api/engine/vendor_http.py`, `apps/api/agents/service.py`,
`apps/workers/campaign_dispatch.py`, `apps/workers/pipeline.py`,
`apps/voice-runtime/webhook_routes.py`, `runbooks/alarm-index.md`.

**Evidence class:** VERIFIED-VENDOR-DOCS — Bolna's own hosted documentation, mirrored
read-only at `bolna-findings/mirror/pages/` with a per-page SHA-256 manifest. Every claim
below cites `<path>:<line>` and quotes the line. Where a page's schema block and its prose
disagree the disagreement is REPORTED, never resolved silently (§8).

Pages read end to end: `api-reference/{errors, rate-limiting, limits, pagination}.md`,
`api-reference/calls/{make, stop_call, overview}.md`,
`guides/post-call/polling-call-status-webhooks.md`, `guides/outbound/auto-retry.md`,
`pricing/outbound-calling-concurrency.md`, `enterprise/concurrency-management.md`,
`changelog/february-2026.md`. Negative searches were run across all 333 pages and are
reported as findings in their own right (§4).

---

## 0. One-line verdicts

| # | Lane question | Verdict |
|---|---|---|
| 1 | Does our error ladder match their codes? | **Two real defects, both fixed.** 429 was already right. The vendor's own error CODE was parsed past and thrown away, and every 4xx/5xx collapsed into one verdict — which settled a campaign contact TERMINALLY, as "this person may have been rung", for a `400` that proves nobody was. §1, §2. **FIXED, red-then-green.** |
| 2 | Do we respect their published rate limits? | **Yes, with one unbounded fan-out that is not an incident yet and has no bound to stop it becoming one.** The dispatcher is 40× inside `/call`'s limit by construction. The execution poller is the only vendor fan-out in the tree with neither a request budget nor a wall-clock budget. §3. **REPORTED with exact text — the change lands in `bolna.py`, which two other lanes hold this wave.** |
| 3 | Idempotency | **They document none.** No idempotency key, no client request id, no dedupe window, in any of 333 pages. Ours is D-181's committed intent row, and it holds. §4. |
| 4 | Timeouts | **10s uniform, and defensible on every route we actually call** — `POST /call` answers `{"status":"queued"}` immediately rather than waiting for the call. No route we call uploads a file. §5. |
| 5 | Their auto-retry vs ours | **Still exactly one ladder and it is ours.** `retry_config` absent, `bypass_call_guardrails` absent, dial body closed-set asserted, `auto_reschedule: false` pinned. Re-verified; nothing re-enables it. §6. |
| 6 | Concurrency: queue vs reject | **Queued, confirmed at both pages.** Nothing in our code assumes rejection — the dispatcher says so in a comment with the citation. **But the seam that pulls a queued dial back is unwired: `VoiceEngine.end_call` has ZERO callers in this repo**, and the big red switch stops new dials without recalling accepted ones. §7. **REPORTED — needs a decision entry, not a patch.** |
| 7 | Delivery semantics | **`bolna.py` says the hosted docs do not corroborate D-352's retry claim. They do — on the Limits page.** *"Bolna retries on non-2xx or timeout"* (`limits.md:61`). No behaviour changes; three stale premises corrected, exact text for the adapter's docstring supplied. §9. |

**The double-dial verdict is §10 and it is: no double-dial exists, and one of the two ways
it could have arrived has been closed this wave.**

---

## 1. The error ladder, code by code

Their table (`api-reference/errors.md:11-20`):

| Their code | Their words (`errors.md`) | What `vendor_http.vendor_request` does | Verdict |
|---|---|---|---|
| `200` / `201` | `:13-14` "Successful GET / action", "`POST /v2/agent`, `POST /batches` — resource created" | parse JSON; a non-JSON body on a 2xx raises `engine_bad_response` rather than becoming `{}` | correct |
| `400` | `:15` *"Invalid or missing parameter — check `message` in the response body"* | `engine_rejected`, **now carrying status + vendor code**, classified as REFUSED on the dial path | fixed, §2 |
| `401` | `:16` *"Missing or invalid API key — add `Authorization: Bearer <key>`"* | as above | fixed, §2 |
| `403` | `:17` *"Valid key but insufficient permissions"* | as above | fixed, §2 |
| `404` | `:18` *"Resource ID doesn't exist or belongs to another account"* | as above; `absent_is_success` only on `delete_agent`, which the Protocol makes idempotent | fixed, §2 |
| `429` | `:19` *"Rate limit hit — back off and retry with exponential backoff"* | 3 attempts, full jitter, `Retry-After` honoured as a floor, then `engine_rate_limited` (`transient`, retryable) | already correct |
| `500` | `:20` *"Unexpected server error — also returned when `scheduled_at` uses the `Z` suffix (use `+00:00` instead)"* | `engine_rejected`, counted into `platform_engine_health`, NEVER retried | correct, and the `Z` trap cannot reach us: we send no `scheduled_at` (`tests/bolna_call_flow_test.py` asserts the dial body is exactly `{agent_id, recipient_phone_number, user_data}`) |

**Neither of the two hazards the lane names was present.** A 429 is not a permanent
failure (it is `transient`, and `pipeline.TRANSIENT_ENGINE_CODES` reads exactly that code);
a 4xx is never retried at all — `tests/engine_audit_test.py::test_a_non_throttle_failure_is_never_retried`
already drove 400/404/500/502/503/504 and asserted one request each.

### The defect: their error BODY was read and thrown away

Their envelope is declared on both a prose page and a schema block, agreeing:

> `errors.md:26-33` — `{ "error": 1001, "message": "agent_id is required" }` … *"The `error`
> integer is an internal code; `message` is human-readable."*

> `api-reference/calls/make.md:229-239` — `Error: required: [error, message]`, with
> `error: {type: integer, format: int32}`.

`vendor_request` logged `{engine, status, route}` and parsed past the body entirely. So
`engine_error status=400 route=/call` was the whole of what an operator got, and it cannot
tell a stale `engine_agent_ref` from a revoked key from a wallet at zero — three different
pages of runbook behind one identical line.

**FIXED** (`apps/api/engine/vendor_http.py:177` `_vendor_error_code`, used at `:341`): the
INTEGER is parsed and rides the log line and the exception. The human `message` is still
discarded unread, and the split is not fastidiousness — their own worked examples for this
endpoint are *"`agent_id is required`"* and *"`recipient_phone_number is required`"*
(`calls/make.md:62-63`), i.e. the field their message names is a caller's phone number, and
`tests/engine_audit_test.py` already drives a 400 whose body carries one. The integer is
admitted only when it is an `int` (not a `bool` — in Python a `bool` IS an `int`) inside
the int32 range their schema declares, a bound that structurally cannot hold an E.164
number: `919876543210` is two orders of magnitude past int32's ceiling. That bound is what
keeps hard rule 6 true if the vendor later widens the field, and it is tested rather than
trusted.

---

## 2. The 4xx/5xx collapse — the defect that could consume a contact list

`DIAL_NOT_PLACED_CODES` (`apps/api/agents/service.py`) decides whether a failed dial keeps
its retry ladder or is settled as "this person may have been rung". Its own comment named
the problem and could not fix it:

> `engine_rejected` is the uncomfortable member of the "unconfirmed" side — the adapters
> collapse every 4xx AND 5xx into it … and we cannot tell them apart from here without an
> adapter that separates them.

So every vendor refusal took the conservative branch: `DialUnconfirmedError` →
`campaign_dispatch._settle_unconfirmed_dial` → contact `failed` on its FIRST attempt,
`exhausted += 1`, escalation to the client. **That is irreversible**: "failed, may have
rung" is not a state anything re-dials from. One stale `engine_agent_ref`, one revoked
`BOLNA_API_KEY`, one calling number the vendor does not recognise
(`calls/make.md:64` — *"Invalid `from_phone_number` … Must be a number purchased in your
Bolna account"*) therefore consumed the entire contact list of every running campaign, one
escalation per contact, each telling the client a human should check a call that was never
placed. On the two CRM buttons it produced the same sentence to a tenant's face —
*"it may have started the call anyway … calling again could ring them twice"* — about a
request the vendor threw away unread.

**FIXED.** The ladder now raises `EngineRejectedError` (`vendor_http.py:138`) carrying
`vendor_status`, and `dial_was_not_placed` (`agents/service.py:192`) is the one place the
question is answered. `REQUEST_REFUSED_STATUSES = {400, 401, 403, 404}`
(`vendor_http.py:131`) is read from their table above — every one of those rows is a
statement about the REQUEST, and `POST /call` documents exactly two responses in its own
OpenAPI block, `200` and `400` (`calls/make.md:196-207`). An intermediary that answers one
of them (a WAF 403, a proxy 404 on a route it does not know) has by construction not
forwarded the request either, so the reading holds for the whole path and not only the
origin.

**What is deliberately NOT in the set, and why the default must stay conservative**: every
5xx (a proxy can answer 502 AFTER the vendor committed) and every 4xx they do not document
— 408, 409, 413, 422 and anything that appears later. A status joins that set by being READ
in their docs, never by looking safe. The cost asymmetry is unchanged: a wrongly-retried
dial is a second unsolicited call, a wrongly-abandoned one is a contact a human looks at.

**A subclass rather than a second error code.** `engine_rejected` is read by name in a
dozen places (the alarm index row, the conformance clauses, `TRANSIENT_ENGINE_CODES`'
complement); splitting it would make each of them a two-branch decision to carry a fact
that belongs on the exception. `isinstance` is opt-in and no existing reader changed.

---

## 3. Rate limits — published, and what our two callers actually do

Published twice, identically (`api-reference/rate-limiting.md:17-25`, announced
`changelog/february-2026.md:51-67`):

> `/v2/agent/{agent_id}/executions` · **500 requests/minute**
> `/v2/agent/{agent_id}` · **500 requests/minute**
> `/call` · **500 requests/minute**
> *"All other API endpoints are subject to a default rate limit of **1000 requests per minute**."*

and the counting unit is the ACCOUNT, not the tenant: *"If your account is part of an
**organization**, the rate limit is shared across all users within that organization"*
(`rate-limiting.md:29`). One Bolna account holds every tenant's agents, so every tenant we
have shares one bucket.

**`Retry-After` is not documented anywhere.** Searched across all 333 mirrored pages:
zero occurrences of `retry-after`. Both pages that discuss 429 give backoff advice and no
header — *"Wait before retrying the request. Implement exponential backoff"*
(`rate-limiting.md:36-37`), and `limits.md:25-34` prints a `2 ** i` loop. We honour a
`Retry-After` as a floor **if one arrives** and fall back to full-jittered exponential
backoff when it does not (`vendor_http.throttle_delay_s`). That is the correct posture for
an undocumented header: costs nothing, and is right the day they add one.

**Dispatcher — safe by construction, with a wide margin.** `PLATFORM_LINES_TOTAL = 10`
minus a 30%/min-4 inbound reserve is an outbound pool of 6, and the tick may never have
more than the pool in flight, so `POST /call` peaks at ~6 requests per 30-second tick =
**12/min against a 500/min limit**. It cannot approach it.

**Reconciliation poller — inside the limit, and the only fan-out with no bound.**
`BolnaEngine.list_executions` issues `1 × GET /v2/agent/all` plus, per agent on the
account, 1..20 × `GET /v2/agent/{ref}/executions` at `page_size=50` (their maximum:
`pagination.md:14` — *"You can request up to `50` results per page"*), looping on
`has_more` (`pagination.md:50` — *"Use `has_more` to determine if you should fetch the next
page"*). We match their contract exactly.

Requests are issued strictly serially, which self-throttles: the achievable burst is
`60 / latency` per minute, so at ≥120 ms per response the poller **cannot** cross 500/min
however many agents exist. That is the honest finding, and it is why this is not filed as a
live incident. What is missing is the bound:

> `list_executions` caps pages PER AGENT (`_LISTING_MAX_PAGES = 20`) and caps nothing else.
> There is no total-request budget and no wall-clock budget, and its two sibling sweeps
> both have one — `engine_reconciliation.SWEEP_BATCH_SIZE = 25` + `SWEEP_BUDGET_S = 120.0`,
> and `pipeline.OUTSTANDING_PROBE_BUDGET = 200` with its own alarm.

The failure is a cliff rather than a slope: arq does not serialise crons (`workers/settings.py`
argues this at the campaign tick — a cron job's id embeds its intended execution time, so
the :00 and :10 ticks are different jobs), and `reconcile_executions` holds no lease. A tick
that outruns its 10-minute interval therefore runs concurrently with the next one, and two
overlapping fan-outs compound into the limit that one could not reach.

**Proposed change — NOT MADE, because it lands in `apps/api/engine/bolna.py`, which two
other lanes hold this wave.** Exact text for whoever takes it:

```python
#: Vendor requests one listing walk may make in total, across every agent. `_LISTING_MAX_
#: PAGES` bounds ONE agent; this bounds the WALK, which is the bound the two sibling sweeps
#: already have (`engine_reconciliation.SWEEP_BATCH_SIZE`, `pipeline.OUTSTANDING_PROBE_
#: BUDGET`) and the one this method shipped without. Their published ceiling on this
#: endpoint is 500 requests/minute per ORGANISATION (`bolna-findings/mirror/pages/api-
#: reference/rate-limiting.md:19`), and requests here are serial — so a single walk cannot
#: reach it at any plausible latency, but two overlapping ticks can, and arq does not
#: serialise crons. 400 leaves headroom for the dispatcher and the outstanding-call sweep
#: inside the same minute.
_LISTING_MAX_REQUESTS = 400
```

with, in the walk, `if pages >= _LISTING_MAX_REQUESTS: reason = reason or "request_budget_exhausted"`
and a `break` out of BOTH loops. No new alarm code is needed: an incomplete listing already
alerts as `reconciliation_listing_incomplete`, whose runbook row already reads "widen the
window by hand or re-run the poll". `ListingIncompleteReason` in
`packages/shared/src/calevate_shared/engine.py` gains the member.

**Their own best-practice line is worth recording because we already follow it**:
*"**Use webhooks** instead of polling for call status updates to minimize requests to
execution endpoints"* (`rate-limiting.md:42`). We do — the poller is the guarantee of
record behind the webhooks, not the primary path (D-31) — and `reconcile_outstanding_calls`
exists precisely so the polling that remains is bounded and per-row rather than fleet-wide.

---

## 4. Idempotency — they document none, stated as a negative result

Searched every one of the 333 mirrored pages for `idempoten`, `x-request-id`, `request-id`
and `dedup`: **zero hits**. There is no idempotency key on `POST /call`, no client-supplied
request id, no documented dedupe window, and no statement about what happens if the same
dial is posted twice. This is a stated negative under D-31/D-32's rule, not an assumption —
and it is now recorded in `DIAL_NOT_PLACED_CODES`' own comment, which previously said only
that their support "is unverified".

**So the whole of the protection is ours**, and it is D-181's shape:

1. `dispatch_call` commits a `calls` INTENT row **in its own transaction, before**
   `start_outbound_call`, keyed on an id we mint (`UNCONFIRMED_ENGINE_CALL_PREFIX = "local:"`).
   A lost response therefore leaves a durable record of a charge we may have incurred,
   rather than a ringing phone with no row.
2. The vendor's handle is stamped over it on a clean return, guarded by `NOT EXISTS` so the
   poller cannot make a second row.
3. Two dispatchers racing one contact collide on the committed `pending → dialing` CAS
   claim, not on the intent row.
4. `campaign_contacts.last_call_id` is written INSIDE the intent transaction (`on_reserved`),
   which is what stops `_reap_stuck_dialing` returning an unlinked contact to the ladder and
   ringing them a second time.
5. The two CRM dial buttons additionally take a BACKEND-PATTERNS §4 idempotency claim,
   committed before the paid call, and deliberately left `processing` on an unconfirmed
   outcome so the next press cannot re-dial.

Nothing in this lane weakened any of it; §2's change makes rung 1 *more* precise by
shrinking the population that reaches "unconfirmed" to the failures that genuinely are.

---

## 5. Timeouts

One value, applied to every route: `REQUEST_TIMEOUT_S = 10.0`, set on the adapter's
`httpx.AsyncClient` (`bolna.py:1644`), so connect/read/write/pool are each 10s.

**Defensible, and the argument is per-route rather than general:**

* `POST /call` does not wait for the call. Its documented success body is
  `{"message": "done", "status": "queued", "execution_id": "…"}` (`calls/make.md:22-27`),
  and the OAS pins the enum to a single value, `queued` (`calls/make.md:216-221`). The call
  is dialled asynchronously afterwards — `queued → initiated → ringing → in-progress`
  (`calls/make.md:51`). So 10s is generous for what is a write-and-acknowledge.
* No route we call uploads a file. Their `POST /knowledgebase` takes a PDF over multipart
  and all three KB methods on this adapter REFUSE (`BOLNA_CAPABILITIES.knowledge_base` is
  False, D-354), so the one plausible long request does not exist here.
* The listing and the per-execution reads are ordinary GETs.
* The vendor documents no timeout of their own, on any page.

**And the classic double-dial cause is already defused**: a read timeout at 10s on
`POST /call` raises `engine_unreachable`, which is NOT in the refused set, so the contact is
settled terminally rather than re-dialled — the conservative direction. D-181's docstring
names this exact scenario ("a read timeout at 10s, a reset connection, a proxy 502 after the
vendor committed") as the failure it was written for.

---

## 6. Their auto-retry vs ours — re-verified, unchanged

`guides/outbound/auto-retry.md:17` — *"Add the `retry_config` object when making a call via
the Make Call API or Create Batch API"* — and the options table at `:49-55` gives
`enabled | boolean | **false**`, `max_retries` 3 (range 1–3, `calls/make.md:141-146`),
`retry_intervals_minutes` `[30, 60, 120]`, `retry_on_statuses` defaulting to
`["no-answer", "busy", "failed"]` with `error` also accepted (`:57-64`).

Verified live in this tree, this wave:

* `retry_config` is absent from the dial body, and `tests/bolna_call_flow_test.py::test_a_dial_never_hands_the_vendor_a_second_retry_ladder` asserts it;
* `bypass_call_guardrails` is absent, asserted by the sibling test — their own accordion recommends it "for Testing in Development", which is verbatim what hard rule 5 forbids;
* the dial body is a **closed set** — `{"agent_id", "recipient_phone_number", "user_data"}` — asserted whole, so the next scheduling key they ship fails a test rather than arriving silently;
* the agent-level toggle the previous lane found (`ConversationConfig.auto_reschedule`) is pinned `False` in `_agent_body` (`bolna.py:2234`) with its own test;
* `POST /batches` has zero references anywhere in `apps/`, `packages/` or `scripts/`.

**Who retries what is therefore unambiguous: exactly one ladder runs and it is ours.** The
reason it has to be ours is unchanged and is worth restating because it is the hard-rule-5
argument, not a preference: each rung of `_record_failure` returns the contact to `pending`
with `next_attempt_at`, so the NEXT dispatch tick re-runs `check_dispatch` — the halt, the
cap, the calling hour and the DNC list — before the second ring. Theirs re-dials from their
own scheduler with no gate at all, so a number that joins the DNC list between attempt 1 and
attempt 2 is called anyway.

§2's fix does not create a second ladder: it puts a contact back on OUR ladder, which runs
the full gate before the retry.

---

## 7. Concurrency — queued, not rejected; and the seam that would pull one back is unwired

**Verified at both pages, in their own words:**

> `pricing/outbound-calling-concurrency.md:41` — *"Outbound calls that don't fit your
> concurrency limit are **queued, not rejected**. They dial automatically as active calls
> finish, so a batch or campaign larger than your limit still runs end to end — it just
> paces itself."*

> `enterprise/concurrency-management.md:64-65` — *"Excess is queued, never dropped … Calls
> that don't fit this cycle stay queued and dial automatically as in-flight calls finish.
> Inbound calls are never queued."*

Tiers: trial **2** concurrent and verified numbers only (`pricing:15`); paid **starts at
10**, "scaling automatically with monthly usage" (`:19`); inbound **never restricted or
queued** (`:26-28`). Capacity is split evenly across the telephony providers an account has
work waiting on (`:63`, `enterprise:73`), and BYOT SIP is not an escape — *"those calls run
on Bolna's SIP infrastructure, so they share platform capacity even though the trunk is
yours"* (`enterprise:80`).

**Nothing in our code assumes rejection**, and the dispatcher says so at the point where
the instinct would arrive, with the citation
(`apps/workers/campaign_dispatch.py:579-593`): *"THIS IS A CALLING-HOURS CONTROL, NOT AN
OPTIMISATION, AND NOBODY MAY READ IT AS A REFUSAL."* `PLATFORM_LINES_TOTAL = 10` is the
vendor's documented paid floor and its comment already carries the `GET /user/me`
`concurrency: {max, current}` read (`limits.md:11-17`) that replaces the guess. Confirmed
and unchanged by this lane.

### NEW FINDING — `VoiceEngine.end_call` has zero callers

`BolnaEngine.end_call` (`bolna.py:2480`) posts `POST /call/{execution_id}/stop` and its
docstring states its purpose:

> `end_call` is the campaign path's way to pull a queued dial back after a DNC addition or
> the big red switch, which is exactly the queued/scheduled case.

**Nothing calls it.** `grep -rn "end_call" apps/` returns the three definitions and no call
site. So:

* the big red switch (`campaign_dispatch._run_tick` returns `halted_by_big_red_switch`)
  stops PLACING dials and recalls nothing already accepted;
* a DNC addition blocks the next dispatch tick — which is what hard rule 5 requires, by the
  letter — but cannot recall a dial the vendor has already taken and is holding.

**How exposed we are depends on a number nobody has read yet**, and that is the sharp part.
`POST /call` returns `status: queued` for EVERY dial (`calls/make.md:25`, the OAS pins the
enum to that one value), so there is always a window between our POST and the ring. Under
the account's concurrency ceiling that window is short. **Over it, the surplus sits in a
vendor queue we cannot see, cancel or DNC-scrub** — and on a TRIAL account the ceiling is
**2** while our outbound pool is **6**, so 4 of every 6 dials would be queued. A contact
cleared by `check_dispatch` at 20:55 IST can ring after 21:00 with our own records showing
it was lawfully cleared, and their calling guardrails are off by default and we do not set
them (previous lane, `docs/evidence/bolna-call-flows.md` §1).

Not patched here: wiring it is a cross-module feature (the ops halt route is a step-up
confirmed action, the DNC write path is compliance's, and it needs a worker job, an alarm
code and a runbook row), and the DNC half needs a decision — `end_call` *"cannot stop a call
already in progress"* (`make-call/SKILL.md`, quoted in the adapter), so a cancel that races
an answer must not be reported as a prevented call. **Proposed decision-log entry, exact
text, §11.**

---

## 8. Where their own documents disagree — reported, not resolved

1. **The `Error` envelope's `error` field is required, and one of their own examples omits
   it.** Schema: `required: [error, message]` (`calls/make.md:229-233`). Example:
   `enterprise/concurrency-management.md:97-101` shows a 400 body of
   `{"message": "Sum of account minimums (60) exceeds the org minimum (50) by 10; …"}` with
   no `error` key at all. **Consequence handled**: `_vendor_error_code` returns `None`
   rather than raising when the key is absent, so a body of either shape is read correctly
   and the log line simply carries no vendor code.

2. **The pagination page's example execution rows carry a `status` vocabulary that is not
   the execution enum.** `pagination.md:34-45` shows `{"id": "ex_101", "status": "success"}`
   and `{"id": "ex_102", "status": "failed"}`. The execution status enum
   (`errors.md:39-56`) has no `success` — its terminal values are `completed`, `no-answer`,
   `busy`, `failed`, `canceled`, `stopped`, `error`, `balance-low`. Both are code blocks, so
   the schema-beats-prose rule does not break the tie. The illustrative ids (`ex_101`, not
   a uuid) suggest the pagination page is generic filler rather than a real listing row, but
   **the consequence if it is not is that every reconciled call reads `failed`**:
   `_STATUS_MAP.get(raw_status, "failed")` (`bolna.py:2798`) degrades an unmapped status
   silently. → **proposed OPERATIONS gate, §11**, and flagged to the response-parsing lane,
   whose file that is this wave.

3. **`errors.md` says `POST /batches` answers `201`** (`:14`) while `calls/make.md`'s OAS
   declares `POST /call` as `200` (`:196`). Not a conflict — different routes — recorded
   because a reader skimming the status table will assume creates are uniformly 201. We
   call neither `/batches` nor treat 201 specially (`vendor_request` branches on `>= 400`).

---

## 9. Delivery semantics — the adapter's own "not corroborated" note is out of date

`apps/api/engine/bolna.py:33-40` currently reads:

> **THE HOSTED DOCS DO NOT CORROBORATE THE RETRY, and that is worth knowing rather than
> glossing**: their webhook page describes the URL, the payload shape and the source IPs and
> says nothing whatever about retries, signing or delivery guarantees.

That is true of the webhook page and false of the hosted docs. The corroboration is on the
**Limits & Quotas** page, in the webhook-delivery table:

> `api-reference/limits.md:55-61` — Source IPs `13.203.39.153`, `13.126.9.249`,
> `13.202.133.53`; **Events per call** *"Multiple (status changes: queued → in-progress →
> call-disconnected → completed)"*; **Expected response** *"HTTP `200` — return fast;
> **Bolna retries on non-2xx or timeout**"*.

So D-352's retry claim no longer rests on the skills repo alone. **No behaviour changes**,
and that is the finding rather than an omission:

* their retry is unspecified in every dimension that would let us rely on it — no count, no
  schedule, no ceiling, no statement that it ever stops other than by silence — so a
  delivery lost to a deploy is still a call that may never be mentioned again, and the
  poller remains the guarantee of record;
* what it DOES bind is the receiver, which must be idempotent under redelivery rather than
  merely tolerant of it. **We are**: `webhook_routes` keys both the Redis fast path and the
  durable inbox on `{execution_id}:{raw_status}` — the PAIR — which is exactly what their
  "multiple events per call" line requires. Keying on the execution id alone would discard
  the vendor's `completed` as a duplicate of its own `queued`;
* the inbox's `payload_hash` is computed from `{engine, execution_id, raw_status}`, a pure
  function of the key, so a vendor retry carrying a slightly different body cannot trip the
  409 spoof signal;
* returning a non-2xx is no longer a silent loss but a redelivery, which makes the
  receiver's deliberate "ack anyway for an event we cannot key" still correct (a payload
  with no execution id will not grow one on redelivery).

**Corrected in this wave** (docs-truth, no behaviour): `apps/workers/pipeline.py::reconcile_executions`
(which asserted at-most-once as the reason the job exists), the `ReconcileVerdict` comment,
the "Bolna publishes no pagination contract" clause in the same function — now false, see §3
— and `apps/workers/settings.py`'s `reconcile_outstanding_calls` note.

**Left, with the reason**: `apps/voice-runtime/{webhook_routes,engine_intake}.py`,
`apps/api/reliability/service.py`, `apps/api/core/{bootstrap,alerting}.py`,
`apps/api/db/session.py` and `docs/{OPERATIONS,BUILD-LOG,ROADMAP}.md` each still carry the
phrase. In every one of them it is an incidental adjective inside reasoning that stays
correct (an unbounded vendor retry is not a guarantee), and a fourteen-file docstring sweep
across three other lanes' surfaces mid-wave buys accuracy at the price of merge conflicts on
files being edited right now. Exact replacement text for the adapter's own paragraph — the
one that is load-bearing, because it is where the next reader goes for the delivery contract:

```
   **THEY ARE NOT AT-MOST-ONCE, which is what this docstring claimed (D-352)**: the
   hosted platform "retries on non-2xx" and fires one delivery per status transition, so
   the receiver must ack 2xx and dedupe on the PAIR — never on the execution id alone, or
   the `completed` transition is discarded as a duplicate of `queued`. **THE HOSTED DOCS
   CORROBORATE IT, on the Limits page rather than the webhooks guide** — *"Expected
   response | HTTP `200` — return fast; Bolna retries on non-2xx or timeout"* and *"Events
   per call | Multiple (status changes …)"* (`bolna-findings/mirror/pages/api-reference/
   limits.md:55-61`); this docstring used to record the corroboration as MISSING, which was
   true of `guides/post-call/polling-call-status-webhooks.md` and false of their docs as a
   whole. What is still unpublished anywhere is the retry's BOUND — no count, no schedule,
   no ceiling — so "payloads as hints, poller as truth" (TRD §5) remains load-bearing: a
   mechanism whose limit nobody states cannot be the guarantee of record.
```

### One residual worth knowing about, not worth acting on

Their agent-level webhook URL can also receive **pre-call** webhooks — *"If a tool sets a
`pre_call_webhook_param` without its own `pre_call_webhook_url`, the pre-call webhook is
sent to **this agent-level Webhook URL** … Distinguish them by the `in-progress` `status`"*
(`polling-call-status-webhooks.md:74`). Such an event would share the dedupe key
`{execution_id}:in-progress` with a genuine in-progress status update, and one of the two
would be dropped as a duplicate. **Not reachable today**: nothing in this tree sets
`pre_call_webhook_param` (grepped: zero hits in `apps/`, `packages/`), the Transfer Call
tool is refused by capability, and the poller recovers a lost transition anyway. It becomes
live the day a tool with a pre-call webhook is adopted, which is the day it should be
re-read.

---

## 10. THE DOUBLE-DIAL VERDICT

**No double-dial exists in this product today, and this wave closed one of the two ways it
could arrive.** Stated as the four mechanisms that could produce one, each with its status:

| Mechanism | Status |
|---|---|
| **Their auto-retry stacked on ours** | **Closed and re-verified.** `retry_config` absent (`enabled` defaults `false`), `auto_reschedule` pinned `False`, dial body closed-set asserted, `/batches` never called. §6. |
| **A retried `POST /call` after a lost response** | **Closed by construction.** Only 429 is ever repeated by the ladder, and a 429 is the one status that states the request was refused. Every other failure — 5xx, transport, timeout — is raised, never repeated. §1, §5. |
| **A campaign contact re-dialled because we lost the link between a dial and its contact** | **Closed by D-181, unchanged.** The intent row and `campaign_contacts.last_call_id` are both committed before the phone can ring; `_reap_stuck_dialing` settles the case that outruns an `except` without a second ring. §4. |
| **A contact re-dialled because we wrongly believed nothing rang** | **Was the hazard, and the direction of the error was the SAFE one.** The system was over-conservative, not under: it treated documented refusals as possible rings, which destroyed contacts rather than duplicating calls. §2's fix moves exactly four documented statuses across, and every ambiguous case keeps the old treatment — pinned by `test_an_undocumented_vendor_status_is_still_treated_as_a_possible_ring`, which drives 500/502/504/409/422 and asserts the terminal outcome and the unconfirmed `calls` row. |

**The one place a person could still be rung when we did not mean it** is §7's unwired
`end_call`: a dial the vendor has accepted and queued is beyond recall, so the big red
switch does not reach it and a DNC addition does not reach it. That is not a DOUBLE dial —
it is a single dial we can no longer stop — and it is the open item this lane hands on.

---

## 11. Exact text to apply centrally

**APPLIED 21 Aug 2026 with centrally assigned numbers**, because five sibling lanes
proposed rows in the same wave: the two decisions below are **D-426** and **D-428**, and
the two gate rows are **32 S** and **33 S** (the proposed 27/28 were already taken by the
telephony lane).

### ROADMAP decision-log row (new) — APPLIED as D-426

| D-426 | **The vendor's own refusal reason reaches the operator, and a documented refusal stops consuming a contact** | (1) `vendor_http.vendor_request` parses the `error` INTEGER out of Bolna's error envelope (`{error: int32, message: str}`, `api-reference/errors.md:26-33` + the `Error` schema at `calls/make.md:229-239`) onto the log line and onto a new `EngineRejectedError(ProblemError)`, which also carries the HTTP status. The human `message` is still discarded unread. (2) `agents.service.dial_was_not_placed` is now the one place the "did a line get seized" question is answered, and it treats `REQUEST_REFUSED_STATUSES = {400, 401, 403, 404}` as proof that none did; everything else — every 5xx, every 4xx they do not document — keeps D-181's terminal treatment. (3) `campaign_dispatch._dial_failure_reason` puts the code, the status and the vendor's integer into `campaign_dial_failed.reason`. No new error code, no new alarm code, no migration. | **`engine_error status=400 route=/call` was the whole of what an operator got**, and it cannot distinguish a stale `engine_agent_ref` from a revoked key from a bad calling number — three different runbooks behind one line, while the vendor was sending its own code in every response body. Worse, all four of those causes reached the campaign dispatcher as `DialUnconfirmedError`, which settles a contact TERMINALLY on its first attempt with an escalation telling the client a human should check a call **that was never placed**: one config mistake consumed a whole contact list irreversibly, because "failed, may have rung" is not a state anything re-dials from. On the two CRM buttons it told a tenant *"it may have started the call anyway … calling again could ring them twice"* about a request the vendor threw away unread. The four statuses are read from their own table, each row a statement about the REQUEST, and `POST /call` documents only `200` and `400` in its OpenAPI block; an intermediary that answers a 4xx has by construction not forwarded the request either. **A subclass rather than a second error code** because `engine_rejected` is read by name in a dozen places and splitting it would make each of them a two-branch decision to carry a fact that belongs on the exception. **The int32 bound is the hard-rule-6 argument, not decoration**: their schema declares `format: int32`, which structurally cannot hold an E.164 number, so the field cannot become a PII channel if they widen it later — tested with a body whose `error` is a sentence containing a caller's number. **What is still not possible** is distinguishing a 5xx that preceded a dial from one that followed it; that needs a vendor-side idempotency key, and Bolna documents none — searched all 333 pages for `idempoten`, `request-id` and `dedup`, zero hits, now recorded as a stated negative rather than "unverified". |

### ROADMAP decision-log row (new, and it names what closes it) — APPLIED as D-428

| D-428 | **A dial the vendor has accepted cannot be recalled, and the method that would recall it has no callers** | DEFERRED, and this row is the deferral. `BolnaEngine.end_call` (`POST /call/{execution_id}/stop`, "Stop a queued or scheduled call") is implemented, conformance-tested, and called by nothing in the tree — while its own docstring says it is "the campaign path's way to pull a queued dial back after a DNC addition or the big red switch". So the big red switch stops placing dials and recalls none already accepted, and a DNC addition blocks the next tick without reaching a dial the vendor is holding. | **What makes it live rather than theoretical**: `POST /call` answers `status: queued` for every dial (`calls/make.md:25`, the OAS pins that enum to one value), and over the account's concurrency ceiling the surplus is **queued, not rejected** (`pricing/outbound-calling-concurrency.md:41`) in a queue we cannot see, cancel or DNC-scrub. On a TRIAL account the ceiling is 2 (`pricing:15`) against our outbound pool of 6, so two thirds of every batch would sit in it; a contact cleared by `check_dispatch` at 20:55 IST can then ring after 21:00 with our records showing it lawfully cleared, because their calling guardrails are off by default and we do not set them. **What closes it, in order**: (a) OPERATIONS §2 gate 13S already asks for `GET /user/me`'s `concurrency.max` — until that number is read, the size of the queue we are creating is unknown; (b) a decision on the DNC half, because `end_call` *"cannot stop a call already in progress"*, so a cancel that races an answer must not be recorded as a prevented call; (c) the halt half is unambiguous and is the one to build first — an ARQ job that walks `calls` in `queued` with a vendor-issued `engine_call_id` and calls `end_call` on each, enqueued by `POST /v1/ops/platform` when `outbound_halted` flips true, with an alarm for the calls it could not stop and a `runbooks/alarm-index.md` row beside `outbound_pool_empty`. **Not built in the failure-contract lane** because it spans the step-up-confirmed ops route, the compliance DNC path and a new worker+alarm+runbook, three of which are other lanes' surfaces this wave. |

### OPERATIONS §2 gate rows (new) — APPLIED as gates 32 S and 33 S

| 32 S | **Execution `status` vocabulary on the LISTING endpoint** | `api-reference/errors.md:39-56` publishes the execution enum and `_STATUS_MAP` covers all sixteen values. But `api-reference/pagination.md:34-45` shows listing rows carrying `"status": "success"` and `"status": "failed"` — a vocabulary that is not in that enum, in a code block, so schema-beats-prose cannot break the tie. `_STATUS_MAP.get(raw_status, "failed")` degrades an unmapped status **silently**, so if the pagination page is real rather than filler, every reconciled call is recorded `failed`, metered as a loss and never repaired. **Read one real page of `GET /v2/agent/{id}/executions` on the pilot account and record the exact `status` strings.** Cheap and decisive. Until then, consider logging an unmapped status rather than defaulting quietly. |
| 33 S | **Does Bolna send `Retry-After` on a 429, and what does their retry of a webhook actually do?** | Neither is documented anywhere in 333 pages (searched `retry-after`: zero hits). We honour a `Retry-After` as a floor if one arrives and fall back to full-jittered exponential backoff otherwise, so the first half costs nothing to be wrong about. The second half bounds D-31: *"Bolna retries on non-2xx or timeout"* (`api-reference/limits.md:61`) with **no published count, schedule or ceiling** — so measure it on the pilot (return 500 to one delivery and record how many redeliveries arrive and over what span). It decides whether the 10-minute poller is the guarantee of record or merely the backstop. |

---

## 12. What was changed, and what was verified red-then-green

| File | Change |
|---|---|
| `apps/api/engine/vendor_http.py` | `REQUEST_REFUSED_STATUSES`, `EngineRejectedError`, `_vendor_error_code`; the `>= 400` branch now parses and logs the vendor's integer and raises the subclass |
| `apps/api/agents/service.py` | `dial_was_not_placed` is the one classifier; `_close_unplaced_dial` takes and logs `vendor_status`; `DIAL_NOT_PLACED_CODES`' comment records the idempotency-key negative |
| `apps/workers/campaign_dispatch.py` | `_dial_failure_reason` replaces `type(exc).__name__` in `campaign_dial_failed` |
| `apps/workers/pipeline.py` | three stale vendor premises corrected (at-most-once ×2, "publishes no pagination contract") |
| `apps/workers/settings.py` | one stale at-most-once premise corrected |
| `runbooks/alarm-index.md` | the `engine_rejected` row now names `vendor_error`, the status split and what a 401 burst means |
| `tests/engine_audit_test.py` | 3 new ladder tests |
| `tests/dispatch_budget_test.py` | 3 new dispatch tests |

**Sabotage verification** — each fix broken, seen RED, restored, seen GREEN
(`cp` backups; no `git checkout`, no `git stash`, no commits):

```
SABOTAGE 1  agents/service.py — the EngineRejectedError arm removed from dial_was_not_placed
  RED  E  AssertionError: {'dialled': 0, 'blocked': 0, 'exhausted': 1}
       E  assert {'exhausted': 1} != {'exhausted': 0}
       FAILED tests/dispatch_budget_test.py::test_a_documented_vendor_refusal_keeps_the_contact_on_the_ladder
  GREEN 2 passed, 12 deselected

SABOTAGE 2  vendor_http.py — the int32 bound and the bool guard removed from _vendor_error_code
  RED  E  AssertionError: {'error': True}
       E  assert True is None
       FAILED tests/engine_audit_test.py::test_a_non_integer_error_field_is_refused_rather_than_logged

SABOTAGE 2b vendor_http.py — the vendor error code discarded again (vendor_error = None)
  RED  E  AssertionError: the vendor's own code was parsed past
       E  assert None == 1001
       FAILED tests/engine_audit_test.py::test_the_vendors_own_error_code_reaches_the_log_and_its_message_never_does

SABOTAGE 3  campaign_dispatch.py — _dial_failure_reason reverted to type(exc).__name__
  RED  E  AssertionError: assert 'EngineRejectedError' == 'engine_rejected:400/1001'
       FAILED tests/dispatch_budget_test.py::test_the_dial_failure_log_line_names_the_refusal_rather_than_the_python_class

RESTORED  tests/dispatch_budget_test.py tests/engine_audit_test.py -> 69 passed
```

**Gates run**: `uv run ruff check --fix . && uv run ruff format .` clean;
`uv run mypy apps packages` — *Success: no issues found in 238 source files*;
`uv run python -m scripts.check_alarm_wiring` — *Alarm wiring OK: 131 alarm code(s) and 15
metric(s), documented*; `tests/vendor_evidence_guard_test.py` — 3 passed (the mirror is
byte-identical). Suites re-run after the repo-wide format: `dispatch_budget`,
`engine_audit`, `campaign_dispatch_audit`, `engine_conformance` (302 passed);
`dial_intent_confirm`, `bolna_call_flow`, `caller_id_and_inbound_routing`,
`bolna_contract`, `bolna_listing`, `pipeline_audit`, `pii_logging_sweep`,
`lead_dial_routes` (all green). The full suite and `make coverage-ratchet` were NOT run,
per the lane brief.
