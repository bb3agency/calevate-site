"use client";

/**
 * WHICH session a client-realm page speaks with — decided once, in one place.
 *
 * Two different principals legitimately arrive at `app.calevate.tech/c/<slug>`:
 *
 *  1. the client's own user, who signs in to the CLIENT Clerk application, and
 *  2. an operator following "View as client" out of the admin console (D-22), who has
 *     only an ADMIN Clerk session and must be marked read-only on every panel.
 *
 * Before this module every `/c/<slug>` screen called `devSession(slug)` for itself, so
 * case 2 was unreachable: the browser sent a client token with no `X-Impersonate-Org`,
 * `me.impersonating` came back false, the amber D-22 banner was dead code, and in
 * staging/prod — where an operator has no client-realm session at all — every panel
 * would have answered 401. `viewAsSession` (admin.ts) already built the right session;
 * nothing told the client layout to use it.
 *
 * ## The handoff, and why it cannot be forged
 *
 * The admin console links to `/c/<slug>?view=admin`. The layout reads that marker and
 * builds `viewAsSession(slug)` instead of `devSession(slug)`, and `Nav` carries the
 * marker forward so a page-to-page click does not silently fall back to a client token.
 *
 * The marker is an INTENT, never an authority. All it selects is which credential this
 * browser presents:
 *
 * - `viewAsSession` presents an ADMIN-realm token. A client-realm user does not have
 *   one, and cannot mint one from a URL — `verify_token(token, "admin")` checks the
 *   admin Clerk application's JWKS (and, locally, rejects a `dev:client:` token for the
 *   admin realm outright: `core/auth.py::_verify_dev_token`).
 * - The API only *looks* at the admin realm when `X-Impersonate-Org` is present
 *   (`core/auth.py::current_any`), and then still requires a row in `admin_users` plus
 *   the `admin:impersonate` permission before it will resolve the slug.
 * - Every MUTATING permission is refused for an impersonating principal
 *   (`requires()` + `MUTATING_PERMISSIONS`), so the read-only promise is enforced
 *   server-side whatever this file does.
 * - The banner renders from `me.impersonating` — the SERVER's answer — never from the
 *   URL, so a client-realm user who types `?view=admin` cannot produce one. What they
 *   actually get is a REDIRECT: `viewAsRequested` mounts `<AdminRealmClerkProvider
 *   protect>` (below), so a document with no admin-realm session goes to
 *   `/admin/sign-in` before any read is attempted. This line used to say "401s, not a
 *   banner" — true of the API and true of this file until `protect` was added, and since
 *   then a sentence about a request that is never made.
 *
 * So the worst a client-realm user achieves by editing the query string is breaking
 * their own page; they cannot claim impersonation, and they cannot read another
 * tenant, because the slug is resolved against an admin identity we verified first.
 *
 * ## What the marker now ALSO selects: which Clerk application this document loads
 *
 * clerk-js is a browser singleton, so a document hosts exactly one Clerk application
 * (`lib/auth/clerkRuntime.tsx`). `viewAsSession` presenting an admin-realm token is
 * therefore only possible if the ADMIN application is the one mounted on this page —
 * and it must be, because in production the operator arriving here from
 * admin.calevate.tech has an admin session and no client-realm session at all. So the
 * same marker, read in the same place, chooses the provider and the session together.
 * Splitting that decision across two files is how they would eventually disagree, and a
 * page whose mounted application and presented credential disagree is a 401 nobody can
 * explain.
 */

import { Suspense, createContext, useContext, useMemo, type ReactNode } from "react";

import { useSearchParams } from "next/navigation";

import { AdminRealmClerkProvider } from "@/lib/auth/adminRealm";
import { ClientRealmClerkProvider, clientRealmSession } from "@/lib/auth/clientRealm";

import { viewAsSession } from "./admin";
import { type Session } from "./client";

/** `/c/<slug>?view=admin` — set by the admin console's "View as client" link. */
export const VIEW_AS_PARAM = "view";
export const VIEW_AS_ADMIN = "admin";

export interface ClientRealm {
  /** The session every hook on a `/c/<slug>` screen must use. */
  session: Session;
  /**
   * Whether this tab ASKED for the operator session. Useful for explaining a failed
   * handoff; it is never proof of anything — read `me.impersonating` for that.
   */
  viewAsRequested: boolean;
  /** Carry the marker across in-realm navigation, so the session survives a click. */
  href: (path: string) => string;
}

const ClientRealmContext = createContext<ClientRealm | null>(null);

export function useClientRealm(): ClientRealm {
  const value = useContext(ClientRealmContext);
  if (value === null) {
    // Throwing beats a default: a screen rendered outside the provider would silently
    // fall back to a client token, which is exactly the bug this module exists to fix.
    throw new Error(
      "useClientRealm() must be used inside <ClientRealmProvider> (app/c/[slug]/layout.tsx).",
    );
  }
  return value;
}

/** The common case: a screen just wants the session to pass to its hooks. */
export function useClientSession(): Session {
  return useClientRealm().session;
}

function Resolver({ slug, children }: { slug: string; children: ReactNode }) {
  const params = useSearchParams();
  const viewAsRequested = params.get(VIEW_AS_PARAM) === VIEW_AS_ADMIN;

  const value = useMemo<ClientRealm>(
    () => ({
      session: viewAsRequested ? viewAsSession(slug) : clientRealmSession(slug),
      viewAsRequested,
      href: (path) =>
        viewAsRequested
          ? `${path}${path.includes("?") ? "&" : "?"}${VIEW_AS_PARAM}=${VIEW_AS_ADMIN}`
          : path,
    }),
    [slug, viewAsRequested],
  );

  const realm = <ClientRealmContext.Provider value={value}>{children}</ClientRealmContext.Provider>;

  // `protect` on both: a console screen is signed-in-only in either realm, and the
  // redirect goes to the sign-in page of whichever application is mounted — so an
  // operator whose admin session lapsed mid-handoff lands on the ADMIN sign-in, not on
  // a client one that could never let them back in. In `dev` mode neither provider
  // mounts anything (there is no Clerk), which is what keeps this the same tree the
  // test suite renders.
  return viewAsRequested ? (
    <AdminRealmClerkProvider protect>{realm}</AdminRealmClerkProvider>
  ) : (
    <ClientRealmClerkProvider protect>{realm}</ClientRealmClerkProvider>
  );
}

/**
 * `useSearchParams` opts a route out of static rendering, and Next wants that bailout
 * to have a boundary. The whole client realm is already client-rendered (TanStack
 * Query everywhere), so the boundary costs nothing but keeps `next build` honest.
 */
export function ClientRealmProvider({
  slug,
  children,
  fallback = null,
}: {
  slug: string;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  return (
    <Suspense fallback={fallback}>
      <Resolver slug={slug}>{children}</Resolver>
    </Suspense>
  );
}
