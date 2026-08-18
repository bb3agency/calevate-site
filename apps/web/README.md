# apps/web

## Authentication (two realms, one Next app, no vendor)

TRD §11 puts the two realms in **two separate credential domains** — admin
(`admin.calevate.tech`) and client (`app.calevate.tech`) — and CLAUDE.md forbids them
sharing session logic. Since D-177 both are ours: there is no identity vendor, and the
credential is an `HttpOnly`, `__Host-`-prefixed session cookie the browser attaches and no
script can read.

| Route tree | Session module | Mounted by |
|---|---|---|
| `/admin/**` | `lib/authn/adminSession.tsx` | `app/admin/layout.tsx` |
| `/c/[slug]/**` | `lib/authn/clientSession.tsx` | `lib/api/session.tsx`, from `app/c/[slug]/layout.tsx` |
| `/auth/**` | neither — these are the sign-in screens themselves | each page, via `AuthPageFrame` |

The two session modules import each other never. `lib/authn/realm.ts` holds the factory
they are both built from, and the realm is a **closure constant** fixed at import — a
literal in every path, with no request-time input able to move a call between realms.
`tests/authnSourceGuards.test.ts` pins that the factory is called exactly twice, with
literals.

Where the pieces live:

- `lib/authn/mode.ts` — which credential this build presents (`session` | `dev`), decided
  by configuration once and never inferred from what happens to work.
- `lib/authn/realmSessions.ts` — the one branch on that mode, per realm.
- `lib/authn/transport.ts` — the cookie-credentialed `fetch` for `/v1/auth/**`.
- `lib/api/client.ts` — everything else, with `credentials: "include"` and an OPTIONAL
  bearer that is only ever the local dev token.

## Environment

`apps/web/.env.example` is the template and `scripts/check_web_env_parity.py` is the gate:
every `NEXT_PUBLIC_*` the tree reads must be declared there and every declared one must be
read. Authentication needs none of them — that is the point of D-177 — so the only
auth-adjacent key is:

```
# Which credential the browser presents. Unset = `dev` locally, `session` in a
# production build. An explicit `dev` in a production build FAILS THE BUILD.
NEXT_PUBLIC_AUTH_MODE=
```

Leave it unset for local work: the app then speaks `dev:<realm>:<subject-uuid>`, which the
API accepts only when `APP_ENV=local` AND the deployment holds no `PLATFORM_KEK`
(`apps/api/core/auth.py::_verify_dev_token`). Both guards, always.

`next.config.ts` refuses a DEPLOY build (`CALEVATE_DEPLOY_BUILD=1`) whose
`NEXT_PUBLIC_API_BASE_URL` is empty — the failure that builds green, health-polls green
and serves an unusable app.
