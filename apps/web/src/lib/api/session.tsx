"use client";

/**
 * WHICH session a client-realm page speaks with — decided once, in one place.
 *
 * Two different principals legitimately arrive at `app.calevate.tech/c/<slug>`:
 *
 *  1. the client's own user, who holds a CLIENT-realm session, and
 *  2. an operator following "View as client" out of the admin console (D-22), who holds
 *     only an ADMIN-realm session and must be marked read-only on every panel.
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
 * - `viewAsSession` presents an ADMIN-realm credential. A client-realm user does not
 *   have one, and cannot mint one from a URL — the realm is inside the session token's
 *   hash domain, so a client cookie computed under the admin realm matches no row at all
 *   (`authn/sessions.token_fingerprint`), and locally a `dev:client:` token is rejected
 *   for the admin realm outright (`core/auth.py::_verify_dev_token`).
 * - The API only *looks* at the admin realm when `X-Impersonate-Org` is present
 *   (`core/auth.py::current_any`), and then still requires a row in `admin_users` plus
 *   the `admin:impersonate` permission before it will resolve the slug.
 * - Every MUTATING permission is refused for an impersonating principal
 *   (`requires()` + `MUTATING_PERMISSIONS`), so the read-only promise is enforced
 *   server-side whatever this file does.
 * - The banner renders from `me.impersonating` — the SERVER's answer — never from the
 *   URL, so a client-realm user who types `?view=admin` cannot produce one. What they
 *   actually get is a REDIRECT: `viewAsRequested` mounts the ADMIN realm's session gate
 *   (below), so a document with no admin-realm session goes to `/auth/admin/sign-in`
 *   before any read is attempted.
 *
 * So the worst a client-realm user achieves by editing the query string is breaking
 * their own page; they cannot claim impersonation, and they cannot read another
 * tenant, because the slug is resolved against an admin identity we verified first.
 *
 * ## What the marker ALSO selects: which realm's session this document restores
 *
 * `viewAsSession` presenting an admin-realm credential is only useful if the ADMIN
 * realm's session is the one this document has restored — and it must be, because the
 * operator arriving here from admin.calevate.tech has an admin session and no
 * client-realm session at all. So the same marker, read in the same place, chooses the
 * provider and the session together. Splitting that decision across two files is how they
 * would eventually disagree, and a page whose restored realm and presented credential
 * disagree is a 401 nobody can explain.
 *
 * The two providers are DISJOINT MODULES (`lib/authn/adminSession.tsx` /
 * `clientSession.tsx`), neither importing the other, so the branch below picks between
 * two independent runtimes rather than parameterising one.
 */

import { Suspense, createContext, useContext, useMemo, type ReactNode } from "react";

import { useSearchParams } from "next/navigation";

import { StepUpPrompt } from "@/components/authn/stepUpPrompt";
import { AdminSessionGate, AdminSessionProvider } from "@/lib/authn/adminSession";
import { ClientSessionGate, ClientSessionProvider } from "@/lib/authn/clientSession";
import { clientRealmSession } from "@/lib/authn/realmSessions";

import { viewAsSession } from "./admin";
import { type Session } from "./client";

/** `/c/<slug>?view=admin` — set by the admin console's "View as client" link. */
export const VIEW_AS_PARAM = "view";
export const VIEW_AS_ADMIN = "admin";

/**
 * Where the CLIENT console lives, as seen from the operator console.
 *
 * ## The bug this exists for
 *
 * "View as client" linked to a RELATIVE `/c/<slug>?view=admin`. That is correct in
 * development, where both realms are one origin on `localhost:3000`, and it 404s in
 * production — because the two realms are two hostnames and `admin.` REFUSES `/c/` on
 * purpose. `infra/nginx/calevate.conf.template` returns 404 there so an operator
 * hostname cannot serve a client dashboard, which is the isolation D-177 and P7.3 are
 * about. The link was asking the operator console for a page it is designed never to
 * serve, and an operator opening view-as got the not-found screen.
 *
 * The realm split is right; the link had simply never been told about it. Nothing in a
 * one-origin dev environment can notice.
 *
 * ## Why a declared variable and not string surgery on the hostname
 *
 * Deriving `app.` from `admin.` — or from `NEXT_PUBLIC_API_BASE_URL` — would work today
 * and encode a guess about how these names relate. They are configuration, not a pattern:
 * a staging deployment, a vanity domain or a single-origin preview all break it, silently
 * and only in the browser. The name is declared, checked by
 * `scripts/check_web_env_parity.py` like every other, and `apps/web/.env.example` says
 * what it is for.
 *
 * ## Empty means "same origin", which is what local development is
 *
 * Left unset, `clientConsoleUrl` returns the path unchanged and the behaviour is exactly
 * what it was — one origin, a relative link. That keeps `pnpm dev` working with no
 * configuration and makes the production value the only thing that has to be right.
 */
const CLIENT_CONSOLE_ORIGIN = process.env.NEXT_PUBLIC_CLIENT_CONSOLE_ORIGIN ?? "";

/**
 * A path on the client console, absolute when the realms are on different hostnames.
 *
 * Every operator-console link into `/c/...` goes through here. A bare `href="/c/…"` in an
 * `app/admin/**` file is the defect above, and `tests/viewAsCrossRealm.test.ts` fails on
 * one.
 */
export function clientConsoleUrl(path: string): string {
  const origin = CLIENT_CONSOLE_ORIGIN.replace(/\/+$/, "");
  return origin === "" ? path : `${origin}${path}`;
}

/** The "view as client" destination for one tenant, wherever the client console lives. */
export function viewAsHref(slug: string, path = ""): string {
  return clientConsoleUrl(`/c/${slug}${path}?${VIEW_AS_PARAM}=${VIEW_AS_ADMIN}`);
}

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

  // GATED on both: a console screen is signed-in-only in either realm, and the gate
  // sends them to the sign-in page of whichever realm this document restored — so an
  // operator whose admin session lapsed mid-handoff lands on the ADMIN sign-in, not on a
  // client one that could never let them back in.
  // `landmark`: this gate replaces the WHOLE console shell — sidebar, header and
  // `<main>` — so when it renders there is no other landmark and no heading in the
  // document, and the shell's `SkipLink` (which is deliberately outside this provider)
  // points at a `#main-content` that does not exist. Measured in a real browser: axe
  // reported `skip-link`, `region` and, on the admin side, `landmark-one-main` and
  // `page-has-heading-one`. See `SessionGate`'s prop.
  // `StepUpPrompt` IS MOUNTED HERE, and its absence was a DEADLOCK rather than a missing
  // dialog. Entering a client is a step-up action (D-210), and the grant that carries it
  // is minted lazily by `impersonationGrant` — inside THIS shell, not the admin one. On a
  // `step_up_required` refusal `admin.ts::mint` awaits `requireStepUp`, whose promise is
  // settled by exactly one thing: `completeStepUpPrompt`/`dismissStepUpPrompt`, both
  // called from `<StepUpPrompt />`. That component was mounted only in
  // `app/admin/layout.tsx`, so under impersonation `publish()` reached NO listener, no
  // dialog appeared, and nothing ever settled the promise.
  //
  // The failure was silent and total: the grant source never returned, so every request
  // in the impersonated console awaited it forever. TanStack held every query `pending`
  // with `data` undefined and `error` null, which meant infinite skeletons on every data
  // screen AND — because `ViewAsBanner` keys on `me.data.impersonating` — no read-only
  // banner at all. An operator sat in a client's account with the D-22 marker absent,
  // looking at a console indistinguishable from that client's own. Found by driving the
  // browser; no unit test could see it, because the deadlock is between a module-level
  // promise and a component tree.
  //
  // Mounted in the `viewAsRequested` arm ONLY, beside the admin provider whose realm it
  // belongs to. A client-realm user never has an admin step-up to prove, and mounting
  // admin-realm machinery in their tree would be the realm bleed CLAUDE.md forbids.
  return viewAsRequested ? (
    <AdminSessionProvider>
      <AdminSessionGate landmark>
        <StepUpPrompt />
        {realm}
      </AdminSessionGate>
    </AdminSessionProvider>
  ) : (
    <ClientSessionProvider>
      <ClientSessionGate landmark>{realm}</ClientSessionGate>
    </ClientSessionProvider>
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
