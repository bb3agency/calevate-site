This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Authentication (two Clerk applications, one Next app)

TRD §11 and D-37 put the two realms in **two separate Clerk applications** — admin
(`admin.calevate.tech`, invite-only) and client (`app.calevate.tech`, self-serve) —
with separate cookies and no shared session logic. This app serves both hostnames, so
both applications live in one codebase without ever being mounted together:

| Route tree | Clerk application | Mounted by |
| --- | --- | --- |
| `/c/**` | client, or **admin** under `?view=admin` (D-22) | `src/lib/api/session.tsx` |
| `/signup`, `/sign-in`, `/sign-up` | client | the page itself |
| `/admin/**` | admin | `src/app/admin/layout.tsx` |

clerk-js is a browser singleton (`window.Clerk`), so a document hosts exactly one
application — which is why the realm is chosen where the session is chosen, in one
place, and never by two files that could disagree. `src/lib/auth/` holds it:
`mode.ts` (which credential this build presents), `clerkRuntime.tsx` (the vendor
bridge), and `clientRealm.tsx` / `adminRealm.tsx`, which are twins on purpose and
import each other never.

### Environment

These are **browser** variables: `next build` inlines them, so changing one needs a
rebuild, not a restart. They are deliberately not `Settings` fields — see the comment
block beside `CLERK_WEBHOOK_SECRET` in the repo's `.env.example`. Put them in
`apps/web/.env.local` (git-ignored).

```bash
# Which credential the browser presents. Unset = `dev` locally, `clerk` in a
# production build. `dev` in a production build FAILS THE BUILD, on purpose.
NEXT_PUBLIC_AUTH_MODE=clerk

# The two applications' publishable keys. They must name the SAME applications as
# CLERK_CLIENT_PUBLISHABLE_KEY / CLERK_ADMIN_PUBLISHABLE_KEY on the API, which
# derives each realm's JWKS host from its copy (`core/auth.py::jwks_url`).
NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY=pk_live_...
NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY=pk_live_...
```

Leave all three unset for local work: the app then mounts no Clerk at all and signs
every request with `dev:<realm>:<id>`, which the API accepts only under `APP_ENV=local`
with no Clerk secret for that realm (`apps/api/core/auth.py::_verify_dev_token`). A
deployment set to `clerk` that has no publishable key renders a "sign-in is not
configured" panel and refuses every request — it never falls back to a dev token.

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
