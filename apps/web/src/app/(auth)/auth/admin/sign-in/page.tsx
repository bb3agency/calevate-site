"use client";

/**
 * `admin.calevate.tech/auth/admin/sign-in` — the operator door (D-174).
 *
 * Two steps, because `MFA_REQUIRED_REALMS` contains this realm: a password, then the
 * six-digit code emailed to the address on file. Which step comes next is the server's
 * answer and never this page's guess — see `components/authn/signInForm.tsx`.
 *
 * `AdminGuestOnly` wraps it with the GUEST audience, not the console's: sharing one
 * `blocked` flag with the protected console would mean a failed restore on `/auth/admin`
 * leaves this page permanently convinced restore is impossible — the one page whose job
 * is to fix that.
 *
 * Same frame and form as the client door, no product panel, and its own realm instance,
 * session wrapper and destination (`adminSignedInDestination`: `?next=` inside `/admin`,
 * otherwise `/admin`). This is the only operator door; `core/auth.py` reads the realm's
 * `__Host-` cookie minted here.
 */

import { Providers } from "@/app/providers";
import { AuthCard, AuthHeading, AuthPageFrame } from "@/components/authPage";
import { SignInForm } from "@/components/authn/signInForm";
import { SignedOutToast } from "@/components/authn/signedOutToast";
import {
  ADMIN_FORGOT_PATH,
  adminAuthn,
  adminSignedInDestination,
} from "@/lib/authn/adminAuthn";
import { AdminGuestOnly } from "@/lib/authn/adminSession";

export default function AdminSignInPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Operator console">
        <SignedOutToast realm="admin" realmLabel="operator console" />
        <AuthCard>
          <AdminGuestOnly>
            <SignInForm
              authn={adminAuthn}
              forgotPath={ADMIN_FORGOT_PATH}
              heading={
                <AuthHeading
                  title="Sign in to the operator console"
                  lead="After your password we email a six-digit code to finish signing in."
                />
              }
              onSignedIn={() => {
                // Hard navigation, per §5.5: a soft one can stall on the way out of a
                // route group, and a stalled redirect right after a sign-in reads as a
                // sign-in that failed.
                window.location.assign(adminSignedInDestination());
              }}
              footer={
                <p className="text-sm text-ink-muted">
                  Operator accounts are created by invitation only.
                </p>
              }
            />
          </AdminGuestOnly>
        </AuthCard>
      </AuthPageFrame>
    </Providers>
  );
}
