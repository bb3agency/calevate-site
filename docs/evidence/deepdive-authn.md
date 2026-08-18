# Deep-dive authentication pass — the first-party surface (D-198)

**Why this pass exists.** `docs/evidence/audit-2026-08-17-register.md` records one coverage
gap by name: the frontend pass read the tree mid-flight while `lib/auth/**` was still Clerk.
Clerk is gone (D-177). `apps/api/authn/` is the only thing that mints a credential, the
credential is an `HttpOnly` `__Host-` cookie, and `apps/web/src/lib/authn/` holds two
separate first-party session modules. **None of that had ever been audited.**

**Posture.** An attacker with a valid low-privilege account in either realm, plus — for the
cookie finding — control of one host under `*.calevate.tech`, which is the threat model
`authn/cookies.py`'s own docstring already accepts as realistic (a compromised marketing
subdomain, a dangling CNAME, a takeover of something nobody thought was
security-relevant).

**Marking.** Every claim is **PROVEN** (executed against the live app or the live module and
the result quoted) or **REASONED** (read, not run).

**Scope.** `apps/api/authn/**`, `core/auth.py`, `core/stepup.py`, `core/deps.py`, the
`apps/api/admin/` invitation and impersonation paths, `apps/web/src/lib/authn/**` and the
login / invite / MFA / reset screens of both realms.

---

## Environment note, because it changes what "I ran it" means

The shared development database was **≈50 migrations behind this tree** when this pass
started: `alembic current` reported `c1f3a7d92b46` against a head of `e7b45c19a308`, and
`SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'auth%'` returned
**zero rows** — the entire first-party authentication schema was absent, and
`users.clerk_user_id` was still `NOT NULL`, which alone makes every invitation redemption a
500. A first `alembic upgrade head` against it failed on `ux_credit_ledger_tenant_reason_ref
already exists` (a `CREATE INDEX CONCURRENTLY` from a sibling's partial run, which cannot be
stamped inside a transaction), stamping nothing and creating nothing.

Rather than fight shared state that four other sessions depend on, this pass created its own
database — `calevate_authn_audit` on the same cluster, same roles — migrated it to head and
seeded it. **Nothing in the shared `calevate` database was migrated, dropped or truncated by
this pass.** The consequence for whoever merges: the shared database still cannot run any
`authn` test, and will need `alembic upgrade head` (with that duplicate index dropped or the
revision stamped by hand) before it can.

---

## FINDING 1 — the `__Host-` prefix was defending nothing, because an unprefixed alias of the same cookie was still read (**PROVEN**)

**Class:** OWASP session fixation / cookie-prefix bypass. **Severity:** high — full account
takeover of a signed-out visitor, surviving sign-out. **Status:** FIXED, sabotage-verified.

### The mechanism

`authn/cookies.py`'s module docstring states the claim the design leans on:

> `__Host-` prefix — … It makes the cookie host-only to the API origin, so no sibling
> subdomain and no compromised `*.calevate.tech` host can set or overwrite it. This is the
> one attribute that defends against cookie FIXATION from a neighbouring host.

That is true of the **prefixed** name and of nothing else. `read_token` was:

```python
for secure in (True, False):
    token = request.cookies.get(cookie_name(realm, secure=secure))
    if token:
        return token
return None
```

`cookie_name(realm, secure=False)` is the same name with `__Host-` stripped — it exists for
plain-HTTP local development, where a browser refuses a `__Host-` cookie outright. The loop
ran on **every** request, whatever the scheme. So a page on any host under the registrable
domain could set

```
calevate_client_session=<a session token the attacker holds>; Domain=.calevate.tech; Path=/
```

and the browser attaches it to `api.calevate.tech`. The prefix stopped a sibling
**replacing** the credential; it did not stop the sibling **supplying** one.

### Proven

Executed against the live module with a request whose scheme is `https` and whose only
cookie is the unprefixed name:

```
scheme https, secure? True
secure name: __Host-calevate_client_session
read_token over TLS with only the UNPREFIXED cookie -> ATTACKER_FIXED_VALUE
```

### What that reaches, end to end, with no other defect anywhere

1. The sibling host plants the cookie.
2. A visitor who is **not signed in** opens the console and is silently signed in as the
   attacker. Every lead they enter, every number they configure, lands in the attacker's
   tenant. This is textbook session fixation, arriving through the one door the design left
   open.
3. Signing out does not undo it. `clear_session_cookie` calls `delete_cookie(path="/")`,
   which expires a **host-only** cookie; a `Domain=`-scoped cookie is a different cookie to
   the browser, is untouched, and is sent again on the next request. The victim is signed
   back into the attacker's account without a second visit.

Rotation on sign-in — which `sessions.py` implements correctly and argues at length — closes
nothing here, because the fixated session is never the victim's to rotate.

### The fix

`read_token` now reads **one** name per request, chosen by `_is_secure(request)` — the same
predicate `set_session_cookie` uses to decide which name to write, so read and write cannot
disagree about which name a deployment speaks. `_is_secure` reads `request.url.scheme` and
falls back to `X-Forwarded-Proto`, so a deployment terminating TLS at nginx is covered; a
test drives that case specifically, because a fix that only read `request.url.scheme` would
be correct in a test and absent in production.

**Rejected: preferring the prefixed name when both are present.** It leaves the stripped
name a live credential exactly when there is no prefixed one to prefer — which is the
signed-out visitor the attack targets.

**Cost, stated:** a deployment that gains TLS between a sign-in and the next request stops
reading the cookie it wrote, and the person signs in again. Once per deployment, in the safe
direction, and `clear_session_cookie` still clears both names so nothing rots in the browser.

**Test:** `tests/authn_cookie_prefix_test.py` (13 cases). Sabotage: restoring the two-name
loop turns exactly the 4 attacker-side cases red; the 9 controls — local HTTP, read/write
agreement, both-names-present, sign-out clearing, cross-realm — stay green, so the test
cannot pass by refusing everything.

---

## FINDING 2 — the password-reset form throttled only the addresses that do not exist (**PROVEN**)

**Class:** user enumeration (OWASP Authentication Cheat Sheet) plus unbounded outbound mail.
**Severity:** medium. **Status:** FIXED, sabotage-verified.

### The mechanism

`throttle.pseudo_subject`'s docstring names this exact back door and closes it on the
sign-in path:

> THE POINT IS THAT AN UNKNOWN ACCOUNT IS THROTTLED EXACTLY LIKE A KNOWN ONE. If the unknown
> path skipped the counter, an attacker could tell real addresses from fake ones by whether a
> burst of attempts eventually produced a 429.

`request_password_reset` had it in the **mirror image** — the throttle call sat *inside* the
`subject is None` arm, so the address that resolves to a real account was never counted at
all. The reset form is the worse place for it: taking an arbitrary stranger's address is its
entire input, so there is no password to guess first and no account to hold.

### Proven

```
KNOWN  : ['202', '202', '202', '202', '202', '202', '202', '202']
UNKNOWN: ['202', '202', '202', '202', '202', 'too_many_attempts', 'too_many_attempts', 'too_many_attempts']
ORACLE : True
reset tokens minted (= emails queued) for the known address: 8
```

Eight requests, eight reset emails to a real mailbox. The caller-keyed request limiter
(`auth` profile, 20/min) is the dimension a distributed attacker simply spreads across; the
per-account budget is the one they cannot.

### The fix

The budget key is chosen **before** the branch — `subject.subject_id`, or the stable
`pseudo_subject` derived from the address — and `check` + `record_failure` run identically on
both paths, in the same order, before anything else happens.

**It is a new budget, `throttle.RESET_BUDGET` (5 per address per realm per 15 minutes), and
deliberately not `OTP_BUDGET`.** That is the security-relevant half of the fix.
`OTP_BUDGET` is the five guesses a person has against their own emailed second factor; the
unknown arm was spending it, which was harmless only because it was spending it against
addresses that do not exist. Symmetrising onto `OTP_BUDGET` would have meant five
unauthenticated reset requests aimed at an operator's address locking that operator out of
finishing a sign-in for ten minutes — a remote denial of service against the admin realm's
**only** second factor, introduced by the fix for an oracle.
`test_reset_requests_do_not_spend_the_second_factor_budget` is the assertion that would go
red if the two were ever merged.

`confirm_password_reset` clears the budget: redeeming a link proves the mailbox, and leaving
the counter spent would refuse the next legitimate reset to somebody who needed two attempts
to find the right email.

**Test:** `tests/authn_reset_throttle_test.py` (4 cases). Sabotage: restoring the
inside-the-branch call turns all 4 red.

### NOT FIXED, named and measured: the wall clock

The known path invalidates outstanding tokens, inserts a token, enqueues mail and appends to
the audit chain (which takes the chain's advisory lock). The unknown path does none of it.
Measured on this hardware, medians of nine runs each:

```
known median      8.13 ms
unknown median    2.40 ms
ratio             3.39x
```

`request_password_reset`'s docstring **claimed** the two paths did "the same quantity of
work". That was never true, and the claim is why nobody measured. It now states the number.

Equalising it is refused rather than deferred: the only honest equaliser is giving the
unknown path an Argon2 verification it has no reason to perform, which hands an
unauthenticated caller 20–30 ms of CPU per request to close a 5.7 ms gap that sits inside
ordinary internet jitter — a denial-of-service lever bought for nothing. The oracle an
attacker could actually read off a response was the 429, and it is closed. **What would
change this answer:** a deployment where the reset route is reachable over a low-jitter link
(a LAN, a co-located attacker), where 5.7 ms becomes separable with enough samples.

---

## FINDING 3 — the admin realm's invitation still handed the operator a live credential, and mailed nobody (**PROVEN**)

**Class:** credential disclosure to a party other than the intended holder; plus a
half-wired seam. **Severity:** medium. **Status:** FIXED, sabotage-verified.

### The mechanism

D-185 found that anyone who can see an invitation token can redeem it, taking the **global**
`users` row for that address (`uq_users_email_lower` makes it the only row) with a password
they chose. It said in as many words that it stopped the escalation and could not stop the
squat, and named what closes it: the token reaching only the invitee. D-190 did that on the
client realm — `InviteOut.token` became `delivery`, and `tenancy/routes.invite_member` began
enqueuing the mail in the invitation's own transaction.

**Its twin was left behind.** `POST /v1/admin/tenants/{tenant_id}/invitations` — the
onboarding wizard's step-8 owner invite — still returned the raw token and mailed nothing at
all. The admin console rendered it on screen under "Copy this now — it is not shown again".

An operator is a narrower attacker than "any tenant owner", which is presumably why the
first pass stopped there. It is not *no* attacker: `admin:tenants` is held by every
`operator`, an invitation may name any address, and the resulting `users` row is global.

The half nobody had called a defect at all is the **seam**: the invitee was told by nobody,
so the one flow that onboards every client depended on a human copying a credential out of an
API response into some other channel.

### Proven

`test_the_operator_is_not_handed_the_token_and_the_invitee_is_mailed_it` fails on the
pre-fix code at the first assertion (`"token" not in body`) and, with the enqueue removed,
at `"the invitee was told by nobody — the seam is not finished"`.

### The fix

The route calls the existing `authn.service.enqueue_invitation_email` inside the
invitation's own `tenant_session`, so the row and its mail share one fate
(BACKEND-PATTERNS §4), and `InviteOut.token` becomes `delivery`. This is D-190's change
applied to the route it was not applied to — not a second mechanism.

Callers moved in the same change, per "migrate rather than accumulate":

- `tests/member_invitations_test._mailed_token` became the public
  `mailed_invitation_token`, and `tests/tenant_birth_test.py` and
  `tests/onboarding_to_live_test.py` import it instead of reading `json()["token"]`. One
  spelling of "read the token out of the mail", for both routes.
- `apps/web/src/app/admin/new/page.tsx`'s `CreatedPanel` confirms the address the link went
  to instead of rendering the secret; `apps/web/tests/newClient.test.tsx` asserts the
  rendered output contains no token, which is the inversion D-190 made to the client
  realm's equivalent test.
- OpenAPI snapshot and `schema.d.ts` regenerated.

**Test:** `tests/admin_invitation_delivery_test.py` (3 cases). Sabotage: putting the token
back in `delivery` and removing the enqueue turns all 3 red.

---

## What was hunted and found sound

A negative result from a real attempt is evidence, so each of these says what was actually
tried.

### Session lifecycle — clean (REASONED, with PROVEN spot checks)

- **Rotation on privilege change** is present at every one of them: sign-in mints a new
  family; second-factor completion rotates (`complete_second_factor`); step-up rotates
  (`complete_step_up`); `refresh` rotates. `rotate_session` carries `absolute_expires_at`
  forward, so no rotation can extend a session past the bound it was born with, and
  `mfa_verified_at` defaults to the old value so an ordinary rotation cannot silently
  downgrade a session that had completed a factor.
- **Reuse detection** is RFC 9700 §4.14.2 with no grace window, and `verify_session` owns
  its own transaction specifically so the family revocation survives the refusal it causes.
  The existing `tests/authn_session_test.py` drives it (19 cases, all green here).
- **Logout invalidates server-side**, not just the cookie: `revoke_session` writes
  `revoked_at` under a CAS on `revoked_at IS NULL`, so a second sign-out cannot overwrite a
  `reuse_detected` reason with `signed_out` and erase the only trace of a leak. Logout
  depends on `live` rather than `authed`, deliberately, so an operator who abandons an MFA
  prompt can drop the partial session.
- **Logout in one realm does not touch the other**, and should not: the realms are separate
  systems and an operator's console session says nothing about a client account they may
  also hold. `revoke_subject_sessions` is realm-scoped for the same reason.
- **There is no in-session "change my password" route**, so the "rotate on password change"
  obligation is discharged by the reset path, which revokes every session for the subject
  (`confirm_password_reset`) as ASVS V7 requires. Recorded as an observation, not a finding:
  nothing half-wired, the capability simply does not exist yet.
- **Signing in again leaves the previous session row live** until its own idle/absolute
  bound. Considered and not filed: nobody holds that token (the cookie was replaced), it
  expires on its own, and multi-device sessions are the reason the behaviour is right.

### Cookie mechanics — one finding (above), rest clean

`Secure`, `Path=/`, no `Domain`, `HttpOnly`, `SameSite=Strict`, and no `Max-Age` (the row is
the authority) are all as the docstring says. The CSRF layer's `Origin`-always check is
correct and already measured by `tests/authn_csrf_test.py` including the sibling-subdomain
case. `session_cookie_present` deliberately matches **both** names for the CSRF middleware,
and that stays: a false positive there only means the origin check runs on a request that
would have passed it.

### The credential itself — clean (REASONED)

256 bits from `secrets.token_urlsafe`; stored as SHA-256 over a **realm-separated** domain,
so a leaked row is not replayable and a cross-realm lookup cannot match as a matter of
arithmetic rather than a `WHERE` clause. A fast hash is correct here and the module argues
why. Passwords are Argon2id at OWASP configuration 2 of 5 over an HKDF-derived pepper from
`PLATFORM_KEK` — env-only by construction and by CI — so a database dump is 32 unknown bytes
away from being useless. `check_needs_rehash` plus the pepper ring drains a KEK rotation
lazily. Unknown-subject verification runs a real Argon2 against a cached dummy hash, and
`tests/authn_enumeration_test.py` measures the timing rather than asserting it.

### Invitations — one finding (above), rest clean

Token is `secrets.token_urlsafe(32)`; single-use is a CAS (`UPDATE … WHERE used_at IS NULL …
RETURNING`) so two tabs produce one winner and one clean refusal; 72 hours matches the
`invite_password` email token's lifetime so the two clocks cannot disagree; unknown, used
and expired all produce one `invitation_invalid` sentence, so a spent token does not reveal
that it was ever real. The tenant comes from the invitation row and the address comes from
the invitation row — a redeemer cannot attach themselves to a tenant they were not invited
to, and cannot influence which address the account is created for. D-185's reuse condition
(an existing account with a password must have a verified address before joining a second
organisation) is present and ordered before the burn, so a refusal leaves the invitation
redeemable by the real owner.

**One rough edge, filed as an observation rather than a finding:** two tabs racing one
invitation both create/find the `users` row and set the password before the CAS decides, so
the loser leaves an account with a password and no membership. It is not a privilege issue
(`_load_client_principal` refuses a member of nothing), it is not reachable by an attacker
who does not already hold the link, and the account is the invitee's own. Named so it is not
rediscovered as a finding.

### MFA — clean (REASONED)

There is no TOTP, no enrolment and no recovery-code sheet; D-170 removed them and the code
says so loudly, so "recovery codes single-use / rate-limited / hashed" has no subject here.
What exists: the emailed six-digit code, HMAC'd under a `PLATFORM_KEK`-derived key that is
not in the database (the reference implementation's unkeyed `sha256(code)` over 900,000
possible codes is the cautionary case, and `codes.py` argues it), a five-guess ceiling **on
the row** and a five-failure budget in Redis, with issuing a new code retiring the previous
one so "resend" cannot multiply the guess budget.

**Can MFA be skipped by hitting a later step directly? No.** `verify_token` applies
`_require_second_factor` for every admin-realm credential, so there is no
`VerifiedCaller(realm="admin")` in existence that skipped it; `authn/routes._authenticated`
applies the same rule on the auth router itself; and `tests/authn_mfa_test.py` asserts the
two copies of `MFA_REQUIRED_REALMS` are the same set. The partial session opens exactly one
door. The two OTP purposes (`login_challenge`, `step_up`) are inside the HMAC domain, so one
cannot answer the other.

**One arithmetic note:** an attacker holding a correct admin password can have both a login
challenge and a step-up challenge live at once, since `issue_challenge` retires only its own
purpose — 10 guesses per window against a 20-bit secret instead of 5. Not filed: 10 in
900,000 is not a threat, and merging the purposes would reintroduce the confusion the
separation exists to prevent.

### Step-up (D-178) — the gate is whole (REASONED)

`core/stepup.StepUp.require` demands both halves — the `X-Confirm-Action` echo and a second
factor proved within `REAUTH_MAX_AGE` (5 minutes) — and the permissive branch the brief asked
about is now `if dev_tokens_permitted(): return`, which is `APP_ENV=local` **and** no
`PLATFORM_KEK`, i.e. the same two conditions that already gate accepting a `dev:` token at
all. `is_fresh(None)` is False, so a session that never proved a factor is refused rather
than waved through. All 15 call sites take the gate as a `Depends`, which is what makes the
pairing structural: `gate.require(...)` cannot be written without a `gate`.

**What SHOULD require it and does not — named, not fixed, because it is a founder's call:**

1. **`POST /v1/admin/impersonation-grants`.** This is the single choke point for entering a
   client's data — `_load_admin_principal` refuses every impersonated request without a
   grant, and grants exist only here — so it is the natural place for "prove it is still
   you before you read a customer's leads, calls and transcripts". BACKEND-PATTERNS §7 names
   raw-transcript access as a step-up action, and a `superadmin` in a view-as session reaches
   `GET /v1/calls/{id}/transcript/raw` and `/recording` today with role + audit and no
   freshness check. Not taken here because it changes operator workflow (an OTP at least
   every 15 minutes to stay in view-as) and needs a code prompt wired into the admin console,
   which is outside this pass's fence. **What closes it:** a decision to accept that
   workflow cost, plus the console prompt.
2. **Raw-transcript access by the tenant's own `owner`.** BACKEND-PATTERNS §7 lists it and
   the client realm has no second factor at all (D-170), so `StepUp.present` is False for
   every client caller and adding the gate there would refuse the action outright. This is a
   genuine conflict between two documents, flagged rather than silently picked, per
   CLAUDE.md. **What closes it:** either a client-realm second factor, or an amendment to
   §7's sentence saying raw-transcript access is role-plus-audit on the client realm by
   design.

### Login surface — clean (REASONED, with the existing PROVEN timing test)

One `invalid_credentials` sentence for unknown address, wrong password, deactivated account,
deleted account and an ambiguous address; the same status, the same body, the same backoff,
and a real Argon2 verification on the unknown path. Lockout is a decaying Redis counter with
an increasing capped delay rather than a durable lock, which is OWASP's and NIST's answer and
avoids handing anybody a denial-of-service primitive aimed at a known address. The failure
budget fails **closed** on a Redis outage, deliberately and consistently with the three other
surfaces that made the same choice. `subjects.py` refuses an ambiguous address rather than
picking a row, and there is no identifier-existence endpoint of any kind —
`tests/authn_enumeration_test.py` asserts one can never be reintroduced.

### Realm boundary — clean (REASONED, corroborated by an existing PROVEN suite)

Every route in `apps/api/admin/routes.py` pins `realm="admin"` (checked by grep over all 26
`requires(...)` declarations — the only two non-matching lines are prose in comments).
`current_any` reaches the admin verifier only when the impersonation header is present.
`_credential` accepts a real session token **only** from the cookie; an `Authorization`
header is honoured for the `dev:` shape and nothing else, so the browser cannot be talked
into carrying our credential where the cookie attributes would not have gone. The realm is
inside the session fingerprint, so a client token presented as an admin one is not a weak
credential, it is no credential. `tests/realm_boundary_test.py` (already present, 15 cases)
drives both directions over HTTP and passes.

### Frontend — clean (REASONED)

Read in full: `lib/authn/{realm,transport,problems,mode,adminSession,clientSession,
adminAuthn,clientAuthn,realmSessions}.ts(x)` and `components/authn/*`.

- **Fail-closed by construction.** `AdminSessionGate` renders children only for
  `status === "ready"` and is written as an allowlist specifically so a status added later
  cannot fall through to the console.
- **No authorization decided in the browser.** `SignInForm` reads the server's
  `authenticated | otp_required` and nothing else — it does not know which realms require a
  second factor, and its docstring says why it must not.
- **No silent mutation failures found.** The one swallowed rejection is `startOver`'s
  `authn.signOut().catch(...)`, and it is argued: a failed sign-out must not trap somebody on
  the code step, the local reset is what the screen needs, and the server-side session
  expires on its own bound. The rotation barrier's swallowed rejection is ordering-only and
  documented as such.
- **The soft/hard failure split is right and load-bearing.** Only a server `unauthorized`
  clears local session state; a 429, a 503, a proxy error page and a dropped connection are
  all soft, which is the property that stops a valid session on a weak mobile link being
  thrown away.
- **No credential in a response body, no `devOtp`, no auto-filled code**, and
  `tests/authnSourceGuards.test.ts` reads the directory's source to keep it that way.
- The one drift found is documentation, fixed here: `authn/invitations.py`'s module
  docstring still described `InvitationCreatedOut.token` as handing the raw token to the
  inviter, which D-190 had already stopped being true on that route and this pass has now
  stopped being true on the other.

---

## What could not be settled

- **The shared development database is ~50 migrations behind this tree** and one of the
  pending revisions (`f9c2b41a8e57`) will not apply cleanly because a partial
  `CREATE INDEX CONCURRENTLY` from another session already created
  `ux_credit_ledger_tenant_reason_ref`. That is a human step, not a code change: drop the
  index or stamp the revision, then `alembic upgrade head`. Named because until it happens
  nobody can run an `authn` test against the shared database at all.
- **Whether the 5.7 ms reset-path timing gap is exploitable over the real edge.** It needs a
  measurement against the deployed nginx from a realistic network position, which this pass
  cannot take — there is no deployment.
- **The two step-up gaps above**, both of which are decisions rather than defects and both
  of which name what closes them.
