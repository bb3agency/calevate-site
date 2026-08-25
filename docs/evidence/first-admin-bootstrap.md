# The first administrator — what actually happens when you run the bootstrap

**Date:** 25 August 2026 · **For:** the operator standing at the VPS terminal, mid first
deploy · **Method:** read out of the code and the runbook, file:line at every claim.
Nothing here was executed against a live host in this pass — where a fact needs a live
host or a live mailbox it is marked **UNKNOWN** rather than guessed.

---

## The stated model, corrected

> "the first superadmin will be invited via email link … it sends an email to that mail
> provided by me in the VPS terminal, and then I should be able to setup my superadmin
> account by providing all details"

**Right in three parts, wrong in two, and one of the wrong ones will stop you today.**

- ✅ There IS a script, it DOES take the address you type on the VPS, it DOES mint a
  single-use setup link, and the role it creates by default IS `superadmin`, which holds
  every permission (`scripts/bootstrap_admin.py:130`, `apps/api/core/rbac.py:145,271`).
- ❌ **The email is not the delivery mechanism you depend on.** The link is PRINTED TO
  YOUR TERMINAL on every run, whether or not mail works, and the send is best-effort with
  a non-fatal failure (`scripts/bootstrap_admin.py:95-107,109-118`). With Resend pending
  you will see `email sent: NO — use the link below` and that is the expected, correct
  output — copy the link off the screen.
- ❌ **You do not "provide all details" on the setup page.** You set A PASSWORD, and
  nothing else. The address is fixed inside the link and is not shown or editable
  (`apps/web/src/app/(auth)/auth/admin/bootstrap/page.tsx:38-54`); there is no name field,
  no MFA enrolment, no QR code (`apps/api/authn/service.py:301-315`).
- ⚠️ **And the part that matters most for a pending Resend:** setting the password is not
  signing in. Admin sign-in requires a six-digit code EMAILED on every attempt
  (`apps/api/authn/service.py:114,261-281`), with no bypass. **Mail does not block the
  bootstrap; mail DOES block your first sign-in.** See "the crux" below.

---

## THE COMMAND TO RUN

On a KVM1 box where the app runs in Compose — **use the container form**. DEPLOYMENT §2
puts no Python and no `uv` on the host, so the `uv run` spelling cannot execute there at
all (`docs/DEPLOYMENT.md:130-139`, `runbooks/first-deploy.md:332-339`):

```sh
docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
  --entrypoint python api -m scripts.bootstrap_admin \
  --email you@yourdomain.example --role superadmin --name "Your Name"
```

`--rm` leaves nothing behind, `--no-deps` never starts redis, and the `api` service reads
`.env` through the shared anchor (`compose.prod.yml:34,64-65`), which is how
`AUDIT_CHAIN_SECRET`, `DATABASE_URL` and `ALEMBIC_DATABASE_URL` reach it.

The host/dev-box form, for completeness only — it needs a venv you do not have on the VPS
(`docs/DEPLOYMENT.md:1378-1381`):

```sh
DATABASE_URL=… ALEMBIC_DATABASE_URL=… uv run python -m scripts.bootstrap_admin \
  --email you@yourdomain.example --role superadmin --name "…"
```

### What it takes, and what it does not

| Flag | Required | Notes |
|---|---|---|
| `--email` | **yes** | the address the link is issued FOR; must contain `@` (`scripts/bootstrap_admin.py:129`, `apps/api/authn/bootstrap.py:156-158`) |
| `--role` | no | `superadmin` (default) or `operator`, nothing else (`scripts/bootstrap_admin.py:130`; validated against `core/rbac.ADMIN_ROLES`, `apps/api/authn/bootstrap.py:108,154-155`) |
| `--name` | no | display name, for the audit trail only (`scripts/bootstrap_admin.py:131`) |

It takes **no password** — none is generated, printed or defaulted anywhere
(`scripts/bootstrap_admin.py:19-25`, `apps/api/authn/bootstrap.py:22-29`). There is **no
`--force`** and there never will be (`apps/api/authn/bootstrap.py:46-51`). It takes no
phone, no MFA, no tenant.

**Two DSNs, two roles, both required or it exits before doing anything**
(`scripts/bootstrap_admin.py:58-73`): `ALEMBIC_DATABASE_URL` (owner role — it writes the
operator allowlist) and `DATABASE_URL` (app role — `auth_credentials` and
`auth_email_tokens` are FORCE-RLS'd against the `app.auth` GUC).

---

## WHAT YOU WILL SEE

On success, exactly this shape on stdout (`scripts/bootstrap_admin.py:108-118`; the same
block is quoted in `runbooks/first-deploy.md:351-357` as observed during the D-188 audit):

```
created admin_users row 0198…-…  (superadmin)
email sent: NO — use the link below
expires:    2026-08-25T…+00:00
Setup link (single use):
https://admin.calevate.tech/bootstrap?token=…
```

- Line 1 says `created …` on a first run and `already present, new link issued for …` on a
  re-run for the same address (`scripts/bootstrap_admin.py:108`).
- Line 2 is `yes` only if the transport reported a successful send. With no
  `EMAIL_PROVIDER` set, a prod deployment resolves to `NullTransport`, which returns
  `False` and logs `email_no_transport` with reason `no_email_provider`
  (`apps/workers/transport.py:497-521,470-494`, `packages/shared/src/calevate_shared/config.py:1330-1339`).
- Both an email and a printed link are attempted on every run — it is not either/or.
- If the send raises rather than returning False you additionally get
  `warning: could not send the email (<ExceptionType>)` on **stderr**
  (`scripts/bootstrap_admin.py:105-106`).

**On refusal** (an operator already has a password) it prints the title, the detail and
the remediation to stderr and exits **1** — not a traceback
(`scripts/bootstrap_admin.py:140-147`, `apps/api/authn/bootstrap.py:129-142`). A bad
`--role` or a malformed address exits **2** (`scripts/bootstrap_admin.py:148-150`).

### What you do with the link

1. Open it. **TTL is 60 minutes, and it is single-use**
   (`apps/api/authn/tokens.py:73`; the runbook says the same at
   `runbooks/first-deploy.md:363-364`). Re-running the command issues a fresh link and
   invalidates the previous one (`apps/api/authn/bootstrap.py:236-251`).
2. On the page you set **a password. That is all** — no MFA enrolment exists in this
   product (`apps/api/authn/service.py:301-307`).
3. The redemption (`POST /v1/auth/admin/bootstrap/confirm`) burns the token first, refuses
   an account that already has a password, installs the password and revokes any sessions
   (`apps/api/authn/bootstrap.py:285-344`).
4. You are then a `superadmin`: every permission by derivation
   (`apps/api/core/rbac.py:145,271`), including the four an `operator` never gets —
   `admin:operators`, `ops:manage`, `platform:config`, `platform:secrets`
   (`apps/api/core/rbac.py:174-181`). `platform:config` is the one that unlocks
   `admin.calevate.tech/ops/config`, i.e. everything `/healthz/ready` is red for
   (`runbooks/first-deploy.md:380-384`).

---

## THE CRUX: does a working mail provider block the first login?

**Two different answers, and conflating them is the mistake.**

**Bootstrap + password: NO, mail does not block it.** The link is printed and delivery
failure is explicitly non-fatal, with the chicken-and-egg spelled out in the code — the
mail credentials are themselves stored by an operator, in the console
(`scripts/bootstrap_admin.py:95-98`, `runbooks/first-deploy.md:359-361`). D-188's finding
is correct as far as it goes (`docs/ROADMAP.md:531`).

**Sign-in: YES, it does.** `MFA_REQUIRED_REALMS = {"admin"}`, unconditional and not
env-gated (`apps/api/authn/service.py:114`). A correct admin password issues a session
that can do exactly ONE thing — answer `POST /v1/auth/admin/login/otp`
(`apps/api/authn/service.py:25-27`, `apps/api/authn/routes.py:289`). The six-digit code is
stored only as a keyed hash and its plaintext exists in one place: the message body
(`apps/workers/transport.py:421-428`). `ConsoleTransport`, which would print it, is
reachable only under `APP_ENV=local` and is gated a second time on the same check
(`apps/workers/transport.py:439-444,456-466`, `packages/shared/src/calevate_shared/config.py:1330-1335`).

So on a prod VPS with no working mail: you can create the superadmin and set its password,
and you cannot get past the sign-in page. **Get mail working before you try to sign in,
not before you bootstrap.**

**With Resend pending specifically:** an unverified sender domain is refused per-send with
a 403, logged as `email_sender_rejected` — it is a hard refusal, not spam-foldering
(`apps/workers/transport.py:271-304`, `packages/shared/src/calevate_shared/config.py:823-826`,
`runbooks/first-deploy.md:460-463`). Whether your specific domain has finished propagating
is **UNKNOWN — it needs a live send against the real Resend account**; `VPS_INPUTS.md:176`
records it as pending.

---

## TRAPS

**1. The printed link 404s as printed. Fix the path by hand.**
**RESOLVED 25 Aug 2026 — the finding below is the defect as found, kept for the record.**
Both composers now delegate to `apps/api/core/console_links`, and
`tests/auth_email_delivery_test` resolves every mailed link against the Next.js route
tree on disk rather than against the other composer. The password-reset link was wrong
the same way and was fixed in the same change.

The script and the email template both compose `https://admin.calevate.tech/bootstrap?token=…`
(`scripts/bootstrap_admin.py:76-77`, `apps/workers/auth_email.py:142-150`). The page the
web app actually serves is **`/auth/admin/bootstrap`**
(`apps/web/src/app/(auth)/auth/admin/bootstrap/page.tsx:4`,
`apps/web/src/lib/authn/adminAuthn.ts:38`); there is no `/bootstrap` route
(`apps/web/.next/types/routes.d.ts:4` enumerates every app route and it is absent), no
Next.js redirect (`apps/web/next.config.ts` declares neither `redirects` nor `rewrites`)
and no nginx rewrite on the admin vhost (`infra/nginx/calevate.conf.template:121-148`).
**Open `https://admin.calevate.tech/auth/admin/bootstrap?token=…` instead.** Hitting the
404 does not spend the token — the token is burned only by the confirm POST
(`apps/api/authn/bootstrap.py:305-311`) — so this costs you a URL edit, not a re-run.
The guard that should have caught this only asserts the script and the email agree with
each other, never that either names a page that exists
(`tests/auth_email_delivery_test.py:205-223`, contrast the client-realm guard at
`tests/auth_email_delivery_test.py:186-202` which reads the path out of the TypeScript).

**2. `AUDIT_CHAIN_SECRET` must be in `.env` BEFORE you run this, and the runbook's
description of the failure is optimistic.** Creating the first operator writes an
`auth.admin_bootstrapped` audit row, and the hash chain refuses to sign without a key
outside `local` (`apps/api/compliance/audit.py:117-138`,
`apps/api/core/settings.py:530-538`). It is normally console-managed, and on a fresh host
the console cannot be the answer — reaching it needs an operator and creating one needs
the key — so it comes from the environment, which beats the store by design
(`docs/DEPLOYMENT.md:1383-1393`, `runbooks/first-deploy.md:341-346`). **But it does not
stop "before it touches the database"** as `docs/DEPLOYMENT.md:1386` says: the row and the
token are committed at `apps/api/authn/bootstrap.py:168-251`, and the audit write is a
LATER, separate transaction at `apps/api/authn/bootstrap.py:259-267`. So a run with the
key missing leaves a real `admin_users` row and a live token that **was never printed**.
Recovery is exactly the documented one — set the key, re-run — because the second run is
the resend case and retires the orphaned token
(`apps/api/authn/bootstrap.py:198-214,236-244`). Symptom to expect: the refusal titled
"The audit chain is not configured", exit 1, with `hmac_key_missing` in the log
(`apps/api/core/settings.py:531-538`).

**3. Mistype the address and you create a second, stranded superadmin row — with a live
60-minute link addressed to a stranger.** The idempotency check matches on the exact
address (`apps/api/authn/bootstrap.py:198-212`), so a typo takes the INSERT branch and a
fresh row is created. `already_bootstrapped` will not protect that row later:
`confirm_bootstrap` refuses only if THAT row already has a password
(`apps/api/authn/bootstrap.py:330-340`), so within the hour the typo'd link is a working
path to a second superadmin. **Read the address back before you press enter.** If mail is
dead the link only ever existed on your screen, which is the one upside of a pending
Resend.

**4. You get one bootstrap, ever, and there is no `--force`.** Once ANY live operator holds
a password the script refuses with `already_bootstrapped`
(`apps/api/authn/bootstrap.py:176-196,129-142`). Further operators come from the console,
where an existing operator vouches (`apps/api/authn/operators.py`). The only escape from
"we lost every operator" is a database-level act by the owner role
(`apps/api/authn/bootstrap.py:46-51`).

**5. `--role operator` on the first admin is a dead end you have to unpick.** The four
superadmin-only permissions include `platform:config` and `platform:secrets`
(`apps/api/core/rbac.py:174-181`), which are exactly what step 8 sends you to
`/ops/config` to fill (`runbooks/first-deploy.md:380-384`). An `operator` cannot get
there, and cannot add operators either (`admin:operators`). Take the default.

**6. The link points at `admin.calevate.tech`, so DNS and TLS must be live before the
60-minute clock runs out.** The runbook's own advice is to finish steps 8–9 first rather
than race it (`runbooks/first-deploy.md:367-368`). Re-running is free, so this is an
annoyance, not a loss.

**7. Both `EMAIL_PROVIDER` and `RESEND_API_KEY` belong in `.env`, not in the console —
otherwise the OTP deadlocks you out.** `RESEND_API_KEY` is env-only by decision
(`apps/api/core/settings.py:239-251`, `packages/shared/src/calevate_shared/config.py:786-802`).
`EMAIL_PROVIDER` is deliberately console-editable
(`packages/shared/src/calevate_shared/config.py:777-798`) — but the console is behind the
sign-in OTP that needs a transport, so on a fresh host set it in the environment too
(environment beats the store, D-95's `env → db → default → refuse`,
`docs/DEPLOYMENT.md:1388-1390`). Neither key appears in `.env.example` — add them by hand.
Note also that `NOTIFICATIONS_FROM` defaults to `support@calevate.tech`
(`packages/shared/src/calevate_shared/config.py:815-826`): the sender domain Resend must
have verified is the one in THAT field.

**8. The OTP email goes through the outbox, so the `workers` container must be running
when you sign in.** The challenge and its delivery job are written in the same transaction
(`apps/api/authn/service.py:262-281`, `apps/api/authn/service.py:800-828`) and relayed by
ARQ. Bootstrap itself does NOT use the outbox — it calls the transport synchronously and
inline (`scripts/bootstrap_admin.py:100-104`), which is why it works on a box where
nothing else is up yet.

---

## One-paragraph summary for the terminal

Run the compose form with `--email` and `--role superadmin`, having put
`AUDIT_CHAIN_SECRET`, `EMAIL_PROVIDER=resend` and `RESEND_API_KEY` in `.env` first. Expect
`email sent: NO` while Resend is pending and copy the printed link, **rewriting
`/bootstrap?token=` to `/auth/admin/bootstrap?token=`**. Set a password — that is the only
thing that page asks for. Then stop: you cannot sign in until mail genuinely delivers,
because the admin realm mails a six-digit code on every sign-in and there is no way to
read it off the server outside `APP_ENV=local`.
