"use client";

/**
 * `/auth/account` — a client user's own session: verify the address, end sessions (D-174).
 *
 * The client-realm twin of `/auth/admin`, and it mounts this realm's §5.5 quartet so none
 * of it is unrendered. What it does NOT carry is the idle-timeout modal: §5.6 puts that on
 * the admin realm only, and `REALM_TIMEOUTS` says why — 30 minutes idle there against 12
 * hours here, "because their blast radii differ by an order of magnitude". A modal warning
 * a clinic receptionist twice a day is a control that teaches people to dismiss controls.
 *
 * It is not the client dashboard: that lives at `/c/<slug>` and still authenticates
 * through Clerk, because `apps/api/core/auth.py` does not yet read the first-party session
 * cookie. See `/auth/admin` for the same note and what closes it.
 */

import { useCallback } from "react";

import { useMutation } from "@tanstack/react-query";
import { LogOut, ShieldCheck, Smartphone } from "lucide-react";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { EmailVerificationPanel } from "@/components/authn/emailVerificationPanel";
import { AuthProblemNotice } from "@/components/authn/fields";
import { Card, DANGER_BUTTON, NoticeBox, SECONDARY_BUTTON } from "@/components/ui";
import { CLIENT_SIGN_IN_PATH, clientAuthn } from "@/lib/authn/clientAuthn";
import {
  ClientSessionGate,
  ClientSessionProvider,
  useClientSession,
} from "@/lib/authn/clientSession";

export default function ClientAccountPage() {
  return (
    <Providers>
      <ClientSessionProvider>
        <AuthPageFrame realmLabel="Client console">
          <div className="space-y-4">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">Your account</h1>
            <ClientSessionGate>
              <ClientAccountBody />
            </ClientSessionGate>
          </div>
        </AuthPageFrame>
      </ClientSessionProvider>
    </Providers>
  );
}

function ClientAccountBody() {
  const { session, retry } = useClientSession();

  const leave = useCallback(() => {
    window.location.assign(CLIENT_SIGN_IN_PATH);
  }, []);

  const signOut = useMutation({ mutationFn: () => clientAuthn.signOut(), onSuccess: leave });
  const signOutAll = useMutation({
    mutationFn: () => clientAuthn.signOutEverywhere(),
    onSuccess: leave,
  });

  return (
    <>
      <Card>
        <div className="space-y-3 text-sm text-ink-muted">
          <NoticeBox
            tone="ok"
            icon={<ShieldCheck aria-hidden className="h-4 w-4" />}
            title="You are signed in"
          >
            <p className="mt-1">
              This session ends by itself after 12 hours without activity, and after 14 days
              regardless.
            </p>
          </NoticeBox>
        </div>
      </Card>

      <Card>
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-ink">Email address</h2>
          <EmailVerificationPanel
            authn={clientAuthn}
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
            session on this account, on every device.
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
    </>
  );
}
