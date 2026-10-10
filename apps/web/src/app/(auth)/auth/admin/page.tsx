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

import type { ReactNode } from "react";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { BACK_LINK, EmailRow, SessionsSection } from "@/components/authn/accountSections";
import { AdminIdleTimeoutModal } from "@/components/authn/adminIdleTimeoutModal";
import { PasswordRow } from "@/components/authn/passwordRow";
import { AccountPageSkeleton } from "@/components/authn/skeletons";
import { StepUpPrompt } from "@/components/authn/stepUpPrompt";
import { Section } from "@/components/console/section";
import { SettingRows } from "@/components/console/settingRow";
import { StatusPill } from "@/components/console/statusPill";
import {
  ADMIN_CONSOLE_PATH,
  ADMIN_SIGN_IN_PATH,
  adminAuthn,
  changeAdminPassword,
} from "@/lib/authn/adminAuthn";
import { adminConsoleUrl } from "@/lib/consoleOrigin";
import {
  AdminSessionGate,
  AdminSessionProvider,
  useAdminSession,
} from "@/lib/authn/adminSession";

export default function AdminSessionPage() {
  return (
    <Providers>
      <AdminSessionProvider>
        <AuthPageFrame realmLabel="Operator console" width="wide" ground="surface">
          <div>
            <header className="space-y-3">
              <Link href={adminConsoleUrl(ADMIN_CONSOLE_PATH)} className={BACK_LINK}>
                <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
                Back to the operator console
              </Link>
              <h1 className="text-title text-ink">Your operator account</h1>
            </header>
            <AdminGate>
              <AdminSessionBody />
            </AdminGate>
          </div>
        </AuthPageFrame>
      </AdminSessionProvider>
    </Providers>
  );
}

/** The realm's fail-closed gate, with this page's own skeleton for the wait. */
function AdminGate({ children }: { children: ReactNode }) {
  const { status } = useAdminSession();
  if (status === "restoring") return <AccountPageSkeleton />;
  return <AdminSessionGate>{children}</AdminSessionGate>;
}

function AdminSessionBody() {
  const { session, retry } = useAdminSession();

  return (
    <>
      {/* Enabled only while there is a session to protect: no listeners and no timers on
          a signed-out page. */}
      <AdminIdleTimeoutModal enabled={session !== null} />
      {/* The step-up prompt has to be mounted on this page, which is outside
          `app/admin/layout.tsx`: without it `requireStepUp` returns a promise nobody can
          settle, and the password change hangs on a stale second factor. */}
      <StepUpPrompt />

      {session?.mfa_complete ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusPill tone="ok">Two-factor complete</StatusPill>
        </div>
      ) : null}

      <div className="mt-10 space-y-10">
        <Section title="Sign-in">
          <SettingRows className="border-y border-line">
            <EmailRow
              authn={adminAuthn}
              verified={session?.email_verified ?? false}
              onVerified={retry}
            />
            {/* `changeAdminPassword`, not `adminAuthn.changePassword`: this realm's route
                also requires a second factor proved in the last 30 minutes, and the
                wrapper turns that refusal into the step-up prompt instead of a dead end. */}
            <PasswordRow realm="admin" changePassword={changeAdminPassword} />
          </SettingRows>
        </Section>

        <SessionsSection
          authn={adminAuthn}
          signInPath={ADMIN_SIGN_IN_PATH}
          lifetime="A session ends after 30 minutes without activity, and after 8 hours regardless. You are warned a few minutes before an idle session ends."
          everywhereHint="Use it if a laptop or phone has gone missing."
          everywhereConsequence="Every operator session on this account ends, on every device, including this one. You will need your password and an emailed code to sign in again."
        />
      </div>
    </>
  );
}
