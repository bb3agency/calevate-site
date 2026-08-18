# Step-up: closing the two gaps D-198 left as decisions (D-210, D-211)

**Why this pass exists.** `docs/evidence/deepdive-authn.md` §"Step-up (D-178) — the gate is
whole" found the gate itself sound and then named two things it deliberately did NOT do,
because both were founder's calls rather than defects:

1. `POST /v1/admin/impersonation-grants` — the single choke point into a client's data —
   took no step-up, while every other high-consequence admin action does.
2. `docs/BACKEND-PATTERNS.md` §7 listed raw-transcript access as a step-up action while the
   client realm has no second factor at all, which is a conflict between two documents.

This pass takes both decisions, implements them, and records the arguments. It also fixes
the seam both of them sit on and which neither could have been useful without: **the
operator console had no step-up prompt of any kind**, so the fifteen routes that already
took the gate were reachable only inside the five minutes after a sign-in.

**Marking.** Every claim below is **PROVEN** (executed, and the result quoted) or
**REASONED** (read, not run).

**Fence.** `apps/api/core/stepup.py`, `apps/api/authn/stepup.py`, the `apps/api/admin/`
impersonation paths, `docs/BACKEND-PATTERNS.md` §7 and the docs that describe step-up,
`apps/web/src/**` only where the prompt had to be surfaced, and tests for the above.

**Environment.** `calevate_replay` on 5433, verified at head. Every test below was run
against it. `APP_ENV=local` with no `PLATFORM_KEK`, which matters and is discussed under
"what a `dev:` token can and cannot test".

---

## Gap 1 — the impersonation door (D-210)

### What was true before

`mint_impersonation_grant` authenticated the operator, checked `admin:impersonate`, refused
a chained mint from inside another account, resolved the slug, minted, and audited. Nothing
asked whether the person at the keyboard was still the operator who signed in.

That matters more here than on most routes, and the reason is structural rather than a
judgement about sensitivity:

- `core/auth.py::_load_admin_principal` refuses **every** impersonated request without a
  grant, and grants exist **only** at this endpoint. So this is not one of several ways into
  a tenant; it is the way.
- BACKEND-PATTERNS §7 names raw-transcript access a step-up action. The route that serves it
  is `GET /v1/calls/{call_id}/transcript/raw` in `apps/api/crm/routes.py`, on the **client**
  realm. A `superadmin` in a view-as session reaches it — `superadmin` is the only admin role
  holding `calls:read_raw` (`core/rbac.ROLE_PERMISSIONS`; `operator` does not) — with role +
  audit and, before this change, no freshness check anywhere on the path.

### The decision

Take the full gate on the mint. `step_up: StepUpGate` + `X-Confirm-Action:
view_as:<slug>`, `view_as_confirmation()` next to the route with its siblings.

**This is the 16th `step_up.require` call site and the first that guards a DOOR rather than
a mutation.** `tests/authn_stepup_test.py`'s census now expects 16 and says why the verb is
not the criterion.

**It does not gate a read on a mutating permission.** D-22 forbids that; `admin:impersonate`
stays out of `MUTATING_PERMISSIONS` and a view-as session still buys nothing but reads.
Step-up asks who is at the keyboard, not what they may do.

### The part that needed an argument: an OTP every fourteen minutes

`REAUTH_MAX_AGE` is 5 minutes. `GRANT_TTL` is 15, and the console re-mints 60 s before
expiry. So the naive shape — demand a fresh factor on every mint — challenges an operator
roughly **every fourteen minutes** for as long as they stay in a client's account, doing
read-only support work.

`apps/api/authn/stepup.py` already names that failure mode in its own words, about this very
control: gating something on a flow that does not work is "a control that gets switched
off". A support session is precisely the workflow it would be switched off for.

**The shape used instead is the established one, not an invention.** For "assume authority
into another account's data", the industry converged on: prove the factor ONCE at the point
of assumption, and give back a session credential with a bounded life. AWS STS `AssumeRole`
is that pattern, and the detail that settles the ceiling is that a **chained** role session
is capped at one hour and cannot be extended past it
(docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp_request.html;
repost.aws/knowledge-center/iam-role-chaining-limit). OWASP's re-authentication guidance
says to re-authenticate for sensitive operations and to **rotate the session immediately
after a successful step-up** — which `service.complete_step_up` already does
(cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html,
Session_Management_Cheat_Sheet.html).

So: **step-up to enter, renewal to stay, one hour on the chain.**

- The grant carries `auth_time` — the registered OIDC Core 1.0 §2 claim meaning "time when
  the End-User authentication occurred". A renewal **inherits** it; it is never restamped.
- `core/impersonation.renewable_grant(raw, admin_id, tenant_id)` answers "may this mint
  continue an existing session?" and is **total**: absent, malformed, forged, expired,
  another operator's, another tenant's, or an unreadable `auth_time` all return `None`, and
  `None` sends the caller to the **stricter** path. There is no input that makes it return a
  grant `verify_grant` would refuse, so it cannot widen anything.
- The console sends the grant it is replacing as `renew` in the mint body.

**Why the body and not `X-Impersonation-Grant`.** That header means "this request is being
made INSIDE the named tenant" and `core/auth.py` reads it beside `X-Impersonate-Org`. A mint
is made from the operator's own admin session and is inside nothing; reusing the header
would make this the one request where it means something else. RFC 8693 — whose claim shape
this grant already borrows — carries the token being exchanged in the request body, for the
same reason.

**Why the gate is not split at this call site.** It would have been possible to demand the
`X-Confirm-Action` echo on renewals too and waive only freshness. `core/stepup.py` demands
both together specifically so that no route ends up with one; and a live grant for this
tenant, signed by us and bound to this operator, is stronger evidence of both intent and
presence than an echo whose string the refusal prints on purpose. So a successful renewal
skips the whole gate and a failed one takes the whole gate.

**The effective ceiling is 1 h + `GRANT_TTL` ≈ 75 minutes**, and that is stated rather than
hidden. Capping `exp` at `auth_time + VIEW_AS_MAX_AGE` would make the boundary exact — and
would make the last grant of a chain arbitrarily short-lived, which the console reads as
"stale, re-mint", i.e. a mint loop against an INSERT-ONLY ledger (hard rule 4). A stated
75-minute ceiling beats an exact 60-minute one bought with a write amplifier.

### The audit obligation is unchanged, and says more than it did (PROVEN)

D-22 requires the start row and requires it to name the actor. Both still hold, on cold
entry and on renewal, and `tests/impersonation_stepup_test.py` asserts `actor_type ==
"admin"` and `actor_id == operator` on each. The summary gains three fields: `auth_time`
(dates the step-up the chain rests on), `renews` (the predecessor's `grant_id`, or `null`)
and `window_s`. Without `renews` the ledger could not tell an operator walking through the
door from a session extending itself — four entries an hour either way, but only one kind
cost a second factor.

The summary is asserted through the **log stream**, not the table: `audit_log` has no
`summary` column and never had one (`compliance/audit.py` — hashing a field the row does not
carry would make the chain unverifiable), so `write_audit` emits it as an `audit` record
keyed by the entry id. That is where an auditor reads it, so that is where the test reads it.

### The refusal executes nothing (PROVEN)

Both refusals happen before `mint_grant` and before `write_audit`. Every refusing test
asserts `_started_rows(tenant_id) == []`. This is what makes the console's retry legitimate:
`lib/api/client.ts` records the rule its own deleted retry rung had to meet — a POST may be
repeated only when the refusal provably executed nothing — and this route is the only
step-up call site with that proof.

---

## Gap 2 — the doc/implementation conflict (D-211)

### The conflict, stated precisely

§7: "**step-up confirmation** … for high-risk admin actions — big red switch, cap raises,
raw-transcript access."

`service.MFA_REQUIRED_REALMS` is `{"admin"}` (D-170 removed TOTP, enrolment and recovery
codes from the client realm). `authn/stepup.STEP_UP_REALM` is `"admin"`, and its comment
says a client-realm freshness check "would have no `mfa_verified_at` to read". So
`StepUp.present` is **False for every client caller**, and declaring the gate on
`/v1/calls/{id}/transcript/raw` would not tighten that route — it would delete it. A tenant
owner reading their own call would be refused with a remediation pointing at
`/v1/auth/admin/step-up`, an endpoint their realm does not have.

### The decision: the doc is right about the admin realm and imprecise about the client one

Both halves are now written out.

**Client realm — role + audit, by design.** The threat models are not the same shape. On the
admin realm the reader is an outsider to the data: our staff reading a customer's customers'
conversations, and step-up defends the tenant against us and against a stolen operator
credential. On the client realm the reader is the Data Fiduciary's own `owner` reading
recordings of their own callers — the controller exercising controllership. The control that
matters there is the one that makes it **attributable**, and that is exactly what is already
enforced: `calls:read_raw` is held by `owner` and never by `staff`, and every read writes
`transcript.read_raw` in the same transaction as the read (hard rule 5). D-181 put the
recording AUDIO on the same pair for the same reason.

**What would change this answer** is a client-realm second factor existing at all. That is a
product decision about Indian SMB owners and email deliverability which D-170 already took;
reversing it is its own decision-log entry, not a consequence of this one, and not an
engineering gap being deferred.

**Admin realm — step-up, at the door.** Gap 1 makes §7's sentence true there for the first
time, and the door is not merely a convenient place for the check: it is the only place it
can live, because the reads are served by a realm with no admin session to check.

**The sentence was amended, not deleted.** It was never wrong about the admin realm.

### Collateral, because §7's heading no longer said anything true

§7 was headed "(ADAPTED — Clerk owns sessions)" and opened by describing raghava's
rotation-with-grace + reuse-detection design as "the reference if we ever self-host auth".
D-177 deleted the vendor and we ship that design (`authn/sessions.py`, RFC 9700 §4.14.2 reuse
detection included). Two other dangling vendor references in the same document are corrected:
the load-shed paragraph claimed `/v1/auth` "named a route this API does not have" (it does
now, and `core/loadshed.py` already records the correct, narrower reason the exemption stayed
removed), and the ops-config bullet said "Clerk + secrets-manager references".

---

## The seam neither gap could have been closed without

**The operator console had no step-up prompt.** Not for impersonation and not for the fifteen
routes that already took the gate — `POST /v1/auth/admin/step-up` and `.../step-up/verify`
existed on the API and nothing in `apps/web/` called either. In practice that meant the
fifteen gated routes were usable only inside the five minutes after a sign-in, and an
operator's only remedy afterwards was to sign out and back in.

What was added, kept as small as the fence allows:

| File | What |
| --- | --- |
| `lib/authn/problems.ts` | `needsReauthentication()` — and a comment on why it is NOT `step_up_required` |
| `lib/authn/adminAuthn.ts` | `requestAdminStepUp` / `confirmAdminStepUp`, admin-realm only, `reset()` first because verify rotates |
| `lib/authn/stepUpPrompt.ts` | the ask, as an external store, single-flighted (new) |
| `components/authn/stepUpPrompt.tsx` | the modal, which settles waiters `false` on unmount (new) |
| `app/admin/layout.tsx` | mounts it once, above every screen |
| `lib/api/admin.ts` | `viewAsConfirmation`, `renew` on re-mint, prompt-then-retry-once |
| `tests/harness.tsx` | dismisses a leaked prompt between tests, beside the two resets already there |

**Why an external store rather than a hook or a context.** The caller that needs it most is
not in React's render path: `admin.ts::mint` runs inside a `GrantSource` the transport calls
while assembling headers. `admin.ts` already argues why `viewAsSession(slug)` cannot become a
hook. `useSyncExternalStore` is what React ships for exactly this.

**Why the ask resolves `false` rather than rejecting.** The caller is already holding the
server's `reauthentication_required` problem, with its own title, sentence and remediation.
A dismissed prompt makes the caller rethrow **that**, rather than this module inventing a
second refusal vocabulary for a condition the API has already named — and a prompt nobody
answers can never become an unhandled rejection.

**Single-flight.** `service.request_step_up` retires the previous challenge on issue, so six
concurrent asks would leave an operator typing a code the sixth request had already
invalidated. One pending promise, shared.

---

## What a `dev:` token can and cannot test, and what this suite does instead

`core/stepup.StepUp.require` waives the FRESHNESS half when `dev_tokens_permitted()` — which
is `APP_ENV=local` **and** no `PLATFORM_KEK`, the same two conditions that let a `dev:` token
authenticate at all. It does **not** waive the echo. So the sibling suites, which all
authenticate with `dev:admin:<uuid>`, can only ever exercise the echo half; their shared
helper `_mint_over_http` now sends `X-Confirm-Action` and every suite that enters a tenant
inherits it.

`tests/impersonation_stepup_test.py` therefore drives the route over HTTP with a **real
first-party admin cookie** — the credential this route has in production — writing
`auth_sessions.mfa_verified_at` directly to age the factor, the same technique
`tests/authn_stepup_test.py` uses and for the same stated reason (what is under test is the
READ).

One finding worth recording from writing it: a session with a NULL `mfa_verified_at` never
reaches the step-up gate at all — `verify_token`'s `_require_second_factor` answers
`401 second_factor_required` first. That is correct (401 = finish signing in; 403 = you are
signed in, prove it is still you) and is now asserted rather than assumed, so no route change
can let a half-authenticated session reach the tenant door.

---

## Results (PROVEN)

```
uv run pytest tests/impersonation_stepup_test.py -q      15 passed
uv run pytest tests/impersonation_grant_test.py -q       14 passed
uv run pytest tests/authn_stepup_test.py -q              16 passed
uv run pytest tests/impersonation_audit_test.py tests/principal_resolution_test.py \
              tests/authz_audit_test.py tests/admin_security_test.py \
              tests/realm_boundary_test.py tests/route_shape_test.py \
              tests/rbac_registry_test.py -q             all passed
pnpm -C apps/web exec vitest run tests/adminStepUp.test.tsx   10 passed
pnpm -C apps/web test                                    90 files, 1158 tests passed
uv run ruff check . / ruff format --check .              clean
uv run mypy apps packages                                233 files, no issues
uv run python -m scripts.check_docs_drift                OK
uv run python -m scripts.check_openapi_fresh             snapshot refreshed, types regenerated
```

### Sabotage verification

Every fix was reverted in place and the suite re-run, to confirm the tests fail for the
intended reason and only there.

| Reverted | Result |
| --- | --- |
| `step_up.require(...)` removed from the mint | 10 failed / 5 passed — every refusal test plus every renewal-fallback test |
| renewal restamps `auth_time = now` | 1 failed — `test_a_renewal_inherits_auth_time_rather_than_restamping_it`, exactly the property the design rests on |
| `VIEW_AS_MAX_AGE` check dropped from `renewable_grant` | 1 failed — `test_a_renewal_stops_at_the_view_as_window` |
| `_as_instant` lets `bool` through (so `auth_time: true` reads as the epoch) | 1 failed — `test_a_grant_whose_auth_time_is_unreadable_is_refused_not_defaulted` |
| renewal trusts the grant's own `sub` (tenant binding dropped) | 3 failed — the cross-tenant test plus the two junk-input cases |
| renewal trusts the grant's own `act.sub` (actor binding dropped) | 3 failed — the other-operator test plus the two junk-input cases |
| `X-Confirm-Action` not sent by the console | 1 failed — the echo test |
| console never sends `renew` | 1 failed — the renewal test |
| console does not prompt on `reauthentication_required` | 5 failed — every prompt test |
| prompt single-flight removed | 2 failed — both store tests |
| prompt does not settle waiters on unmount | 1 failed — the unmount test, after a 5s hang |

---

## Still open, named rather than left implicit

- **The ops console's step-up writes still render a refusal instead of raising the prompt.**
  The prompt is mounted and general, but the fifteen pre-existing call sites are not wired to
  prompt-then-retry, and this is not a transport rung: `lib/api/client.ts`'s rule is that a
  repeated POST needs proof the refusal executed nothing, and only the mint has that proof
  (`record_commercial_terms`, for one, reads rows before `step_up.require`). Wiring each is
  per-route work with a per-route safety argument. **Ours, not blocked on anything external.**
- **`GEMINI_MODEL_CONFIRMED_IN_REGION`-class external blockers: none apply here.** Nothing in
  this pass waits on a vendor, a regulator or a signed term.
- **Whether one hour is the right ceiling for a support session** is a number, not a
  mechanism. It is `core/impersonation.VIEW_AS_MAX_AGE`, argued against AWS's, and changing it
  is one constant and one test.
