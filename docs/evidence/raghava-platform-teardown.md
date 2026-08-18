# raghava-organics platform teardown — guardrails, SLOs, modules, and the frontend auth surface

**Read this before writing a new guardrail, before building the first-party auth SCREENS,
and before anyone proposes an error-budget release gate.**

**What this is.** A source read of everything in the founder's other project that the two
previous dives did not cover — its guardrail scripts, its SLO/alerting apparatus, its
module and API discipline, its React auth surface, its core-sync machinery and its payment
redesign. Two areas are deliberately absent because they are already mined: the **auth
BACKEND** (five defects found and designed out; the first-party module is built in a
parallel slice, and on THIS branch Clerk is still the live authenticator —
`apps/api/core/auth.py`) and the **deploy/VPS/DR tooling**
(`docs/evidence/raghava-deploy-teardown.md`, whose findings are implemented).

**Provenance.** Read-only clone at `/workspace/bb3agency/raghava-organics-site`, read on
2026-08-17. Every path below is relative to that clone's root; every path prefixed
`apps/`, `scripts/`, `docs/` or `tests/` is ours. Nothing was executed — this is a source
read, so where a behaviour depends on a running host or on CI secrets the claim is about
what the code *would* do, and is marked as such.

**Posture.** A read-only reference is not a trusted one, and this repository keeps earning
that. The deploy dive found a DR suite that fabricates its own evidence and then validates
it in CI. The same pattern recurs here **three more times, in three different subsystems**,
and it is the single most important thing to carry across: this project's characteristic
failure is not a missing gate, it is a gate that runs and structurally cannot fail. §3 and
§8 are where those live.

**What this is NOT.** Not a port. Their backend is Node/TypeScript on Fastify + Prisma +
BullMQ; ours is Python/FastAPI with alembic and ARQ, and CLAUDE.md forbids a second backend
language. Nothing here proposes copying a line of their backend. The **frontend** is the
exception and is treated as such in §5: React and Next.js 15 App Router are the same
technology on both sides, and their auth surface is the closest thing we have to a written
specification for screens we have not built.

**Decisions taken here:** D-172 (`check_raw_sql`) and D-173 (`check_public_routes`).
Everything else in this document is either already covered by the guardrail pack
(`make guardrails` — enumerated by `tests/guardrail_audit_test.py` off the live
`scripts/check_*.py` glob rather than by any count written in prose), or was considered and
rejected. §9's table records which, and the rejections are the more useful half.

---

## 1. The guardrail family we had not mined

Their pack is ~20 scripts run by one npm alias, `ci:reliability-gates`
(`backend/package.json:68`), which chains 23 commands with `&&`. Taken as a set it is
genuinely impressive for a two-person project. Taken one at a time, the quality varies by
more than an order of magnitude, and the variance is not random: **the checks that read a
LIVE artefact are strong, and the checks that compare two hand-written lists are weak.**

### 1.1 `security:sql-injection-guard` — right question, weakest possible answer

`backend/scripts/sql-injection-guard.js:16-27` is two regexes: `$queryRawUnsafe|
$executeRawUnsafe` and `Prisma.raw(`. It walks `src/`, `queues/` and `scripts/`
(`:8-12`), skips `node_modules`, `dist`, `artifacts`, `prisma/migrations`, and skips
**itself and its own test file** (`:35-36`) — which is the correct move and one people
forget.

What it cannot see is everything that matters. Prisma's *safe* tagged template
`$queryRaw` becomes unsafe the moment somebody writes `` $queryRaw`...${Prisma.sql([x])}` ``
or builds the template string first. It has no notion of where a value came from. It is a
grep with a name.

**But the question is exactly right for us, and we were not asking it.** Our tree runs 493
raw `text()` statements in `apps/` + `packages/` alone, because most tenant-scoped access
here is hand-written SQL rather than ORM queries — and every one of them executes as a role
that is `NOSUPERUSER NOBYPASSRLS`, inside a session whose `tenant_id` GUC is the entire
tenancy boundary. **An injection in our tree is not one account's leak; it is one
`SET LOCAL` from every account.** That asymmetry is why we did not copy their mechanism and
built a much stronger one: **D-172, `scripts/check_raw_sql.py`** (§9, and the entry in
ROADMAP §6).

Two live premises in our own code motivated it, both true today and enforced by nobody
until now:

- `apps/api/billing/plans.py:108-132` — `plan_in_effect_sql(columns, *, at)` interpolates
  both arguments into a SELECT, and its docstring says *"a caller that passes a user string
  is writing an injection, and no caller does."* That is a statement about today's six
  callers dressed as an invariant.
- `apps/api/db/transition.py:107-150` — interpolates a table name and a status column,
  which is correct because `_identifier()` refuses anything outside a fixed character
  class. Nothing verified that the validator stayed applied to the name being spliced.

The check now reads the CALL SITES when a SQL fragment is a parameter, which is the half a
linter cannot do and the half that turns both of those sentences into gates.

### 1.2 `serializer:exposure-check` — the pattern we already took, in its weakest form

`backend/scripts/serializer-exposure-check.js:8-29` is four hardcoded file paths with
`required` and `forbidden` substring lists. Three problems, in ascending order of severity:

1. **A required token of `'return {'`** (`:26`) for `users.service.ts`. Any object literal
   return in a 1,000-line file satisfies it.
2. **`forbidden: ['return order;', 'return updatedOrder;']`** (`:12`) is defeated by
   `return { ...order }`, by renaming the variable, or by returning through a helper.
3. **It scans four files, not the tree.** A fifth service exposing a password hash is
   invisible, and the check reports success.

We took the *idea* and `scripts/check_redaction_exposure.py` implements it against the live
OpenAPI schema, transitively through nested models, with per-field rather than per-model
exemptions and a clause that verifies its own allowlist's promises against the live app.
**Ours is strictly stronger; adopting theirs as well would be two mechanisms answering one
question.** Rejected, with the reason now recorded in ENGINEERING-PRACTICES §2.

### 1.3 `route:discipline-check` — our RBAC assertion already beats it, and its FLAW is what we built

`backend/scripts/route-discipline-check.js` parses Fastify route registrations out of
`*.routes.ts` via the TypeScript AST (`route-ast-utils.js:24-55`, which is the right tool)
and then asks, per route, whether the config source contains `schema:`, `preHandler:`,
`opsAuthGuard`, `opsPermissionGuard`, `adminPermissionGuard(`, or a role guard
(`:43-85`).

Four defects, and the fourth is the useful one:

1. **The guard test is a regex over the config's SOURCE TEXT** (`:66`, `:74`, `:77`). A
   comment mentioning `opsAuthGuard` inside the route config satisfies it. Our own checks
   go out of their way to strip comments for exactly this reason (`check_wiring`,
   `check_docs_drift`, `check_web_env_parity` all do).
2. **The customer half is default-OPEN.** `shouldRequireCustomerPreHandler` (`:31-41`) is a
   hand-written list of seven path prefixes. A new customer-scoped module — subscriptions,
   addresses, anything — requires no `preHandler` until somebody remembers to add it here.
   The admin/ops half is default-closed by prefix; the half holding customer PII is not.
   That is backwards.
3. **It cannot see what the app actually serves.** A route registered with a computed path,
   or a plugin-mounted route, is not in a `*.routes.ts` string literal. They know this:
   `admin-layer-drift-check.js:76-78` *hardcodes two routes into the results* because
   they are "plugin-driven".
4. **`AUTH_ADMIN_EXEMPT_ROUTES` (`:8-29`) is twelve hand-commented entries that nothing
   ever re-validates.** An entry naming a route that has moved or been deleted goes on
   exempting forever, and the day a path is reused it exempts the new one silently.

Ours is `apps/api/core/rbac.py:262-332`, `assert_policy_registry_complete`, and it is a
different class of thing: it runs at BOOT on the live route table, requires each route to
DECLARE a permission *and* enforce it via a dependency, refuses a permission that is not a
real `Permission`, refuses one that no role holds ("a lock with no key"), and **raises if it
found zero routes to check** — because a registry that checks nothing reads as a passing
guardrail. It also carries its own history in a comment: `GET /v1/me` once shipped with
`Depends(current_any)` beside `permission_meta("ops:manage")` and satisfied every clause.

**So we rejected their mechanism and built their flaw instead.** `assert_policy_registry_complete`
opens with:

```python
if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
    continue
```

A prefix is default-OPEN for everything mounted under it later, and `/v1/auth/` holds one
route today while the first-party auth module is about to put login, refresh, logout, password reset,
OTP request/verify and invite setup under it. Their repo is the demonstration of where that
trajectory ends. **D-173, `scripts/check_public_routes.py`**, enumerates the exempt set
instead — ten routes, each with a reason and the credential it verifies in place of a
session, each credential checked against the module actually serving the route.

### 1.4 `admin:layer-drift-check` — the best idea in their pack, and we already have its core

`backend/scripts/admin-layer-drift-check.js:82-148` compares three artefacts: a declared
endpoint→permission→sensitivity-layer registry (`admin-endpoint-policy-registry.ts`), the
permission definitions with their own layer labels (`admin-permissions.ts`), and the routes
parsed out of source. It checks **both directions** (`:110-120` route→registry, `:122-146`
registry→route), catches a permission mismatch, catches a layer mismatch against the
permission's own policy, and forbids an ops route that is not Layer C.

That bidirectionality is the good idea, and our RBAC assertion already has it in a stronger
form (declared vs *enforced*, on the live table). What theirs adds that ours does not have
is the **sensitivity LAYER** — a second axis saying how dangerous an endpoint is, checked
for consistency against the permission. We have no equivalent, and after consideration we
do not want one: our step-up-confirmation mechanism (`apps/api/core/stepup.py`) already
marks the dangerous mutations, one axis, at the call site. A second classification would be
two ways of saying "this one is dangerous".

Its own defects, for the record: `parseRegistryEntries` (`:10`) is a single regex requiring
the four fields in exactly one order — reorder them and the entry silently vanishes from
the registry, which makes the check *weaker* with no error; `EXEMPT_ADMIN_LAYER_C_ENDPOINTS`
(`:7`) is an empty exemption set that nothing prevents from growing; and `:137` hardcodes
four permission strings as the only legitimate "Layer B" values.

### 1.5 `docs:runtime-drift-check` — same charter as ours, opposite method

`backend/scripts/docs-runtime-drift-check.js:37-80` asserts that specific strings appear in
specific documents: the exact Dockerfile CMD in the TRD, the auth coverage floor formatted
to one decimal place, and roughly a dozen verbatim markdown table rows such as
`'| Catalogue reads (`/products*`, `/reviews/product/*`, `/reviews/recent`) | 300 per minute (route profile) |'`.

The intent is identical to our `check_docs_drift`. The method is the opposite: **they
duplicate the doc's text inside the check**, so the check is a third copy of the same fact
that can itself go stale, and a legitimate reword of a table row fails CI without anything
being wrong. Ours DERIVES the expected value from the live artefact (the Makefile, the
package manifest, `ROADMAP §6`, the capability constants, the nginx template) and compares.

One thing they do that we do not: they pin the **plugin registration ORDER** in `main.ts`
with a single multiline regex (`:76-78`) against the order the TRD documents. Bootstrap
order is load-bearing for us too (BACKEND-PATTERNS names it as locked), and it is worth
knowing this is checkable. It is not worth a check today: our bootstrap order lives in one
function in `apps/api/core/bootstrap.py` and is covered by tests that would fail on a
reorder, whereas theirs is spread across `main.ts` and `app.ts`.

### 1.6 `config:runtime-parity-check` / `env-runtime-contract` — we have both halves already

`config-runtime-parity-check.js:69-106` checks `.env.example` keys against a declared
contract and checks that each compose service either declares `env_file` or lists every
required variable. Ours is `check_env_parity` (root `.env.example` ⟷ `Settings`, both
directions) plus `check_web_env_parity` (the browser tier) plus `check_config_applies` (when
a console-managed change takes effect) plus `check_bootstrap_keys` (the six keys that may
only come from the environment). We are ahead on every axis.

One genuinely nice detail worth noting even though we do not need it: their parser
deliberately accepts **commented stubs** (`# KEY=`) as declarations for keys that are
managed by the ops-config overlay rather than the env file (`:25-45`). We solved the same
problem differently and better — a second `.env.example` inside `apps/web` — precisely
because "a declaration no machine can read" was the failure mode we hit.

### 1.7 `ops:config-contract-proposal` — a tool, not a gate, and worth remembering

`ops-config-contract-proposal.js` (226 lines) generates the diff that adds a new config key
to the example file, the runtime contract and the docs *together*. ENGINEERING-PRACTICES §2
already lists this under "patterns deliberately adopted", and it remains the right idea:
the anti-drift move is making the right way the easy way. It is not a guardrail and does
not belong in the pack; it is a scaffold. Not built here, and not deferred either — our
config surface is currently small enough that `check_env_parity` failing loudly is a
cheaper teacher than a generator.

### 1.8 `deep-endpoint-smoke` — shallower than its name, in the exact place it matters

`backend/scripts/deep-endpoint-smoke.js` enumerates routes with a **regex** over
`*.routes.ts` (`:25`) — a second, weaker route-enumeration mechanism living beside the AST
one in `route-ast-utils.js`, which is their own "one way per problem" violation — fills in
a plausible body per route (`:66-...`), hits every one, and fails only on 5xx (`:313-326`).

The idea is sound and it is the kind of check that would have caught one of the five
already-known auth defects (the reset path that 500s on a deleted account). The
implementation has one flaw that hollows it out:

> `loginAdmin()` requires `process.env.ADMIN_OTP`; without it the function logs
> "skipping admin token acquisition; admin routes will be exercised unauthenticated
> (expect 401/403, not 5xx)" and returns null (`:192-196`).

**CI never sets `ADMIN_OTP`** (`.github/workflows/reliability-ci.yml:225` runs the script
with no such variable). So in the gate that blocks merge, the entire `/api/v1/admin/**`
surface — the largest and most privileged part of the application — is "deep smoke tested"
by confirming it returns 401. The name promises depth exactly where there is none.

Two further softenings: the token is read as `body?.data?.accessToken ?? body?.accessToken
?? null` (`:211`), so an envelope change silently degrades every authenticated probe to an
anonymous one while still exiting 0; and every path parameter is a fixed UUID
(`materializePath`, `:57-64`), so most handlers return 404 before reaching their bodies.

**Rejected for us**, and the reason is not their implementation: FastAPI + Pydantic v2
answers a malformed or absent body with a 422 before a handler runs, so the defect class
this catches is largely pre-empted by the framework. Our `make smoke` (`pytest -m smoke`)
walks the one path that actually matters end to end — tenant → agent → signed webhook →
lead with extraction — and the RBAC boot assertion plus `check_public_routes` now cover the
"is this route reachable" half statically.

### 1.9 `stress:flash-sale` — a real contention harness, neutered in CI

`backend/scripts/flash-sale-contention.js` (533 lines) is the most substantial piece of
engineering in the pack: seeded RNG, four named scenarios (`hot-normal`, `bot-burst`,
`fairness-abuse`, `payment-drop`), a fairness floor, p95/p99 latency ceilings, an API error
rate ceiling, and an oversell invariant.

CI runs it as:

```
FLASH_SALE_ENFORCE_INVARIANTS=false npm run stress:flash-sale:api:matrix
```

(`.github/workflows/reliability-ci.yml:226`). And in the script:

```js
if (enforceInvariants && invariantFailures.length > 0) { ... }
if (enforceInvariants && (report.oversell || (mode === 'api' && report.errorRate > apiErrorRateMax))) { ... }
```

(`flash-sale-contention.js:523,526`). **The harness runs four scenarios against a live
backend, computes oversell and every invariant failure, and then does not act on them,**
because the one environment variable that makes the verdict binding is set to false in the
only place it runs. This is the third independent instance of the pattern (§3.1 and the
deploy teardown's DR finding are the other two).

Our analog exists and is binding: `tests/webhook_storm_test.py` (ENGINEERING-PRACTICES §2's
`stress:webhook-storm`), which asserts rather than reports and cannot be switched off by an
environment variable. That row in §2 said "M2" and now says SHIPPED — corrected in this
change.

### 1.10 `diagnose-notifications` / `diagnose-*` — diagnostics, correctly not gates

`diagnose-notifications.js` (288 lines) probes the notification transport chain and prints.
It is in no CI list, which is right. Our equivalents are `scripts/host_alert.py`,
`scripts/qa_report.py` and the ops console's secret probes
(`apps/api/ops/secret_probes.py`). No gap.

### 1.11 `parity:scorecard` — one command, one table, and evidence that proves nothing

`parity-scorecard.js:29-80` defines seven axes, each with `checks` (files that must exist),
`evidenceCommands` (npm scripts that must be defined) and `evidenceArtifacts` — files whose
presence, the comment says, *"proves that the gate was recently run, not just that the
script file exists"* (`:24-27`).

It does not prove that. `artifacts/` is gitignored (`backend/.gitignore:21`) and is
regenerated inside the same CI job, so an artefact's presence proves only that something
earlier in this run wrote it, and its mtime is minutes old by construction. On a developer
machine it proves the file was written once, at any time in the past. **An evidence check
whose evidence is produced by the run it validates is a tautology** — the same shape as
§3.1 and as the DR finding in the deploy teardown.

The *idea* — one command, one pass/fail table — is already ours as `make guardrails`, and
ENGINEERING-PRACTICES §2 records that. What we should not adopt is the "evidence artifact"
half in this form. Our version of that idea is `check_drill_freshness`, which reads a
COMMITTED evidence file with an expiry, so the artefact outlives the run that produced it
and can therefore go stale — which is the only way an evidence check can bite.

---

## 2. Their exemption lists, as a class

Worth stating separately because it is the single most transferable lesson and it appears
five times:

| Exemption registry | File | Validated against reality? |
|---|---|---|
| `AUTH_ADMIN_EXEMPT_ROUTES` (12 entries) | `route-discipline-check.js:8-29` | No |
| `shouldRequireCustomerPreHandler` prefixes | `route-discipline-check.js:31-41` | No — and default-OPEN |
| `EXEMPT_ENDPOINTS`, `EXEMPT_ADMIN_LAYER_C_ENDPOINTS` | `admin-layer-drift-check.js:6-7` | No |
| `isPublicRoute()` prefixes | `deep-endpoint-smoke.js:44-56` | No |
| `core-purity-allow.txt` | consumed by `check-core-purity.mjs` | No — and see §6 |

Not one of them fails when it stops describing the code. Ours are built the other way and
this teardown reinforced the habit: `UNWIRED_BASELINE` is checked against itself and may
only shrink; `PUBLIC_BY_DESIGN` is verified live; `RAISED_BUDGETS` waivers are deleted the
moment the area improves past them; and both new checks here follow the same rule —
`SPLICE_ALLOWANCES` entries must match a live finding, `UNAUTHENTICATED_ROUTES` entries must
match a live exempt route.

---

## 3. SLOs, burn-rate alerting, and tested Prometheus rules

This was the section the brief expected most from, and it is the section with the most
wrong in it. There are three artefacts: `backend/observability/slo-rules.yml` (recording
rules + alerts), `slo-rules.test.yml` (promtool unit tests), and two scripts.

### 3.1 The error-budget release gate cannot fail

Two scripts, run back to back in `ci:reliability-gates` (`backend/package.json:68`):

- `release-policy-state.js` **writes** `artifacts/reliability/release-policy-state.json`
  (`:140-141`), computing `errorBudgetRemainingPercent` from Prometheus if
  `PROMETHEUS_BASE_URL` is set, and otherwise from `ERROR_BUDGET_CONSUMED_PERCENT ?? '0'`
  (`:11,97`).
- `reliability-release-guard.js` **reads** that file (`:6-22`) and blocks the release on
  freeze, unresolved criticals, or `releaseDecision === 'blocked'` (`:43`).

In CI there is no `PROMETHEUS_BASE_URL`, `mode` defaults to `auto` (`release-policy-state.js:10`),
the live query throws, the `auto` branch swallows it (`:91-98`), and the fallback is
100% budget remaining → `releaseDecision: 'approved'` → the guard passes. `artifacts/` is
gitignored, so the file never carries state from a previous run either.

**The error-budget release gate is, in the only environment where it runs, a script that
writes "approved" to a file and a second script that reads it back.**

There is a second door as well: `hasApprovedException` (`reliability-release-guard.js:24-29`)
lets `RELEASE_EXCEPTION_APPROVED=true` plus any non-empty `RELEASE_EXCEPTION_TICKET` string
bypass the gate. Nothing verifies the ticket exists.

**What we take from this**: the shape (recording rules first, then burn-rate alerts, then a
deploy gate) is correct and is already ENGINEERING-PRACTICES §2's `release:guard` row at
M3+. What we take from the *failure* is a design constraint now written into that row: the
budget figure must come from an artefact the gating run did not produce.

### 3.2 The burn-rate alerts are not burn-rate alerts

`slo-rules.yml:33-53` defines three checkout alerts whose annotations name the canonical
Google SRE multiwindow pairs:

```yaml
- alert: CheckoutErrorBudgetFastBurn
  expr: (1 - slo:checkout_success:ratio_5m) > (14.4 * 0.001)
  for: 5m
  annotations: { summary: "Checkout SLO fast burn (5m/1h)" }
```

The 14.4 / 6 / 1 burn-rate multipliers are right, and the 0.1% error budget is right. **But
every one of the three evaluates the same 5-minute ratio.** There is no 1h window, no 6h
window and no 3d window anywhere in the file; the second window of each pair — the one that
makes a multiwindow alert reset promptly and resist a single bad scrape — does not exist.

The consequence is worst for the ticket alert: `for: 6h` on a 5-minute ratio requires the
5-minute error rate to stay above 0.1% *continuously for six hours*. One scrape below
threshold resets the timer to zero. That is a strictly different and far stricter condition
than "6-hour burn rate above 1", and in practice `CheckoutErrorBudgetTicket` will
essentially never fire. The annotation says it is watching a 3-day budget; it is watching a
5-minute ratio with a 6-hour patience.

### 3.3 `clamp_min(denominator, 1)` pages continuously on a low-traffic store

Three recording rules divide by `clamp_min(sum(rate(...)), 1)`
(`slo-rules.yml:5,15,19`). Clamping the DENOMINATOR to a minimum of **1 request per
second** does not prevent a divide-by-zero (an absent series already yields an empty
vector); it rewrites the ratio whenever real traffic is below 1 req/s.

Work it through. A store doing 100 checkouts a day is 0.00116 req/s. The numerator is
0.00116, the denominator is clamped to 1, so `slo:checkout_success:ratio_5m` records
0.00116, and `1 - ratio` is **0.9988** — three orders of magnitude above the fast-burn
threshold of 0.0144. Held for 5 minutes, `severity: page`.

**Any nonzero checkout traffic below one per second pages, permanently, with the system
perfectly healthy.** For this business that is every day. The same clamp sits on the
auth-challenge ratio and the queue terminal-failure ratio.

### 3.4 The promtool tests are real, and their fixtures hide the bug in 3.3

`npm run test:slo-rules` (`promtool-test-rules.js`) does run `promtool test rules` in CI,
and CI provisions promtool deterministically with a gzip integrity check
(`reliability-ci.yml:138-153`). That is better than most projects manage, and the tests do
assert real alert firing (`slo-rules.test.yml:13-34`).

They cannot see §3.3 because **every input series in the test file is high-rate**: the
healthy case is `'0+100x30'` at a 1-minute interval — 100 checkouts per minute, ≈1.67
req/s, comfortably above the clamp (`slo-rules.test.yml:9-19`). The test data is shaped
like a load test, and the production traffic is shaped like a small store. The bug lives
exactly in the gap.

This is the most instructive finding in the document, because the gate here is *good*: the
rules are unit-tested, in CI, with a real tool. **A tested rule is only as good as the
regime its fixtures cover**, and "one order of magnitude below the smallest tested rate" is
a regime nobody wrote a fixture for.

### 3.5 The local fallback silently downgrades to a substring check

`promtool-test-rules.js:25-57`: if the promtool binary is absent and `CI !== 'true'`, the
script "validates" by checking that `slo-rules.test.yml` contains the strings
`rule_files:`, `tests:`, `eval_time:`, `alertname:` and `exp_alerts:`, warns, and **exits
0**. It never opens `slo-rules.yml` at all. A developer could delete every rule and this
passes locally with a green tick. The CI branch is correct; the local one manufactures
confidence in the loop where people actually work.

### 3.6 `simulate:burnrate` is a print statement

`slo-burnrate-simulate.js:5-15` re-declares the thresholds as JavaScript constants
(`14.4 * 0.001`, `6 * 0.001`, `1 * 0.001`) rather than reading them from `slo-rules.yml`,
runs three hardcoded scenarios, prints, and always exits 0. It can agree with itself
perfectly while the rules file says something else, and it has no verdict to give. It is
correctly absent from `ci:reliability-gates`.

### 3.7 What we have, and what we are not building yet

We have SLOs as prose (`docs/OPERATIONS.md:380-383`: lead visible ≤ 2 min at 99%, webhook
ack < 500ms, dashboard p95 < 800ms, voice p50 ≤ 1.1s, 99.5% monthly voice-runtime
availability), OTel and Sentry, and one of those numbers exists as a constant
(`apps/voice-runtime/webhook_routes.py:132`, `_ACK_BUDGET_MS = 500.0`). We have **no
Prometheus, no recording rules and no alert rules**, and `docs/OPERATIONS.md:385-404`
already carries the operational reasoning that would go into them (D-55's capacity-vs-bug
triage for `webhook_ack_slow`).

Building the rules file now would be a half-wired feature: a YAML document nothing scrapes,
alerting nobody, drifting from the code from day one. ENGINEERING-PRACTICES §2 already
scheduled this at M3+ with "needs Prometheus" as the condition, and that condition is
correct and unchanged. What this teardown adds is a **paragraph of design constraints** in
that row, so whoever builds it inherits the evidence rather than repeating the arithmetic:
two windows per burn-rate alert, no `clamp_min` on the denominator, promtool fixtures at
production-shaped rates, and a budget figure the gating run did not write.

---

## 4. Module and API discipline vs `docs/BACKEND-PATTERNS.md`

Their `backend/src/modules/` holds 24 modules with a consistent anatomy —
`X.routes.ts` / `X.service.ts` / `X.types.ts` / `X.schema.ts` plus colocated `.test.ts`,
`.e2e.test.ts`, `.security.test.ts` — and `backend/src/common/` holds the cross-cutting
machinery (`idempotency/`, `reliability/`, `security/`, `observability/`, `guards/`,
`rate-limit/`). The shape is the shape BACKEND-PATTERNS describes. Four specific
comparisons:

### 4.1 Idempotency — same design, one dangerous scope fallback

`backend/src/common/idempotency/idempotency.ts` keys on
`(scopeKey, route, method, idempotencyKey)` with a request-body hash and a 24-hour TTL
(`:9,70-77`), stored in Postgres with a `PROCESSING | FAILED | COMPLETED` state. That is the
standard and it matches our reliability triad.

The scope key is where it goes wrong (`:24-38`):

```js
if (request.user?.sub)  return `user:${fingerprint(request.user.sub)}`;
if (cartCookie)         return `cart:${fingerprint(cartCookie)}`;
return `anon:${fingerprint(request.ip)}`;
```

For an unauthenticated caller with no cart cookie, the idempotency scope is the **client
IP** — and behind nginx or a CDN, `request.ip` is our own edge unless `trustProxy` is
configured correctly. They do configure it (`backend/src/main.ts:55,90`), so this is a
conditional defect rather than a live one; but the failure mode if that configuration is
ever wrong is not a bad log field, it is **user A receiving user B's cached response** for
the same route and key.

This is precisely the defect class our `check_audit_ip` exists for — eighty of our handlers
once read the socket peer inline, which behind nginx is our own edge — and it is worth
recording that the same mistake, in a place where the consequence is response replay rather
than a wrong audit column, is one config flag away in a repo that had already thought about
it.

### 4.2 Error envelope — theirs wraps, ours is RFC-9457

Their client parses `{ success, data }` on success and `{ error: { code, message, details } }`
on failure (`frontend/lib/api.ts:59-80`). Ours is `problem+json` per RFC 9457, which is the
published standard and generates cleanly into the typed client. No change; noted only
because §5's port needs the difference stated: **their `ApiError.code` string maps to our
`type`/`code` member of the problem document, and every error-handling branch in §5 must be
re-keyed accordingly.**

### 4.3 Serializers — a genuine idea we already have twice

`orders.service.ts` routes every response through `serializeOrder(...)` and
`fingerprintIdentifier(...)` with an `exposeProviderReferences` flag
(`serializer-exposure-check.js:11`). One function decides what leaves; a flag decides
whether provider references are visible. We do the same thing with response models plus
`check_redaction_exposure` plus `tests/crm_egress_redaction_test.py` (which asserts against
the actual BYTES on four egress paths, including the CSV and the signed webhook body).
Ahead; no action.

### 4.4 CAS / concurrency — theirs is real, and our doctrine already says so

`PAYMENT_FLOW_REDESIGN.md:217` claims "Race condition handling: CAS pattern prevents double
capture", and the inbox/ledger reasoning in their order path is sound in outline. Our
BACKEND-PATTERNS CAS doctrine covers the same ground and our append-only ledgers are
enforced by a DB trigger plus `check_ledger_immutability`, which is a stronger statement
than a code convention. No gap.

---

## 5. The frontend auth surface — the specification for what we build next

**This is the section to build against.** We own authentication end to end — the
first-party auth module is designed and lands in a parallel slice (Clerk is still the live
authenticator on this branch, `apps/api/core/auth.py`) — and we have NO screens: no login,
no reset, no OTP entry, no invite acceptance, no session handling. Their implementation is ~3,200 lines of React across
`stores/`, `lib/`, `hooks/`, `contexts/` and `components/auth|admin|ops`, on Next.js App
Router with Zustand, react-hook-form and zod — the same stack we use. It ports more
directly than anything else in the repository, **and it must not be ported uncritically**:
§5.7 lists nine defects in it, two of them serious.

### 5.1 The session model, in one paragraph

**Access token in memory, refresh token in an httpOnly cookie.** The access token lives in
a Zustand store (`frontend/stores/auth.ts:25-63`) and is never written to
`localStorage`/`sessionStorage`. The refresh token is a cookie the browser sends on
`POST /auth/refresh` with `credentials: "include"`. On mount, the app attempts a **cookie
restore**: refresh → new access token → optional profile hydrate. That is the correct
modern shape (an XSS cannot read the refresh token; a page reload does not log you out),
and it is the shape we should build.

### 5.2 The single-flight refresh — the most valuable idea here

`frontend/lib/restore-auth-session.ts:33-71`. Refresh tokens are single-use and rotated, so
two concurrent `POST /auth/refresh` calls send the *same* cookie: the first rotates it, the
second is told "already consumed", and the app hard-logs-out. Their comment records this as
the live bug it fixed — *"randomly logged out mid-session on desktop"* — caused by admin
pages bursting parallel GETs that all 401 together the moment the access token expires.

The fix has two parts and both are needed:

1. an **in-flight promise** (`refreshInFlight`) so concurrent callers await one network
   refresh;
2. a **3-second result cache** (`recentRefresh`, `REFRESH_RESULT_CACHE_MS = 3_000`) so a
   React Strict Mode remount immediately after a completed refresh does not rotate again.

Everything that can refresh must funnel through it — both the session restore and the API
client's 401 retry (`frontend/lib/authenticated-api.ts:43`). **Build this before building
any screen.** It is invisible until it is missing, and when it is missing the symptom is
"users get logged out at random", which is nearly impossible to diagnose from a report.

### 5.3 The API client's 401 retry ladder

`frontend/lib/authenticated-api.ts:18-76`, and the shape is right:

1. call with the current access token;
2. on `ApiError`, if `shouldAttemptTokenRefresh(error)` — 401 with code `TOKEN_EXPIRED` or
   `UNAUTHORISED` (`lib/error-messages.ts:399-404`) — and this is not already a retry:
   refresh once through the single-flight, store the new token, retry the request once with
   `_retryAfterRefresh: true`;
3. if the refresh itself fails: `onAuthFailure()` and rethrow;
4. **429 on an idempotent GET** gets one delayed retry (1200ms, `_retriedAfterRateLimit`) —
   because rapidly switching admin sections bursts past a per-minute limit and a single
   pause turns a "Something went wrong" flash into a barely-noticeable delay;
5. `shouldForceLogin(error)` or a 401 that survived the retry ⇒ `onAuthFailure()`.

`shouldForceLogin` (`lib/error-messages.ts:406-419`) carries the distinction that matters
and that is easy to get wrong: **a wrong password or wrong OTP is a 401 that must NOT clear
an otherwise valid session.** `INVALID_CREDENTIALS` is explicitly excluded. Getting this
wrong means an admin who fat-fingers a step-up confirmation is thrown out of the console.

For us, translate the code checks to our RFC-9457 problem `code` values, and keep the
retry-count guards as separate private option flags exactly as they are — one flag per
retry reason, so a refresh retry and a rate-limit retry cannot cancel each other.

### 5.4 Restore-on-mount, with a deadline and a soft-vs-hard failure distinction

`frontend/hooks/use-auth-session-restore.ts` is the piece with the most hard-won behaviour
in it, and most of it should survive the port:

- **Audiences.** `"admin" | "admin-guest" | "customer"` (`:23`), each with its own
  `blocked` flag and in-flight promise (`:72-79`). `admin-guest` exists so the sign-in page
  does not share a blocked state with the protected console — without it, a failed restore
  on `/admin` leaves `/admin/login` permanently convinced restore is impossible. **We need
  the same split**, and ours is three-way in a different sense: admin realm, client realm,
  and the guest pages of each.
- **A 15-second deadline** (`RESTORE_DEADLINE_MS`, `:67`) with a comment recording that an
  8-second cap "spuriously logged out valid sessions on 3G/weak links" — the exact "works
  on desktop, drops on mobile" report. Keep the number and the reasoning.
- **Timeout is a SOFT failure.** `{ ok: false, reason: "timeout" }` leaves `blocked` false
  and does not clear the session, so a remount or navigation retries; only `unauthorised` /
  `invalid_token` set `blocked` and clear (`:210-228`). This distinction is the difference
  between a slow network and a logged-out user, and collapsing them is how a valid session
  gets stranded.
- **A generation counter** (`restoreGeneration`, `:70`) so an in-flight restore that
  resolves after a fresh login cannot clear the new session. This is the kind of thing
  nobody writes until it bites.
- **Sparse-user fallback.** `buildUserFromAccessToken` (`lib/restore-auth-session.ts:15-31`)
  builds a minimal user from JWT claims when `GET /users/me` is unreachable, so the admin
  shell renders on claims alone (`hydrateProfile: false` for admin audiences, `:90`).

### 5.5 Guards, gates and the loading states

Four layers, and the layering is deliberate:

| Component | File | Role |
|---|---|---|
| `AdminAuthProvider` | `contexts/admin-auth-context.tsx:33-107` | Runs restore, resolves the admin user, renders a gate while checking, provides context |
| `AdminGuard` | `components/auth/AdminGuard.tsx:17-67` | Per-subtree guard; also checks `canAccessAdmin(user)` |
| `AdminSessionRestoreGate` | `components/auth/AdminSessionRestoreGate.tsx` | The visible "Restoring admin session…" block, with an optional auto-redirect on timeout |
| `AdminGuestOnly` | `components/auth/AdminGuestOnly.tsx` | The inverse — bounces an already-signed-in admin off `/admin/login` |

Two details worth copying:

- **A watchdog** (`ADMIN_RESTORE_WATCHDOG_MS = 12_000`,
  `contexts/admin-auth-context.tsx:22,54-64`) that redirects to sign-in if the app is still
  "checking" or "restoring" after 12 seconds — because the page may already be a 200 from
  RSC and a spinner that never resolves is the worst possible state. Its comment notes it
  **redirects only** and deliberately does not call `logoutLocalSession()`, which would bump
  the restore nonce and restart a cookie refresh while navigation is in flight (a mobile
  redirect loop they hit).
- **Hard navigation, not soft.** `redirectToAdminLogin()` uses `window.location.assign`
  (`lib/admin-auth-navigation.ts:11-16`) because `router.replace` can stall when leaving the
  `/admin` route group, and `redirectToAdminLoginIfNeeded()` refuses to redirect when already
  on a guest path (`:19-27`) — the reload-loop guard.

### 5.6 The forms

- **`AdminLoginForm`** (`components/auth/AdminLoginForm.tsx`, 437 lines) — two steps,
  `"credentials" | "otp"`. Step 1 posts email+password and receives `{ expiresAt }`; step 2
  posts email+OTP and receives `{ accessToken, admin }`. Between them: a 60-second resend
  cooldown, a live OTP expiry countdown driven by the server's `expiresAt`, a Turnstile
  widget remounted by key on every step change and every resend (tokens are single-use), a
  "Use different email" back link, and a submit button disabled until
  `isCompleteOtpCode(otp)`.
- **`ForgotPasswordForm` / `ResetPasswordForm`** (92 / 98 lines) — both send an
  **idempotency key** (`lib/auth-api.ts:162-184`), which is right: a double-submitted reset
  request must not send two emails or consume two tokens. On success the reset form clears
  the local session and navigates to `/login?reset=success` after a 2s message
  (`ResetPasswordForm.tsx:30-43`).
- **`AdminIdleTimeoutModal`** (`components/auth/AdminIdleTimeoutModal.tsx`) — 25 minutes to
  warning, 5 more to logout (`:13-15`), driven by `useIdleTimeout`
  (`hooks/use-idle-timeout.ts`), which listens to seven passive activity events and
  reschedules two `setTimeout`s. "Stay Signed In" refreshes through the single-flight and
  **re-checks the role claim on the new token** before accepting it (`:47-55`). An
  `alertdialog` with `aria-modal`, labelled and described. **This is the piece our admin
  realm needs and does not have** — SEC-COMP's admin-session posture wants an idle bound,
  and this is a good implementation of it.

### 5.7 What is WRONG in it — do not port these

1. **The restore deadline leaks a timer that breaks the single-flight it depends on.**
   `runRestoreWithDeadline` (`hooks/use-auth-session-restore.ts:93-105`) races the restore
   against a `setTimeout` that is **never cleared**. When the restore wins, the timer still
   fires 15 seconds later and calls `resetAuthSessionRestoreCache()`, which sets
   `refreshInFlight = null` (`lib/restore-auth-session.ts:116-119`). If a *different*
   refresh is in flight at that instant, the single-flight invariant is broken and two
   callers can send the same single-use cookie — **which is the exact bug §5.2 exists to
   prevent, reintroduced by the timeout added to fix a different one.** Clear the timer in a
   `finally`.
2. **A user-enumeration oracle at the admin login, documented as a feature.**
   `lib/admin-auth-api.ts:53-59` states the contract: `401 INVALID_CREDENTIALS` for a known
   admin with a wrong password, `401 UNAUTHORISED` for a deactivated admin, and a **200 with
   a generic message** for an unknown email. An unauthenticated caller therefore learns
   whether an address is a live admin, a deactivated admin, or nothing. This is the same
   defect class as the already-known `/api/v1/auth/check-identifier` oracle, at the more
   sensitive endpoint, and the UI amplifies it by rendering three distinct messages
   (`AdminLoginForm.tsx:196-208`). **Our login must return one answer and one timing profile
   for every unknown-account case.**
3. **Two dev OTP bypasses whose only guard is an environment variable.** The login response
   carries `devOtp` and the form auto-fills it (`lib/admin-auth-api.ts:63`,
   `AdminLoginForm.tsx:101-112,359-370`), and separately the backend writes the plaintext
   OTP to Redis at `auth:admin:login-otp:ci-plaintext:<sha256(email)>` for
   `admin-contract-check.js` to read (`scripts/admin-contract-check.js:40`). Both are gated
   on `NODE_ENV !== 'production'` alone. Combined with the already-known 6-digit OTP under
   unsalted SHA-256, that is three independent ways to hold a live admin's second factor.
   **We must never put a credential in a response field, whatever the flag.**
4. **Duplicated countdown intervals.** `startOtpCountdown` (`AdminLoginForm.tsx:161-176`)
   creates a `setInterval` that is only cleared when it reaches zero, and resend calls it
   again (`:227`) while the previous OTP's interval is still running. Two intervals both
   decrement `otpRemainingSec`, so after a resend the displayed expiry ticks down at double
   speed. Neither interval is cleared on unmount, so both keep setting state on an unmounted
   component. Use one `useEffect` with a cleanup, keyed on `expiresAt`.
5. **The password is held in form state across the OTP step and re-sent on resend.**
   `handleResendOtp` reads it back out of the form (`AdminLoginForm.tsx:218-222`). It works,
   but it keeps a plaintext password in a React field for the whole OTP window. A
   server-issued short-lived challenge id is the standard alternative and is what we should
   issue.
6. **Timing-unsafe credential comparison on the ops console.**
   `lib/ops-ui-auth.ts:63-66` compares the basic-auth username and password with `===`.
   Use a constant-time comparison; on our side this surface does not exist in the same form,
   but the ops console is the highest-value target we have and the lesson stands.
7. **The client trusts unverified JWT claims for authorization UI.**
   `lib/jwt-utils.ts:8-21` base64-decodes the payload with no signature check (correct and
   unavoidable in a browser), and `buildUserFromAccessToken` then sets `isVerified: true`
   unconditionally (`lib/restore-auth-session.ts:27`) while `hasPermission` grants
   everything on a `"*"` entry (`stores/auth.ts:59-62`). That is fine for *rendering* and
   catastrophic if any of it is ever mistaken for enforcement. Our rule: client claims decide
   what is **shown**, never what is **allowed**, and the server answer is authoritative —
   the same fail-closed/fail-visible doctrine `make web-check` already tests for.
8. **The frontend advertises a password length the backend truncates.**
   `lib/validators.ts:21-24` accepts up to 128 characters; the already-known bcrypt defect
   silently truncates at 72 bytes. The client half of a known defect, and a reminder that a
   validator which is more permissive than the hasher is a security bug rather than a
   cosmetic mismatch.
9. **`OpsSessionGate` renders `error ?? "Sign in to continue."` for every failure**
   (`components/ops/OpsSessionGate.tsx:61-70`), so a transient network failure and an
   expired session look identical to the operator. Distinguish them; "we could not reach the
   server" and "you are signed out" have different remedies.

### 5.8 The build order for our screens

Derived from the above, and stated as an order because the dependencies are real:

1. `lib/auth/session.ts` — the single-flight refresh + result cache (§5.2). Nothing else
   works without it, and adding it later means rewriting every caller.
2. `lib/auth/client.ts` — the 401/429 retry ladder (§5.3), keyed on our problem-document
   codes, with `INVALID_CREDENTIALS` excluded from force-logout.
3. `hooks/use-session-restore.ts` — audiences, the 15s deadline, soft-vs-hard failure, the
   generation counter (§5.4).
4. The provider + guard + gate + guest-only quartet per realm (§5.5), with the watchdog and
   hard navigation.
5. The forms (§5.6), in the order the flows need them: login → OTP → invite acceptance →
   forgot/reset. Idempotency keys on forgot and reset from the first commit.
6. The idle-timeout modal for the admin realm (§5.6).

Every behavioural rule in §5.3–§5.5 is exactly the kind `tsc` cannot see and `make
web-check` was built for (D-53): fail-closed vs fail-visible, verdicts keyed on the server's
computed answer, a soft failure that must not clear a session. **Each one needs a vitest
case, and the nine items in §5.7 should each become a test asserting the opposite.**

---

## 6. Core-sync / template versioning — reaffirmed as not ours, plus one defect

`core-manifest.json`, `core-purity-allow.txt`, `core-purity-denylist.txt`,
`scripts/sync-core.mjs`, `PLATFORM_VERSION`, and the `core-drift.yml` / `core-sync.yml` /
`release-train.yml` workflows implement a template-repo→client-repo model: paths are
declared CORE (synced from a pinned template tag) or CLIENT (allowed to differ),
`PLATFORM_VERSION` pins `backend-core: 0.1.99` / `frontend-core: 0.1.70` with a
`requires-backend-core` compatibility floor and an `approved-divergence` list carrying
per-entry justification, owner and expiry.

It is a well-thought-out answer to a problem we do not have. ENGINEERING-PRACTICES §2
already records this under "explicitly NOT adopted" — Calevate is ONE multi-tenant product,
not a repo per client — and this read confirms it rather than changing it. The one thing
worth keeping is the **`approved-divergence` shape**: path, justification, owner, expiry.
That is the same discipline as our `RAISED_BUDGETS` waivers and our `DEFERRED_MIRRORS`, and
it is a good pattern independent of the machinery around it.

**The defect, because it is the §2 lesson again:** `check-core-purity.mjs:30-44` exits **0**
with `"core-purity-denylist.txt not found — skipping purity check"` when its input file is
missing, and exits 0 again with `"denylist empty — nothing to check"` when it is present but
empty. The guard that stops one client's brand and keys overwriting another's is disabled by
deleting one untracked-looking text file, and CI stays green. Our equivalent posture is the
opposite by construction and now has a third instance of it: `check_raw_sql` exits **2** if
it finds no `text()` statements, `check_public_routes` raises if it finds no exempt routes,
and `check_coverage_ratchet` refuses to score a run it cannot vouch for.

---

## 7. Payments — we are ahead, and their redesign moved backwards

`PAYMENT_FLOW_REDESIGN.md` describes replacing "order created in `PENDING_PAYMENT` → pay →
mark `CONFIRMED`" with "prepare a checkout session → pay → create a `CONFIRMED` order
atomically". The stated goals are reasonable (no orphaned `PENDING_PAYMENT` rows in the
customer's order list) and the atomic creation is genuinely nicer.

**The in-flight checkout has no durable record.** `prepareCheckout`
(`backend/src/modules/orders/orders.service.ts:1508-1673`) creates the Razorpay order, then
writes the entire checkout — cart contents, prices, coupon, shipping address, chosen courier
— to **Redis, with a 30-minute TTL**:

```js
await this.fastify.redis.set(sessionId, JSON.stringify(sessionData), 'EX', 1800);
```

`confirmPrepaid` reads that key and, if it is gone, throws:

> `'Checkout session expired or not found. Please restart checkout.'` — a 404
> (`orders.service.ts:1678-1681`).

So: the customer pays at Razorpay; their browser dies, or the network drops, or they take
more than thirty minutes, or Redis restarts without persistence. **The money is captured and
there is no order, no payment row, and nothing to reconcile from**, because the only record
of what was being bought was the Redis key. The customer is told to "restart checkout" after
paying. There is a `POST /api/v1/payments/webhook`, but nothing in the redesign document or
the flow makes it capable of constructing an order — it has no session to read either.

The document's "Known Limitations" (`PAYMENT_FLOW_REDESIGN.md:230-237`) lists Shiprocket
auto-booking and email delay. It does not list this. Its "Security Considerations" section
(`:210-218`) lists *"Session storage: Checkout session stored in Redis (30-min TTL)"* as the
first security feature.

**Ours (D-98) is the other design and stays that way**: server-side order creation with a
durable Postgres record before the provider is called, an inbox-claimed webhook, and a
credit ledger row as the permanent fact. `apps/api/billing/payment_routes.py:395-435` puts
the signature check before any parse and fails CLOSED when the webhook secret is unset,
because "an unverifiable payment feed credits wallets on anyone's say-so". The rule this
teardown confirms, and which is now worth stating out loud: **no state that a payment
depends on may live only in Redis.** Redis is a cache and a queue here; it is not where a
₹5,500 obligation is recorded.

---

## 8. Things the brief did not anticipate

1. **The self-validating-gate pattern is systemic, not incidental.** Four instances now:
   the DR evidence generator and its validator in one job (deploy teardown); the
   error-budget state file written and read by consecutive CI steps (§3.1); the contention
   harness run with `FLASH_SALE_ENFORCE_INVARIANTS=false` (§1.9); and `parity:scorecard`
   treating same-run artefacts as proof the gate ran (§1.11). **Any check we write must be
   able to name what would make it fail, and that thing must not be produced by the run.**
2. **`ci:reliability-gates` is one 23-command `&&` chain** (`backend/package.json:68`). The
   first failure stops the rest, so a red build reports one problem and hides twenty-two.
   Ours is separate CI steps with `if: ${{ !cancelled() }}` on each, which is why our red
   builds report every guardrail at once. Worth keeping deliberately — it is a small thing
   that changes how many round trips a fix takes.
3. **Two independent route enumerators.** `route-ast-utils.js` (TypeScript AST, correct) and
   `deep-endpoint-smoke.js:25` (regex, weaker) both answer "what routes exist", and they can
   disagree without anything noticing. This is the "one way per problem" defect in its
   purest form, and it is a good argument for our habit of deriving from a live registry.
4. **`edge-policy-drift-check.js` reads a value and discards it.** It parses
   `appLimitPerMinute` out of the edge policy (`:20-22`) and never compares it to anything.
   The whole point of having both an app-level and an edge-level rate limit is the relation
   between them — if the app limit is above the edge limit the app's limiter is dead code;
   if far below, the edge never protects anything. The check compares the edge rate and
   burst to nginx and leaves the interesting question unasked. It is also one-directional
   (an nginx zone with no edge rule is not flagged), and its rule parser
   (`/(\w+)\s*:\s*\{([\s\S]*?)\}/g`) is a non-greedy brace match that silently yields fewer
   rules when an entry nests an object — under-coverage with a green tick, again.
   **Our `check_docs_drift` clause 4 does the nginx half properly and its deferral has
   already fired and closed**; `infra/nginx/rate-zones.conf.template` exists and
   `DEFERRED_MIRRORS` is empty. ENGINEERING-PRACTICES §2 still described that clause as
   deferred, which was stale — corrected in this change, and it is the same defect class the
   check itself exists for.
5. **`frontend/design-tokens.contract.json`** exists and is checked by a theme-boundary
   script (`core-manifest.json`'s frontendCore comment names
   `frontend/scripts/check-theme-boundary.mjs`: *"engine code must NEVER import a theme
   file"*). That is a real idea — an import-direction rule enforced in the frontend — and it
   is the frontend analogue of our `lint-imports` contracts. We have no theme/engine split
   and one product, so there is no boundary to enforce; noted as the reference if a
   white-label tier ever un-defers.

---

## 9. Prioritised: mechanism → what it catches → do we have it → is it worth building

| # | Mechanism | What it catches | Do we have it | Worth it? | Depends on |
|---|---|---|---|---|---|
| 1 | **Raw-SQL literal-only rule with call-site resolution** (`security:sql-injection-guard`, rebuilt) | A runtime value spliced into SQL. In our tree that is cross-tenant, not per-account, because the app role is `NOBYPASSRLS` and `tenant_id` is a session GUC | **No** — 493 `text()` sites, two documented-but-unenforced premises | **BUILT — D-172** | Nothing. Syntax-decidable, no DB, no app boot, 2.5s |
| 2 | **Enumerated unauthenticated surface** (their `AUTH_ADMIN_EXEMPT_ROUTES` flaw, inverted) | A route mounted under a public prefix that nobody declared — about to matter a great deal as `/v1/auth/` grows into the whole auth module | **No** — `PUBLIC_PREFIXES` is default-open and unvalidated | **BUILT — D-173** | App boots (same as `check_openapi_fresh`) |
| 3 | Multiwindow burn-rate alerts + promtool-tested rules + error-budget deploy gate | Sustained SLO burn; a release shipped into a burned budget | No — SLOs are prose in OPERATIONS §5 | **Yes, at M3+** — the shape is right, the arithmetic in theirs is not (§3.2–§3.6) | **Prometheus.** Not ours to code around: a rules file nothing scrapes is a half-wired feature |
| 4 | Endpoint 5xx smoke over every route | A handler that crashes on an absent/edge resource | Partially — `make smoke` walks the one critical path | **No.** FastAPI answers 422 before the handler; theirs is also blind on the whole admin surface (§1.8) | — |
| 5 | Serializer exposure by named tokens | A service returning a raw model | **Yes, stronger** — `check_redaction_exposure` walks the live OpenAPI transitively | **No** — two mechanisms, one question | — |
| 6 | Route auth/permission discipline | An unguarded or mislabelled route | **Yes, stronger** — `assert_policy_registry_complete` at boot on the live table | **No** — but its blind spot became #2 | — |
| 7 | Admin sensitivity LAYER registry | A dangerous endpoint classified inconsistently | No | **No** — `core/stepup.py` already marks dangerous mutations on one axis | — |
| 8 | Config/env parity, compose pass-through | A key declared and not read, or read and not declared | **Yes, four ways** — `check_env_parity`, `check_web_env_parity`, `check_config_applies`, `check_bootstrap_keys` | **No** | — |
| 9 | Docs↔runtime drift | A doc stating a value the code does not have | **Yes, better** — ours derives, theirs duplicates the doc text into the check | **No** | — |
| 10 | Contention/oversell stress harness | Lost updates under concurrency | **Yes** — `tests/webhook_storm_test.py`, and ours cannot be switched off by an env var (§1.9) | **No** | — |
| 11 | Coverage ratchet | Test coverage silently regressing | **Yes, far stronger** — per-hard-rule-surface uncovered COUNTS, equality gate, derived area list, refusal-to-score | **No** | — |
| 12 | core-sync / core-purity / release-train | One client's core drifting from the template | N/A — one product | **No** (ENGINEERING-PRACTICES §2 already says so; §6 adds the defect) | A white-label tier un-deferring |
| 13 | Config contract-proposal generator | A new config key added to one file of three | No | **No, not yet** — a scaffold, not a gate; `check_env_parity` failing loudly is the cheaper teacher at this size | — |
| 14 | Evidence-artifact freshness in a scorecard | A gate that has not been run recently | **Yes, correctly** — `check_drill_freshness` reads a COMMITTED artefact with an expiry | **No** — theirs reads same-run output, which proves nothing (§1.11) | — |
| 15 | Theme/engine import-direction rule | Engine code importing a per-client theme | N/A — `lint-imports` covers our real boundary | **No** | A white-label tier un-deferring |
| 16 | **The frontend auth surface** (§5) | — | **No screens at all** | **Yes — it is the next slice**, and §5.8 is the build order. Nine defects in §5.7 must each become a test asserting the opposite | The first-party auth cutover; not a guardrail |

---

## 10. What changed in this repository as a result

- `scripts/check_raw_sql.py` + `tests/raw_sql_guard_test.py` — **D-172**. In `make
  guardrails` and CI.
- `scripts/check_public_routes.py` + `tests/public_routes_guard_test.py` — **D-173**. In
  `make guardrails` and CI.
- `docs/ENGINEERING-PRACTICES.md` §2 — two new rows; `stress:webhook-storm` marked SHIPPED;
  the `release:guard` row gained the design constraints from §3; the "explicitly NOT
  adopted" list gained five entries with reasons; and the stale claim that
  `check:docs-drift` clause 4 is deferred was corrected — the nginx template landed, the
  deferral fired as designed, and the comparison is live.
- `docs/ROADMAP.md` §6 — D-172 and D-173.

Nothing in `apps/web` was touched: §5 is the specification for that slice, not the code.
No migration was written. Nothing in `infra/` was changed, and nothing in `infra/` has ever
been applied to a host.
