# Deep dive — the half-wired CLASS, swept

**Date** 2026-08-18 · **Scope** `apps/api`, `apps/workers`, `apps/voice-runtime`,
`packages/shared`, `alembic`, `scripts` · **Decisions** D-230 … D-235 ·
**Guardrail** `scripts/check_half_wired.py` (`make guardrails`, CI)

CLAUDE.md's sharpest rule is *"Leave no half-wired feature. A route nobody mounted, a job
nobody registered, a column nobody reads and a migration nobody applied are not progress
— they are defects that look like progress on a screen."* Six audit waves fixed instances
of it by hand. This sweep asked the question of the whole backend, derived every candidate
from the tree rather than from a hand-list, and shipped a guardrail that fails on
regressions.

Every finding below is labelled **PROVEN** (a scan or a test executed against the tree) or
**REASONED** (established by reading). Sections that found nothing are listed too — a
sweep that reports only its hits is a sweep nobody can tell was run.

---

## 0. How each class was derived

| Class | Derivation | Tool |
|---|---|---|
| 1. Columns nobody reads | every `Mapped[...]` in `models.py`/`base.py`; each occurrence elsewhere classified by AST position and, for `text()` SQL, by clause (INSERT column list / SET target = write; everything else including `RETURNING` = read) | `check_half_wired.write_only_columns` |
| 2. Settings/config keys | every `Settings` attribute off the AST, against every mention outside `config.py`, `platform_config.py`, `core/settings.py` | `check_half_wired.unconsumed_settings` |
| 3. Functions/classes with no caller | every public module-level function, minus framework dispatch (route verbs, validators, `pytest_*`, `main`, `upgrade`/`downgrade`), against every `Name`/`Attribute`/string reference in `apps` + `packages` + `scripts` + `tests`, with `__all__` and docstrings excluded as non-callers | `check_half_wired.unreferenced_exports` |
| 4a. Routes nobody mounts | already guarded | `check_wiring.unmounted_routers` |
| 4b. Mounted routes no client calls | 175 mounted paths against `apps/web`, excluding the generated `openapi.json`/`schema.d.ts` | one-off scan, reported not gated |
| 5. Stubs and markers | `pass` / `...` / `NotImplementedError` bodies outside `Protocol`/`ABC`; `TODO`/`FIXME`/`XXX`/`HACK` over raw text (comments never reach an AST) | `check_half_wired.stub_bodies`, `unclosed_deferrals` |
| 6. Feature flags | `flags/registry.FLAGS` against every `flag_enabled` call site | by hand; now enforced by `assert_flag_registry_wellformed` |
| 7. Exception paths that swallow | every `except:` / `except Exception` / `except BaseException`, body classified by whether it does anything at all | `check_half_wired.swallowed_exceptions` |
| 8. Two ways per problem | every function name defined in more than one module under `apps` + `packages` | one-off scan, then read |

---

## 1. Columns nobody reads — **9 candidates, 4 are false, 5 real**

529 `Mapped[...]` columns. `check_wiring` already guards "no code touches it at all"
(8 recorded deferrals, all still valid). This sweep asked the harder question its
docstring declines: **written, never read.**

**PROVEN — nine columns have a writer and no SELECT, no `RETURNING`, no response field.**

**Four are not findings, and the reason generalises: a DB constraint is a reader**, and
the sharpest kind — it evaluates the column on every write and refuses the row.

| Column | Its reader |
|---|---|
| `AuthSession.revoked_reason` | `CHECK (revoked_at IS NULL OR revoked_reason IS NOT NULL)` + the enum CHECK |
| `QaCallSample.reviewed_by_admin_id` | `CHECK review_is_complete_or_absent` |
| `FirstCampaignReview.decision_source` | `CHECK (decision_source <> 'operator' OR decided_by_admin_id IS NOT NULL)` |
| `RecordingErasureHold.tenant_erasure_id` | `CHECK (num_nonnulls(request_id, tenant_erasure_id) = 1)` |

Counting these would have made the guard's first run four-fifths noise, which is how a
guardrail teaches people to add exemptions until it means nothing. The rule is encoded in
`_check_constraint_names` and pinned by
`half_wired_guard_test.py::test_a_column_read_only_by_a_check_constraint_is_not_a_finding`.

**Five were real.**

| Column | Verdict | Action |
|---|---|---|
| `CampaignContact.dedupe_hash` | **PROVEN** — `sha256(phone)[:16]`, unsalted, written on every upload. The upload dedupes on `seen` within a batch and `UNIQUE (campaign_id, phone_e164)` across batches, both on the number itself; the only other statement naming it is retention's erase, which NULLs it. A reversible derivative of PII with no reader, ever. | **FIXED** — write stopped (D-233), two-step per hard rule 8, DROP migration named as the closer. Test: `campaigns_test.py::test_a_contact_upload_stores_no_hash_of_the_number`, sabotage-verified. |
| `WebhookInboxEvent.enqueued_at` | **PROVEN** — written by `mark_inbox_enqueued`, read by nothing. | **FIXED** — `record_inbox_lag` on the dispatcher tick reports the oldest row still parked at `enqueued`, i.e. a webhook whose arq job never reported back (D-234). |
| `WebhookInboxEvent.processed_at` | **PROVEN** — written by `mark_inbox_processed`, read by nothing. | **FIXED** — `record_inbox_handling_ms` off that statement's own `RETURNING`, so the deferred half of a webhook is measured as well as the 500ms ack (D-234). Both tests sabotage-verified. |
| `WebhookDelivery.signature_valid` | **PROVEN** write-only. Forensic: it records whether an inbound engine webhook was HMAC-verified or merely IP-allowlisted (SEC-COMP §4). Its reader is a person with psql. | **BASELINED** with what closes it — an ops incident-scope surface, which is a response-model change and therefore `apps/web`'s snapshot. See "Referred to the frontend owner". |
| `Lead.first_call_id` | **PROVEN** write-only. `last_call_id` is selected and returned by `crm/service.py`; `first_call_id` is written by the same INSERT and read nowhere. | **BASELINED** — surfacing it means a field on `LeadOut`, which regenerates `apps/web/src/lib/api/openapi.json`. Referred. |

---

## 2. Settings and console-managed keys — **1 finding of 60**

**PROVEN.** Every `Settings` field has a consumer except one.

`cohere_api_key` was declared in `packages/shared/.../config.py`, classified
`AppliesRule(LIVE)` in `apps/api/core/platform_config.py` — so the ops console offered it
to an operator as an installable credential — and read by **no code path in the
repository**. D-28 makes retrieval a managed API service that owns its own embeddings.

Its last consumer was `tests/platform_secrets_test.py`, which used it as the FIXTURE key
for the env-shadowing test. That is how a dead key survives an audit: the fixture looks
like a use. **FIXED** — field and classification row deleted together, fixture repointed
to `cartesia_api_key` (D-231). `check_env_parity` and `check_config_applies` both stay
green; the guard's section 2 goes red if it comes back (sabotage-verified).

**CLEAN:** the other 59 fields, all six bootstrap keys, and every `AppliesRule` row.

---

## 3. Functions and classes with no caller — **4 findings**

971 public module-level functions after excluding framework dispatch.

**PROVEN — three had no reference anywhere**, not in another module, not in their own,
not in the suite. Each is also a second way to do something the repo already does:

| Symbol | The way that is used | Action |
|---|---|---|
| `core/settings.fail_fast` | `BootstrapError`, which is what `validate_bootstrap_env` actually raises | deleted (D-232) |
| `quality/sampling.get_sample` | `find_sample` + the route's own `not_found` | deleted (D-232) |
| `agents/voices.voice_selection_available` | `voice_selection_capability().available` | deleted (D-232) |

Proof of death rather than absence of grep hits: no reference in `apps/`, `packages/`,
`scripts/`, `alembic/` or `tests/`; not decorated, so no FastAPI or pytest dispatch; not
present as a string, so no `getattr` and no arq job name; and `apps/web` reaches the
backend over HTTP, never by Python name.

**PROVEN — two shutdown functions were written, exported and called from nowhere**, which
is the same shape with teeth: `core/queue.close_queue` and
`core/alert_admission.close_admission`. The API lifespan closed only `core/redis`; the
worker's `on_shutdown` flushed only tracing — under a `job_completion_wait = 45` comment
that explicitly budgets fifteen seconds for "the pool teardown". `close_admission`'s own
docstring claimed it was "called from the same shutdown path as `close_redis`".
**FIXED** (D-230), both processes, each closer under `suppress` and ahead of the span
flush; `tests/service_teardown_test.py`, sabotage-verified (4/4 fail without the fix).

**BASELINED:** `scripts/pilot/record.py::recorded_fixtures` — the replay seam for adapter
fixtures captured during the Bolna pilot. External blocker: a Bolna account with credit
(OPERATIONS §2).

**Classes:** no finding. Response models referenced only by their own routes module, and
ORM classes reached through `Base.metadata`, are alive by construction; a scan that
reported them would be a scan people route around.

---

## 4. Routes

**4a — routers nobody mounts: CLEAN.** `check_wiring` reports 47 routers, all mounted.

**4b — mounted routes no client calls: CLEAN, reported not gated.** 175 mounted paths
checked against `apps/web` with the generated `openapi.json` and `schema.d.ts` excluded.
21 had no literal match, and every one is explained: `/healthz*` and `/hooks/v1/razorpay`
are not browser surfaces, and the `/v1/auth/{realm}/…` family is built by
`lib/authn/*.ts` from a realm variable. This class is deliberately **not** in the
guardrail: an admin route that ships ahead of its screen is legitimate, and a gate whose
only remedy is an exemption is a gate that decays.

---

## 5. Stubs, markers and placeholder logic — **1 finding**

**TODO/FIXME/XXX/HACK: CLEAN.** Zero markers in the scanned tree. The three textual hits
are the marker VOCABULARY — `check_deploy_env`'s refusal pattern, `check_coverage_ratchet`
arguing about waivers, and a conformance test's sentence about what a refusal "becomes …
the day an engine grows campaign objects". The guard's regex requires `# MARKER` or
`MARKER:`/`MARKER(`, so prose that names the vocabulary does not match
(`test_prose_that_names_the_vocabulary_is_not_a_marker`).

**`NotImplementedError`: CLEAN.** None in the tree.

**`...` bodies: CLEAN.** 35 found, 33 are `Protocol` members (`calevate_shared/engine.py`
alone is 20) — the language's own spelling of a signature, excluded by CLASS rather than
by a name list that would need editing every time the Protocol grows.

**Constant-returning functions:** two, both deliberate and both documented at length —
`engine/fake.py::holds_credentials` (the fake adapter IS its own vendor) and
`engine/cartesia.py::_cost` (a stamped guess at a vendor's currency is worse than no cost;
closes at pilot gate 4, an external blocker).

**REASONED, one finding:** `flags/registry.FLAGS["call_timing_breakdown"]`'s description
claimed the view "renders numbers we already record on the call row" — and `calls.latency`
was dropped in migration `f1a7c39d5be2` because nothing wrote it. See §6.

---

## 6. Feature flags — **1 finding of 1**

The repo declares exactly one flag. `call_timing_breakdown` had `consumed_by=None` — a
legitimate state, and the console renders it beside the switch — but nothing anywhere said
what would change it, and its description promised data a migration had already deleted.

**FIXED.** `FlagSpec` gains `blocked_by`, REQUIRED exactly when `consumed_by is None` and
forbidden otherwise, asserted by `assert_flag_registry_wellformed` at boot beside the RBAC
assertion. The flag's blocker is named: pilot gate 4, the vendor's per-component timings
validated against a stopwatch, which needs a Bolna account placing a real call. The
description no longer promises a column that does not exist.

The rule is not "flags must be consumed" — landing a mechanism before the feature it gates
is deliberate. The rule is CLAUDE.md's: *a deferral is a statement of what closes it, or it
is not a deferral.* Tests:
`feature_flags_test.py::test_an_unconsumed_flag_must_say_what_would_consume_it` and
`::test_a_flag_may_not_claim_a_consumer_and_a_blocker_at_once`.

**Flags checked but never set: CLEAN** — `flag_enabled` has no call sites at all, which is
the same finding from the other side and is what `blocked_by` now documents.

---

## 7. Exception paths that swallow — **1 finding**

**PROVEN, and the headline is that this class is in good shape.** 33 handlers have a
trivial body (`pass` / `return None` / `continue`); **every one of them is narrow** —
`ValueError`, `KeyError`, `VerifyMismatchError`, `httpx.InvalidURL` — i.e. the function's
interface, not a swallow. Of the ~40 broad handlers, all but one log, alert, re-raise or
change state, most with the argument written above them.

The one finding: `scripts/pilot/knowledge.py::_delete_is_accepted` did
`except Exception: return False`, collapsing "the vendor says this handle is unknown" —
the informative answer — with "our own adapter raised a TypeError". A pilot gate then
reported a knowledge base as absent on the strength of a bug in the prober. **FIXED**: the
exception's class is carried out and lands in `delete_refused_with` on the sub-check a
human reads.

**The rule the guard encodes is narrower than "must log", and that matters.** A first cut
demanded a logging call and reported four correct handlers — `health.ready` setting
`redis_ok = False` (the failure IS the readiness verdict), the tracing exporter bumping a
dropped-span counter, the Sentry readiness check appending a `ReadinessProblem`. What
CLAUDE.md forbids is sharper: a handler whose body does **nothing at all**.

---

## 8. Two ways per problem — **1 finding**

**PROVEN.** 71 function names are defined in more than one module. Almost all are the
route/service pairs the module anatomy prescribes (`add_contacts`, `create_campaign`,
`list_sources` …) or deliberately-distinct locals (`_out`, `_json`, `_retry_after`).
Two looked like duplicates and are not: `derive_slug` is a documented delegate
(`tenancy.signup` → `admin.service`, with the seam argued in place), and the engine
adapters' `_parse_dt` twins are inside the isolation boundary hard rule 2 draws.

**One was a genuine duplicate:** `splice_t0_block` existed twice, byte-identical in body,
in `apps/api/admin/intake.py` and `apps/api/agents/t0.py`, along with `T0_HEADER` and
`_INSERT_BEFORE`. `tests/t0_recompile_test.py` pinned the two copies to identical output —
a test whose whole job was to stop them drifting.

The reason given for the copy was a cycle, `admin.intake → kb.service → agents.t0 →
admin.intake`, and the file disproved it at line 79: `admin/intake.py` has always done
`from apps.api.agents import t0`, and `t0` imports nothing from `admin`. The docstring
called the fix "a one-line change in a module this wave does not own".

**FIXED.** One definition, in the module that owns the format. The pinning test is now
`test_the_block_format_has_a_single_owner` — two implementations agreeing today is not one
implementation, it is the state the drift starts from. Sabotage-verified.

---

## The guardrail

`scripts/check_half_wired.py`, in `make guardrails` and `.github/workflows/ci.yml`, with
negative controls in `tests/half_wired_guard_test.py` (21 tests: one red state per
section, plus the states that must NOT fail — a CHECK-constrained column, a `RETURNING`
read, a route handler, a Protocol member, a narrow handler, a handler that records state,
prose that names a marker).

**It refuses rather than reporting OK on a tree it cannot read** (`check_wiring`'s D-176
doctrine): floors of 100 columns, 20 settings, 100 public functions, 50 handlers, and
exit code **2** — nothing was judged — rather than a green 0.

**Two files rather than one**, and both say so. `check_wiring` asks whether a declaration
appears in the registry that gives it effect; its answers are yes/no against a live object
and it needs no exemptions. This one judges POSITION and BODY and carries two shrink-only
baselines. Merging them would put an exemption file inside the check that does not have
one.

**It blinded itself twice while being written**, and both are pinned by tests:

1. `WRITE_ONLY_BASELINE` names the columns it exempts in strings, and string identifiers
   count as reads (they must — most column access here is raw `text()` SQL). Every
   baselined column therefore looked consumed, and `stale_baselines()` demanded the whole
   registry be deleted. Dropping the registry files wholesale then reported the script's
   own section functions as dead code. The fix is narrow: a registry file's **strings** are
   not evidence, its **calls** still are.
2. The negative-control file's docstring named `voice_selection_available`, which made the
   test proving it dead the reference proving it alive. Docstrings are excluded from the
   reference scan for the same reason `_positions_in` excludes them.

**What it does NOT check, said in the file:** frontend consumption of a mounted route;
whether a recorded metric is anybody's alarm (`alerting._record` reaches a log and no
pipeline); whether a read is a MEANINGFUL read (position is decidable, purpose is not);
enum and `Literal` member reachability (legitimately produced by a DB row, an engine
payload or client input).

---

## Referred to the frontend owner (`apps/web`, out of this fence)

Both are backend columns whose only possible reader is an API response field, and adding
one regenerates `apps/web/src/lib/api/openapi.json`:

1. **`Lead.first_call_id`** — add to the lead SELECT, `LeadOut` and `_row`, symmetric with
   `last_call_id` which is already returned. One line each.
2. **`WebhookDelivery.signature_valid`** — the ops incident-scope surface SEC-COMP §4 and
   OPERATIONS §7 both assume exists. "How many inbound engine webhooks did we accept on an
   IP allowlist rather than a signature" currently has no answer outside psql.

A third, adjacent: **`QaCallSample.reviewed_by_admin_id`** is written and constraint-read
but never returned, so the admin QA queue cannot show who signed off a verdict. Not a
half-wired defect (the CHECK is a reader), but the same one-line response-model change.

---

## Still open, and why

| Item | Blocker |
|---|---|
| `call_timing_breakdown` has no consumer | **External** — OPERATIONS §2 pilot gate 4: a Bolna account placing a real call, with per-component timings validated against a stopwatch. Recorded as the flag's `blocked_by`. |
| `engine/cartesia.py::_cost` returns None | **External** — one real completed Cartesia call, to read the currency and granularity off the cost object. |
| `scripts/pilot/record.py::recorded_fixtures` has no caller | **External** — no pilot has run, so there are no fixtures and no replay tests. |
| `campaign_contacts.dedupe_hash` DROP | **Ours, next** — hard rule 8 forbids dropping in the release that stops writing. The migration is the whole remaining step. |
| `Lead.first_call_id`, `WebhookDelivery.signature_valid` readers | **Ownership** — a sibling owns `apps/web` and its OpenAPI snapshot this session. |
