# Calevate — Replacing Clerk with a First-Party Auth Module (D-165)

Version 1.0 · 17 Aug 2026 · **DESIGN + a proof-of-concept slice. Clerk is still the live
authenticator and every Clerk path in this repo still works.**

This document is the plan for removing Clerk from Calevate and the acceptance criteria
for that removal. §1 is the criteria: a capability missing from that table is a
capability that disappears silently on cutover day. §§2–7 are the design. §8 is what the
reference implementation gives us and what it cannot. §9 is what a person has to decide
before implementation continues.

**What has actually shipped with this document** is the vertical slice §10 lists: two
tables, a migration, Argon2id hashing with a KEK-derived pepper, opaque session
issue/verify/rotate/revoke, and 49 tests including a negative control per security
property. Nothing is mounted on a router; nothing authenticates anybody yet.

---

## 0. Why

Two drivers, both real, and only one of them is about money.

**Residency.** D-25 already moved hosting to a general-purpose VPS with an India-resident
data plane, and the founder is moving it again, to a **Hostinger India VPS**. The point of
that move is the DPDP posture: SECURITY-COMPLIANCE §4 can say "everything the caller says
is processed in India" because every model endpoint is pinned to an Indian region and a
guardrail (`scripts/check_model_residency.py`) fails the build on anything else. Clerk is
the hole in that sentence. It holds the identity data — email addresses, names, phone
numbers, sign-in events, IP addresses and device metadata for every operator and every
client user — on infrastructure outside India, and no amount of pinning our own endpoints
changes that. The move to an Indian VPS with Clerk still in the stack buys a claim about
where the *calls* are processed and leaves the claim about where the *people* are
recorded exactly where it was.

**Control and cost.** Secondary, and stated honestly as secondary. Clerk's per-MAU pricing
is not the constraint at zero production tenants; the constraint is that authentication is
the one dependency whose outage is total (`core/auth.py` answers 503
`auth_provider_unavailable` when Clerk's JWKS host is unreachable, which is the right
answer and is still an outage nobody can work around), and that two Clerk applications
are two vendor accounts, two dashboards and two sets of settings that no test in this
repository can assert anything about.

**What this does NOT change.** D-37's actual load-bearing decision — *our Postgres is the
system of record; Clerk authenticates and does not own our data model* — is what makes
this migration tractable at all. `users`, `memberships`, `organizations`, `admin_users`,
RLS and every authorization rule already key off OUR ids. Only the authentication leg
moves. That was the promise `tenancy/clerk_webhooks.py` was written on ("if Clerk is ever
replaced, the tenancy model does not move — only the token verification does"), and this
document is the invoice for it.

**The constraint the design has to respect, which the founder has not seen.** The prior
implementation being learned from (`raghava-organics-site`) is **Node/TypeScript**;
Calevate's backend is **Python 3.12 / FastAPI**, and CLAUDE.md's Do-NOT list forbids a
second backend language. So that repository is a *requirements checklist and a design
reference*, not a drop-in. §8 says exactly which parts survive the crossing.

---

## 1. Capability inventory — the acceptance criteria

Sixty-six files in this repository mention Clerk. What follows is the behaviour behind
them: everything that must still exist the day Clerk is gone. **A row missing from this
table is a regression nobody will notice until a customer does.**

| # | Capability | Where Clerk does it today | How we will do it | How it is tested |
|---|---|---|---|---|
| C-01 | Verify a bearer credential and produce a realm-bound identity | `core/auth.py::verify_token` — RS256 against the realm's JWKS, 30 s leeway, `exp` re-checked, `sub` rejected if it carries a control byte | `authn/sessions.py::verify_session` — opaque token → row. No signature, no JWKS, no network. Realm is inside the fingerprint (§3) | **shipped:** `tests/authn_session_test.py` (live, tampered, unknown, cross-realm) |
| C-02 | Two realms that cannot be confused | Two Clerk applications, two JWKS hosts (`jwks_url`), two publishable keys; `missing_realm_separation_keys` makes a collapsed deployment fail `/healthz/ready` | Realm-separated hash domain + `realm` column + per-realm cookie name + per-realm CORS origin allowlist (§3) | **shipped:** `tests/authn_session_test.py::test_the_realm_is_inside_the_fingerprint` and both direction tests. **To keep:** `tests/realm_boundary_test.py` must pass unchanged through cutover |
| C-03 | Prove a password | Clerk's own credential store, invisible to us | `authn/hashing.py` + `authn/credentials.py` — Argon2id + KEK-derived pepper (§2, §4) | **shipped:** `tests/authn_password_test.py`, `tests/authn_rls_test.py` |
| C-04 | Sign out; sign out everywhere | Clerk session revocation | `sessions.revoke_session` / `revoke_family` / `revoke_subject_sessions` | **shipped:** `tests/authn_session_test.py` revocation block |
| C-05 | Session expiry, idle and absolute | Clerk session settings (a dashboard checkbox, unassertable from this repo) | `REALM_TIMEOUTS`, enforced server-side on the row, different per realm | **shipped:** both bounds have their own negative control |
| C-06 | Rotate the session identifier on privilege change | Clerk internal | `sessions.rotate_session`, CAS on `superseded_at`, lifetime carried forward | **shipped** |
| C-07 | Detect a stolen/replayed session | Not available from Clerk to us | Replay of a superseded token revokes the family (`reuse_detected`) | **shipped** |
| C-08 | Mandatory MFA on the admin realm | `fva` claim on Clerk's default session token; gate in `verify_token` (D-68) | `auth_sessions.mfa_verified_at` + TOTP enrolment (§2.3). The gate stays in the verifier, for the reason `core/auth.py` argues: an admin identity that skipped MFA must not be constructible | **shipped (carrier only):** rotation preserves it. **TODO:** the TOTP enrol/verify flow |
| C-09 | Step-up confirmation for high-risk admin acts | `X-Confirm-Action` (ours) + Clerk re-auth | Unchanged for the header half; the re-auth half becomes "re-enter password or TOTP within N minutes", read off `mfa_verified_at` / a new `reauth_at` | **TODO** |
| C-10 | Mirror identity into our Postgres | `tenancy/clerk_webhooks.py` (Svix HMAC) + `core/clerk_identity.py` JIT reconcile (D-124) | **Deleted, not replaced.** There is no upstream to mirror: `users` becomes the origin of an identity rather than its shadow. The whole `identity_mirror_pending` transient-refusal path and its race disappear with it | **TODO:** delete `tests/identity_mirror_race_test.py`, `tests/clerk_mirror_security_test.py` and the `/hooks/v1/clerk` rate-limit rule in the same change |
| C-11 | Self-serve signup (account, then workspace) | Clerk hosted `/sign-up` mints the account; `POST /v1/auth/signup` creates the org | One flow, ours: email + password + verification → `users` row → `POST /v1/auth/signup` unchanged. `current_identity` keeps its shape (a verified identity with no membership yet) | **TODO** |
| C-12 | Email verification | Clerk | Our own: a single-use hashed token, 24 h, delivered through the existing outbox + Resend transport | **TODO** |
| C-13 | Password reset | Clerk | Single-use hashed token, 1 h, **must revoke every session on use** (ASVS V7) | **TODO** |
| C-14 | Team invitations | **Already ours.** `invitations` table, 72 h, hash-at-rest, burned by CAS on `used_at`, read under `app.invite_hash` | Unchanged, except the recipient binding: today `accept_invitation` compares `users.email` (populated from Clerk's verified `email_addresses`), tomorrow from our own verified-email column | **existing:** `tests/member_invitations_test.py`; add a case that an unverified address cannot redeem |
| C-15 | Client staff roles | **Already ours.** `memberships.role`, `core/rbac.py` policy registry validated at boot | Unchanged | **existing:** `tests/rbac_registry_test.py` |
| C-16 | Operator allowlist | **Already ours.** `admin_users`, ops-managed, never auto-created (`clerk_identity.py` is explicit that auto-creating one is "privilege escalation wearing a race condition's clothes") | Unchanged, minus the `clerk_user_id` column; `scripts/bootstrap_admin.py` takes an email instead | **existing:** `tests/admin_identity_test.py`; the bootstrap script needs its own |
| C-17 | Instant deactivation despite a cached session | `users.deactivated_at` re-read on every request (BACKEND-PATTERNS §7) | Unchanged — and strictly better, because the session itself is now revocable rather than only the authorization built on it | **existing:** `tests/api_security_test.py` |
| C-18 | D-22 impersonation and its audit trail | **Already ours.** `core/impersonation.py` mints an RFC-8693-shaped grant signed with `IMPERSONATION_GRANT_SECRET`; `_load_admin_principal` verifies it and writes `admin.impersonation_read` | Unchanged. The grant is deliberately NOT a credential — it is presented alongside the operator's own session — so replacing what that session IS changes nothing about it | **existing:** `tests/impersonation_grant_test.py`, `tests/impersonation_audit_test.py` |
| C-19 | Per-caller rate limiting | `RateLimitMiddleware._caller` keys on `bearer_token(...)` | Same function, now reading the session cookie as well as the header. **The bucket key must become the session id, not the raw token** — a rotated session must not get a fresh bucket | **TODO**, with a test that rotation does not reset the bucket |
| C-20 | Readiness gate on auth configuration | `runtime_config_missing_keys` reports `CLERK_*` keys; `missing_realm_separation_keys` reports a collapsed realm pair | Replaced by: `PLATFORM_KEK` present (already reported), and a new check that the two realms' cookie names and CORS origins differ | **TODO** |
| C-21 | Local development without a vendor | `dev:<realm>:<id>` tokens, accepted only when `APP_ENV=local` AND the realm has no Clerk secret | A seeded local password, or the same dev-token shape re-pointed at `authn`. The two guards must survive verbatim — `tests/authz_audit_test.py` pins them | **existing test, new subject** |
| C-22 | Browser session lifecycle | `@clerk/nextjs` `ClerkProvider`, `getToken()`, `RedirectToSignIn`, hosted sign-in UI | Ours: an `HttpOnly` cookie the browser never reads, a `GET /v1/auth/session` bootstrap call, our own sign-in pages (§6) | **TODO** — `apps/web` is out of scope for this change |
| C-23 | Bot detection on sign-up/sign-in | Clerk built-in | **Not replaced on day one.** §7 names it as accepted risk; Cloudflare Turnstile is the reference implementation's answer and is the obvious follow-up | — |
| C-24 | Breached-password checks | Clerk built-in (HIBP) | **Not replaced on day one.** §7 | — |
| C-25 | Device/session management UI | Clerk built-in | Buildable from `auth_sessions` the day a column for it is added; deliberately not added yet (a column nobody reads is a defect — `scripts/check_wiring.py`) | — |
| C-26 | Social sign-in (Google) | Clerk built-in, offered on the client realm | **Dropped unless the founder says otherwise (§9 Q3).** A first-party Google OIDC client is a week of work and a residency question of its own | — |

---

## 2. Schema

### 2.1 What ships now

Migration `e9a4c1d70b52`. Both tables are **platform-level, not tenant-scoped**, and both
are FORCE-RLS'd anyway.

```
auth_credentials
  id uuid pk · realm text · subject_id uuid · password_hash text
  password_set_at timestamptz · created_at · updated_at
  UNIQUE (realm, subject_id) · CHECK realm IN ('admin','client')

auth_sessions
  id uuid pk · family_id uuid · realm text · subject_id uuid
  token_hash bytea UNIQUE · last_seen_at · idle_expires_at · absolute_expires_at
  superseded_at · revoked_at · revoked_reason · mfa_verified_at
  CHECK realm IN (...) · CHECK revoked_reason IN (...) · CHECK revoked ⇒ reason
  INDEX (family_id) · INDEX (realm, subject_id)
```

**Why they are NOT tenant-scoped.** Identity crosses tenants: one person can be the owner
of one clinic and staff at another, which is what `memberships` is for (DATA-MODEL §2). A
password or a session carrying a `tenant_id` would be duplicated per membership or would
be wrong. `users` and `admin_users` are outside tenant isolation for the same reason.

**What protects them instead, and why it is stricter than a tenant policy.** `users` today
has no RLS at all — any session in the process can read it — and that is tolerable for a
directory of email addresses. It is not tolerable for password hashes and live session
fingerprints, where the same mistake is platform-wide account takeover. So both tables get
`ENABLE` + `FORCE ROW LEVEL SECURITY` with a **deny-by-default** policy:

```sql
CREATE POLICY credential_store_only ON auth_sessions
  USING (current_setting('app.auth', true) = 'on')
  WITH CHECK (current_setting('app.auth', true) = 'on');
```

`app.auth` is set by `db/session.credential_session()` and by nothing else. A
`tenant_session`, an `admin_session`, a `user_session`, an `invite_session` and a bare
`untenanted_session` all see zero rows — which is the cross-tenant property hard rule 1
asks for, reached from the other side: tenant A sees none of tenant B's owner's rows
because it sees none of *anybody's*. `tests/authn_rls_test.py` drives all five against
rows that are definitely there, with a control that proves the table is not merely empty,
and a `WITH CHECK` negative control proving a tenant session cannot plant a credential
either.

Both are registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that reasoning, because
that dict's contract is "the one place a reviewer learns what is deliberately not
tenant-isolated" and a password store absent from it would be the worst possible omission.

**`subject_id` has no foreign key.** It points at `users.id` or `admin_users.id` depending
on `realm`, and PostgreSQL has no polymorphic FK. Two nullable FKs plus a CHECK, or one
merged identity table, were the alternatives; the first makes every query learn which
column to join, the second collapses the realm separation this whole migration exists to
preserve. Orphans are not reachable through the application: `users` is soft-deleted
(`deactivated_at`), never hard-deleted, because memberships and audit rows must survive.

### 2.2 What the full migration still needs

Named here so the cutover cannot quietly skip them. Each is one table plus its policy in
one migration, on the same `app.auth` pattern.

| Table | Holds | Notes |
|---|---|---|
| `auth_mfa_secrets` | `(realm, subject_id)` → envelope-encrypted TOTP secret, `confirmed_at` | Encrypted with `core/envelope.seal(...)` under AAD `mfa_secret:<realm>:<subject_id>` — the D-97 KEK doctrine, reused rather than reinvented (§4). Unconfirmed secrets are deleted, never left half-enrolled |
| `auth_recovery_codes` | one row per code: `(realm, subject_id)`, `code_hash`, `used_at` | Hashed like a session token (SHA-256 over a 128-bit random code), not like a password: they are high-entropy, so a slow KDF buys nothing. Ten codes, single-use, regenerating invalidates the set |
| `auth_email_tokens` | verification and password-reset tokens: `purpose`, `token_hash`, `expires_at`, `used_at` | One table, two purposes, `purpose` in the hash domain so a verification token cannot be redeemed as a reset. Burned by CAS on `used_at IS NULL`, exactly as `invitations` already is |
| `users.email_verified_at`, `users.password_migrated_at` | on the existing table | `email_verified_at` is the column `accept_invitation`'s recipient binding starts trusting instead of "Clerk said so". `password_migrated_at` is how the cutover in §5 knows who is done |

**Columns being removed, in a two-step (hard rule 8):** `users.clerk_user_id` and
`admin_users.clerk_user_id`. Stop writing them in the release that stops reading them;
drop them one release later.

### 2.3 What is deliberately NOT a table

- **Login throttling and lockout.** Redis, via `core/ratelimit.py`, which already owns the
  vocabulary of "per caller, per IP, per tenant". A `failed_attempts` column would be a
  second answer to a question this repo already answers, and a durable lockout counter is
  a denial-of-service primitive an attacker can aim at a known account.
- **A session denylist.** The sessions are opaque; the row *is* the authority.
- **Password history.** A previous hash is a liability with no reader. "When did this
  password last change" is what a support conversation needs, and `password_set_at`
  carries it.

---

## 3. The realm boundary — the most dangerous part of this migration

Today the separation is a property of the *vendor*: two Clerk applications, two JWKS
hosts, and `core/auth.py::jwks_url` verifying each realm against its own. An admin token
is not a weak client token; it is not a token at all. `missing_realm_separation_keys`
exists because a deployment that set `CLERK_FRONTEND_API` and forgot the publishable keys
collapsed both realms onto one host and reported `/healthz/ready` green — the exact failure
that turns an authentication boundary into an authorization check.

When both realms are ours, the separation has to be rebuilt out of our own materials. A
`realm` column that queries remember to filter on is **not good enough**: it is one
forgotten `WHERE` clause away from being nothing, and the forgetting would be silent. Four
independent mechanisms, so that no single omission collapses it:

1. **The realm is inside the hash.** `sessions.token_fingerprint(token, realm)` is
   `SHA-256(b"calevate/auth-session/v1/" + realm + b"\x00" + token)`. The stored
   fingerprint of a client token computed under the admin realm is different 32 bytes —
   there is no row the admin lookup could match. Cross-realm confusion is arithmetic, not
   a predicate. *(Shipped and tested both directions, with the control that the same token
   succeeds on its own realm in the same test — the discipline `tests/realm_boundary_test.py`
   already insists on.)*
2. **The `realm` column is still in the WHERE clause.** Belt to that brace. Two independent
   reasons for one refusal.
3. **Two cookie names, one per realm.** `__Host-calevate_admin_session` and
   `__Host-calevate_client_session`. The `__Host-` prefix forbids a `Domain` attribute and
   forces `Path=/`, so each cookie is host-only to the API origin
   (draft-ietf-httpbis-rfc6265bis §4.1.3). **This is the part that needs stating plainly:
   because both realms' browsers talk to one API host, both cookies land on that host.**
   The cookie name is therefore an addressing convention, not a boundary — mechanisms 1, 2
   and 4 are the boundary.
4. **Per-realm origin enforcement.** `admin.calevate.tech` and `app.calevate.tech` are
   *different origins* but the *same site* (`calevate.tech` is the registrable domain), so
   `SameSite` does not separate them and CORS must. The admin dependency refuses any request
   whose `Origin` is not the admin console's, and vice versa; `Sec-Fetch-Site: cross-site`
   is refused outright on both. A per-realm allowlist rather than one shared list, for the
   same reason the two frontend realm modules refuse to share a file.

**Two deploys stay two deploys.** `apps/web` renders the realms as disjoint route trees
with disjoint providers, and `clerkRuntime.tsx` already records the uncomfortable fact that
the *hostname* half of that separation is not enforced by anything (one nginx `server`
block serves both names, so `app.calevate.tech/admin` reaches the operator console). That
was survivable while Clerk's JWKS split did the real work. **It is less survivable with
cookies**, because a `__Host-` cookie set by the API is sent from either hostname — so the
edge change that file describes (`location ^~ /admin { return 404; }` on `app.`, `^~ /c/`
on `admin.`) moves from "worth doing" to **a prerequisite of cutover** (§5 step 0).

**`tests/realm_boundary_test.py` must keep passing, unchanged in intent.** It drives valid
credentials of the wrong kind at both doors and sweeps every mutating route under a real
view-as grant. Its fixtures mint `dev:<realm>:<id>` tokens; those become
`authn`-issued sessions, and nothing else in the file should have to move. **If that suite
needs a semantic change to pass, the boundary changed and the change is the finding.**

---

## 4. Secrets and key management

Three key materials, and the design's goal is that this migration introduces **zero new
environment variables**.

| Purpose | Key | Rotation |
|---|---|---|
| Session token → stored fingerprint | *none* — SHA-256, unkeyed | n/a. A 256-bit random token needs no key; keying the hash would add a rotation problem with nothing on the other side of it |
| Password pepper | HKDF-SHA-256(`PLATFORM_KEK`, info=`calevate/password-pepper/v1`) | Rides the KEK ring: the retired KEK yields the retired pepper, a hash that verifies under it is reported `needs_rehash`, and the successful sign-in rewrites it. Drains lazily; locks nobody out |
| TOTP secret at rest | Envelope-encrypted via `core/envelope.seal(...)`, AAD `mfa_secret:<realm>:<subject_id>` | D-97's KEK re-wrap. `rewrap_all` already exists and already never decrypts the payload |

**Why the pepper is derived rather than stored.** OWASP is explicit that a pepper "should
not be stored along with the generated hash" and wants a secrets vault. Both obvious homes
fail that test here:

- **`platform_secrets`** is in the same database as `auth_credentials`, so the dump that
  takes the hashes takes the pepper. It is encrypted under the KEK — which makes the real
  key the KEK, one indirection later, plus a false sense that the two are separate.
- **A ninth bootstrap environment variable.** `.env.example` argues that the bootstrap set
  is eight because a key belongs there only when "a process cannot reach the store without
  it". A pepper is not that. Adding one anyway would make that file's stated rule stop
  describing its contents.

`PLATFORM_KEK` is *already* env-only by construction and by CI: `ENV_ONLY_KEYS` keeps it out
of `apply_platform_overrides`, `scripts/check_bootstrap_keys.py` fails the build on any
change that would let it resolve from the console store, and `core/envelope.py` states the
reason in one line — "a database holding both the lock and the key is theatre". That is
exactly the property a pepper needs, already guaranteed and already tested. HKDF with a
distinct `info` string (RFC 5869) is key *separation*, not key reuse.

**The coupling this creates, said out loud**, because `core/impersonation.py` refused a
derived key on precisely this ground ("coupled rotations are the ones that never happen"):
rotating the KEK now also rotates the pepper. That is survivable here in a way it would not
be there, because the KEK is a **ring** — `PLATFORM_KEK_RETIRED` unwraps and never wraps —
and `pepper_ring()` walks it in the same order. The one real consequence is in
`tests/authn_password_test.py::test_a_second_rotation_drops_the_generation_that_fell_off_the_ring`:
a password never used across **two** KEK rotations stops verifying and needs a reset. That
is an operational fact for the rotation runbook, not a defect — the alternative is a ring
that keeps every key the deployment has ever held, which defeats retiring one.

**What is deleted.** `CLERK_ADMIN_SECRET_KEY`, `CLERK_CLIENT_SECRET_KEY`,
`CLERK_ADMIN_PUBLISHABLE_KEY`, `CLERK_CLIENT_PUBLISHABLE_KEY`, `CLERK_FRONTEND_API`,
`CLERK_WEBHOOK_SECRET`, and the browser's `NEXT_PUBLIC_CLERK_*` pair. `scripts/check_env_parity.py`
and `scripts/check_web_env_parity.py` fail the build if a `Settings` field is declared in
neither `.env.example` nor the console, so removing them is a checked operation rather than
a hopeful one.

---

## 5. The cutover

Zero production tenants makes this cheap. It does not make it unplanned — the sequence
below is what makes each step individually revertible, and it names the one step that is
not.

**Step 0 — prerequisites, before any auth code ships.**
(a) The nginx split from §3: two `server` blocks, `/admin` 404 on `app.`, `/c/` 404 on
`admin.`. (b) `PLATFORM_KEK` actually set on the target host — today a local box falls back
to a public derived constant, and a production deployment that forgot the variable would be
peppering every password with a value printed in this repository. `/healthz/ready` already
reports it; make it a go-live tick. **Reversible.**

**Step 1 — schema.** `e9a4c1d70b52` (shipped) plus the §2.2 tables. Additive only; nothing
reads them. **Reversible** by `alembic downgrade`.

**Step 2 — the module.** `apps/api/authn` complete: TOTP, recovery codes, email tokens,
reset. Still mounted on nothing. **Reversible.**

**Step 3 — mount the routes behind a config flag.** `POST /v1/auth/login`, `/logout`,
`/session`, `/password/reset/*`, `/mfa/*`, as a plain config row (D-78's "feature flags via
plain config rows"), default off. Both credential paths exist; only one is reachable.
**Reversible** by flipping the row.

**Step 4 — populate.** For each `admin_users` row and each `users` row, send a
**set-your-password** email (the §2.2 reset-token path, one-time, longer expiry). There are
a handful of operators and no production clients, so this is a list a person can read.
**Do NOT import password hashes from Clerk** — Clerk does not export them, and a design
that assumed otherwise would fail at the worst moment. `users.password_migrated_at` is the
progress column. **Reversible** — nothing is switched over yet.

**Step 5 — flip the flag, realm by realm, admin first.** The admin realm is a handful of
people who can be told, and it exercises the MFA path that the client realm does not have.
Watch for a week — with zero production tenants, "a week" is a real option and costs
nothing. **Reversible** by flipping back, *provided step 6 has not run.*

**Step 6 — remove the Clerk paths.** Delete `core/clerk_identity.py`,
`tenancy/clerk_webhooks.py`, the `/hooks/v1/clerk` route and its rate-limit rule, the
`CLERK_*` settings, the `@clerk/nextjs` dependency, and the two `clerk_user_id` columns'
*writers*. **THIS IS THE IRREVERSIBLE STEP.** Not because the code cannot be restored from
git, but because from here on the Clerk applications' sessions are dead, and reverting means
every user signs in again through a vendor whose webhook we have stopped answering — i.e.
it is a restore, not a rollback. Do not run step 6 in the same deploy as step 5.

**Step 7 — drop the columns.** One release after step 6 (hard rule 8's two-step). Delete
the Clerk applications from the vendor dashboard **only after** a backup of their user list
exists in the ops record, because that list is the only remaining evidence of which email
addresses were verified upstream.

**What is not reversible at any point:** any password a user sets on our side is ours and
Clerk never learns it, so a rollback between steps 4 and 6 leaves users holding two
credentials. That is the honest cost of the flag-based cutover, and it is small: the Clerk
one keeps working until step 6.

---

## 6. The frontend plan (design only — `apps/web` is out of scope for this change)

The React/Next.js patterns port far more directly than the backend ones, because they are
not language-bound. What changes shape:

- **`lib/auth/mode.ts` survives almost verbatim.** Its whole job — "which credential does
  this build present, decided by configuration once, never inferred from what happens to
  work" — is unchanged; only the enum members change (`session | dev` instead of
  `clerk | dev`). Its two-independent-guards argument against a production dev-token
  fallback is exactly as load-bearing afterwards.
- **`lib/auth/clerkRuntime.tsx` is deleted.** It is the vendor bridge, and there is no
  vendor. Its `assertMountedApplication` check has no successor and needs none: there is no
  browser singleton to mis-mount.
- **`adminRealm.tsx` / `clientRealm.tsx` keep their shape and their duplication.** They stop
  wrapping `ClerkProvider` and start providing "is there a session" from a `GET
  /v1/auth/session` bootstrap call. **The duplication stays deliberate** — a `realm`
  parameter on one shared module is one bad conditional away from presenting an admin
  credential on a client surface, which is the argument those files already make.
- **`lib/api/client.ts` loses `TokenSource` and gains `credentials: "include"`.** With an
  `HttpOnly` cookie the browser attaches the credential; nothing in JavaScript can read it,
  which is a strict improvement over holding a bearer token in memory.
- **CSRF becomes ours.** With a bearer token, CSRF was structurally impossible; with a
  cookie it is not, and `SameSite=Lax` alone is **not** sufficient — OWASP's CSRF cheat
  sheet is explicit that Lax "only blocks unsafe methods" and that same-site is not
  same-origin, which matters here precisely because `admin.` and `app.` are one site. The
  design: (a) reject `Sec-Fetch-Site: cross-site` on every unsafe method, with an
  `Origin` allowlist fallback for clients that do not send it; (b) a signed double-submit
  token (HMAC over the session id under a server-side key) in an `X-CSRF-Token` header on
  every mutating request. Both, because the cheat sheet's own bottom line is to layer them.
- **Ported from the reference repo, and worth porting:** `AdminIdleTimeoutModal` +
  `use-idle-timeout` (warn before the idle bound bites, rather than losing a form),
  `AdminSessionRestoreGate` (do not flash a signed-out shell while the bootstrap call is in
  flight), `AuthErrorBanner`, and the `guest` variant of the restore hook so the sign-in page
  does not fight its own guard. These are the parts of that codebase that were learned from
  production traffic.
- **Not ported:** its Zustand `accessToken` in memory (we have no access token) and its
  session-restore-nonce machinery (it exists to re-trigger a refresh-token exchange we do
  not have).

---

## 7. Threat model

| Threat | Control | Residual |
|---|---|---|
| **Credential stuffing** | Argon2id makes verification expensive for us AND the attacker; per-IP and per-caller limits (`core/ratelimit.py`) with a dedicated `auth` profile; identical timing and identical response for unknown-account and wrong-password | **No breached-password check and no bot detection on day one (C-23, C-24).** A stuffing run against known-good credential pairs succeeds at whatever rate the limiter allows. Turnstile + a HIBP range-API check are the named closers |
| **User enumeration** | `verify_password_blocking(pw, None)` performs a real Argon2 verification against a dummy hash rather than returning early — the difference is otherwise four orders of magnitude and measurable over the network. Sign-up and reset must answer identically for known and unknown addresses | The invitation flow's `invitation_wrong_recipient` refusal is a deliberate exception, and it stays: it is reachable only by someone holding a valid invite token, and the alternative is an honest invitee with no way to understand the refusal |
| **Session fixation** | The session identifier is regenerated on every privilege change (`rotate_session`); a session is never created from a client-supplied identifier — there is no code path that accepts one | — |
| **Session theft / replay** | `HttpOnly` (no JavaScript read), `Secure`, `__Host-` prefix, absolute timeout, and family-wide revocation on replay of a superseded token | Binding to IP or User-Agent is **deliberately not done**: the reference implementation removed IP binding after carrier-grade NAT made it a logout generator, and a UA is spoofable by anyone who has the cookie |
| **Privilege escalation across realms** | Four independent mechanisms (§3), of which the hash domain is structural rather than procedural | The shared API host means both cookies reach one origin; mechanisms 1, 2 and 4 are what stop that mattering, and `tests/realm_boundary_test.py` is what stops it silently stopping |
| **Impersonation abuse** | Unchanged from D-22: `admin:impersonate` re-checked per request, a grant bound to (operator, tenant) with a 15-minute life, `admin.impersonation_started` at mint and `admin.impersonation_read` per window, and read-only enforcement on every mutating permission | Unchanged — and the audit trail gets *better*, because `auth_sessions.id` gives the trail a session to join on that a Clerk session id never could |
| **Invitation replay** | Single-use (CAS on `used_at IS NULL`), 72 h, hash-at-rest, bound to the invited address | The address binding gets *stronger* after cutover: today it trusts Clerk's `email_addresses` array; afterwards it trusts our own `email_verified_at` |
| **Offline attack on a stolen database** | Argon2id at OWASP parameters **plus a pepper the database does not contain** — the dump alone is not crackable | If the attacker also has `PLATFORM_KEK` (i.e. host compromise, not database compromise) the pepper buys nothing. That is the stated scope of peppering, not a gap |
| **Our own future code reading the credential store** | Deny-by-default RLS on both tables; only `credential_session()` opens them | A future author who reaches for `credential_session()` where they meant `tenant_session()` is not stopped by anything but review. The narrow name is the mitigation |

---

## 8. The reference implementation: what crosses the language boundary

`/workspace/bb3agency/raghava-organics-site` — ~8,200 lines of TypeScript across
`backend/src/modules/auth/` and `backend/src/common/auth/`, plus ~1,800 lines of frontend.

**Genuinely reusable, as-is or nearly:**

- **The frontend components and hooks** (§6). React is React; these port by rename.
- **The refresh-token reuse-detection design** (`revokeSessionFamilyOnReuse`,
  RFC 9700 §4.14.2) — adopted wholesale as *session* reuse detection, minus its
  concurrency grace window, which exists because their tokens rotate on every refresh and
  ours rotate only on privilege change. A grace window here would sell a replay window for
  a race that cannot happen.
- **The cookie doctrine in `auth-cookies.ts`**, including its argument for `SameSite=Lax`
  over `Strict` on a flow that must survive a top-level navigation from another site.
  (Our API is only ever reached by `fetch`, so we take `Strict` — but the *reasoning* is
  the thing worth keeping, and it is the reasoning that decides which of us is right.)
- **The device-binding retraction.** They bound refresh tokens to IP, discovered that
  mobile carriers rotate egress addresses, and removed it. We inherit the conclusion
  without paying for it.
- **`admin-endpoint-policy-registry.ts` + its boot-time validation.** We already have this
  (`core/rbac.py`, validated at boot); worth noting only because it is convergent evidence
  the pattern is right.

**Must be rewritten in Python, with no line of theirs surviving:**

- Everything in `auth.service.ts` (1,600 lines): Fastify, Prisma, `jsonwebtoken`, BullMQ.
  The *behaviours* are the C-01…C-13 checklist above; the code is not portable and
  CLAUDE.md forbids a second backend language.
- Their JWT access/refresh pair. We are not building one — see `authn/sessions.py` on why
  opaque server-side sessions win for a product whose whole authorization model is re-read
  per request.
- Their OTP machinery (`otp-code.ts`, `otp-channel.ts`, the SMS/WhatsApp delivery split).
  Ours is TOTP, admin-only. **SMS OTP is specifically not adopted**: NIST SP 800-63B-4
  classifies SMS/PSTN one-time passcodes as a *restricted authenticator*, which imposes
  obligations on the relying party rather than forbidding it, and there is no reason to
  take those on for an operator console where an authenticator app is available.
- Turnstile integration (`auth-turnstile.ts`, `turnstile-verify.ts`) — the right idea and a
  named follow-up (C-23), but a rewrite.

**Explicitly NOT copied, as defects:**

- **`bcryptjs`.** §2 and `authn/hashing.py` give the citation.
- **Two different bcrypt cost factors** (10 in three call sites, 12 in two others), so the
  strength of a password depends on which flow created the account. Ours is one constant,
  asserted against the PHC string rather than against itself.
- **bcrypt over refresh tokens**, compared in a loop against candidate rows — a
  deliberately-slow KDF per candidate, per refresh, for a value with 256 bits of entropy
  that needs no slow hash at all.
- **`stableHash` / `deriveDeviceKeyHash` device binding.** Retracted by them; not
  reintroduced by us.

---

## 9. Open questions the founder must answer before implementation continues

Each is a decision, not an engineering task, and each blocks a specific row above.

1. **Is Hostinger India actually the target, and does it meet the CPU/RAM profile?**
   Argon2id at 19 MiB per concurrent verification and `--workers=2` is a real memory line
   item on a small VPS. If the plan is the smallest tier, the parameters need re-picking
   *before* passwords are hashed with them — every change afterwards is a lazy rehash the
   users pay for. Blocks: nothing yet; changes §2.
2. **Which email transport is live at cutover?** C-12 and C-13 are undeliverable without
   one, and step 4 of the cutover *is* an email. `email_transport` currently names Resend
   as the founder's Aug 2026 choice — is the account real? **This is an external blocker
   (a vendor account), not an engineering task.**
3. **Do we keep Google sign-in (C-26)?** Dropping it is the default. Keeping it means a
   first-party OIDC client, and it means Google learns when each client user signs in —
   which is a smaller residency question than Clerk's but not a zero one.
4. **MFA on the client realm: still admin-only?** SEC-COMP §5 says admin-only today, and
   `MFA_REQUIRED_REALMS` encodes it. Owning the implementation makes offering optional TOTP
   to client owners nearly free. Offering it and *requiring* it are different answers.
5. **Are the timeout numbers right?** Admin 30 min idle / 8 h absolute; client 12 h / 14
   days. These are defensible and they are not measured. The client absolute bound in
   particular is a product decision about how often an SMB owner is willing to sign in.
6. **Who is the second operator?** Step 5 flips the admin realm first, and a single-operator
   deployment that loses its TOTP device with no recovery codes and no second superadmin is
   locked out of its own console. `scripts/bootstrap_admin.py` is the break-glass, and it
   requires SSH.
7. **Is Turnstile (or equivalent) in scope for the first cutover, or accepted risk?**
   C-23/C-24 are the honest gap versus Clerk. Accepting it is reasonable at zero tenants
   and should be a recorded acceptance rather than an omission.

---

## 10. What shipped with this document

- `alembic/versions/e9a4c1d70b52_first_party_credentials_and_sessions.py` — both tables,
  FORCEd deny-by-default RLS, reversible (`upgrade`/`downgrade` both exercised).
- `apps/api/authn/` — `models.py`, `hashing.py`, `credentials.py`, `sessions.py`. No
  router, by design; the cutover's step 3 is what mounts one.
- `apps/api/db/session.py::credential_session` — the only opener of `app.auth`.
- `apps/api/db/registry.py` — model import + both RLS exemption entries with their reasons.
- `tests/authn_password_test.py` (17), `tests/authn_session_test.py` (19),
  `tests/authn_rls_test.py` (13) — 49 tests at **100% statement and branch coverage of
  `apps/api/authn/`**, with a negative control for every security
  property claimed: wrong password, unknown subject, malformed hash, foreign pepper,
  a pepper two rotations old, expired-by-idle, expired-by-absolute, revoked, cross-realm
  both directions, tampered token, replayed rotated token, double rotation,
  tenant-session read, tenant-session write, and a legacy password shorter than a floor
  that arrived after it — plus a sweep asserting the refusal vocabulary is exactly the
  set the code can produce, in both directions.
- **One design decision worth its own line, because a test nearly missed it.**
  `verify_session` OWNS its transaction rather than taking one. Reuse detection revokes
  the whole family, and that write is the point of the branch that also has to say no —
  run inside the caller's transaction it is undone by the refusal it causes, leaving the
  thief refused and the victim's session live. The alternative fix, a second session for
  the revocation, breaks the invariant `db/session.py` relies on for `max_overflow=0`, on
  a branch an attacker can reach on demand. `test_replaying_a_rotated_token_revokes_the_
  whole_family` now closes the transaction between the detection and the check, and was
  driven red against a deliberate rollback before being accepted.
- One dependency: `argon2-cffi` 25.1.0 (+ `argon2-cffi-bindings`), prebuilt `abi3` wheels,
  transitively requiring only `cffi`, which `cryptography` already brings (hard rule 9).

---

## Sources

Every claim above that is not about this repository was read on the date given. Where a
site is unreachable from this build host, the reachable mirror is named — the same
convention `core/auth.py` and `core/clerk_identity.py` already use.

| Source | Read | Used for |
|---|---|---|
| OWASP **Password Storage Cheat Sheet** — `github.com/OWASP/CheatSheetSeries`, `cheatsheets/Password_Storage_Cheat_Sheet.md` (`cheatsheetseries.owasp.org` is blocked from this host) | 2026-08-17 | Argon2id first, scrypt second, "bcrypt … only … in legacy systems"; the five equivalent Argon2id configurations (`m=47104,t=1,p=1` … `m=7168,t=5,p=1`) and that they "provide an equal level of defense"; bcrypt's 72-byte input limit and the pre-hashing/shucking hazard; peppering ("shared between stored passwords", "should not be stored along with the generated hash", `hmac` then the KDF) |
| OWASP **Session Management Cheat Sheet** — same repository | 2026-08-17 | ≥64 bits of session-id entropy; `Secure`/`HttpOnly`/`SameSite`/`__Host-`; "renewed or regenerated … after any privilege level change" as the session-fixation defence; idle 15–30 min for low-risk and 2–5 for high-value, absolute 4–8 h for an office-worker scenario; both timeouts enforced server-side |
| OWASP **CSRF Prevention Cheat Sheet** — same repository | 2026-08-17 | `SameSite` is defence-in-depth, not sufficient ("Lax only blocks unsafe methods"); signed double-submit / HMAC token as the recommended stateless pattern; custom request headers for SPAs; `Sec-Fetch-Site` rejection with `Origin`/`Referer` as fallback |
| OWASP **ASVS 5.0** (2025) — V7 Session Management, V9 Self-Contained Tokens | 2026-08-17 | Self-contained tokens moved to their own chapter with explicit key-rotation and revocation requirements — the argument for opaque sessions; revocation required when a user's entitlements or roles change |
| **NIST SP 800-63B-4**, Digital Identity Guidelines | 2026-08-17 | SMS/PSTN OTP as a *restricted authenticator*; TOTP lifetime bounded by expected clock drift plus network and entry allowance; password minimum lowered to 8 with 15 recommended, composition rules discouraged |
| **RFC 6238** (TOTP) — `rfc-editor.org/rfc/rfc6238` | 2026-08-17 | 30-second default time step; HMAC-SHA-1 base with SHA-256/512 permitted; 6 digits; a bounded out-of-sync window (±1 step) for clock drift |
| **RFC 5869** (HKDF) | prior art, cited 2026-08-17 | Extract-then-expand; salt optional when the input keying material is already uniformly random (§3.1) — the pepper derivation |
| **RFC 9700** §4.14.2 (OAuth 2.0 Security BCP) | via the reference implementation's own citation, 2026-08-17 | Refresh-token reuse detection → revoke the family. Adapted to sessions |
| **draft-ietf-httpbis-rfc6265bis** (Cookies) — `datatracker.ietf.org` (`httpwg.org` is blocked from this host) | 2026-08-17 | "same site" is decided by the **registrable domain**, so `admin.calevate.tech` → `api.calevate.tech` is same-site and `SameSite` does not separate the realms; `__Host-` requires `Secure`, `Path=/` and no `Domain` |
| **argon2-cffi** 25.1.0, released 2025-06-03 — `pypi.org/project/argon2-cffi` | 2026-08-17 | Library version, maintenance status, `PasswordHasher` / `verify` / `check_needs_rehash` API, and the library defaults (`m=65536,t=3,p=4`) this repo overrides |
| **DPDP Act 2023** + **DPDP Rules 2025** (notified 13 Nov 2025; Schedule 1 penalties from 13 May 2027) | 2026-08-17 | The residency driver. The Act does not blanket-prohibit cross-border transfer — §16 permits it except to countries the Central Government restricts, and the Rules add conditions — so **Clerk is not per se unlawful.** What it is, is a foreign sub-processor holding identity data that has to be disclosed in every client DPA, kept in the sub-processor list, and defended in every enterprise conversation, while the rest of the stack is being pinned to India. Bringing authentication in-house removes a named sub-processor, shortens the breach-notification surface (a Clerk incident is our reportable incident), and makes DPDP erasure a single-database operation instead of a two-system one. **That is the honest framing: a posture and disclosure improvement, not the closing of a legal violation** — and SECURITY-COMPLIANCE §4's existing Bolna CAUTION is the precedent for saying so plainly rather than overclaiming |

Cross-references: SECURITY-COMPLIANCE §4/§5 · BACKEND-PATTERNS §7 · TRD §11 ·
DATA-MODEL §1/§2 · PLATFORM-CONFIG §3/§4 · ROADMAP §6 D-165.
