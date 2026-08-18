"use client";

/**
 * The two realms' API sessions — which credential a `lib/api/*` call presents (D-177).
 *
 * ONE FILE, TWO FUNCTIONS, AND NO SHARED BRANCH. CLAUDE.md forbids the realms sharing
 * session logic and AUTH-MIGRATION §3 says why: "a `realm` parameter on one shared module
 * is one bad conditional away from presenting an admin credential on a client surface".
 * Neither function below takes a realm; each names its own as a literal, in the one place
 * a realm appears at all — the dev token's second segment. There is nothing else to share
 * or to get wrong, because in `session` mode NEITHER function produces a credential: the
 * browser attaches the realm's `__Host-` cookie itself and no JavaScript can read it.
 *
 * That is the whole shape change. The Clerk-era `lib/auth/{adminRealm,clientRealm}.tsx`
 * had to be two files because each held a publishable key, a provider, a token fetcher
 * and a set of doors; what is left after the vendor is one branch on `AUTH_MODE`, twice,
 * and duplicating a hundred lines of provider machinery to express it would be ceremony
 * rather than separation. The SESSION providers stay two modules
 * (`lib/authn/{adminSession,clientSession}.tsx`) because those genuinely hold state.
 *
 * `tests/authnSourceGuards.test.ts` is what keeps that honest.
 */

import { devToken, type Session } from "@/lib/api/client";

import { AUTH_MODE } from "./mode";

/** The local operator subject, when a developer wants to be a particular row. */
const DEV_ADMIN_SUBJECT = process.env.NEXT_PUBLIC_DEV_ADMIN ?? "";
const DEV_CLIENT_SUBJECT = process.env.NEXT_PUBLIC_DEV_USER ?? "";

/**
 * The ADMIN realm's API session.
 *
 * In `session` mode it carries no token at all and the `__Host-calevate_admin_session`
 * cookie is the credential (`apps/api/authn/cookies.py`). Locally it carries
 * `dev:admin:<uuid>`, which is refused by two independent server-side conditions
 * anywhere that is not a developer's machine.
 */
export function adminRealmSession(orgSlug = ""): Session {
  return AUTH_MODE === "dev"
    ? { token: devToken("admin", DEV_ADMIN_SUBJECT), orgSlug }
    : { orgSlug };
}

/** The CLIENT realm's API session. Same shape, its own literal, its own cookie. */
export function clientRealmSession(orgSlug: string): Session {
  return AUTH_MODE === "dev"
    ? { token: devToken("client", DEV_CLIENT_SUBJECT), orgSlug }
    : { orgSlug };
}
