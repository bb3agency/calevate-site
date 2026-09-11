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
 * It is not the client dashboard: that lives at `/c/<slug>` and authenticates with the
 * SAME session this page manages — `core/auth.py` reads the realm's `__Host-` cookie
 * (`authn/cookies.read_token`) and D-177 left no identity vendor behind it. This note
 * used to say the dashboard "still authenticates through Clerk, because
 * `apps/api/core/auth.py` does not yet read the first-party session cookie"; that was the
 * migration state, and it closed.
 */

import { useCallback } from "react";

import { useMutation, type UseQueryResult } from "@tanstack/react-query";
import Link from "next/link";
import { Building2, LogOut, ShieldCheck, Smartphone, UserRound } from "lucide-react";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { ChangePasswordForm } from "@/components/authn/changePasswordForm";
import { EmailVerificationPanel } from "@/components/authn/emailVerificationPanel";
import { AuthProblemNotice } from "@/components/authn/fields";
import {
  Card,
  DANGER_BUTTON,
  Fact,
  NoticeBox,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import type { Me } from "@/lib/api/client";
import { useUnscopedMe } from "@/lib/api/hooks";
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
  // WHICH ACCOUNT THIS SESSION IS IN, from the server — the one thing this page could not
  // previously say. The session itself carries a realm, a subject id and a verified flag
  // and nothing a person recognises, so "Your account" named no account: an owner of two
  // businesses, or a colleague invited to one, had no way to tell from this screen whose
  // account they were about to change the password on.
  //
  // `useUnscopedMe` rather than `useMe(session)`: this page is inside a session and
  // outside an account, and has no slug to key by (`lib/api/hooks.ts`).
  const me = useUnscopedMe();

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
        <div className="space-y-4 text-sm text-ink-muted">
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
          <WhoseAccount me={me} />
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
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-ink">Change password</h2>
          {/* The CLIENT realm's own call, unwrapped: there is no step-up on this realm to
              answer — `service.MFA_REQUIRED_REALMS` is `{"admin"}`, so nothing here ever
              stamps the `mfa_verified_at` a freshness check would read. What proves it is
              them is the current password, which the API demands on both realms. */}
          <ChangePasswordForm
            realm="client"
            changePassword={(input) => clientAuthn.changePassword(input)}
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

      {/* THE WAY BACK, and there was none. The console links here (the sidebar footer's
          "Your account"); this page linked nowhere, so verifying an address or changing a
          password ended on a screen whose only exits were two sign-out buttons. The
          operator realm already had its twin of this line (`/auth/admin`), which is the
          precedent this follows rather than a new pattern.

          `/c` rather than `/c/<slug>`, EVEN WHERE THE SLUG IS ON SCREEN ABOVE: `/c` is the
          junction that resolves "which console is mine" and already renders every failure
          of that question. A second link built from `me.data` would be a second answer to
          it, dead in exactly the case the junction handles — the read that failed. */}
      <p className="text-sm text-ink-muted">
        <Link
          href="/c"
          className="text-brand-strong underline underline-offset-2 dark:text-brand-bright"
        >
          Open your console
        </Link>
      </p>
    </>
  );
}

/**
 * The account this session is in, and what this person is in it.
 *
 * §52 throughout: in flight is a skeleton, a failed read is a refusal, and neither is an
 * account name. Nothing here is coalesced to a placeholder — a dash where an account name
 * belongs is indistinguishable from a dash where the API is dead, which is the defect the
 * console sidebar had to grow an amber arm for.
 */
function WhoseAccount({ me }: { me: UseQueryResult<Me> }) {
  if (me.error != null) {
    return (
      <div className="space-y-2">
        <AuthProblemNotice error={me.error} />
        <p>
          Your sign-in is fine — this is the separate read that says which account it
          belongs to. Reload to try again. If you belong to more than one Calevate account,
          open the one you want from its own link: this page can only describe one.
        </p>
      </div>
    );
  }
  if (!me.data) return <Skeleton rows={2} label="Reading your account…" />;

  const organization = me.data.organization;
  const role = me.data.role;
  if (!organization && !role) {
    return (
      <p>
        This sign-in is not attached to an account yet. Ask whoever invited you to send the
        invitation again.
      </p>
    );
  }

  return (
    <dl className="grid gap-4 sm:grid-cols-2">
      {organization && (
        <Fact
          label="Account"
          icon={<Building2 aria-hidden className="h-3.5 w-3.5" />}
          hint={organization.slug}
        >
          {organization.name}
        </Fact>
      )}
      {role && (
        <Fact
          label="Your role"
          icon={<UserRound aria-hidden className="h-3.5 w-3.5" />}
          // DERIVED FROM THE PERMISSIONS THE SERVER SENT, not from the word "owner": the
          // set is what every gated control on the console previews itself against
          // (`useWriteAccess`), so the sentence here and the controls there cannot
          // disagree about what this person may do.
          hint={
            me.data.permissions.includes("org:manage")
              ? "You can change this account's settings and invite colleagues."
              : "Settings, billing and the team are your account owner's to change."
          }
        >
          <span className="capitalize">{role}</span>
        </Fact>
      )}
    </dl>
  );
}
