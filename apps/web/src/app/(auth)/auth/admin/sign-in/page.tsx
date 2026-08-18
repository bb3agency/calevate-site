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
 * ## This route exists alongside the Clerk one, and that is the migration, not a fork
 *
 * `/admin/sign-in` still mounts Clerk and still works. AUTH-MIGRATION §5 step 6 ("deleting
 * Clerk") is explicitly NOT built, `apps/api/core/auth.py` does not yet accept the
 * first-party session cookie, and this slice owns `apps/web` only — so pointing the
 * existing path here would sign an operator into a console every one of whose API calls
 * would then 401. Two paths until the backend leg lands; one afterwards.
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
