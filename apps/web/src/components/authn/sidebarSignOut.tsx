"use client";

/**
 * The way out, on every shell that has a sidebar.
 *
 * WHAT WAS MISSING. Both consoles showed WHO you are signed in as at the bottom of the
 * sidebar and offered no way to stop being them. The only sign-out in the product lived
 * on `/auth/account`, which a client user reaches through a link and an operator does not
 * reach at all — the admin realm has no account screen — so the honest answer to "how does
 * an operator sign out" was "close the tab and wait for the idle timer", and a shared or
 * unattended machine makes that a real exposure rather than an inconvenience.
 *
 * ONE COMPONENT, BOTH REALMS, and that is not a violation of the rule that keeps the two
 * realms' session logic apart. CLAUDE.md forbids SHARED SESSION LOGIC; this holds none.
 * It is presentation over a `signOut` function and a path, both handed in by the caller —
 * `adminAuthn` in the admin shell, `clientAuthn` in the client one — so the two realms
 * still have separate instances, separate cookies and separate sign-in URLs, exactly as
 * `adminAuthn.ts` and `clientAuthn.ts` declare them. What would break the rule is this
 * file IMPORTING either realm and deciding between them, which is why it takes `authn` as
 * a parameter and names no realm anywhere.
 *
 * A REFUSED SIGN-OUT STAYS ON SCREEN, and this was written the other way first. The
 * original navigated away on failure too, reasoning that `RealmAuthn.signOut` clears
 * local state in a `finally` before it re-raises, so the console was already sitting over
 * a dead session and had to move. `tests/surfaceStatesGuard.test.ts` — BUILD-LOG §52,
 * "failure is a refusal" — caught it, and it was right: `reset()` clears the realm's
 * internal caches and notifies NOBODY, so nothing re-renders and nothing bounces. Staying
 * is not only possible, it is the only way the person finds out. So a failure now states
 * itself where the click happened, with the one action that resolves it.
 *
 * "Signed out" and "signed out here only" are different facts and the second is the
 * person's to act on: this browser has stopped holding the session, but the server never
 * confirmed it ended, so it may still be open on another device until the 12-hour idle or
 * 14-day absolute bound retires it. The remedy is to sign in and use "Sign out
 * everywhere", which is why the refusal offers exactly that door and carries the reason
 * with it.
 *
 * THE COLLAPSED RAIL IS THE ONE EXCEPTION, because 72px cannot hold a sentence. There the
 * refusal travels instead of being stated — to the sign-in screen, as a query parameter
 * the shared `SignInForm` renders. The information is never dropped; only its location
 * depends on whether there is room to read it.
 */

import { useCallback, useEffect } from "react";

import { useMutation } from "@tanstack/react-query";
import { LogOut } from "lucide-react";

import { SidebarLabel } from "@/components/sidebarCollapse";

/**
 * The query parameter a sign-in screen can read to explain an incomplete sign-out.
 *
 * Exported so the screen that renders the notice and the button that causes it cannot
 * drift to two spellings — the defect class D-103/D-105 exist for, in one string.
 */
export const SIGN_OUT_INCOMPLETE_PARAM = "signout";
export const SIGN_OUT_INCOMPLETE_VALUE = "incomplete";

export interface SidebarSignOutProps {
  /** The realm's session object. Only `signOut` is used; the realm is never named here. */
  readonly authn: { signOut(): Promise<number> };
  /** Where this realm's people sign in — `ADMIN_SIGN_IN_PATH` or `CLIENT_SIGN_IN_PATH`. */
  readonly signInPath: string;
  /** Matches the sidebar's collapsed state so the control collapses with its neighbours. */
  readonly isCollapsed: boolean;
}

export function SidebarSignOut({ authn, signInPath, isCollapsed }: SidebarSignOutProps) {
  const leave = useCallback(
    (complete: boolean) => {
      const url = complete
        ? signInPath
        : `${signInPath}?${SIGN_OUT_INCOMPLETE_PARAM}=${SIGN_OUT_INCOMPLETE_VALUE}`;
      // `assign`, not the router: the whole point is to discard every cache and provider
      // this console built while signed in. A client-side navigation would keep the React
      // tree — and its TanStack cache of another account's data — alive across the change.
      window.location.assign(url);
    },
    [signInPath],
  );

  const signOut = useMutation({
    mutationFn: () => authn.signOut(),
    onSuccess: () => leave(true),
    // NO `onError` that navigates. The refusal is rendered below instead -- see the
    // module docstring for why staying is both possible and necessary. The collapsed rail
    // is the exception, and it is handled where the refusal would otherwise be drawn.
  });

  const busy = signOut.isPending;
  const refused = signOut.error != null;

  // 72px of rail cannot state a refusal, so it carries one instead — to the sign-in
  // screen, which has room. In an EFFECT, not in the render body: `leave` navigates, and a
  // navigation fired while React is rendering is a side effect during render, which
  // StrictMode double-invokes and which can re-enter before the assign settles.
  useEffect(() => {
    if (refused && isCollapsed) leave(false);
  }, [refused, isCollapsed, leave]);

  return (
    <div className="space-y-2">
    <button
      type="button"
      // `disabled` while in flight rather than a guard inside the handler: a second click
      // would issue a second POST against a session the first one is already revoking, and
      // the second reliably 401s — turning a successful sign-out into the incomplete
      // notice.
      disabled={busy}
      onClick={() => signOut.mutate()}
      title={isCollapsed ? "Sign out" : undefined}
      aria-label="Sign out"
      // `px-5` inside the footer's `px-2` puts this glyph's centre on 36px — the collapsed
      // rail's centre line, the same one every other leading glyph in the panel sits on
      // (`components/sidebarCollapse.tsx`). It therefore does not move while the panel
      // animates; only the label beside it does.
      className="flex w-full items-center gap-3 overflow-hidden rounded-lg px-5 py-2 text-sm font-medium text-ink-muted transition-colors hover:bg-black/5 hover:text-ink disabled:cursor-not-allowed disabled:opacity-60 dark:hover:bg-white/5"
    >
      <LogOut aria-hidden className="h-4 w-4 shrink-0" />
      {/* Mounted in both states and faded, not unmounted: the only way out of the console
          keeps its accessible name on the collapsed rail. */}
      <SidebarLabel isCollapsed={isCollapsed}>{busy ? "Signing out…" : "Sign out"}</SidebarLabel>
    </button>
    {refused && !isCollapsed && (
      // `role="alert"`, because this appears after an action the person took and a screen
      // reader is otherwise never told the control did anything.
      <div
        role="alert"
        className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs leading-snug text-amber-800 dark:text-amber-300"
      >
        <p className="font-semibold">Signed out on this device only</p>
        <p className="mt-1">
          Calevate could not be reached, so this session may still be open elsewhere until
          it times out.
        </p>
        <button
          type="button"
          onClick={() => leave(false)}
          className="mt-2 font-semibold underline underline-offset-2"
        >
          Go to sign-in to end it everywhere
        </button>
      </div>
    )}
    </div>
  );
}
