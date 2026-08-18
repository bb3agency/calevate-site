# Red team, final pass before production

**Date:** 2026-08-18 · **Scope:** `apps/api/**`, `apps/voice-runtime/**`, `packages/shared/**`,
and `apps/web` only where it decides something the server should · **Posture:** a valid
low-privilege account and a hostile network, plus a hostile position anywhere under the
`calevate.tech` registrable domain.

Everything in §1 and §2 was **driven over HTTP against the running ASGI app with real
credentials** — a real `auth_sessions` row and its cookie, or a real `admin_users` row —
against a private database (`calevate_redteam`) migrated base→head. §4 is separated on
purpose: it is reasoning, not measurement.

Two of the three files this brief named as prior evidence do not exist in this tree
(`docs/evidence/deepdive-authn.md`, `docs/evidence/deepdive-stepup.md`), and the tree
carries no D-198 and no `auth_time` claim — the step-up that exists is D-178's
`mfa_verified_at` freshness read. The auth surface was therefore re-attacked from
`docs/evidence/deepdive-attack.md` and from the code, not from a changelog.

---

## 1. What broke

### 1.1 — HIGH — Session fixation on both consoles: an unprefixed cookie alias defeated `__Host-` (D-330)

`apps/api/authn/cookies.py` picked `__Host-` for exactly one reason, and says so:

> `__Host-` … makes the cookie host-only to the API origin, so no sibling subdomain and no
> compromised `*.calevate.tech` host can set or overwrite it. **This is the one attribute
> that defends against cookie FIXATION from a neighbouring host**, which `SameSite` does
> not touch.

`read_token` then read the prefixed name first and the **bare** name second,
unconditionally, on every request, whatever the scheme. The prefix forbids a sibling
setting the *prefixed* name. It says nothing about the bare one.

**The request** (a real, live, MFA-complete admin session token, over TLS):

```
GET /v1/auth/admin/session HTTP/1.1
Host: api.calevate.tech
Cookie: calevate_admin_session=<token>
X-Forwarded-Proto: https
```

**The result** — and the same on `https://` directly, and the same on the client realm:

```
A) __Host- name over https -> 200 {"realm":"admin","subject_id":"0e70a144-…","mfa_complete":true}
B) bare alias over https   -> 200 {"realm":"admin","subject_id":"0e70a144-…","mfa_complete":true}
C) bare alias + XFP https  -> 200 {"realm":"admin","subject_id":"0e70a144-…","mfa_complete":true}
…
bare client alias over https -> 200
```

**The attack this is.** Any host under `calevate.tech` — a dangling CNAME, a marketing
subdomain, a takeover of something nobody thought was security-relevant; the same
population D-178 already treats as hostile when it made `enforce_same_origin` check the
`Origin` unconditionally — issues:

```
Set-Cookie: calevate_admin_session=<the attacker's own live token>; Domain=.calevate.tech; Path=/
```

The browser attaches it to every `api.calevate.tech` request. A victim who has **not signed
in yet** is silently operating inside the attacker's account: the leads they type, the
knowledge source they upload, the teammate they invite all land where the attacker can read
them at leisure. A victim who *has* signed in is unaffected — their `__Host-` cookie is
present and wins — which is why this is fixation and not takeover, and why the test asserts
both halves rather than only the refusal.

**The fix.** The name that may be **read** is now decided by `_is_secure(request)`, the same
predicate that decides which name is **set**. TLS request → the `__Host-` name and nothing
else. Cleartext → either name, deliberately: a browser will not send a `__Host-` cookie over
plain HTTP at all, so the stripped name is the only credential a local console can hold, and
on a cleartext connection no cookie is trustworthy against a network attacker anyway — which
is the reason the prefix is dropped there in the first place. Rejected: deciding it from
`APP_ENV`, because a second predicate for "is this deployment TLS" is precisely how a read
side and a write side come to disagree.

**Test:** `tests/authn_cookie_prefix_test.py` (10 assertions) — the refusal on both realms in
both the `https` and `X-Forwarded-Proto` shapes; the end-to-end fixation scenario (attacker's
alias and victim's `__Host-` cookie in one `Cookie:` header must resolve as the **victim**,
which a fix that merely reordered the two names would fail); and three controls — the
prefixed name still authenticates over TLS, the stripped name still authenticates over
cleartext, and `read_token` asserted as the mirror of `set_session_cookie`.

**Sabotage:** removing the hoisted branch turns exactly 6 of the 10 red, and the 4 controls
stay green — so the tests measure the fix and not the absence of a feature.

### 1.2 — MEDIUM — The fifth D-193 write path: a provisioned number could name another tenant's agent (D-331)

D-193 closed four cross-tenant foreign-key writes. This is the fifth, and it was missed
because it is the only one on the **admin** router: it takes its tenant from the path rather
than from a session, so it does not look like "a client naming a neighbour's row". The
mechanism is identical — PostgreSQL validates a foreign key with row security bypassed, and
a tenant-scoped policy's `WITH CHECK` constrains only the `tenant_id` **of the row**.

**The request** (valid `superadmin`, tenants A and B both created by this pass):

```
POST /v1/admin/tenants/<B>/numbers
{"e164": "+919883185919", "series": "160", "agent_id": "<tenant A's agent>"}
```

**The result:**

```
201 {"id":"01a0143c-fc63-7002-a400-246ab9fa0de7","e164":"+919883185919",
     "series":"160","dlt_status":"pending"}
```

and the row is really there, cross-tenant:

```
SELECT p.id, p.tenant_id, p.agent_id, a.tenant_id AS agent_tenant
FROM phone_numbers p JOIN agents a ON a.id = p.agent_id
WHERE p.tenant_id <> a.tenant_id;

 01a0143c-fc63-… | 01a0143c-fbff-…(B) | 01a0143c-fb87-…7e73 | 01a0143c-fb87-…9fe3 (A)
```

**What it is not, stated rather than implied.** No dial and no disclosure. Nothing reads
`phone_numbers.agent_id` today — the campaign paths join `phone_numbers` on `number_id` and
scope the agent separately. What survives is the **stored reference**, which is the same
residue D-193 recorded for its own campaign cases and the same reason it fixed them rather
than noting them: it is one un-scoped `JOIN` away from a client's screen naming a
neighbour's agent, and the column exists precisely so that something will eventually read
it.

**The fix.** `agents.service.provision_number` calls
`db.ownership.assert_visible(session, "agent", agent_id)` before the INSERT and before any
lock — the same primitive and the same position as D-193's four, rather than a fifth
spelling. 404, never 403: from inside a tenant, "that id is not yours" and "there is no such
id" are the same fact.

**Test:** appended to `tests/cross_tenant_reference_test.py` — the attack (404 + `not_found`
+ a count assertion that **no row was written**, without which a guard that refused the
response *after* writing would pass), plus two non-vacuity controls (the tenant's own agent
still provisions; a `null` agent still provisions, because a number recorded before its
agent exists is the ordinary onboarding order).

**Sabotage:** replacing the `assert_visible` line with `pass` turns exactly the one attack
test red and leaves the six others green.

**How the search was done**, so the next pass can repeat it rather than re-derive it: every
foreign key whose referent is a tenant-scoped table was enumerated from `pg_constraint`
(51 of them), and each traced to whether its value can arrive in a request body. Six reach a
body; five resolve the reference under RLS before use — `crm.service._assert_assignable` on
`leads.assigned_to`, `agents.experiments._version_id` on the variant prompt versions, the
path-param agent on prompts and extraction schemas, and D-193's four — and this one did not.

---

## 2. What held, and what was tried

Every line below was **driven**, not read.

### 2.1 The impersonation chain (`core/impersonation.py`, `core/auth.py`)

| Attack | Request | Result |
|---|---|---|
| Enter a tenant with the header alone | `GET /v1/leads` + `X-Impersonate-Org: <slug>` | **403** `impersonation_grant_required` |
| **Replay across tenants** | grant minted for tenant B, presented with `X-Impersonate-Org: <A's slug>` | **403** `impersonation_grant_tenant_mismatch` |
| **Renew by another operator** — a leaked grant paired with a second admin's own session | grant minted for admin #2, presented by admin #1 | **403** `impersonation_grant_actor_mismatch` |
| **Forge** — algorithm confusion | `alg: none` JWT with correct `aud`/`sub`/`act`/`jti`/`exp` | **403** `impersonation_grant_invalid` |
| **Extend the life** — self-signed, 9h `exp`, wrong key | HS256 under an attacker key | **403** `impersonation_grant_invalid` |
| Expired grant | `exp` one hour in the past | **403** (refused before any read) |
| **Mint from inside an impersonation** (RFC 8693 nested `act` chaining) | `POST /v1/admin/impersonation-grants` while carrying a valid grant + header for another tenant | **403** "Start view-as from the operator console, not from inside another account." |
| **Write under a read-only view-as** | `PATCH /v1/leads/{id}` inside a valid grant | **403** "Impersonation is read-only." |
| Valid grant, own tenant (non-vacuity) | `GET /v1/leads` + header + grant | **200** |

The audit still names the actor on every branch: `admin.impersonation_started` is written in
the mint route's own transaction from the returned grant, and `admin.impersonation_read` is
written by `_load_admin_principal` — the only function in the tree that can produce
`impersonating=True` — **before** the route's permission check, so an operator who enters and
is then refused is still in the ledger. Both carry `grant_id`, so a start row and its reads
join exactly.

**The read-only guarantee is only as complete as `MUTATING_PERMISSIONS`**, so that was
audited rather than trusted: the route table was walked and every mutating-method route
cross-checked against its declared permission. Seven POSTs declare a read permission and all
seven are reads-shaped-as-POSTs already enumerated and argued in
`tests/authz_audit_test.READS_SHAPED_AS_POSTS`. No route was found where the check and the
work disagree.

**What was *not* found and is worth naming as a design fact rather than a hole:** the mint
route requires `admin:impersonate` and does **not** require step-up. That is deliberate and
correct on this tree's terms — D-22 forbids gating a read on a mutating permission, and
`core/rbac.py` names step-up as the control for "the dangerous switches", which view-as is
not. Revocation is instant either way: `admin_users` and the role are re-read on every
request, so a grant outlives nothing.

### 2.2 Sessions, cookies, realms (`authn/sessions.py`, `authn/cookies.py`)

- **Cross-realm confusion.** A live *client* session token presented on the admin realm:
  **401**. It is arithmetic rather than a predicate — the realm is inside
  `token_fingerprint`'s hash domain, so there is no stored value the admin lookup could
  match — with `AND realm = :realm` as the belt to that brace.
- **Rotation on privilege change.** Sign-in issues `mfa_verified_at = NULL`; completing the
  second factor and completing a step-up both **rotate** (new token, old row
  `superseded_at` under a CAS). `absolute_expires_at` is carried forward and never
  recomputed, so a session that rotates cannot outlive the bound it was born with — read
  and re-read, because "extended past its hour" was on the brief.
- **Replay of a rotated token** revokes the whole family (`reuse_detected`), and
  `verify_session` owns its own transaction specifically so that revocation survives the
  refusal it causes. Attempting to make the revocation roll back requires the caller to own
  the transaction, and no caller does.
- **Logout, both realms.** `/logout` depends on `live` (so a half-authenticated session can
  drop itself) and `/logout/all` on `authed`; both revoke by CAS on `revoked_at IS NULL`, so
  a second sign-out cannot overwrite a `reuse_detected` reason and erase the trace of a leak.
- **Cookie scope.** `SameSite=Strict`, `HttpOnly`, no `Max-Age` (the row is the authority),
  and — after §1.1 — a name that is host-bound on every TLS request.
- **More than one place a credential is read from.** There are exactly two:
  `read_token` (the cookie) and `bearer_token` for the `dev:` shape only, which
  `_credential` refuses to look up as a session at all, and which is confined by two
  independent facts (`APP_ENV=local` **and** no `PLATFORM_KEK`). A real session token
  presented as `Authorization: Bearer` is refused before any lookup.

### 2.3 Authorization

- `assert_policy_registry_complete` walks the whole dependency tree at boot, so a declared
  permission with no lock behind it, a lock that checks a different permission, a
  misspelled-but-consistent pair, and a permission no role holds all fail the build. 204
  routes checked; 34 unauthenticated routes, all declared and backed
  (`scripts/check_public_routes`).
- A client-realm credential cannot reach an admin-realm answer: `current_principal` refuses
  the impersonation header outright with `impersonation_not_available_here` rather than
  letting the realm complaint surface, and `current_any` reaches the admin verifier only
  when that header is present.

### 2.4 Secrets

- Every HMAC secret goes through one ladder (`core/settings.resolve_hmac_key`) whose refusal
  bodies and log lines carry the **env var name and the purpose**, never a value — checked
  for the KEK, the audit-chain secret, the impersonation-grant secret and the idempotency
  scope secret. The local fallback is scoped to `app_env == "local"`; everywhere else an
  absent secret is a loud outage reported at `/healthz/ready` before an operator finds out
  by clicking.
- `scripts/check_redaction_exposure` passes: 4 role-gated exceptions verified role-checked
  **and** audited, 14 field patterns checked transitively, 3 acknowledged passthroughs.
- No secret-shaped value appears in a response model, a log `extra`, an error `detail`, a
  metric label or an alert detail on the paths walked.

### 2.5 Injection, SSRF, egress

- **SSRF.** Every outbound URL the app can be told to fetch goes through
  `integrations/egress_guard.assert_public_http_url`, and it is re-run **per attempt** and
  **per redirect hop** rather than once at creation: outbound webhook delivery
  (`integrations/service.deliver`) and recording copies (`workers/storage`, which follows
  redirects by hand with `follow_redirects=False`). KB sources cannot fetch at all — a
  `kind` of `url` or `file` is refused with `kb_kind_unsupported` before anything is written,
  so there is no fetcher to point anywhere. No avatar/logo fetch exists.
- **CSV formula injection.** `crm.service._csv_value` routes every cell through
  `core.spreadsheet_safety.disarm_for_csv`, header row included, and the Sheets writer shares
  it.
- **Raw SQL.** `scripts/check_raw_sql.py` refuses a table name as a parameter, which is why
  `db/ownership.py` is a `Literal` plus a dict of literal statements rather than a
  table-name argument.
- **Log injection / PII in logs.** The impersonation read row records the **route template**,
  never the resolved path and never the query string — a filter can carry a phone number and
  a template cannot carry an identifier at all. `scripts/check_audit_ip.py` fails the build
  on any new inline `request.client` read, so the one legitimate socket-peer read stays one.

### 2.6 Egress and DoS

- **Unauthenticated Argon2.** `POST /v1/auth/{realm}/login` is bounded three ways: the
  `auth` rate profile (20/min per address), a per-subject failure budget with exponential
  penalty (`authn/throttle.py`), and a `max_length` on the password field enforced by
  Pydantic *before* the HMAC. The unknown-address path verifies against a **cached** dummy
  hash (`@lru_cache`), once per pepper generation — computing it per request would both
  double the cost and reopen the enumeration oracle with the sign flipped.
- **Body caps.** Enforced including bodies that declare no length
  (`Transfer-Encoding: chunked`) — the D-193-era finding, still pinned in
  `tests/adversarial_pass_test.py`.
- **Caller-controlled query cost.** Every `limit` on the route table carries an `le=`; every
  request-model list carries a `max_length` (contacts 5000, DNC numbers
  `MAX_NUMBERS_PER_ADD`, schedule days 7). `offset` is `ge=0` and unbounded, which is not a
  lever: the scan it costs is bounded by the tenant's own row count under RLS, not by the
  number the caller typed.
- **A view-as session charges the tenant's own rate-limit bucket** (`charge_tenant_quota`
  runs for an impersonating principal). That is intentional — the reads *are* that tenant's
  — and it is the one place an operator can degrade a client's throughput. It is bounded by
  `admin_api`'s own per-operator ceiling and it is audited, so it is recorded here as a
  known, accepted property rather than a finding.

### 2.7 Rate limiting and enumeration

- Sign-in answers identically for an unknown address and a wrong password — same status,
  same body, and the same **wall-clock cost**, by construction (a real Argon2 verification
  against a real hash) rather than by a `sleep` that would drift the moment the parameters
  change.
- Password reset answers `202` with an empty body always. The prior wave's defect (throttling
  only addresses that do **not** exist) is closed and `throttle.pseudo_subject` gives an
  unknown identifier a real budget.
- Invitation redemption cannot be enumerated: the token is 256 bits and is burned by one
  `UPDATE … WHERE used_at IS NULL … RETURNING`, so two concurrent submissions produce exactly
  one winner at the database. Since D-190 the token is emailed and returned to nobody, so the
  squat it enabled is gone rather than narrowed.
- The ingest and payment webhook receivers are keyed per `webhook_id`, which is the tenant
  dimension on a surface with no session — one client's form flood cannot 429 another
  client's leads.

---

## 3. Gates

`ruff check` · `ruff format --check` · `mypy apps packages` (230 files) ·
`check_rls_coverage` (44 tenant tables, 48 policies, 8 append-only triggers) ·
`check_redaction_exposure` · `check_public_routes` · `check_docs_drift` (198 decisions, no
dangling reference) — all green. Targeted suites: `authn_*`, `authz_audit`,
`realm_boundary`, `adversarial_pass`, `admin_security`, `cross_tenant_reference`,
`authn_cookie_prefix`.

---

## 4. Reasoned, not driven

Kept separate because it was not measured.

1. **`_is_secure` believes `X-Forwarded-Proto` from any peer.** Its docstring argues this is
   safe because getting it wrong makes the cookie *more* restrictive, and after §1.1 that is
   still true in both directions — a forged `https` now makes the **read** stricter too. It
   is only unsafe in a deployment where the edge does not strip the header **and** a
   legitimate client must be served over cleartext, which no Calevate deployment is. Not
   changed.
2. **The signed double-submit CSRF token is still not built.** D-178 argued it away and the
   argument survives this pass: the one condition OWASP's cheat sheet named as unmet (shared
   registrable domain) is now met by checking the `Origin` unconditionally. What a token
   would still buy is a same-site attacker who can also suppress or forge `Origin`, which a
   browser does not permit page script to do.
3. **`admin:impersonate` grants read access to every client's leads, calls and redacted
   transcripts, and `operator` holds it.** That is D-22's design, and the compensating
   control is the two-row ledger rather than a narrower grant. Named here because it is the
   largest standing authority in the system and a reader should meet it deliberately.
4. **`docs/evidence/deepdive-authn.md` and `docs/evidence/deepdive-stepup.md` were named in
   this brief and are not in the tree.** If they exist on an unmerged sibling branch, the
   findings in them have not been reconciled with this pass.

---

## 5. Verdict

**Go, on the security surface, with §1.1 as the gating fix** — it is committed here and it
is the only finding in this pass that a stranger could have reached. Nothing that was tried
against the impersonation chain, the session layer, the realm boundary, the permission
registry, the egress guard or the unauthenticated surfaces produced a result the design did
not already predict, and several of those refusals are structural (arithmetic in a hash
domain, a boot assertion over the route table, a database answering a visibility question)
rather than a check somebody has to remember.

The residual risk that is **not** ours to close is unchanged and belongs on the launch
checklist rather than in this repo: the `*.calevate.tech` DNS surface. §1.1's fix removes
the fixation lever a hostile sibling had, and `enforce_same_origin` removes the CSRF one,
but a subdomain takeover remains a phishing and reputation problem that only DNS hygiene
answers.
