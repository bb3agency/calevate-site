"use client";

/**
 * The ADMIN realm's provider, guard, gate and guest-only quartet (D-174, §5.5).
 *
 * Duplicated from — never shared with — `clientSession.tsx`. CLAUDE.md forbids the two
 * realms sharing session logic, and this file names `adminAuthn` and the admin paths as
 * literals in every position where a realm could otherwise be a variable. The presentation
 * (`components/authn/sessionGate.tsx`) IS shared, because it holds no session and takes no
 * realm — it is given a status and a label and renders neither differently.
 *
 * ## The watchdog only ever redirects
 *
 * §5.5's is 12 seconds and its comment records why it does nothing else: clearing the
 * session there would bump the restore nonce and start a fresh cookie exchange while a
 * navigation is already in flight, which is a mobile redirect loop they hit. Ours keeps
 * the redirect-only rule and moves the NUMBER, for a reason of our own.
 *
 * Theirs fires at 12s against a 15s restore deadline, so a slow-but-working 13-second
 * restore is redirected away — which contradicts the same file's hard-won rule that a
 * timeout is soft and must not strand a valid session. Ours fires at the deadline plus a
 * margin, so it cannot pre-empt a restore that is about to succeed, and the only thing it
 * can catch is the state it is actually for: a gate still saying "checking" after the
 * machinery that was supposed to resolve it did not. That is a bug or a suspended tab, and
 * either way a spinner that never resolves is the worst screen to leave somebody on.
 */

import { createContext, useContext, useEffect, type ReactNode } from "react";

import { SessionGate } from "@/components/authn/sessionGate";
import { Skeleton } from "@/components/ui";
import { adminConsoleUrl } from "@/lib/consoleOrigin";

import {
  ADMIN_CONSOLE_PATH,
  ADMIN_SIGN_IN_PATH,
  adminAuthn,
} from "./adminAuthn";
import { RESTORE_DEADLINE_MS, type AuthnSession } from "./realm";
import { useRealmSession, type RealmSessionState } from "./useRealmSession";

/** See the file docstring. Deliberately AFTER the restore deadline, not before it. */
export const ADMIN_WATCHDOG_MS = RESTORE_DEADLINE_MS + 2_000;

const ADMIN_REALM_LABEL = "operator console";

/** Guest paths this realm owns — where a redirect to sign-in would be a reload loop. */
const ADMIN_GUEST_PATHS = [
  ADMIN_SIGN_IN_PATH,
  "/auth/admin/forgot-password",
  "/auth/admin/reset-password",
  "/auth/admin/bootstrap",
];

/**
 * Hard navigation, not `router.replace` (§5.5).
 *
 * `window.location.assign` because a soft navigation can stall when leaving a route group,
 * and a stalled redirect out of a dead session is a console nobody can escape. The
 * already-on-a-guest-path check is the reload-loop guard: redirecting the sign-in page to
 * the sign-in page is an infinite navigation, and it is reachable the moment a restore
 * fails on that page — which is the normal state of somebody about to sign in.
 */
export function redirectToAdminSignIn(): void {
  if (typeof window === "undefined") return;
  const here = window.location.pathname;
  if (
    ADMIN_GUEST_PATHS.some(
      (path) => here === path || here.startsWith(`${path}/`),
    )
  )
    return;
  window.location.assign(ADMIN_SIGN_IN_PATH);
}

const AdminSessionContext = createContext<RealmSessionState | null>(null);

/**
 * Runs the restore for the protected admin surface and provides its result.
 *
 * Renders its children unconditionally — the GUARD decides what to show. Splitting them is
 * §5.5's layering and it earns its keep: a screen that wants to render a signed-out shell
 * with a sign-in prompt inside it (the session home does) needs the context without the
 * gate, and a screen that must not paint at all before a session exists needs the gate.
 */
export function AdminSessionProvider({ children }: { children: ReactNode }) {
  const state = useRealmSession(adminAuthn, "session");
  const { status } = state;

  useEffect(() => {
    if (status !== "restoring") return;
    const timer = setTimeout(redirectToAdminSignIn, ADMIN_WATCHDOG_MS);
    // Cleared on EVERY exit — the same discipline §5.7 defect 1 is about. A watchdog that
    // outlives the state it was watching redirects a console that has since resolved.
    return () => clearTimeout(timer);
  }, [status]);

  return (
    <AdminSessionContext.Provider value={state}>
      {children}
    </AdminSessionContext.Provider>
  );
}

export function useAdminSession(): RealmSessionState {
  const state = useContext(AdminSessionContext);
  if (!state) {
    throw new Error(
      "useAdminSession must be used inside <AdminSessionProvider>",
    );
  }
  return state;
}

/**
 * Paints nothing but the gate until this realm has a live, fully authenticated session.
 *
 * Fail-closed: the default arm is the gate, and `ready` is the only status that reaches
 * `children`. Written as an allowlist rather than as `status === "signed-out" ? gate :
 * children` on purpose — the second form renders the console for every status somebody
 * adds later and forgets to handle.
 */
export function AdminSessionGate({
  children,
  /**
   * Passed through to `SessionGate`. TRUE from the console shell, where this gate is the
   * entire document and must supply its `main` landmark and its heading; FALSE (the
   * default) from `/auth/admin`, which renders it inside `AuthPageFrame`'s `<main>` and
   * under that page's own `<h1>`.
   */
  landmark = false,
}: {
  children: ReactNode;
  landmark?: boolean;
}) {
  const { status, retry } = useAdminSession();
  if (status === "ready") return <>{children}</>;
  return (
    <SessionGate
      status={status}
      realm="admin"
      realmLabel={ADMIN_REALM_LABEL}
      signInPath={ADMIN_SIGN_IN_PATH}
      onRetry={retry}
      landmark={landmark}
    />
  );
}

/**
 * The inverse: bounce an operator who is already signed in off a guest page.
 *
 * Its own audience (`"guest"`), which is the split §5.4 insists on — without it a failed
 * restore on the console would set one shared `blocked` flag and the sign-in page, whose
 * entire job is to fix that, would refuse to try.
 *
 * `partial` deliberately renders the children: a session that has proved a password and
 * owes a code belongs ON the sign-in page, at its second step. Bouncing it to the console
 * would send it to a gate that refuses it, and back, forever.
 */
export function AdminGuestOnly({ children }: { children: ReactNode }) {
  const { status, session } = useRealmSession(adminAuthn, "guest");
  const alreadyIn = status === "ready" && session !== null;

  useEffect(() => {
    if (!alreadyIn || typeof window === "undefined") return;
    // THE CONSOLE, and this is the half that made the sign-in redirect unreliable rather
    // than merely wrong. `SignInForm.onSignedIn` navigates, and in the same commit the
    // session goes non-null, so THIS effect fires too -- two `window.location.assign`
    // calls in one tick, and the later one wins. While these two named different
    // destinations, where an operator landed after signing in was a race, which is why it
    // looked intermittent. Both now name `/admin`, so the race has one outcome.
    window.location.assign(adminConsoleUrl(ADMIN_CONSOLE_PATH));
  }, [alreadyIn]);

  // A wait while the restore runs, so the sign-in form does not paint and then vanish
  // under a redirect — and `Skeleton` rather than null, per BUILD-LOG §52, because a blank
  // screen is not a loading state.
  if (status === "restoring" || alreadyIn)
    return <Skeleton rows={4} label="Checking…" />;
  return <>{children}</>;
}

/** The session this realm holds, for screens that want it without the gate's opinion. */
export function useAdminSessionRow(): AuthnSession | null {
  return useAdminSession().session;
}

export const ADMIN_SESSION_LABEL = ADMIN_REALM_LABEL;
