"use client";

/**
 * The BRIDGE to clerk-js. Realm-agnostic on purpose, and it holds no session.
 *
 * TRD §11 and D-37 forbid the two realms sharing session logic, and this file is not
 * that: nothing here knows which realm it is serving, which user is signed in, or what
 * a session looks like. It is the vendor seam — the same role `lib/api/client.ts` plays
 * for `fetch`, which both realms have always shared. The realm-specific parts (the
 * publishable key, the provider, the sign-in path, the session builder) are written out
 * twice, in `clientRealm.tsx` and `adminRealm.tsx`, and those two files never import
 * each other.
 *
 * ## Why the token is read from the Clerk singleton and not from a React context
 *
 * `@clerk/nextjs` exports a framework-free `getToken()` for exactly this job — its own
 * docstring names "API interceptors, data fetching layers" as the use case, and it
 * waits for clerk-js to finish loading rather than returning null while it boots
 * (`@clerk/shared/getToken`, read from node_modules at 4.28.1). The alternative, a
 * context read via `useAuth()`, would force `adminSession()` and its twenty-five call
 * sites to become hooks; the token is a property of the loaded Clerk instance, not of a
 * React subtree, so the hook would be ceremony around the same global.
 *
 * ## The single-instance fact, and the assertion that makes it safe
 *
 * clerk-js is a **browser singleton**: it installs itself on `window.Clerk`, and one
 * document can therefore host exactly ONE Clerk application. That is not a limitation
 * we work around — it is the invariant this app is built on. `/admin/**` and `/c/**`
 * are disjoint route trees on disjoint hostnames (admin.calevate.tech and
 * app.calevate.tech), so only one realm's provider is ever mounted in a document, and
 * the D-22 "view as client" handoff mounts the ADMIN application on the client-realm
 * path precisely because that document must present an admin credential
 * (`lib/api/session.tsx`).
 *
 * `assertMountedApplication` turns "the right provider is mounted" from an assumption
 * into a checked fact. Without it, a future mis-wiring would send a CLIENT token to
 * `/v1/admin/*`; the API refuses it — `verify_token(token, "admin")` resolves the
 * signing key against the admin application's JWKS and an unknown `kid` is a 401 — so
 * this is not the thing standing between a client and the admin console. It is the
 * thing standing between an operator and an unexplainable sign-out loop.
 *
 * ## Two Clerk applications under one registrable domain
 *
 * Both realms live under `*.calevate.tech`, and a Clerk production instance scopes its
 * cookies to the registrable domain so subdomains can share a session. Two applications
 * would collide on those names — except that clerk-js SUFFIXES them: the cookie name
 * carries the first 8 characters of a URL-safe base64 SHA-1 of the publishable key
 * (`getCookieSuffix` / `getSuffixedCookieName` in `@clerk/shared/keys`), so the admin
 * and client applications hold `__client_uat_<a>` and `__client_uat_<b>` side by side.
 * That is what makes two applications on one domain workable at all, and it is the
 * reason the publishable keys must stay distinct rather than being a single key reused.
 */

import { getToken } from "@clerk/nextjs";
import { KeyRound } from "lucide-react";

import { NoticeBox } from "@/components/ui";
import { AuthProblem } from "@/lib/api/client";

/**
 * The publishable key of the Clerk application currently loaded in this document, or
 * `undefined` if clerk-js has not installed itself yet.
 *
 * A narrow structural read rather than a global `declare` block: widening the `Window`
 * type for the whole app would let any file reach for `window.Clerk` and get type
 * support for doing it, which is the opposite of keeping the vendor behind one seam.
 */
function mountedPublishableKey(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const clerk = (window as { Clerk?: { publishableKey?: string } }).Clerk;
  return typeof clerk?.publishableKey === "string" ? clerk.publishableKey : undefined;
}

/** What a realm must tell this bridge about itself for one token fetch. */
export interface ClerkRealmConfig {
  /** For error text only — "client" or "admin", as a person would say it. */
  readonly realm: string;
  /** The environment variable that carries this realm's key, named in the refusal. */
  readonly publishableKeyEnv: string;
  /** This realm's publishable key, exactly as configured (may be empty). */
  readonly publishableKey: string;
  /** Where a person signs in to this realm. */
  readonly signInPath: string;
}

/**
 * Refuse if the mounted Clerk application is not the one this realm expects.
 *
 * Silent while clerk-js is still loading (`undefined`): `getToken()` waits for it, and
 * pre-judging a boot as a mismatch would turn every first paint into an error.
 */
function assertMountedApplication(config: ClerkRealmConfig): void {
  const mounted = mountedPublishableKey();
  if (mounted === undefined || mounted === config.publishableKey) return;
  throw new AuthProblem(
    "realm_mismatch",
    `This page is using the ${config.realm} account but a different Calevate ` +
      "application is loaded in this tab.",
    "Reload the page. If it keeps happening, open this screen from its own console.",
  );
}

/**
 * This realm's bearer credential, or a refusal a person can act on.
 *
 * Every failure below is a DIFFERENT sentence because the remedies differ: a missing
 * key is an operator's job, a missing session is the user's, a load failure is neither
 * and only wants a retry. One "authentication failed" for all three is how a support
 * conversation starts at zero.
 */
export async function clerkSessionToken(config: ClerkRealmConfig): Promise<string> {
  if (!config.publishableKey) {
    // The loud half of `lib/auth/mode.ts`'s doctrine: a deployment configured for real
    // auth that cannot obtain a token says so, at every call, and never reaches for the
    // dev credential instead.
    throw new AuthProblem(
      "auth_not_configured",
      `Sign-in for the ${config.realm} console is not configured on this deployment.`,
      `Set ${config.publishableKeyEnv} to this realm's Clerk publishable key and redeploy.`,
    );
  }

  assertMountedApplication(config);

  let token: string | null;
  try {
    token = await getToken();
  } catch {
    // `getToken()` throws a `ClerkRuntimeError` when clerk-js never loads (10s timeout)
    // or when the browser is offline. Neither is the caller's session being invalid, so
    // neither may be reported as "sign in again" — that sends a signed-in user through
    // a sign-in flow that will also fail.
    throw new AuthProblem(
      "auth_provider_unavailable",
      "We could not reach the sign-in service.",
      "Check your connection and reload the page.",
    );
  }

  if (token === null) {
    throw new AuthProblem(
      "not_signed_in",
      `You are not signed in to the Calevate ${config.realm} console.`,
      `Sign in at ${config.signInPath}.`,
    );
  }
  return token;
}

/**
 * What a realm renders INSTEAD of its Clerk provider when it has no publishable key.
 *
 * Not a thrown error: a throw during render of a route Next prerenders at build time
 * would fail `next build` on any machine without Clerk credentials — CI, for one — and
 * a guard that stops the build is a guard that gets deleted. This renders, so the build
 * is fine and the DEPLOYMENT is unmistakably broken, which is the correct division. It
 * also replaces the surface rather than sitting above it, so there is no path on which
 * a screen half-works against an API that is refusing every call.
 */
export function ClerkNotConfigured({
  realm,
  publishableKeyEnv,
}: {
  realm: string;
  publishableKeyEnv: string;
}) {
  return (
    <div className="mx-auto max-w-xl p-6">
      <NoticeBox
        tone="stop"
        icon={<KeyRound aria-hidden className="h-4 w-4" />}
        title="Sign-in is not configured"
      >
        <p className="mt-1">
          This deployment is set up to use Clerk for the {realm} console but no
          publishable key was supplied, so it cannot sign anybody in.
        </p>
        <p className="mt-2">
          Set <code className="font-mono">{publishableKeyEnv}</code> and redeploy. Nothing
          is signed in, and no fallback credential is used.
        </p>
      </NoticeBox>
    </div>
  );
}
