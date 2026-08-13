"use client";

/**
 * The ADMIN realm's identity: its own Clerk application, its own session, its own door.
 *
 * The twin of `clientRealm.tsx`, and separate from it on purpose — see that file's note.
 * TRD §11 and D-37 put the two realms in two Clerk applications with two cookies and two
 * deploys, and `core/auth.py::jwks_url` enforces the same split server-side: an admin
 * token is verified against the ADMIN application's JWKS, so a client token presented
 * here is not a weak admin token, it is not a token at all.
 *
 * ## One door, and no second one
 *
 * D-37: the admin realm is **invite-only, signup disabled**. There is therefore no
 * `/admin/sign-up` route and no `signUpUrl` on the provider below. An operator account is
 * created in the Clerk dashboard and mirrored into `admin_users`; a self-serve path into
 * the operator console is not a feature that was skipped, it is one that must not exist.
 */

import type { ReactNode } from "react";

import { ClerkProvider, RedirectToSignIn, Show } from "@clerk/nextjs";

import { devToken, type Session, type TokenSource } from "@/lib/api/client";

import { clerkSessionToken, ClerkNotConfigured, type ClerkRealmConfig } from "./clerkRuntime";
import { AUTH_MODE } from "./mode";

/** Where an operator signs in. Inside `/admin/**` so the realms stay separable by path
 * as well as by host — the admin console is its own deploy target (TRD §11). */
export const ADMIN_SIGN_IN_PATH = "/admin/sign-in";

/**
 * The admin application's publishable key — a DIFFERENT Clerk application from the
 * client realm's, never the same key with a flag. See `clientRealm.tsx` on why neither
 * realm uses `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`.
 */
const ADMIN_PUBLISHABLE_KEY_ENV = "NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY";
const ADMIN_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY ?? "";

const ADMIN_REALM: ClerkRealmConfig = {
  realm: "admin",
  publishableKeyEnv: ADMIN_PUBLISHABLE_KEY_ENV,
  publishableKey: ADMIN_PUBLISHABLE_KEY,
  signInPath: ADMIN_SIGN_IN_PATH,
};

/** This realm's bearer credential, fetched fresh for every request. */
const adminRealmToken: TokenSource = () => clerkSessionToken(ADMIN_REALM);

/**
 * The LOCAL admin credential. `dev:admin:` and never `dev:client:` — `_verify_dev_token`
 * checks the realm segment, so a client token pasted into an admin surface is refused by
 * the API rather than merely being the wrong shape.
 */
function devAdminToken(): TokenSource {
  return devToken("admin", process.env.NEXT_PUBLIC_DEV_ADMIN ?? "admin_local");
}

/**
 * The session every admin-realm call speaks with.
 *
 * `lib/api/admin.ts::adminSession()` delegates here, which is why that function keeps
 * its name and signature across all twenty-five of its call sites: the credential
 * changed, the seam did not.
 */
export function adminRealmSession(orgSlug: string): Session {
  return AUTH_MODE === "dev"
    ? { token: devAdminToken(), orgSlug }
    : { token: adminRealmToken, orgSlug };
}

/**
 * Mounts the ADMIN Clerk application for this document.
 *
 * Same shape as the client realm's provider and deliberately not shared with it. In
 * `dev` mode it mounts nothing, so the admin test suites keep running on `dev:admin:`
 * tokens with `fetch` as the only seam.
 */
export function AdminRealmClerkProvider({
  children,
  protect = false,
}: {
  children: ReactNode;
  protect?: boolean;
}) {
  if (AUTH_MODE === "dev") return <>{children}</>;

  if (!ADMIN_PUBLISHABLE_KEY) {
    return <ClerkNotConfigured realm="admin" publishableKeyEnv={ADMIN_PUBLISHABLE_KEY_ENV} />;
  }

  return (
    <ClerkProvider
      publishableKey={ADMIN_PUBLISHABLE_KEY}
      signInUrl={ADMIN_SIGN_IN_PATH}
      // No `signUpUrl`: D-37 makes this realm invite-only, and a "Sign up" link on the
      // operator console's sign-in card would point at a door that must stay shut.
      afterSignOutUrl={ADMIN_SIGN_IN_PATH}
    >
      {protect ? (
        // Core 3 replaced `<SignedIn>`/`<SignedOut>` with `<Show when=…>`; see the note
        // in `clientRealm.tsx`.
        <Show when="signed-in" fallback={<RedirectToSignIn />}>
          {children}
        </Show>
      ) : (
        children
      )}
    </ClerkProvider>
  );
}

/** Renders `children` only for someone who has an admin-realm identity. */
export function AdminRealmSignedIn({
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

/** The mirror of `AdminRealmSignedIn`: what someone without an operator session sees. */
export function AdminRealmSignedOut({ children }: { children: ReactNode }) {
  if (AUTH_MODE === "dev") return null;
  return <Show when="signed-out">{children}</Show>;
}
