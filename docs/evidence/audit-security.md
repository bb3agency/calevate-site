# Security, tenancy and data-egress audit

**17 August 2026.** A find-and-document pass over `apps/api`, `apps/voice-runtime`,
`apps/workers`, `packages/shared`, `apps/web/src` and `infra/nginx`, against CLAUDE.md
hard rules 1, 5 and 6, `docs/SECURITY-COMPLIANCE.md` and `docs/DATA-MODEL.md` §1.
**Nothing was fixed.** Every entry says whether it was PROVEN by running something or
REASONED from reading the code, and cites `file:line`.

Two documents the brief named do not exist in the tree — `docs/AUTH-MIGRATION.md` and
`docs/evidence/our-gates-audit.md`. `docs/ROADMAP.md` §6 (D-01…D-164) and
`docs/LEGAL-SURFACE.md` §5 (F-1…F-10) were read in full and nothing below re-reports one
of their entries.

The headline is not the findings list. This tree is materially better defended than the
median SaaS of its size: SSRF is closed on every outbound path with a resolve-then-judge
guard and per-hop re-vetting, the trusted-proxy predicate is a single shared definition
that fails closed, RLS is FORCEd with a boot-time registry and a live-catalog guardrail,
the audit chain is HMAC-keyed with a verifying key ring, the envelope crypto is textbook,
and every HMAC comparison in the tree is constant-time. The four findings below are the
places the discipline has a seam, not a collapse.

---

## Findings

### S-1 — Call recording audio is reachable with `calls:read`, which `staff` holds

**Severity: Medium.** **REASONED** (route + role table read directly; not exercised
against a live DB).

`apps/api/crm/routes.py:185-220` declares `GET /v1/calls/{call_id}/recording` with
`permission_meta("calls:read")` and `Depends(requires("calls:read"))`.
`apps/api/core/rbac.py:75-82` grants `calls:read` to the client-realm `staff` role. The
handler mints a presigned URL to **our** copy of the call audio
(`apps/workers/storage.py:741`, `recording_key` at `:196`).

The concrete accident: `docs/SECURITY-COMPLIANCE.md:446-447` and
`docs/DATA-MODEL.md:34` both state that `staff` gets **no raw (unredacted) transcript**,
and the whole redaction apparatus exists to hold that line — `text_redacted` is the
default in every response, the raw transcript route is `calls:read_raw` + `audit_log`
(`crm/routes.py:159-184`), the CSV export was *moved* to `calls:read_raw` for exactly
this reason (`crm/routes.py:652-663`), and `crm/service.py:96-147` goes to the trouble of
redacting `calls.summary` on the way out because a staff member could otherwise read
transcript content off the calls list. The audio is the **source** of the text that all
of that protects: a caller who reads out an Aadhaar number, a card number or an OTP is
masked in `text_redacted` and audible in the `.wav`. A `staff` account — the role a
client hands to a junior telecaller — can play or download every one of them.

Partly mitigated, and the mitigation is why this is Medium and not High: the route writes
a `recording.read` audit row before minting the link (`crm/routes.py:196-205`), and the
link's TTL is derived from the call duration (D-153). So it is *audited* unredacted
access, which is the shape hard rule 5 asks for on the raw transcript — it is just
missing the role half of "role check + audit_log write".

Note the same route is reachable by an admin-realm `operator` inside a view-as session:
reading is not a `MUTATING_PERMISSION`, so D-22 does not refuse it. That is probably
intended (an operator debugging a call), and it is doubly audited
(`admin.impersonation_read` + `recording.read`); it is recorded here only so the blast
radius is stated.

**What would fix it:** either gate the route on `calls:read_raw` — the permission that
already means "you may see the unmasked artefact and your having seen it is recorded" —
and accept that a staff work-queue loses the player; or, if audio-for-staff is the
product decision (`docs/SURFACES.md:72-80` describes the player and transcript as one
instrument on the per-call screen, which reads like it is), write the decision into
ROADMAP §6 and amend SEC-COMP §5 and DATA-MODEL §2 so the two documents stop asserting a
rule the code does not keep. What is not tenable is the current state, where three
documents say staff cannot reach unredacted call content and one route hands them the
audio.

---

### S-2 — `users.email` is an authorization input, and the mirror never checks that the address is verified

**Severity: Medium.** **REASONED.** **In-flight area — a sibling agent is mid-change on
the Clerk surface, so treat as possibly-already-addressed.**

`apps/api/core/clerk_identity.py:186-204`:

```python
primary_id = payload.get("primary_email_address_id")
entries = [e for e in emails if isinstance(e, dict)]
chosen = next(
    (e.get("email_address") for e in entries if e.get("id") == primary_id),
    next((e.get("email_address") for e in entries), None),
)
```

Nothing reads `verification.status` on the chosen entry, and the fallback takes the
**first address in the array** whenever `primary_email_address_id` is absent or does not
resolve to a listed entry.

That value becomes `users.email` (`clerk_identity.py:249-254`), and `users.email` is the
sole binding on invitation redemption: `apps/api/tenancy/routes.py:519-540` reads the
signed-in user's `users.email` and compares it casefolded against `invitations.email`,
after which `accept_invitation` creates the membership with the invited role — which can
be `owner`.

The module's own docstring (`clerk_identity.py:50-62`) names this exact threat and
refuses to mint the email from the `email` token claim, "a claim whose verification
status the token does not state — an attacker who adds `victim@example.com` to their own
Clerk account, unverified, would mint a mirror row that satisfies the binding." The
Backend-API path is then defended as placing "EXACTLY the trust in Clerk that the webhook
path already places" — which is true, and is also the problem: **neither path checks the
one field that makes the address an authenticated fact.** The whole binding rests on a
property of the Clerk dashboard configuration (verification required at sign-up; primary
must be verified) that is asserted nowhere in this repo and pinned by no test. Clerk's
own Backend API `createEmailAddress()` takes `primary` and `verified` as *independent*
parameters, so "primary" and "verified" are not synonyms in the data model we are
reading.

The concrete accident, stated at the strength the evidence supports: an outstanding
invitation to `finance@client.example` plus any Clerk-side arrangement in which an
address the attacker controls the listing of — an unverified primary, or the first entry
under an absent `primary_email_address_id` — is what `_primary_email` returns, and the
attacker redeems that invitation and joins the tenant with the invited role. Full read of
that client's leads, calls, recordings and (at `owner`) the disclosure toggles.

**What would fix it:** require the chosen entry to carry
`verification.status == "verified"`, delete the first-entry fallback (an address that is
not the primary is not an identity claim), and refuse to write `users.email` at all when
no verified address is present — the caller already has a clean refusal path in
`identity_mirror_pending`. A test that feeds `mirror_clerk_user` a payload with an
unverified address and asserts the invite is refused turns the Clerk-console assumption
into a code guarantee.

---

### S-3 — Phone numbers travel in a URL query string on two client-realm routes, and nginx logs the request line

**Severity: Medium.** **REASONED** (code + config read; no live nginx to prove the log
line).

`GET /v1/leads?search=…` (`apps/api/crm/routes.py:461-479`) and
`GET /v1/leads/export.csv?search=…` (`crm/routes.py:652-690`) take `search` as a query
parameter. The predicate it feeds is explicitly a phone match —
`apps/api/crm/service.py:468-472`:

```python
clauses.append("(l.name ILIKE :search OR l.phone_e164 LIKE :phone_suffix)")
params["phone_suffix"] = f"%{search}"
```

and the audit row for the export deliberately records `"searched": bool(search)` rather
than the text, "hard rule 6, and the search box accepts a phone suffix"
(`crm/routes.py:717-720`). So the repo knows the value is a phone number. The browser
sends it in the URL: `apps/web/src/lib/api/leads.ts:252-267` builds `URLSearchParams` and
appends `search`.

`infra/nginx/` contains no `log_format` and no `access_log` directive
(`000-default.conf.template`, `calevate.conf.template`, `snippets/*`), so nginx uses the
built-in `combined` format, whose `$request` is the full request line **including the
query string**. Every leads search a client performs therefore writes
`GET /v1/leads?search=%2B919876543210 HTTP/1.1` into the origin access log — and, because
every zone is Cloudflare-proxied (D-27), into the edge's request log as well. It is also
in browser history and in the `Referer` of any subsequent navigation.

This is not a novel judgement about hard rule 6; it is the judgement this repo has
already made twice and not applied here. `POST /v1/dnc/check` is a POST for precisely
this reason — its summary reads *"(POST: the identifier IS the personal data)"*
(`apps/api/compliance/dnc_routes.py:157-161`) — and SEC-COMP §4's messaging-consent
paragraph specifies "number in the body and never in a URL". Two shapes for one problem
is the defect class CLAUDE.md names, and the weaker shape is the one on the busiest
screen in the product.

**What would fix it:** make the lead lookup a POST with the term in the body (the DNC
`/check` precedent), or — if a GET is wanted for cacheability and shareable links — set an
explicit `log_format` in `infra/nginx` that logs `$uri` rather than `$request`, plus a
Cloudflare Transform Rule scrubbing the parameter, and say in SEC-COMP §5 which of the two
is the control. The API-side logging is already clean (`_route_template` at
`apps/api/core/auth.py:1013-1022` uses the template, and Sentry scrubs `query_string` at
`apps/api/core/observability.py:134`); the gap is entirely at the edge, which is exactly
where nobody looks.

---

### S-4 — `DELETE /v1/dnc/{entry_id}` deletes rather than tombstones, so a suppression can be un-done with no surviving record of the number

**Severity: Low.** **REASONED.**

`apps/api/compliance/dnc.py:264-299` performs a hard `DELETE FROM dnc_list WHERE id = :id`
after refusing global entries and non-`manual` sources. The refusals are correct and well
argued (`is_removable` at `:256` is the one definition, rendered as a flag by
`list_entries` and enforced here), and `dnc_list` is deliberately not in
`APPEND_ONLY_TABLES` (`apps/api/db/registry.py:255-282`).

The residual: the audit row written by the route (`dnc_routes.py:200+`) carries the
`source` and the entry id, never the number — correctly, per hard rule 6. So after a
removal, *nothing anywhere* records which number stopped being suppressed. If a `manual`
row was ever mis-sourced (an in-call opt-out recorded by a staff member as `manual`, which
`SOURCES` permits), its removal is unreviewable and the number goes back into the dial
pool with no trail. TRAI's obligation attaches to the number, and the compensating-entry
doctrine of hard rule 4 exists for exactly this shape.

**What would fix it:** either make `dnc_list` removal a compensating INSERT (a
`released` row) so the register keeps its own history, or write the entry's
`subject_ref` — the same salted hash `compliance/export.py:100` already uses as a
non-PII stand-in for a number — into the audit summary, so "which number was released"
is answerable without putting a number in the ledger.

---

## Examined and found clean

Listed because the absence of a finding here is the evidence, not an omission.

**Tenancy / RLS**
- `apps/api/db/session.py` — all six session flavours. GUCs are set with
  `set_config(..., true)` (transaction-local, so a pooled connection cannot carry one
  request's tenant into the next); `admin_session` widens `USING` on `organizations`
  only and no `WITH CHECK` anywhere; `user_session`, `invite_session` and
  `ingest_config_session` each widen exactly one read by one unguessable key.
  `untenanted_session` sets nothing, so tenant tables answer zero rows.
- Every `tenant_session(` call site in `apps/api` and `apps/workers` (41 of them). Each
  takes its tenant from a path segment behind `admin:tenants`/`ops:manage`, from a
  resolved principal, or from a worker's own row — none from an unverified header or body.
- Every `untenanted_session(` / `admin_session(` call site. None reads a tenant table
  expecting rows; the two that resolve a tenant (`_load_admin_principal`,
  `dispatcher.py:307`) document why `admin_session` and not `untenanted_session`.
- `apps/api/db/registry.py` — `TENANT_TABLES` (52 entries), `RLS_EXEMPT_TENANT_COLUMNS`
  (8 entries). Every exemption carries a reviewable reason; the two that matter most
  (`audit_log`'s global hash chain, `engine_agent_routes`' read-only global widening with
  a FORCEd write policy on top) are correct. `webhook_deliveries` has no RLS **and no
  tenant_id**, and every one of its five read paths is scoped through the RLS'd
  `outbound_webhooks` by `endpoint_id IN (SELECT id FROM outbound_webhooks)` —
  `integrations/service.py:356-390`, `integrations/routes.py:637-650`,
  `crm/attention.py:247`. Verified all five.
- Dynamic SQL: every `text(f"…")` in the tree interpolates a module constant or a clause
  list built from a fixed vocabulary; every caller value is a bound parameter, facet keys
  included (`crm/service.py:480-490`).
- Static scan of `alembic/versions/*`: no table `ENABLE`s row-level security without
  `FORCE`.

**Authorization / realms**
- `apps/api/core/auth.py` in full. The MFA gate lives inside `verify_token`, so
  `VerifiedToken(realm="admin")` and "passed MFA" are the same object; absent `fva` fails
  closed. `jwks_url` resolves each realm against its own publishable key, and
  `missing_realm_separation_keys` refuses the collapse-to-one-host arrangement at the
  readiness gate. Dev tokens are unreachable outside `APP_ENV=local` with no Clerk
  secret, and `APP_ENV` has no default. `_impersonation_slug` refuses a blank header
  rather than producing the third state. The `_PRINCIPAL_MEMO` is keyed by realm, so it
  cannot hand a client resolver an admin principal.
- `apps/api/core/impersonation.py` + the two ledger actions. Entry needs an RFC-8693-shaped
  grant bound to operator **and** tenant, `admin:impersonate` is checked before the slug
  lookup (so 404-vs-403 is not a slug oracle), authority is re-read from `admin_users`
  every request, and `impersonating` is derived from the *resolved* tenant.
  `_record_impersonated_read` fails towards recording when Redis is down.
- `apps/api/core/rbac.py` — permission union, `ROLE_PERMISSIONS`, `MUTATING_PERMISSIONS`,
  `PUBLIC_PREFIXES`. The boot assertion checks label, lock, agreement and existence.
  Aside from S-1 the role split matches DATA-MODEL §2.
- Step-up: `apps/api/core/stepup.py` is the single definition and every route
  SEC-COMP §3/§4 promises it on actually calls it — ops halt/spend-cap/DLQ replay,
  admin spend ceiling, secret set + KEK rewrap, config set + revert, tenant erasure,
  global DNC suppress/release, preference scrub. Ten call sites checked one by one.
- The disclosure toggle (`apps/api/agents/routes.py:265-295`) is `org:manage`, which is
  in `MUTATING_PERMISSIONS`, so no impersonating session reaches it; and
  `set_disclosure_posture` (`agents/publishing.py:880`) is its only writer.

**PII egress**
- `packages/shared/src/calevate_shared/client_address.py` — one hop, one header,
  `CF-Connecting-IP` only, fails closed off `local`. This is the predicate an unsigned
  engine's whole authenticity rests on and it is correct.
- `apps/workers/redaction.py` — Aadhaar/Verhoeff, PAN, Luhn card, OTP, email, UPI VPA,
  spoken-digit runs, and a phone-span matcher with group-shape constraints.
- `apps/api/crm/assist.py` — the Gemini leg reads `transcript_turns.text_redacted` and
  the raw column is not named in the file; the prompt carries no extraction payload.
- `apps/api/core/observability.py:858-888` — httpx spans record host + path, never
  `url.full`, precisely because client webhook URLs can carry a key or a number.
  Sentry scrubs `query_string`; traces are redacted at the exporter.
- `apps/api/core/errors.py:186-270` — validation `input` dropped, 5xx bodies generic,
  unhandled-exception alert fingerprinted on the exception type with no payload.
- `get_engine(hide_parameters=True)` (`db/session.py:52`) keeps bound parameters out of
  every rendered DBAPI error string.
- Grepped every `log.*(extra={…})` in `apps/` for a PII-shaped value. The only
  near-misses are `apps/workers/transport.py:425` (`subject`, `ConsoleTransport`, which
  `build_transport` can only return when `APP_ENV=local` with no provider) and email
  addresses reduced to `_domain(to)` everywhere else.
- Exports: `GET /v1/leads/export.csv` is `calls:read_raw` + audited, with the audit
  summary carrying counts, column keys and facet keys and never values;
  `core/spreadsheet_safety.disarm_for_csv` covers formula injection.

**Secrets**
- `packages/shared/src/calevate_shared/config.py` — no secret carries a default; the only
  defaulted value in the file is `engine = "fake"`.
- `apps/api/core/envelope.py` — AES-GCM, 96-bit nonces from `os.urandom`, one encryption
  per DEK (so the birthday bound is not a question), AAD bound to the context, fresh
  `dek_nonce` on every re-wrap, KEK env-only with a retired slot that unwraps and never
  wraps.
- Every MAC/token comparison in the tree uses `hmac.compare_digest`
  (`clerk_webhooks.py:95`, `audit.py:253`, `payments.py:410`, `ingest/meta.py:389,422`,
  `ingest/service.py:190`, `integrations/service.py:172`, `engine/fake.py:603`). The one
  plain equality — the invitation recipient check — argues in place why constant time is
  the wrong instrument there, and it is right.
- `apps/api/ops/secret_probes.py` sends the candidate in an `Authorization` header, never
  a query string, logs only the exception type, and parses no vendor body.
- No credential appears in a URL or query string anywhere in the tree.
- The audit chain's generation-0 public constant is reachable only under `local`, because
  `_active_key` refuses to sign without a secret off `local` and `_matching_generation`
  ratchets the floor forward.

**Input handling**
- `apps/api/integrations/egress_guard.py` — the best-argued module in the repo. Resolve
  then judge (so every alternate IPv4 spelling is covered by construction), explicit
  category tests under `is_global` rather than on top of it, IPv4-mapped and
  6to4/Teredo/NAT64 refused, ports 80/443 only, and a cross-check that httpx's own
  IDNA-2008 parse names the same host as the stdlib's IDNA-2003 one. Re-run at connect,
  not only at registration.
- Every outbound fetcher was checked against it: `integrations/service.deliver`
  (vetted + `follow_redirects=False` on client *and* request),
  `workers/storage._fetch_recording` (vetted **per hop**, hop-bounded, byte-capped,
  deadline-wrapped). The remaining clients (`engine/bolna`, `engine/cartesia`,
  `billing/payments`, `ingest/graph`, `workers/google_sheets`, `workers/whatsapp_cloud`,
  `clerk_identity`, `ops/secret_probes`, `workers/extraction`) all address fixed vendor
  hosts with redirects off.
- No `subprocess`/`eval`/`exec`/`pickle`/`yaml.load` outside `scripts/restore_drill.py`
  and the alert/heartbeat entry points; no shell interpolation of caller data.
- Object keys: `recording_key`, `payload_key`, `delivery_body_key` are pure functions of
  (tenant, call/subject); the one vendor-controlled component is last, and object stores
  do not resolve `..`, so it cannot escape the tenant prefix.
- `apps/web/src` has no `dangerouslySetInnerHTML`, no `innerHTML`, no `localStorage` or
  cookie handling of session material.
- CORS: `install_middleware` (`core/middleware.py:467-485`) **raises at boot** on a
  wildcard origin with credentials, which Starlette itself does not.

**Compliance invariants**
- The dial gate `compliance.service.check_dispatch` is called on every dial path —
  campaign dispatcher per contact (`workers/campaign_dispatch.py:105,328`), the D-21
  single-lead button and callback (`crm/routes.py:1008,1156,1199`), and webhook-triggered
  dispatch (`ingest/service.py:389`). No path reaches the engine around it.
- `dnc.remove_entry` refuses `scope='global'` and every non-`manual` source, so a consumer
  opt-out cannot be un-done from the client realm (see S-4 for the residual).
- The truthful-answer floor is a `Final` in the portability contract, appended by
  `compose_engine_prompt`, read back by `agents/verification.judge` on publish, and
  `scripts/check_compliance_invariants.py` passes its code half here (**PROVEN** — run,
  reported `code OK; schema unchecked` for want of a database).
- Voice-runtime `verify_source` (`engine_intake.py:100-190`): the auth method is looked
  up per engine, the allowlist is looked up per engine (a second `source_ip` engine gets
  a refusal, not Bolna's addresses), `hmac` fails closed rather than falling back, and
  the `none` branch opens only when that engine *is* this deployment's engine.
- `scripts/check_docs_drift` passes (**PROVEN**, run after `uv sync --all-packages`).

---

## Open questions

1. **Is staff access to call audio a decision or an oversight?** S-1 cannot be closed by
   an engineer: either the permission moves or three documents change. `docs/SURFACES.md`
   reads as though the player is deliberately on the staff screen, and SEC-COMP §5 reads
   as though it cannot be. Founder's call, ROADMAP §6 entry either way.
2. **What does the Clerk instance actually enforce about email verification?** S-2's
   severity is entirely a function of that answer, and no artefact in this repo records
   it. Whatever the answer, the code should stop depending on it.
3. **Does anything downstream of nginx retain access logs, and for how long?** S-3's blast
   radius is the retention of the origin and Cloudflare logs, and `infra/` says nothing
   about either — no `log_format`, no rotation policy, no retention statement. The DPDP
   §8(7) storage-limitation question applies to an access log carrying phone numbers
   exactly as it applies to a transcript.
4. **`X-Confirm-Action` is in `allow_headers`,** so a browser on an allowed origin can
   send it. That is required for the console to work and is not a finding; it is worth
   recording that step-up's CSRF protection is therefore the origin allowlist plus the
   preflight, not the header's existence — and that SEC-COMP §5 already names browser
   reverification as the real next step.
