"use client";

/**
 * What a guarded surface shows while it does not yet have a session (D-174, §5.5).
 *
 * Presentation only — no realm, no session, no fetch. It is given a status and renders
 * the one screen that status deserves, which is why both realms can use it without
 * sharing any session logic: there is none here to share.
 *
 * ## §5.7 defect 9, which is the whole reason this takes a status rather than an error
 *
 * `OpsSessionGate` rendered `error ?? "Sign in to continue."` for every failure, so a
 * transient network failure and an expired session were one sentence to the operator.
 * They have opposite remedies. "You are signed out" tells somebody whose connection
 * dropped to go and re-enter a password that was never the problem, and it does it at the
 * exact moment the network is too broken to accept one. So the two are separate states
 * here, with separate copy and separate controls: `unreachable` offers RETRY and says
 * nothing about the credential; `signed-out` offers SIGN IN and says nothing about the
 * network.
 *
 * BUILD-LOG §52 governs the third: waiting is a waiting state, not a blank and not an
 * empty state, and it announces itself so a screen reader is not left on silence.
 */

import type { ReactNode } from "react";

import Link from "next/link";
import { PlugZap, ShieldAlert } from "lucide-react";

import { Card, NoticeBox, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import type { RealmSessionStatus } from "@/lib/authn/useRealmSession";

export interface SessionGateProps {
  status: RealmSessionStatus;
  /** Names the door in the copy, so an operator can see which realm refused them. */
  realmLabel: string;
  /** Where the sign-in link goes. The caller's realm decides; this component never does. */
  signInPath: string;
  /** Re-run the restore. The remedy for `unreachable`, and only for it. */
  onRetry: () => void;
  /** What a `partial` session should do next — the emailed-code step. */
  secondFactor?: ReactNode;
}

export function SessionGate({
  status,
  realmLabel,
  signInPath,
  onRetry,
  secondFactor,
}: SessionGateProps) {
  if (status === "restoring") {
    return (
      <Card>
        {/* `role="status"` with `aria-live="polite"`: a gate that renders silently is a
            screen reader user waiting on nothing. `Skeleton` is the app's loading shape
            elsewhere; here the wait is the whole screen, so it gets a sentence. */}
        <div role="status" aria-live="polite" className="space-y-2 text-sm text-ink-muted">
          <p className="font-medium text-ink">Checking your {realmLabel} session…</p>
          <p>
            This takes a moment on a slow connection. Nothing has been signed out — we are
            asking the server whether your session is still good.
          </p>
        </div>
      </Card>
    );
  }

  if (status === "partial") {
    return (
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <NoticeBox
            tone="warn"
            icon={<ShieldAlert aria-hidden className="h-4 w-4" />}
            title="This sign-in still needs its emailed code"
          >
            <p className="mt-1">
              Your password was accepted. Until the six-digit code we emailed is entered,
              this session can only finish signing in.
            </p>
          </NoticeBox>
          {secondFactor ?? (
            <Link href={signInPath} className={PRIMARY_BUTTON}>
              Enter the code
            </Link>
          )}
        </div>
      </Card>
    );
  }

  if (status === "unreachable") {
    return (
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          {/* NOT "you are signed out". Nothing here is evidence of that — see the file
              docstring. The copy is about the REQUEST, and it says explicitly that the
              session was not ended, because the reflex on seeing a session screen fail is
              to assume it was. */}
          <NoticeBox
            tone="warn"
            icon={<PlugZap aria-hidden className="h-4 w-4" />}
            title="We could not reach Calevate"
          >
            <p className="mt-1">
              Your session has not been ended — we simply could not ask about it. This is
              usually the connection.
            </p>
          </NoticeBox>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={PRIMARY_BUTTON} onClick={onRetry}>
              Try again
            </button>
            <Link href={signInPath} className={SECONDARY_BUTTON}>
              Sign in instead
            </Link>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="space-y-3 text-sm text-ink-muted">
        <NoticeBox
          tone="stop"
          icon={<ShieldAlert aria-hidden className="h-4 w-4" />}
          title="You are signed out"
        >
          <p className="mt-1">
            This {realmLabel} session is no longer valid. Sessions end on their own after a
            period of inactivity, and signing out everywhere ends them immediately.
          </p>
        </NoticeBox>
        <Link href={signInPath} className={PRIMARY_BUTTON}>
          Sign in
        </Link>
      </div>
    </Card>
  );
}
