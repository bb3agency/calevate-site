"use client";

/**
 * The CLIENT realm's identity: its Clerk application, its session, its doors.
 *
 * `adminRealm.tsx` is this file's twin and the duplication between them is REQUIRED,
 * not an oversight. TRD §11 and D-37: two Clerk applications, two session cookies, two
 * deploys, and "never share session logic" (CLAUDE.md conventions). A `realm` parameter
 * on one module would be one bad conditional away from presenting an admin credential
 * on a client surface — which is the same argument `lib/api/admin.ts` already makes for
 * existing as a separate file. The two modules import each other never; the only thing
 * they have in common is the vendor bridge (`clerkRuntime.tsx`), which holds no session.
 *
 * ## The doors
 *
 * - `/sign-in` — returning users. Clerk's own component, path-routed.
 * - `/sign-up` — a stranger creating a Calevate ACCOUNT (D-37: email/password + Google).
 * - `/signup` — a signed-in user creating their WORKSPACE (`POST /v1/auth/signup`).
 *
 * The last two are one hyphen apart and are genuinely different steps, in that order: an
 * account is an identity Clerk owns, a workspace is an organization OUR Postgres owns
 * (D-37 keeps our DB the system of record). `/signup` predates the account routes and is
 * linked from the landing page and named in the tests, so it kept its name; the account
 * route takes Clerk's conventional one. Every link between them is spelled from the
 * constants below rather than typed out, so the hyphen is decided once.
 */

import type { ReactNode } from "react";

import { ClerkProvider, RedirectToSignIn, Show } from "@clerk/nextjs";

import { devSession, type Session, type TokenSource } from "@/lib/api/client";

import { clerkSessionToken, ClerkNotConfigured, type ClerkRealmConfig } from "./clerkRuntime";
import { AUTH_MODE } from "./mode";

/** Where a client-realm person signs in, signs up, and lands afterwards. */
export const CLIENT_SIGN_IN_PATH = "/sign-in";
export const CLIENT_SIGN_UP_PATH = "/sign-up";
/** A new account has no workspace yet, so the account flow ends at the workspace form. */
export const CLIENT_AFTER_SIGN_UP_PATH = "/signup";

/**
 * The client application's publishable key.
 *
 * Deliberately NOT `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, which is the name `@clerk/nextjs`
 * picks up on its own. A realm-blind default is the failure this whole file is arranged
 * to prevent: with it set, a provider that forgot its `publishableKey` prop would still
 * mount — silently, with whichever application that variable happened to name. Both
 * realms therefore use explicit, realm-named variables and pass the prop every time.
 */
const CLIENT_PUBLISHABLE_KEY_ENV = "NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY";
const CLIENT_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY ?? "";

const CLIENT_REALM: ClerkRealmConfig = {
  realm: "client",
  publishableKeyEnv: CLIENT_PUBLISHABLE_KEY_ENV,
  publishableKey: CLIENT_PUBLISHABLE_KEY,
  signInPath: CLIENT_SIGN_IN_PATH,
};

/** This realm's bearer credential, fetched fresh for every request. */
const clientRealmToken: TokenSource = () => clerkSessionToken(CLIENT_REALM);

/**
 * The session every client-realm surface speaks with.
 *
 * The mode decision lives here, at the point the credential is chosen, rather than at
 * each of the call sites: one branch, one place, and `devSession` stays exactly what its
 * name says — the local path, which the entire frontend test suite runs through.
 */
export function clientRealmSession(orgSlug: string): Session {
  return AUTH_MODE === "dev" ? devSession(orgSlug) : { token: clientRealmToken, orgSlug };
}

/**
 * Mounts the CLIENT Clerk application for this document.
 *
 * In `dev` mode it mounts nothing at all — no provider, no clerk-js, no network — which
 * is what keeps the 308-test suite running against `dev:client:` tokens with `fetch` as
 * its only seam. In `clerk` mode with no key it renders the refusal panel instead of the
 * surface, for the reason `ClerkNotConfigured` documents.
 *
 * `protect` turns the subtree into a signed-in-only area. It is off by default because
 * the sign-in and sign-up routes are themselves inside this provider and must stay
 * reachable by a stranger — a redirect there is a loop.
 */
export function ClientRealmClerkProvider({
  children,
  protect = false,
}: {
  children: ReactNode;
  protect?: boolean;
}) {
  if (AUTH_MODE === "dev") return <>{children}</>;

  if (!CLIENT_PUBLISHABLE_KEY) {
    return <ClerkNotConfigured realm="client" publishableKeyEnv={CLIENT_PUBLISHABLE_KEY_ENV} />;
  }

  return (
    <ClerkProvider
      publishableKey={CLIENT_PUBLISHABLE_KEY}
      signInUrl={CLIENT_SIGN_IN_PATH}
      signUpUrl={CLIENT_SIGN_UP_PATH}
      signUpFallbackRedirectUrl={CLIENT_AFTER_SIGN_UP_PATH}
      afterSignOutUrl="/"
    >
      {protect ? (
        // `Show` replaced `<SignedIn>`/`<SignedOut>` in Clerk Core 3 (@clerk/nextjs 7 —
        // neither of the old components is exported any more; verified against
        // node_modules/@clerk/react 6.14.1). It renders null while auth is loading, so
        // a signed-in user never flashes the redirect on the way in.
        <Show when="signed-in" fallback={<RedirectToSignIn />}>
          {children}
        </Show>
      ) : (
        children
      )}
    </ClerkProvider>
  );
}

/**
 * Renders `children` only for someone who has a client-realm identity.
 *
 * In `dev` mode there is no Clerk and the dev token IS the identity, so everything
 * renders — the same statement the API makes when it accepts `dev:client:<id>` without
 * asking anything else.
 */
export function ClientRealmSignedIn({
  children,
  fallback,
}: {
  children: ReactNode;
  fallback?: ReactNode;
}) {
  if (AUTH_MODE === "dev") return <>{children}</>;
  return (
    <Show when="signed-in" fallback={fallback}>
      {children}
    </Show>
  );
}

/** The mirror of `ClientRealmSignedIn`: what a stranger sees. Nothing, locally. */
export function ClientRealmSignedOut({ children }: { children: ReactNode }) {
  if (AUTH_MODE === "dev") return null;
  return <Show when="signed-out">{children}</Show>;
}
