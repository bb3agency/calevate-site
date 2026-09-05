# Post-merge verification — D-532…D-541, 5 Sep 2026

**What this is.** Roughly a dozen lanes landed on one branch on 4–5 Sep 2026. This document
records what was checked, HOW it was checked, and the verdict — with the distinction hard
rule 11 requires between *demonstrated*, *suspected* and *not verifiable from this
container* kept on every line.

**The archetype being hunted** is the one that already bit twice on this branch: a function
that exists, is correct, is documented, and has **no caller**
(`engine/bolna._handoff_leg`, fixed at `f93aab0`); and a step whose visible failure masked
an expensive one (`scripts/pilot/gates_api.run_gate_2` would have bought a phone number on
every operator run, fixed at `8adbdaf`). A green guard is not proof and a docstring is not
a feature, so every claim below names the command or the file:line it rests on.

**Scope note.** `apps/api/copilot/**`, `apps/web/src/lib/copilot/**`,
`apps/web/src/components/copilot/**`, `apps/api/kb/**`, `apps/api/retrieval/**` and
`runbooks/alarm-index.md` belong to a lane that was running concurrently. Nothing in them
was edited; findings that land there are reported, not fixed. The tree moved twice during
this pass (that lane committed `95df2e7` and left four files uncommitted), which is itself
recorded below.

---

## 1. What was fixed, with the test that fails without the fix

| # | Defect | Where | Commit |
|---|---|---|---|
| 1 | `ruff check .` — a CI gate — was RED on an unsorted import block | `tests/presigned_disposition_test.py` | `43d462b` |
| 2 | The drift sweep's `not_applied` sentence named four properties and omitted the fifth, so the one drift a roster can produce reported the wrong cause | `apps/api/agents/publishing.py::_drift_of` | `93fad36` |
| 3 | A constant defined twice under a comment claiming it was imported; the original had NO reader | `apps/workers/kb_ingest.py` / `apps/api/kb/models.UPLOAD_RETRYABLE` | `7e033e0` |
| 4 | D-538's invitation-resend route had **no caller anywhere in the console** — the founder's verbatim ask was served by an endpoint an operator could not reach | `apps/web/src/lib/api/admin.ts`, `apps/web/src/app/admin/new/page.tsx` | `66e4d25` |

### 1.1 The drift sentence (`93fad36`)

`agents/verification.judge` scores five properties in its `checked` tuple; the handover
destination joined it with D-533. `publishing._drift_of` respells the `not_applied` detail
for the sweep (the publish-time wording assumes a write just happened) and that respelling
still enumerated four. A console-added transfer number — the exact case
`bolna._agent_handoff_destinations` was written to catch, a stranger's phone on a client's
agent — therefore read back to an operator as *"a different script, opening line,
truthful-answer rule or voice"*, four properties that were all identical.

Test: `tests/engine_drift_reconciliation_test.py::
test_a_handover_drift_says_so_instead_of_blaming_the_script`. The console edit is injected
AFTER the publish, because the publish's own read-back scores the same property and refuses
the agent outright (observed: `engine_publish_not_applied: … handover destination did not
read back as sent`). Verified red without the fix.

### 1.2 The duplicated retry list (`7e033e0`)

```
#: The statuses the sweep re-drives. `kb/models.UPLOAD_RETRYABLE`, imported rather than
#: spelled, so a status that stops being retryable stops being swept in the same edit.
_RETRYABLE: Final = (UPLOAD_RECEIVED, UPLOAD_CONVERTING, UPLOAD_PROCESSING)
```

The comment described a seam that did not exist: it was spelled, not imported, and
`UPLOAD_RETRYABLE` had zero readers in the tree (`grep -rn UPLOAD_RETRYABLE apps/ tests/
scripts/` returned only its own definition and two prose mentions). The two lists agreed on
the day they were written, which is the only day a duplicated constant ever agrees.

Test: `tests/kb_uploads_test.py::
test_the_sweep_redrives_exactly_the_statuses_the_model_calls_retryable`. Two halves — the
identity (`kb_ingest.UPLOAD_RETRYABLE is UPLOAD_RETRYABLE`, which is what fails on the
duplicate) and the behaviour, driven off `UPLOAD_RETRYABLE` so a third copy cannot creep
into the test either. It also proves `conversion_unavailable` and `error` are NOT swept.
Verified red without the fix.

### 1.3 The invite resend with no button (`66e4d25`)

D-538 shipped `POST /v1/admin/tenants/{id}/invitations/{id}/resend` complete: the in-place
token rotation (so two live keys cannot exist), the 2-minute/10-send rate limit computed on
the database's own clock, the `admin.invitation_resent` / `admin.invitation_readdressed`
audit actions, and the `send_count` / `last_sent_at` columns. The founder's requirement was
verbatim *"the invite link can be re-sent via the admin panel for a client business until
that mail sets up their business"*.

Nothing called it. `grep -rn "resend" apps/web/src` outside `schema.d.ts` returns only the
OTP resend, the operator setup link, and the step-up prompt. The admin console's only
invitation surface is the creation wizard, which offers `useInvite`,
`useTenantInvitations` and `useRevokeTenantInvitation` — mint, list, **cancel**. An
operator whose first mail never arrived could throw away a live key and nothing else.

The button lands where the need shows up: the `invitation_already_pending` refusal, in both
its arms (the invitation this tab minted, and one a colleague issued that the panel has to
fetch). The screen states that the previous link has stopped working, because the rotation
kills it in the statement that mints the new one.

Test: `apps/web/tests/newClient.test.tsx::"re-sends the link the wizard issued…"` asserts
the POST reaches `…/resend`, not merely that a button exists.

---

## 2. OUTSTANDING — ranked by whether it breaks a real person's day

### 2.1 FATAL-ISH · "Never transfer outside business hours" is enforced at PUBLISH ONLY, and nothing republishes at the boundary

**Owner: the handoff lane / a founder decision. Not fixed here — the fix is a design
choice.**

D-533's decision 4 and `agents/service._to_config`'s own comment both state the mechanism:

> Outside every roster member's hours, `agents/handoff.on_duty` returns nobody, this is
> None, the adapter emits no transfer tool at all, and the model has nothing to fire —
> which is the only way "never transfer outside business hours" can be enforced on an
> engine where the destination is fixed at publish time.

That is true of the CONFIG a publish sends. It is not true of the ENGINE, because the
destination is fixed at publish time and **no code path republishes an agent when its hours
close**. `grep -rn "publish_agent" apps/ scripts/` finds three production callers — the
intake wizard, the LLM-model route, and the console publish — and no cron, no sweep and no
hours-boundary trigger. `agents/handoff_routes.py` says so explicitly for roster edits
(*"Editing the roster changes what the NEXT publish sends; it does not reach a live
agent"*) and `pending_publish` is how the client is told; the CLOCK has no equivalent
notice at all.

**Demonstrated**, not reasoned. A scratch test published an agent with one roster member
inside a window containing "now", then moved only the clock (patching
`apps/api/agents/handoff.datetime`) twelve hours forward — no edit, no republish:

```
engine still holds: handoff_destinations == ("+919000000001",)
engine_drift_for  : STATE: not_applied  handoff_applied: False
```

Two consequences, and the second is the one that will be noticed first:

1. **A named person's private mobile keeps ringing out of hours.** The engine holds the
   transfer tool and the number until somebody republishes. Decision 4 is the reason the
   roster carries per-member hours at all, and the founder's stated concern was precisely
   that this is a private phone.
2. **Every such agent scores `not_applied` on every 30-minute drift tick between the hours
   closing and the next publish** (`apps/workers/engine_reconciliation.SWEEP_MINUTES ==
   {7, 37}`), which raises `engine_agent_drift_detected` and stamps `drift_state =
   'not_applied'` + `drift_detected_at` on the routing row the client-facing engine-state
   screen reads. Overnight, every agent with a roster is reported as running something
   other than what we published — which is true, and which is caused by our own expected
   value moving rather than by anything drifting.

The comment in `publishing.engine_drift_for` argues the opposite ("a sweep that rebuilt it
any other way … would score every agent published in the morning as drifted by nightfall").
Using `spec_for` at sweep time is what CREATES that mismatch, not what avoids it: the
engine cannot change itself, so an expectation computed from the current clock cannot match
an object written at an earlier one.

**The three candidate answers, none of which is mine to pick:**

- a boundary republish (a cron that republishes agents whose duty verdict has changed) —
  makes decision 4 real, costs a vendor round trip per agent per boundary;
- exclude `handoff` from the drift verdict and score it only at publish — silences the
  false drift, leaves the out-of-hours mobile ringing;
- publish the whole roster to the engine and let it decide — not achievable: the engine
  latches after one handover and selects the tool by NAME (D-533, VERIFIED-OSS
  `bolna-ai/bolna@cd2e192`, `task_manager.py:3116-3126`).

### 2.2 MEDIUM · `handoff_brief_channel_absent` fires on EVERY successful handover, for ever

`apps/workers/handoff.py::_send_brief` raises this alarm unconditionally on every recorded
handover. Its own runbook row calls it **"EXTERNAL BLOCKER, not an incident — nothing in
this repository closes it"** (gate 46d: a WABA plus an approved template). So it is a page
for a permanent, known, documented deployment state, attached to a normal successful event.

Blast radius, measured against `core/alerting.py` rather than assumed: the fingerprint is
`f"{stage}:{code}"` (line 236) with no ids in it, so repeat suppression is
`ALERT_REPEAT_INTERVAL_S = 900` **platform-wide** — at most four deliveries an hour. That is
not a storm, but it is a standing consumer of up to 20% of `ALERT_BUDGET_PER_HOUR = 20`, and
it is the shape the repo elsewhere refuses in the mirror image: `handoff.py:238` deletes
`handoff_leg_recording_unretained` on the ground that *"an alarm whose condition has been
fixed is worse than no alarm — it teaches an operator to ignore the family."* An alarm whose
condition is permanently TRUE teaches the same lesson.

Suggested (a decision, not a fix I took): keep the `handoff_brief_undelivered` log line,
drop the per-event alert, and carry the gap where the other unclosable ones already live —
`legal/readiness.py` / the ops readiness ladder — so it is reported once as a standing state
rather than once per caller.

### 2.3 MEDIUM · SUSPECTED, NOT DEMONSTRATED · the recording player now gets `Content-Disposition: attachment`

`1b69dbf` signed `ResponseContentDisposition: attachment` into every presigned URL, in
`apps/workers/storage.presigned_url`, naming its three callers — and one of them
(`crm/routes.py:226`) is the CALL RECORDING link, which
`apps/web/src/components/callAudioPlayer.tsx:196` puts straight into `<audio src=…>`. The
commit body reasons about the KB reviewer clicking a link and about the CSP; it does not
mention the audio element, and the same day's CSP work added `media-src` specifically so
that player would keep working.

**I have not demonstrated a break.** The HTML media element loads its resource without
consulting `Content-Disposition` as far as I understand it, but the specs and vendor pages
that would settle it are egress-blocked from this container and MinIO is not running here,
so there is nothing to measure against. **This is SUSPECTED, not demonstrated**, and I have
deliberately not "fixed" it on a guess.

**The cheap check, in one minute:** open any call detail page with a recording and press
play. If it downloads instead of playing, the fix is to make the disposition a parameter of
`presigned_url` — `attachment` for the KB original and the integration delivery body,
`inline` for the recording with `ResponseContentType` pinned to the audio type we stored,
which keeps the security property (the browser never renders attacker-chosen bytes as
markup) while letting the player work.

### 2.4 LOW · `handoff_attempts.leg_cost_reported` is written and never read

`workers/handoff.py:209` writes it; nothing in `apps/`, `scripts/` or the web client reads
it. It is evidence for OPERATIONS §2 gate 46c (does the vendor charge separately for the
transferred leg), answerable only by SQL against a live account. That is a legitimate reason
for a column with no code reader — recording it here so the next half-wired sweep does not
re-raise it as a finding.

### 2.5 LOW · the transferred leg's recording is retained but never served

`calls.transfer_recording_url` has a writer (`pipeline._copy_recordings`), a retention
reader, and both erasure paths (`retention.py:854/1554/2030/2527`), which is exactly what
D-533's 5 Sep decision required. It has no READ path to a person: `GET /calls/{id}/recording`
serves `recording_ref_for` (the first leg) only. Retention and erasure are the obligation, so
this is not a defect — but a client who asks "let me hear what my staff member said" cannot
be served today, and nothing on the screen says so.

### 2.6 LOW · the resend route's address-correction half still has no UI

`ResendInviteIn` accepts `email` + `attestation` and records
`admin.invitation_readdressed`. My fix wires the plain resend only: re-pointing an
invitation at a different mailbox is an operator attestation about an address nothing
verified, and it needs its own note field and its own confirmation rather than riding a
one-click button. Named here so it is a deferral with an owner rather than a silent gap.
The client-realm email-change flow is separately and deliberately open (D-538: no MFA in
the client realm, so OWASP's both-addresses-confirm variant applies).

### 2.7 Cross-lane, informational

- `check_alarm_wiring` was **RED** at the start of this pass
  (`copilot_transcript_sweep_failed` raised and undocumented). The copilot lane fixed it
  mid-session at `95df2e7` before I could report it. Nothing to do; recorded because it
  means CI was red on the branch for a window today.
- That lane also has four uncommitted files in the working tree
  (`components/copilot/CopilotPanel.tsx`, `lib/copilot/conversation.ts`,
  `lib/copilot/useCopilotConversation.ts`, `tests/copilotConversationSync.test.tsx`).
  Everything below was measured with those present.

---

## 3. VERIFIED — what was checked and passed

### 3.1 Migrations are reversible, and the round trip is byte-identical (hard rule 8)

Run in a **throwaway database** (`calevate_migcheck`), never against the shared dev DB, so
no other lane's state moved:

```
ALEMBIC_DATABASE_URL=…/calevate_migcheck  alembic upgrade head        # base -> head, clean
                                          alembic downgrade -1  x7    # every new revision
                                          alembic current             # a8d3f61c04e7
                                          alembic upgrade head        # c7e0b2a94f13
pg_dump --schema-only  calevate_migcheck  vs  calevate                # 25 diff lines, all
                                                                      # pg_dump preamble
                                                                      # and \restrict nonce
```

The seven revisions downgraded individually and cleanly: `c7e0b2a94f13` (copilot
transcript), `b8d1f04c73a9` (transfer recording), `e6c1a49d2f70` (closure),
`a71f3c9e5d84` (grants + trials), `d1e58c7a94f2` (numbers), `c4a91e60d7b3` (handoff),
`b3f7c21ea940` (kb uploads). `alembic heads` prints ONE head — no forked chain. Database
dropped afterwards.

### 3.2 Every guard, and the toolchain

| Gate | Result |
|---|---|
| all 24 `scripts.check_*` guards | pass (after `95df2e7` fixed `check_alarm_wiring`) |
| `uv run lint-imports` | 2 contracts kept, 0 broken |
| `uv run ruff check .` / `ruff format --check .` | pass (after `43d462b`) |
| `uv run mypy apps packages` | 417 files, no issues |
| `pnpm -C apps/web typecheck` | clean |
| `pnpm -C apps/web lint` | 0 errors (1 pre-existing unused-import warning in `tests/spend.test.tsx`) |
| `pnpm gen:api` regenerated into a temp copy | **`schema.d.ts` is byte-identical to `openapi.json`** — no stale frontend contract |
| `tests/absent_tenant_answer_test.py`, `edge_route_policy_test.py`, `rate_limit_census_test.py`, `loadshed_exemption_test.py` | 61 passed — every new route is in the 404 census, the edge policy and the rate-limit census |

`make coverage-ratchet` was deliberately NOT run (the founder runs it once at the end; a
concurrent run poisons it). `make db-reset` was deliberately NOT run.

### 3.3 Background fleet — registration AND a schedule that can fire

Every job added on this branch is imported in `apps/workers/settings.py` and appears in
either `functions` or a `cron(...)`:

| Job | Registration | Schedule | Reachable? |
|---|---|---|---|
| `record_handoff_started` | `settings.py:233` | enqueued by `voice-runtime/tool_routes.py::HANDOFF_JOB` | yes — name asserted equal in `tests/handoff_tool_test.py` |
| `settle_handoff` | not a job by design | called by `pipeline._post_call_stages:1093` | yes |
| `notify_account_closed` | `settings.py:255` | enqueued by `admin/closure_routes.py:272,325` and `admin/routes.py:422` | yes |
| `sweep_due_erasures` | `settings.py:564` | `minute={25}` | yes |
| `ingest_kb_source` | `settings.py:249` | outbox enqueue in `kb/uploads.create_upload` | yes |
| `sweep_kb_uploads` | `settings.py:687` | `minute={7, 37}` | yes |
| `meter_number_rentals` | `settings.py:447` | `day={1} hour={2} minute={20}` | yes — 02:20 on the 1st is 07:50 IST on the 1st, inside the IST billing month the job asks `current_billing_month()` for |
| `reconcile_engine_numbers` | `settings.py:459` | `hour={2} minute={35}` | yes (short-circuits when `number_provisioning_capability().available` is false — correct) |
| `sweep_trials` | `settings.py:549` | `hour={2} minute={25}` | yes |
| `sweep_ended_conversations` | `settings.py:327` | `minute={17}` | yes (copilot lane) |

Every cron field set was evaluated at runtime rather than read: none is empty, all minutes
are 0–59 and `day={1}` is a day every month has. There is no cron on this branch that cannot
match.

### 3.4 Alarms — all 26 new codes are raised somewhere and documented

`check_alarm_wiring` proves both directions (204 codes, 16 metrics). Each of the eleven new
codes I hand-traced has a live `alert(...)` call site with a reachable condition. The two
worth naming separately are §2.2 above (permanently true) and `trial_erasure_blocked`, which
is correctly reachable — it is what fires when a trial's grace expires while the account is
still commercially open, and it names the screen that clears it.

### 3.5 Number provisioning / Model A (D-537) — GAP-1 is closed end to end

- **`phone_numbers.engine_number_ref` now has three production writers**, where this morning
  it had none: `agents/service.provision_number` (the INSERT, `service.py:2306`),
  `agents/service.link_engine_number` (`service.py:2405`, the operator's bind route
  `admin/number_routes.py:303`), and the buy path
  (`campaigns/number_supply.buy_number` → `provision_number(engine_number_ref=ref)`).
- **The inbound publish no longer raises.** `agents/service.route_inbound_numbers`
  (`service.py:1207-1224`) catches `ProblemError` per number, alarms
  `engine_inbound_binding_failed`, and returns counts — a number with no vendor handle is
  the ordinary state and cannot fail a publish.
- **search → buy → bind → release** all exist, all pass
  `assert_number_supply_authorized()` (including the read-only search, deliberately), and
  buy is protected by an advisory lock on the E.164 + a globally-unique read under it + an
  alarm naming the vendor handle if the vendor charged and our INSERT failed. `release`
  refuses a number we did not buy, is idempotent on `released_at`, and unbinds before it
  deletes.
- `scripts/pilot/gates_api.run_gate_2` exercises `search_numbers` and records the buy as
  `not_run` with its ground — verified at `8adbdaf`, and re-read here.
- `number_provisioning_capability()` is unavailable by default: it needs the engine
  capability AND `Settings.number_resale_authorization` (a document reference, not a
  boolean). Gate 47.

### 3.6 Agent deletion + the write guard (D-527)

The choke point holds. `core/auth.requires()` calls `guard_agent_write` for every
permission in `rbac.MUTATING_PERMISSIONS` (`core/auth.py:1065-1072`), and
`rbac.assert_policy_registry_complete` refuses to boot a process in which a non-public
route declares a permission it does not enforce through that dependency — so the guard is
inherited rather than remembered.

The gap it structurally cannot see is a write whose agent arrives in the BODY. Enumerated
rather than recalled: `assert_agent_writable` is called at
`kb/service.py:304` (all three knowledge doors), `ingest/service.py:710` (lead sources),
`copilot/write_tools.py:961`, and `agents/service.py:2274` (number attach). A route-table
walk for mutating routes outside `{agent_id}` paths carrying an `agent_id` body field found
nothing else.

### 3.7 KB uploads + OCR (D-534) — every status has a writer and a reader

All seven members of `UPLOAD_STATUSES` are written by `kb_ingest._mark` or by
`kb/uploads.create_upload`, and all seven are read by the client's own screen
(`app/c/[slug]/knowledge/uploadCopy.ts:72,94,103,112,156,167` plus `processed` as the
terminal arm) and by the polling stop condition (`lib/api/kb.ts:132-135`, which correctly
treats `received` + a non-null `text_provenance` as rest — the photograph that has been
read and is waiting for a human). `original_sha256` is written at insert and READ at
`kb_ingest.py:333` as `expected_sha256`, which `_extract` verifies before it converts.
No status is set that nothing reads; no column here is write-only.

### 3.8 Trials and grants (D-535/D-536)

- **The dial-gate arm is inside the predicate, not beside it**
  (`compliance/service.credits_exhausted`), so the gate's ORDER is untouched and every
  other reader — admin health, `legal/readiness`, campaign launch, the wallet summary —
  inherits it without learning what a trial is.
- **Nothing is written to `credit_ledger` for a trial.** Verified by reading the module:
  the founder refused the "grant them credit" implementation precisely so the ledger does
  not assert money nobody gave.
- **The charge decision is taken on the CALL's own instant**, not on the settlement clock
  (`workers/pipeline.py:2642` — `trial_covers(at=snapshot.ended_at or now)`), so an ARQ
  retry hours later cannot bill a minute that was free when it was spoken. `usage_events`
  and `unit_cost_paid` are untouched, which is what makes "what did this trial cost us"
  answerable.
- **The counter reset happens on BOTH ends** — the operator's stop and the nightly sweep
  both go through `end_trial`, which calls `reset_client_counters` in the same transaction
  and stamps the boundary `counter_epoch` publishes. `usage_summary` is the client-facing
  reader and applies the epoch (`billing/service.py:1852,1871`); `margin_for_tenant`
  deliberately does not, because the admin margin panel must still see the whole month.
- **Erase-after-grace** is `_file_erasure_if_due`, and its `"blocked"` third outcome (the
  account is still commercially open) is reported rather than swallowed.

### 3.9 Closure (D-538)

`churned` really is read by the five places the module claims — verified by grep, not by
the docstring: `compliance/service.account_stopped_blocker:246`,
`campaigns.service.launch_blockers`, the membership resolution in `core/auth.py`,
`tenancy/lifecycle.assert_account_open:32`, and both ends of the invitation path. The
`ck_organizations_closed_implies_churned` CHECK is what stops the two columns disagreeing.
The four things that survive a close are stated in the module and one of them (inbound
still answers, because nothing releases the number at the vendor) is named as a GAP rather
than dressed as a decision — which is the right shape, and `engine.release_number` from
D-537 is the thing that would close it.

### 3.10 CSP enforcement + collector (D-541)

Measured against the running app rather than reasoned about:

```
OPTIONS /reports/v1/csp  Origin: https://calevate.tech   -> 200, ACAO echoed,
                                                            allow-headers includes Content-Type
OPTIONS /reports/v1/csp  Origin: null                    -> 400 (CORS refusal)
POST    /reports/v1/csp  application/csp-report          -> 204
POST    /reports/v1/csp  application/reports+json        -> 204
```

The route is mounted (`main.py:396`), enumerated in `check_public_routes` as the one route
with no credential of any kind, carries its own `csp_report` rate-limit profile
(`core/ratelimit.py:140,244`) and is deliberately outside
`loadshed.ALWAYS_ALLOWED_PREFIXES`. The web half emits both `report-uri` and `report-to`,
with `Reporting-Endpoints` suppressed on a non-HTTPS collector so `report-uri` survives in
dev. The path constant matches the route exactly.

**NOT VERIFIABLE HERE:** whether a browser's Reporting API delivery carries the document
origin or `Origin: null`. If it is `null`, the preflight above is refused and reports for
that delivery mechanism never arrive — `report-uri` would still work. MDN, the WHATWG and
Chrome's developer site are all egress-blocked from this container (the file's own docstring
records the same measurement), so this is an open question, not a finding. OPERATIONS §2
gate 44 — the attended first payment — is the cheap way to settle it: watch the collector's
log while the checkout screen is open.

### 3.11 Session persistence (D-539) and the sidebar

- `session_cookie_max_age` is DERIVED from the row's `absolute_expires_at`, never chosen,
  and `COOKIE_PERSISTENCE` is data rather than a conditional at a call site. `admin` stays
  a browser-session cookie deliberately.
- The docstring's claim that "every re-issue hands the browser a SHORTER `Max-Age`" holds:
  the only re-issues that exist are login and second-factor completion, and both go through
  `set_session_cookie` (`authn/routes.py:331,711`) with the carried-forward absolute bound.
- `components/sidebarCollapse.tsx` is imported by BOTH shells
  (`app/admin/layout.tsx:39`, `app/c/[slug]/layout.tsx:23`) and by
  `components/authn/sidebarSignOut.tsx`. There is no second copy left behind.

---

## 4. NOT VERIFIABLE FROM THIS CONTAINER

Listed so nobody mistakes silence for a pass.

1. **Browser behaviour for CSP report delivery** (`Origin` on a Reporting API POST). MDN,
   `developer.chrome.com`, `datatracker.ietf.org` and `webkit.org` are all egress-blocked.
   §3.10.
2. **Whether `<audio>` ignores `Content-Disposition: attachment`.** Same class, plus MinIO
   is not running here. §2.3.
3. **Anything requiring a live Bolna account**: whether a non-Twilio Indian number binds
   through `POST /inbound/setup`, the `phone_number_id` format, whether
   `AZURE_OPENAI_API_VERSION` is real on the v1 surface, and whether the vendor charges
   separately for a transferred leg. OPERATIONS §2 gates 16f, 25, 45, 46, 46b, 46c, 46d, 47.
   `www.bolna.ai` is 403 on CONNECT; the hash-pinned mirror is what every vendor claim in
   this tree cites instead.
4. **The Indian regulatory position on reselling a DID.** `www.dot.gov.in` is
   egress-blocked; `campaigns/provisioning.py` states this as an UNKNOWN and gate 45 puts it
   to the advocate.

---

## 5. Method, so this can be repeated

```
# guards (all 24)
for g in wiring half_wired job_wiring alarm_wiring list_bounds public_routes rls_coverage \
         metadata_columns config_applies compliance_invariants redaction_exposure docs_drift \
         openapi_fresh raw_sql idempotency_scope audit_ip session_nesting env_parity \
         web_env_parity model_residency model_lifecycle observability_ready image_paths \
         bootstrap_keys; do uv run python -m scripts.check_$g; done

# toolchain
uv run lint-imports; uv run ruff check .; uv run ruff format --check .
uv run mypy apps packages
pnpm -C apps/web typecheck && pnpm -C apps/web lint

# the frontend contract, regenerated and diffed rather than trusted
cd apps/web && cp src/lib/api/schema.d.ts /tmp/before && pnpm gen:api && diff /tmp/before src/lib/api/schema.d.ts

# migrations, in a THROWAWAY database (never the shared one)
createdb calevate_migcheck
ALEMBIC_DATABASE_URL=…/calevate_migcheck uv run alembic upgrade head
ALEMBIC_DATABASE_URL=…/calevate_migcheck uv run alembic downgrade -1   # x7
ALEMBIC_DATABASE_URL=…/calevate_migcheck uv run alembic upgrade head
pg_dump --schema-only both databases and diff
dropdb calevate_migcheck

# cron reachability — evaluated, not read
uv run python -c "from apps.workers import settings as s; print(s.KB_UPLOAD_SWEEP_MINUTES, …)"

# the CSP collector, driven as a browser would
uv run python -   # OPTIONS + POST against apps.api.main:app via ASGITransport (§3.10)
```
