# Calevate — Replacing Clerk with a First-Party Auth Module (D-165)

Version 2.0 · 17 Aug 2026 · **BUILT AND MOUNTED. This is now the only authentication this
product has.** Clerk's code paths still exist and still pass their tests; they are dead
weight awaiting deletion, not a live peer. See ROADMAP §6 D-170 / D-171.

> **If you are looking for TOTP, stop.** The second factor is a six-digit code emailed to
> the address on file, and nothing else — no authenticator app, no shared secret, no QR
> code, no recovery codes. All of that was built and then removed on the founder's
> decision (D-170). §2.3 and §7 carry what that trade costs.

This document is the plan for removing Clerk from Calevate and the acceptance criteria
for that removal. §1 is the criteria: a capability missing from that table is a
capability that disappears silently on cutover day. §§2–7 are the design. §8 is what the
reference implementation gives us and what it cannot. §9 is what a person has to decide
before implementation continues.

**What has actually shipped** is now the whole backend: four tables across two migrations,
Argon2id with a KEK-derived pepper, opaque sessions, emailed one-time codes as the second
factor, password reset, email verification, first-party invitation redemption, the
first-administrator bootstrap, step-up re-authentication, and **26 mounted endpoints** —
every one of them in the committed OpenAPI contract, behind
`Settings.first_party_auth_enabled` (default TRUE, a kill switch rather than a cutover
flag). The frontend shipped separately (D-174). **The CSRF double-submit token is not
built and is no longer owed** — D-178 argues it away and closes the same-registrable-domain
hole it would have papered over. §11 is the inventory of what remains.

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
| C-08 | Mandatory MFA on the admin realm | `fva` claim on Clerk's default session token; gate in `verify_token` (D-68) | **An emailed six-digit code, and nothing else (D-170).** A correct admin password issues a session with `mfa_verified_at IS NULL` that can reach exactly one route — `POST /v1/auth/admin/login/otp` — and answering it ROTATES the session. `MFA_REQUIRED_REALMS` is asserted equal to `core/auth.py`'s copy so the sign-in path and the verifier cannot disagree | **shipped:** `tests/authn_mfa_test.py` — password alone yields `otp_required`, the pre-code token dies on rotation, the client realm needs no code (the control), and no TOTP/recovery surface survives anywhere. This is task #66 closed |
| C-09 | Step-up confirmation for high-risk admin acts | `X-Confirm-Action` (ours) + Clerk re-auth | **Both halves, demanded together by `core/stepup.require_step_up` (D-178).** The header still echoes the action (intent); `authn/stepup.py` additionally requires `auth_sessions.mfa_verified_at` to be under `REAUTH_MAX_AGE` (5 min — presence). `POST /v1/auth/admin/step-up` mails a `step_up`-purpose code and `.../step-up/verify` answers it, rotating the session and carrying `absolute_expires_at` forward so re-proving cannot extend a session. This is the flow whose absence `core/auth.py` records as the reason freshness was not enforced on the Clerk credential | **shipped:** `tests/authn_stepup_test.py` — stale refused, fresh passes, never-verified refused, the wrong code refused, a login code cannot answer a step-up prompt (and vice versa), and a census asserting every one of the 15 call sites takes the composed gate |
| C-10 | Mirror identity into our Postgres | `tenancy/clerk_webhooks.py` (Svix HMAC) + `core/clerk_identity.py` JIT reconcile (D-124) | **Deleted, not replaced.** There is no upstream to mirror: `users` becomes the origin of an identity rather than its shadow. The whole `identity_mirror_pending` transient-refusal path and its race disappear with it | **TODO:** delete `tests/identity_mirror_race_test.py`, `tests/clerk_mirror_security_test.py` and the `/hooks/v1/clerk` rate-limit rule in the same change |
| C-11 | Self-serve signup (account, then workspace) | Clerk hosted `/sign-up` mints the account; `POST /v1/auth/signup` creates the org | One flow, ours: email + password + verification → `users` row → `POST /v1/auth/signup` unchanged. `current_identity` keeps its shape (a verified identity with no membership yet) | **TODO** |
| C-12 | Email verification | Clerk | Two mechanisms, both ours: a six-digit OTP (`POST .../otp/request` + `/otp/verify`, 10 min) sets `users.email_verified_at`; and redeeming an invitation sets it directly, because possession of the emailed token IS the proof | **shipped:** `tests/authn_mfa_test.py` (code lifecycle), `tests/authn_flow_rls_test.py` |
| C-13 | Password reset | Clerk | Single-use keyed-hash token, 1 h, revokes every session on use AND invalidates every other outstanding reset (ASVS V7). The request answers 202 with an empty body for known and unknown addresses alike | **shipped:** `tests/authn_enumeration_test.py` — including the deleted-account refusal and the measured timing equalisation |
| C-14 | Team invitations | **Already ours.** `invitations` table, 72 h, hash-at-rest, burned by CAS on `used_at`, read under `app.invite_hash` | **`POST /v1/auth/client/invitations/accept`** takes `{token, password, name}` and does what two calls used to: creates the `users` row, sets the password, burns the invitation through the EXISTING `admin_service.accept_invitation`, and issues a session. The address comes from the INVITATION and never from the request — strictly stronger than the old comparison, and it removes `invitation_wrong_recipient` from this path entirely. The `/invite?token=` page contract is unchanged | **shipped:** `apps/api/authn/invitations.py`; the Clerk `POST /v1/invitations/accept` is untouched and still passes `tests/member_invitations_test.py` |
| C-15 | Client staff roles | **Already ours.** `memberships.role`, `core/rbac.py` policy registry validated at boot | Unchanged | **existing:** `tests/rbac_registry_test.py` |
| C-16 | Operator allowlist | **Already ours.** `admin_users`, ops-managed, never auto-created (`clerk_identity.py` is explicit that auto-creating one is "privilege escalation wearing a race condition's clothes") | `admin_users` gains `email` (unique on `lower(email)`); `clerk_user_id` drops NOT NULL. `scripts/bootstrap_admin.py` takes `--email` and mails a single-use setup link — **the first administrator now arrives by invite** (D-171, §11) | **shipped:** `tests/authn_bootstrap_test.py` (12 cases); `tests/admin_identity_test.py` unchanged |
| C-17 | Instant deactivation despite a cached session | `users.deactivated_at` re-read on every request (BACKEND-PATTERNS §7) | Unchanged — and strictly better, because the session itself is now revocable rather than only the authorization built on it | **existing:** `tests/api_security_test.py` |
| C-18 | D-22 impersonation and its audit trail | **Already ours.** `core/impersonation.py` mints an RFC-8693-shaped grant signed with `IMPERSONATION_GRANT_SECRET`; `_load_admin_principal` verifies it and writes `admin.impersonation_read` | Unchanged. The grant is deliberately NOT a credential — it is presented alongside the operator's own session — so replacing what that session IS changes nothing about it | **existing:** `tests/impersonation_grant_test.py`, `tests/impersonation_audit_test.py` |
| C-19 | Per-caller rate limiting | `RateLimitMiddleware._caller` keys on `bearer_token(...)` | Same function, now reading the session cookie as well as the header. **The bucket key must become the session id, not the raw token** — a rotated session must not get a fresh bucket | **TODO**, with a test that rotation does not reset the bucket |
| C-20 | Readiness gate on auth configuration | `runtime_config_missing_keys` reports `CLERK_*` keys; `missing_realm_separation_keys` reports a collapsed realm pair | Replaced by: `PLATFORM_KEK` present (already reported), and a new check that the two realms' cookie names and CORS origins differ | **TODO** |
| C-21 | Local development without a vendor | `dev:<realm>:<id>` tokens, accepted only when `APP_ENV=local` AND the realm has no Clerk secret | A seeded local password, or the same dev-token shape re-pointed at `authn`. The two guards must survive verbatim — `tests/authz_audit_test.py` pins them | **existing test, new subject** |
| C-22 | Browser session lifecycle | `@clerk/nextjs` `ClerkProvider`, `getToken()`, `RedirectToSignIn`, hosted sign-in UI | Ours: an `HttpOnly` cookie the browser never reads, a `GET /v1/auth/session` bootstrap call, our own sign-in pages (§6) | **shipped:** ten screens, D-174. The CSRF token this row used to owe is retired rather than outstanding — §11 |
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

### 2.2 What migration `b3d9f6a2c815` added

| Table / column | Holds | Notes |
|---|---|---|
| `auth_email_tokens` | `purpose`, `realm`, `subject_id` XOR `invitation_id`, `token_hash`, `expires_at`, `used_at` | **Four** purposes — `email_verify` (24 h), `password_reset` (1 h), `invite_password` (72 h), `admin_bootstrap` (60 min, D-171). The purpose is INSIDE the hash domain, so a verification token presented at the reset endpoint is not "the wrong purpose", it is 32 bytes matching no row. Burned by `UPDATE … RETURNING` on `used_at IS NULL` — one statement, so two concurrent clicks cannot both be told they won |
| `auth_otp_challenges` | `purpose`, `realm`, `subject_id`, `code_hash`, `expires_at`, `consumed_at`, `attempts` | The second factor (`login_challenge`) and the email-verification code. Six digits, ten minutes, **five guesses on the row** — a ceiling that survives a Redis flush, which is the half an attacker cannot reset. `code_hash` is an HMAC under a `PLATFORM_KEK`-derived key, never a bare digest (§4) |
| `users.email_verified_at` | on the existing table | What `accept_invitation`'s recipient binding trusts instead of "Clerk said so" |
| `admin_users.email` | on the existing table | Unique on `lower(email)`. The admin realm had no address of its own; a first-party operator signs in with one |
| `users.clerk_user_id`, `admin_users.clerk_user_id` | NOT NULL dropped | Step 1 of hard rule 8's two-step. Both columns still exist and every Clerk path still writes them; they simply stop being mandatory, because a first-party account has no vendor id. UNIQUE survives — Postgres treats NULLs as distinct. **Dropping them is a later release.** |

**NOT added, and deliberately: `auth_mfa_secrets` and `auth_recovery_codes`.** Version 1.0
of this document specified both, on a design where the second factor was TOTP. Both were
built and then removed (D-170). Shipping the tables anyway would be a table nothing writes
and a column nothing reads — the half-wired defect `scripts/check_wiring.py` exists to
catch. If TOTP is ever wanted it is a migration written then, against a design made then.

**Also not added, and now permanently: `users.password_migrated_at`.** It was specified as
the cutover's progress column. D-178 retires the promise rather than deferring it: D-170
makes first-party auth the ONLY authenticator, so there is no population of Clerk-era
passwords to migrate — Clerk never gave us a hash — and every account acquires its
first-party password by redeeming a link, which `auth_credentials.password_set_at` already
timestamps. The column would be a second, emptier copy of a fact the credential row holds.

**Closed by `c7a1e93d40b8` (D-178): `users` now carries `uq_users_email_lower`** — unique
on `lower(email)` WHERE `deactivated_at IS NULL`. The predicate is the one departure from
`admin_users`' index and is what makes the two express the same rule: "at most one LIVE
account per address" is exactly what `subjects._CLIENT_SELECT` and
`invitations._find_or_create_user` already assumed, and `admin_users` has no soft-delete to
predicate on. Without it, an SMB owner whose account was deactivated could never be
re-onboarded under their own address. The migration REFUSES BEFORE WRITING if live rows
already collide, printing the row ids and never the addresses (hard rule 6). Not
`CONCURRENTLY`: that cannot run in a transaction, can leave an INVALID index behind, and
buys nothing on a table holding tens of rows.

`subjects.resolve_by_email`'s ambiguity refusal STAYS — a guard made true by a constraint is
what fails safe if the constraint is ever dropped — and `_find_or_create_user`'s
read-then-write became `ON CONFLICT (lower(email)) WHERE deactivated_at IS NULL DO NOTHING`
plus a re-read, so the "two invitations to one address in the same millisecond" race is
decided by the database rather than by arrival order.

### 2.3 What is deliberately NOT a table

- **Login throttling and lockout.** Redis, via `core/ratelimit.py`, which already owns the
  vocabulary of "per caller, per IP, per tenant". A `failed_attempts` column would be a
  second answer to a question this repo already answers, and a durable lockout counter is
  a denial-of-service primitive an attacker can aim at a known account.
- **A session denylist.** The sessions are opaque; the row *is* the authority.
- **Password history.** A previous hash is a liability with no reader. "When did this
  password last change" is what a support conversation needs, and `password_set_at`
  carries it.
- **TOTP, and recovery codes — not a table, and not built at all (D-170).** The second
  factor is the emailed OTP challenge and nothing else. **The cost, stated plainly: the
  strength of the admin realm's second factor is the strength of the operator's mailbox.**
  It defends against a stolen password; it does not defend against a compromised email
  account, which a TOTP secret would. What it buys is one mechanism instead of three —
  secret storage, enrolment, recovery — no device to lose, and no enrolment step standing
  between a fresh deployment and a usable console. If a client or a regulator ever requires
  a phishing-resistant factor, the right thing to build then is WebAuthn, not the TOTP that
  was removed.

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
| One-time codes and emailed tokens | HKDF-SHA-256(`PLATFORM_KEK`, info=`calevate/auth-code-key/v1`), used as an HMAC key | RFC 5869 key SEPARATION from the password pepper — a distinct `info`, one derivation function (`hashing.derived_ring`), so the two cannot drift in construction or be traded for one another. Rides the KEK ring the same way; verification walks every generation, so a rotation does not invalidate a link somebody is about to click. **This is what makes a 6-digit code safe to store**: the key is not in the database, so the 900,000-entry rainbow table cannot be built from a dump |
| ~~TOTP secret at rest~~ | — | **Removed (D-170).** There is no TOTP and no `auth_mfa_secrets` table, so there is no third key material. The AAD scheme this row specified is not in use |

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

> **Version 2.0 note.** This section was written when Clerk was a live peer and the plan
> was a flag-gated migration beside it. **That is no longer the plan** (D-170): Clerk is
> being removed entirely and the first-party module is the system of record. Steps 1–3 are
> DONE; step 4 is replaced by D-171's bootstrap for operators and by invitation redemption
> for client users; step 5's flag is now a kill switch that ships ON. Steps 6 and 7 are the
> remaining work and are unchanged in substance — they are the next slice. The original
> sequence is kept below because its REVERSIBILITY analysis is still the right analysis and
> step 6 is still the irreversible one.

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
  **Ours is an EMAILED code and it is the second factor itself** (D-170) — `authn/otp.py`,
  rewritten in Python, with the two defects of theirs designed out (unkeyed SHA-256 over a
  6-digit code; a generator that never returns its own stated maximum).
  **SMS OTP is specifically not adopted**: NIST SP 800-63B-4 classifies SMS/PSTN one-time
  passcodes as a *restricted authenticator*, which imposes obligations on the relying party
  rather than forbidding it, and email is the channel we already have a transport for. The
  channel split (`otp-channel.ts`) is therefore not ported — there is one channel.
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

## 10.5 The endpoint surface, as built

Two realms, two independent routers from one factory whose realm is a **closure constant**
rather than a runtime branch — so there is no request-time input that can move a handler
between realms, which is the hazard §3 warns about. `{realm}` is `admin` or `client` and
appears as a literal in every path.

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/v1/auth/{realm}/login` | none | `{email, password}` → `authenticated` or `otp_required`; sets the cookie either way |
| POST | `/v1/auth/{realm}/login/otp` | live session | The second factor. Rotates the session |
| POST | `/v1/auth/{realm}/login/otp/resend` | live session | 202. A new code retires the old one |
| GET | `/v1/auth/{realm}/session` | authenticated | Bootstrap call; re-reads the subject, so deactivation bites here |
| POST | `/v1/auth/{realm}/session/refresh` | authenticated | Fresh token, same lifetime, same MFA state |
| POST | `/v1/auth/{realm}/logout` | live session | Deliberately `live`, not `authenticated` — an abandoned MFA prompt must be able to sign itself out |
| POST | `/v1/auth/{realm}/logout/all` | authenticated | Every session in this realm |
| POST | `/v1/auth/{realm}/password/reset/request` | none | **202, empty body, always** |
| POST | `/v1/auth/{realm}/password/reset/confirm` | none | 204. Revokes every session |
| POST | `/v1/auth/{realm}/otp/request` | authenticated | Email verification. Scoped to the caller's OWN subject — no address parameter |
| POST | `/v1/auth/{realm}/otp/verify` | authenticated | 204 |
| POST | `/v1/auth/{realm}/step-up` | authenticated | 202. Admin realm ONLY. Mails a `step_up`-purpose code before a dangerous mutation. D-178 |
| POST | `/v1/auth/{realm}/step-up/verify` | authenticated | Admin realm ONLY. Rotates the session with `mfa_verified_at = now`, carrying the absolute bound forward |
| POST | `/v1/auth/admin/bootstrap/confirm` | none | Admin realm ONLY (not declared on the client router, so it 404s there). D-171 |
| POST | `/v1/auth/client/invitations/accept` | none | `{token, password, name}` → account + membership + session |

Every failure is RFC-9457 problem+json. `first_party_auth_disabled` (403) when the kill
switch is off; `invalid_credentials` (401) for every sign-in failure including unknown and
deactivated accounts; `invalid_second_factor` (401); `invalid_reset_token` /
`invalid_bootstrap_token` / `invitation_invalid` (422); `cross_site_request` (403);
`step_up_required` / `reauthentication_required` (403, from `core/stepup.py` on the
dangerous mutations elsewhere in the API); `too_many_attempts` (429, with `Retry-After`);
`rate_limited` (429, from the middleware).

**No route here honours `Idempotency-Key`** — D-178, argued in §11 and in
`authn/routes.py`'s module docstring.

---

## 11. What is NOT built

Named so the next reader does not have to discover it. **Four entries that used to be here
are gone — three built, one retired — and each says which, because a list that only ever
grows is a list nobody reads.**

- **Self-serve signup's public intake (C-11).** The credential half exists; the flow that
  chains it to `POST /v1/auth/signup` does not. Invitation redemption is the path that
  works end to end today.
- **Deleting Clerk (§5 step 6).** Every Clerk path still exists and still passes. This
  change deliberately breaks none of them. The `clerk_user_id` DROP is the second step of
  hard rule 8's two-step and belongs to that change (§2.2).
- **Turnstile / bot detection and breached-password checks (C-23, C-24).** Unchanged
  accepted risk from §7.
- **A real email transport.** External blocker (§9 Q2) — a vendor account, not an
  engineering task. Until one exists, the bootstrap link is read off the operator's own
  terminal and every other code is delivered by whatever `get_transport()` resolves to.

### What left this list, and how (D-178)

- **The frontend — BUILT.** Ten screens, D-174. §6 is the design it was built from.
- **Step-up re-authentication (C-09) — BUILT.** `core/stepup.require_step_up` now demands
  intent (the `X-Confirm-Action` echo) AND presence (`mfa_verified_at` under five minutes,
  read by `authn/stepup.py`), and `POST /v1/auth/admin/step-up{,/verify}` is the flow that
  clears it. `core/auth.py` records that freshness was not enforced on the Clerk credential
  because there was no browser flow to raise the prompt; D-170 built one, so the objection
  was spent.
- **`users.email` uniqueness — BUILT.** `uq_users_email_lower`, migration `c7a1e93d40b8`.
  §2.2 carries the shape and the predicate's reasoning.
- **The CSRF double-submit token — RETIRED, not deferred.** OWASP's CSRF cheat sheet (read
  2026-08-17) lists the conditions under which `Origin` verification plus `SameSite` is
  sufficient without a token: no shared registrable domain, no state change via GET,
  `SameSite=Strict`, `Origin`/`Referer` verified, browser-support gap accepted. We met four
  outright. **The one we did not meet was the first, and it was a live hole rather than a
  caveat**: `admin.calevate.tech`, `app.calevate.tech` and the API share one registrable
  domain, so any `*.calevate.tech` host issues requests the browser labels `same-site` with
  the session cookie attached — and `enforce_same_origin` returned early on `same-site`
  without consulting the allowlist. `SameSite=Strict` does not stop it (it is not
  cross-site) and `__Host-` does not stop it (that prefix stops a sibling SETTING the
  cookie, not the browser sending it).

  The fix is three lines, not a token: the `Origin` is checked whenever it is present, and
  `core/middleware.CookieCsrfMiddleware` applies the same rule to EVERY mutating request
  carrying one of our cookies, so the argument stays true of the whole API on the day
  cookies authenticate the whole API. What a token would still buy is defence against a
  same-site attacker who can also forge the `Origin` header, which browsers do not permit
  page script to do; what it would cost is a secret to distribute, a header on every
  mutating request in the generated client, and an "absent" branch that is either a header
  nothing sends or a check that defends nothing. `tests/authn_csrf_test.py` drives the hole
  from the attacker's side.
- **`users.password_migrated_at` — RETIRED.** There is no population of Clerk-era passwords
  to migrate (Clerk never gave us a hash), and `auth_credentials.password_set_at` already
  carries the fact it would have held. §2.2.
- **`Idempotency-Key` on `/v1/auth/**` — DECIDED AGAINST, and it is a decision rather than a
  gap.** The header is allowed through CORS and the frontend's reset forms send one; no auth
  route takes the dependency and none will. The reason is the SCOPE: `reliability.scope_key`
  takes `tenant_id`/`user_id` as `UUID | None` and nothing else, because a replay cache two
  strangers can share serves caller A caller B's stored response (`scripts/check_idempotency_scope.py`,
  D-175, written after a reference platform fell back to the client address). The auth routes
  a double submit could hurt are the UNAUTHENTICATED ones, and an unauthenticated caller has
  no principal — the only candidate scopes are the submitted address (any stranger can type
  it) and the socket peer (the D-175 defect verbatim). Weakening the guard to fit was not on
  the table. What answers the double submit instead is per-route and stronger: the reset,
  bootstrap and invitation confirmations burn their token with ONE `UPDATE … WHERE used_at
  IS NULL … RETURNING`, so exactly one of two concurrent submissions wins at the database;
  the request/resend routes retire the previous secret when they issue the next, so a double
  click leaves one live key rather than two. `tests/authn_idempotency_test.py` asserts the
  absence as a property and drives both.

  The second click on a spent reset link is answered 422 rather than replayed, and that is
  correct rather than a wart: nothing here can distinguish the person who double-clicked
  from somebody replaying a leaked link, and the safe answer to both is the same.

---

## 12. What shipped with version 1.0 of this document

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
| ~~**RFC 6238** (TOTP)~~ | 2026-08-17 | **No longer load-bearing.** It informed the TOTP implementation that was built and then removed (D-170). Kept as a row so a reader who remembers the citation learns why it is gone rather than assuming the parameters are still in force somewhere |
| OWASP **Authentication Cheat Sheet** — `github.com/OWASP/CheatSheetSeries`, `cheatsheets/Authentication_Cheat_Sheet.md` | 2026-08-17 | Generic "invalid user ID or password" on login and a non-committal reset response; the timing-equalisation argument (check-user-first quick-exit vs always hashing); lockout attaches to the ACCOUNT not the source address; exponential backoff from one second as the alternative to a hard lock |
| OWASP **Forgot Password Cheat Sheet** — same repository | 2026-08-17 | CSPRNG token "long enough to protect against brute-force"; expiry, single use, hashed at rest; invalidate sessions on reset; a consistent message AND a consistent RESPONSE TIME for existent and non-existent accounts |
| OWASP **Multifactor Authentication Cheat Sheet** — same repository | 2026-08-17 | One-time codes are single-use and must be invalidated on successful verification — the rule `auth_otp_challenges.consumed_at` implements |
| **NIST SP 800-63B** — `pages.nist.gov/800-63-4/sp800-63b` | 2026-08-17 | A verifier SHALL limit consecutive failed attempts on one account to ≤100, lower limits permitted; an increasing wait as the mitigation for lockout-as-DoS; **rate limiting REQUIRED whenever an authenticator output carries fewer than 64 bits of entropy** — which a 6-digit code does, and which is why the OTP has two independent budgets |
| **RFC 5869** (HKDF) | prior art, cited 2026-08-17 | Extract-then-expand; salt optional when the input keying material is already uniformly random (§3.1) — the pepper derivation |
| **RFC 9700** §4.14.2 (OAuth 2.0 Security BCP) | via the reference implementation's own citation, 2026-08-17 | Refresh-token reuse detection → revoke the family. Adapted to sessions |
| **draft-ietf-httpbis-rfc6265bis** (Cookies) — `datatracker.ietf.org` (`httpwg.org` is blocked from this host) | 2026-08-17 | "same site" is decided by the **registrable domain**, so `admin.calevate.tech` → `api.calevate.tech` is same-site and `SameSite` does not separate the realms; `__Host-` requires `Secure`, `Path=/` and no `Domain` |
| **argon2-cffi** 25.1.0, released 2025-06-03 — `pypi.org/project/argon2-cffi` | 2026-08-17 | Library version, maintenance status, `PasswordHasher` / `verify` / `check_needs_rehash` API, and the library defaults (`m=65536,t=3,p=4`) this repo overrides |
| **DPDP Act 2023** + **DPDP Rules 2025** (notified 13 Nov 2025; Schedule 1 penalties from 13 May 2027) | 2026-08-17 | The residency driver. The Act does not blanket-prohibit cross-border transfer — §16 permits it except to countries the Central Government restricts, and the Rules add conditions — so **Clerk is not per se unlawful.** What it is, is a foreign sub-processor holding identity data that has to be disclosed in every client DPA, kept in the sub-processor list, and defended in every enterprise conversation, while the rest of the stack is being pinned to India. Bringing authentication in-house removes a named sub-processor, shortens the breach-notification surface (a Clerk incident is our reportable incident), and makes DPDP erasure a single-database operation instead of a two-system one. **That is the honest framing: a posture and disclosure improvement, not the closing of a legal violation** — and SECURITY-COMPLIANCE §4's existing Bolna CAUTION is the precedent for saying so plainly rather than overclaiming |

Cross-references: SECURITY-COMPLIANCE §4/§5 · BACKEND-PATTERNS §7 · TRD §11 ·
DATA-MODEL §1/§2 · PLATFORM-CONFIG §3/§4 · ROADMAP §6 D-165.
