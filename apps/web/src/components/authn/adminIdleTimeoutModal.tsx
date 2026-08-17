"use client";

/**
 * "You are about to be signed out" — the admin realm's idle bound, made visible (D-174).
 *
 * §5.6, and admin-only for the reason `clientSession.tsx` records: the two realms' idle
 * timeouts differ by an order of magnitude because their blast radii do.
 *
 * ## Extending re-checks the SERVER'S answer, never a claim this browser decoded
 *
 * §5.7 defect 7 is a client that base64-decodes a JWT payload with no signature check and
 * then treats what it finds as authorization — `isVerified: true` set unconditionally, and
 * a `hasPermission` that grants everything on a `"*"` entry. Rendering from unverified
 * claims is fine; deciding from them is not.
 *
 * **We hold no token to decode**, so the defect is structurally out of reach here, and the
 * equivalent check is stronger rather than merely different: `rotateSession()` returns the
 * server's own `SessionOut`, freshly re-read from the subject row (`_session_out` in
 * `apps/api/authn/routes.py`, which exists precisely so a deactivation bites on the next
 * request), and this component accepts the extension only if that answer still says
 * `realm: "admin"` with the second factor complete. A deactivated operator pressing "stay
 * signed in" is signed out by it.
 *
 * The rotation goes through `adminAuthn.rotateSession`, which is the single-flight — the
 * one legitimate rotation caller in the app, and the reason `realm.ts` has a barrier
 * around it at all.
 */

import { useCallback, useRef, useState } from "react";

import { LogOut, RefreshCw, Timer } from "lucide-react";

import { DANGER_BUTTON, NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import { useFocusTrap } from "@/lib/focusTrap";
import { ADMIN_SIGN_IN_PATH, adminAuthn } from "@/lib/authn/adminAuthn";
import { useCountdown } from "@/lib/authn/useCountdown";
import { useIdleTimeout } from "@/lib/authn/useIdleTimeout";

/**
 * 25 minutes to the warning, 5 more to the sign-out — 30 in total, which is exactly
 * `REALM_TIMEOUTS["admin"].idle` in `apps/api/authn/sessions.py`.
 *
 * The equality is the justification, not a coincidence: see `useIdleTimeout.ts` for why
 * the server's own bound never fires under a polling console, and why this is what makes
 * it true again. Five minutes of warning because the thing being protected from a false
 * positive is an operator mid-way through a KYC review, and because a warning short enough
 * to miss while making tea is a warning that only ever loses work.
 */
export const ADMIN_IDLE_WARNING_MS = 25 * 60 * 1000;
export const ADMIN_IDLE_LOGOUT_MS = 5 * 60 * 1000;

export function AdminIdleTimeoutModal({ enabled }: { enabled: boolean }) {
  const [deadline, setDeadline] = useState<number | null>(null);
  const [extending, setExtending] = useState(false);
  const [failed, setFailed] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const remaining = useCountdown(deadline);

  const endSession = useCallback(() => {
    setDeadline(null);
    void adminAuthn.signOut().finally(() => {
      if (typeof window !== "undefined") window.location.assign(ADMIN_SIGN_IN_PATH);
    });
  }, []);

  useIdleTimeout({
    warningAfterMs: ADMIN_IDLE_WARNING_MS,
    logoutAfterWarningMs: ADMIN_IDLE_LOGOUT_MS,
    onWarning: () => {
      setFailed(false);
      setDeadline(Date.now() + ADMIN_IDLE_LOGOUT_MS);
    },
    onActive: () => setDeadline(null),
    onLogout: endSession,
    enabled,
  });

  const visible = deadline !== null;

  const extend = useCallback(() => {
    setExtending(true);
    setFailed(false);
    void adminAuthn
      .rotateSession()
      .then((session) => {
        // The server's answer, re-read from the subject row. See the file docstring.
        if (session.realm === "admin" && session.mfa_complete) {
          setDeadline(null);
          return;
        }
        endSession();
      })
      .catch(() => {
        // NOT a sign-out. A failed rotation is most often a dropped connection, and
        // ending a live admin session because one request did not land is the §5.7 defect
        // 9 mistake with real consequences. The countdown keeps running, so an operator
        // who is genuinely gone is still signed out on time.
        setFailed(true);
      })
      .finally(() => setExtending(false));
  }, [endSession]);

  // Escape does NOT dismiss: closing the warning without extending would leave the
  // countdown running behind a screen that no longer mentions it. The two buttons are the
  // only exits, which is what an `alertdialog` is for.
  useFocusTrap(panel, visible, () => {}, "container");

  if (!visible) return null;

  const minutes = Math.floor(remaining / 60);
  const seconds = String(remaining % 60).padStart(2, "0");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={panel}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="admin-idle-title"
        aria-describedby="admin-idle-body"
        tabIndex={-1}
        className="w-full max-w-md rounded-card border border-line bg-surface p-4 shadow-lg outline-none sm:p-6"
      >
        <h2 id="admin-idle-title" className="flex items-center gap-2 text-[17px] font-semibold text-ink">
          <Timer aria-hidden className="h-4 w-4" />
          Still there?
        </h2>
        <div id="admin-idle-body" className="mt-3 space-y-3 text-sm text-ink-muted">
          <p>
            This operator console signs itself out after 30 minutes without activity.{" "}
            {/* `role="timer"` with a polite live region: a countdown that only changes
                visually is a deadline a screen-reader user cannot see coming. */}
            <span role="timer" aria-live="polite" className="font-semibold tabular-nums text-ink">
              {minutes}:{seconds}
            </span>{" "}
            remaining.
          </p>
          <p>Anything you have typed and not saved will be lost when it does.</p>
          {failed && (
            <NoticeBox tone="warn" title="We could not extend the session">
              <p className="mt-1">
                Your session has not been ended — the request did not reach Calevate. Check
                your connection and try again before the timer runs out.
              </p>
            </NoticeBox>
          )}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className={PRIMARY_BUTTON} disabled={extending} onClick={extend}>
            <RefreshCw aria-hidden className="h-4 w-4" />
            {extending ? "Extending…" : "Stay signed in"}
          </button>
          <button type="button" className={DANGER_BUTTON} disabled={extending} onClick={endSession}>
            <LogOut aria-hidden className="h-4 w-4" />
            Sign out now
          </button>
        </div>
      </div>
    </div>
  );
}
