"use client";

/**
 * `admin.calevate.tech/auth/admin/sign-in` — the operator door (D-174).
 *
 * Two steps, because `MFA_REQUIRED_REALMS` contains this realm: a password, then the
 * six-digit code emailed to the address on file. Which step comes next is the server's
 * answer and never this page's guess — see `components/authn/signInForm.tsx`.
 *
 * `AdminGuestOnly` wraps it with the GUEST audience, not the console's, which is §5.4's
 * split: sharing one `blocked` flag with the protected console would mean a failed restore
 * on `/auth/admin` leaves this page permanently convinced restore is impossible — the one
 * page whose job is to fix that.
 *
 * ## THIS IS THE ONLY OPERATOR DOOR — the migration this note used to describe is over
 *
 * It said "`/admin/sign-in` still mounts Clerk and still works … `apps/api/core/auth.py`
 * does not yet accept the first-party session cookie". Both halves are now false and the
 * second is the one that matters: `core/auth.py` reads the realm's `__Host-` cookie
 * through `authn/cookies.read_token` and there is no identity vendor left to fall back to
 * (D-177). There is no `/admin/sign-in` route in this app either — this path is where an
 * operator signs in, and the console it lands them in authenticates with the session
 * minted here.
 */

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { SignInForm } from "@/components/authn/signInForm";
import {
  ADMIN_FORGOT_PATH,
  ADMIN_SESSION_PATH,
  adminAuthn,
} from "@/lib/authn/adminAuthn";
import { AdminGuestOnly } from "@/lib/authn/adminSession";

export default function AdminSignInPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Operator console">
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Sign in to the operator console
          </h1>
          <AdminGuestOnly>
            <SignInForm
              authn={adminAuthn}
              forgotPath={ADMIN_FORGOT_PATH}
              onSignedIn={() => {
                // Hard navigation, per §5.5: a soft one can stall on the way out of a
                // route group, and a stalled redirect immediately after a sign-in reads
                // as a sign-in that failed.
                window.location.assign(ADMIN_SESSION_PATH);
              }}
              footer={
                <p className="text-xs text-ink-faint">
                  Operator accounts are created by invitation only. There is no sign-up
                  here, and there is no route that makes one.
                </p>
              }
            />
          </AdminGuestOnly>
        </div>
      </AuthPageFrame>
    </Providers>
  );
}
