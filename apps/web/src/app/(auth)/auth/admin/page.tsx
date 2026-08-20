"use client";

/**
 * `/auth/admin` — the operator session itself: what it is, and how to end it (D-174).
 *
 * This is the screen that mounts the whole §5.5 quartet on the admin realm —
 * `AdminSessionProvider` (restore + watchdog), `AdminSessionGate` (fail-closed), the shared
 * `SessionGate` presentation, and the idle-timeout modal — so none of them is a component
 * nobody rendered. CLAUDE.md: "a route nobody mounted … is a defect that looks like
 * progress on a screen."
 *
 * It also earns its place independently. `POST /logout/all` is the only way to end a
 * session that is live on a device an operator no longer holds, and until this page
 * existed there was no way to reach it from a browser at all.
 *
 * ## What this page is NOT
 *
 * It is not the operator console — that is `/admin`, which authenticates with the SAME
 * session this page manages: `core/auth.py` reads the realm's `__Host-` cookie through
 * `authn/cookies.read_token`, and D-177 left no identity vendor behind it. This note
 * used to say `/admin` "still authenticates through Clerk because `apps/api/core/auth.py`
 * does not yet accept the first-party session cookie", which was the migration state and
 * has not been true since that verifier landed. What is left here is the half a console
 * shell has no business carrying: ending a session on a device the operator no longer
 * holds, and verifying the address the six-digit code is sent to.
 */

import { useCallback } from "react";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { LogOut, ShieldCheck, Smartphone } from "lucide-react";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { AdminIdleTimeoutModal } from "@/components/authn/adminIdleTimeoutModal";
import { EmailVerificationPanel } from "@/components/authn/emailVerificationPanel";
import { AuthProblemNotice } from "@/components/authn/fields";
import { Card, DANGER_BUTTON, NoticeBox, SECONDARY_BUTTON } from "@/components/ui";
import { ADMIN_SIGN_IN_PATH, adminAuthn } from "@/lib/authn/adminAuthn";
import {
  AdminSessionGate,
  AdminSessionProvider,
  useAdminSession,
} from "@/lib/authn/adminSession";

export default function AdminSessionPage() {
  return (
    <Providers>
      <AdminSessionProvider>
        <AuthPageFrame realmLabel="Operator console">
          <div className="space-y-4">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">
              Your operator session
            </h1>
            <AdminSessionGate>
              <AdminSessionBody />
            </AdminSessionGate>
          </div>
        </AuthPageFrame>
      </AdminSessionProvider>
    </Providers>
  );
}

function AdminSessionBody() {
  const { session, retry } = useAdminSession();

  const leave = useCallback(() => {
    window.location.assign(ADMIN_SIGN_IN_PATH);
  }, []);

  const signOut = useMutation({ mutationFn: () => adminAuthn.signOut(), onSuccess: leave });
  const signOutAll = useMutation({
    mutationFn: () => adminAuthn.signOutEverywhere(),
    onSuccess: leave,
  });

  return (
    <>
      {/* Enabled only while there is a session to protect — no listeners and no timers on
          a signed-out page. */}
      <AdminIdleTimeoutModal enabled={session !== null} />

      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <NoticeBox
            tone="ok"
            icon={<ShieldCheck aria-hidden className="h-4 w-4" />}
            title="You are signed in to the operator console"
          >
            <p className="mt-1">
              Two-factor authentication is complete on this session. It ends by itself
              after 30 minutes without activity, and after 8 hours regardless.
            </p>
          </NoticeBox>
          <p>
            This console warns you a few minutes before an idle session ends, so you can
            keep it open without losing what you were doing.
          </p>
        </div>
      </Card>

      <Card>
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-ink">Email address</h2>
          <EmailVerificationPanel
            authn={adminAuthn}
            verified={session?.email_verified ?? false}
            onVerified={retry}
          />
        </div>
      </Card>

      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <h2 className="text-base font-semibold text-ink">Ending sessions</h2>
          <p>
            Signing out ends this browser&apos;s session. Signing out everywhere ends every
            operator session on this account, on every device — use it if a laptop or phone
            has gone missing.
          </p>
          <AuthProblemNotice error={signOut.error ?? signOutAll.error} />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={signOut.isPending || signOutAll.isPending}
              onClick={() => {
                if (signOut.isPending) return;
                signOut.mutate();
              }}
            >
              <LogOut aria-hidden className="h-4 w-4" />
              {signOut.isPending ? "Signing out…" : "Sign out"}
            </button>
            <button
              type="button"
              className={DANGER_BUTTON}
              disabled={signOut.isPending || signOutAll.isPending}
              onClick={() => {
                if (signOutAll.isPending) return;
                signOutAll.mutate();
              }}
            >
              <Smartphone aria-hidden className="h-4 w-4" />
              {signOutAll.isPending ? "Signing out…" : "Sign out everywhere"}
            </button>
          </div>
        </div>
      </Card>

      <p className="text-sm text-ink-muted">
        <Link href="/admin" className="text-brand-strong underline underline-offset-2">
          Open the operator console
        </Link>
      </p>
    </>
  );
}
