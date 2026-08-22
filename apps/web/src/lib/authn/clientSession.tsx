"use client";

/**
 * The CLIENT realm's provider, guard, gate and guest-only quartet (D-174, §5.5).
 *
 * The twin of `adminSession.tsx` and duplicated from it rather than sharing with it —
 * CLAUDE.md's "never share session logic", and AUTH-MIGRATION §3's reason for the rule:
 * "a `realm` parameter on one shared module is one bad conditional away from presenting an
 * admin credential on a client surface". Every realm-dependent value below is a literal
 * naming the client realm, and neither file imports the other.
 *
 * ## What differs from the admin twin, and why — because a copy that differs by accident
 * ## is worse than either
 *
 *  - **No idle-timeout modal.** §5.6 puts one on the admin realm only, and the timeouts
 *    say why: `REALM_TIMEOUTS` (`apps/api/authn/sessions.py`) gives the admin realm 30
 *    minutes idle and 8 hours absolute, and the client realm 12 hours and 14 days. Those
 *    differ "because their blast radii differ by an order of magnitude". A modal warning a
 *    clinic receptionist that their session expires in five minutes, twice a day, is a
 *    control that trains people to dismiss controls.
 *  - **The guest bounce lands on the account page**, not on a console — the client console
 *    lives at `/c/<slug>` and this realm's session machinery does not yet know a slug (see
 *    D-174 on what the cutover still owes).
 */

import { createContext, useContext, useEffect, type ReactNode } from "react";

import { SessionGate } from "@/components/authn/sessionGate";
import { Skeleton } from "@/components/ui";

import { CLIENT_CONSOLE_PATH, CLIENT_SIGN_IN_PATH, clientAuthn } from "./clientAuthn";
import { RESTORE_DEADLINE_MS, type AuthnSession } from "./realm";
import { useRealmSession, type RealmSessionState } from "./useRealmSession";

/** After the restore deadline, never before it — see `adminSession.tsx` for the argument. */
export const CLIENT_WATCHDOG_MS = RESTORE_DEADLINE_MS + 2_000;

const CLIENT_REALM_LABEL = "Calevate";

const CLIENT_GUEST_PATHS = [
  CLIENT_SIGN_IN_PATH,
  "/auth/forgot-password",
  "/auth/reset-password",
  "/auth/accept-invitation",
];

/** Hard navigation with the reload-loop guard. See the admin twin for both reasons. */
export function redirectToClientSignIn(): void {
  if (typeof window === "undefined") return;
  const here = window.location.pathname;
  if (CLIENT_GUEST_PATHS.some((path) => here === path || here.startsWith(`${path}/`))) return;
  window.location.assign(CLIENT_SIGN_IN_PATH);
}

const ClientSessionContext = createContext<RealmSessionState | null>(null);

export function ClientSessionProvider({ children }: { children: ReactNode }) {
  const state = useRealmSession(clientAuthn, "session");
  const { status } = state;

  useEffect(() => {
    if (status !== "restoring") return;
    const timer = setTimeout(redirectToClientSignIn, CLIENT_WATCHDOG_MS);
    return () => clearTimeout(timer);
  }, [status]);

  return <ClientSessionContext.Provider value={state}>{children}</ClientSessionContext.Provider>;
}

export function useClientSession(): RealmSessionState {
  const state = useContext(ClientSessionContext);
  if (!state) {
    throw new Error("useClientSession must be used inside <ClientSessionProvider>");
  }
  return state;
}

/** Fail-closed: `ready` is the only status that reaches `children`. */
export function ClientSessionGate({
  children,
  /**
   * Passed through to `SessionGate`. TRUE from the console shell, where this gate is the
   * entire document and must supply its `main` landmark — including the `#main-content`
   * the shell's always-rendered `SkipLink` points at — and its heading; FALSE (the
   * default) from `/auth/account`, which renders it inside `AuthPageFrame`'s `<main>`.
   */
  landmark = false,
}: {
  children: ReactNode;
  landmark?: boolean;
}) {
  const { status, retry } = useClientSession();
  if (status === "ready") return <>{children}</>;
  return (
    <SessionGate
      status={status}
      realmLabel={CLIENT_REALM_LABEL}
      signInPath={CLIENT_SIGN_IN_PATH}
      onRetry={retry}
      landmark={landmark}
    />
  );
}

/** Bounces an already-signed-in user off a guest page. Its own audience — see §5.4. */
export function ClientGuestOnly({ children }: { children: ReactNode }) {
  const { status, session } = useRealmSession(clientAuthn, "guest");
  const alreadyIn = status === "ready" && session !== null;

  useEffect(() => {
    if (!alreadyIn || typeof window === "undefined") return;
    // THE CONSOLE, and this is the half that would have made the sign-in redirect
    // unreliable rather than merely wrong — the same pair D-441 found on the admin realm.
    // `SignInForm.onSignedIn` navigates, and in the same commit the session goes non-null,
    // so this effect fires too: two `window.location` calls in one tick, later one wins.
    // While the two named different destinations, where a person landed after signing in
    // was a race. Both now name `/c`.
    window.location.assign(CLIENT_CONSOLE_PATH);
  }, [alreadyIn]);

  if (status === "restoring" || alreadyIn) return <Skeleton rows={4} label="Checking…" />;
  return <>{children}</>;
}

export function useClientSessionRow(): AuthnSession | null {
  return useClientSession().session;
}

export const CLIENT_SESSION_LABEL = CLIENT_REALM_LABEL;
