"use client";

/**
 * `/auth/admin/reset-password?token=…` — spend an operator reset link (D-174).
 *
 * The token leaves the URL on the first client render (`useLinkToken`), so it is not left
 * in the address bar, the history or a `Referer`. Confirming revokes every session on the
 * account — the API's own behaviour, stated on screen because it is the part a person
 * would otherwise discover by being signed out of another tab.
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { MissingLinkCode, SetPasswordForm } from "@/components/authn/setPasswordForm";
import { Card, NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import { ADMIN_FORGOT_PATH, ADMIN_SIGN_IN_PATH, adminAuthn } from "@/lib/authn/adminAuthn";
import { useIdempotencyKey } from "@/lib/authn/useIdempotencyKey";
import { useLinkToken } from "@/lib/authn/useLinkToken";

export default function AdminResetPasswordPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Operator console">
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Choose a new operator password
          </h1>
          <AdminResetBody />
        </div>
      </AuthPageFrame>
    </Providers>
  );
}

function AdminResetBody() {
  const { token } = useLinkToken();
  // Keyed on the token, so a retry after a dropped connection reuses the key and a
  // different link mints a fresh one. See `useIdempotencyKey`.
  const idempotencyKey = useIdempotencyKey(`reset-confirm:admin:${token}`);

  return (
    <SetPasswordForm
      submitLabel="Set my new password"
      intro={
        <>
          <p>
            This link works once and expires an hour after it was sent. Setting a password
            here also ends every operator session on this account, everywhere.
          </p>
        </>
      }
      onSubmit={({ token: linkToken, password }) =>
        adminAuthn.confirmPasswordReset({ token: linkToken, password }, idempotencyKey)
      }
      renderSuccess={() => (
        <Card>
          <div className="space-y-3 text-sm text-ink-muted">
            <NoticeBox tone="ok" title="Your password has been changed">
              <p className="mt-1">
                Every operator session on this account has been ended. Sign in again with
                the new password — you will be asked for an emailed code as usual.
              </p>
            </NoticeBox>
            <Link href={ADMIN_SIGN_IN_PATH} className={PRIMARY_BUTTON}>
              Go to sign-in
            </Link>
          </div>
        </Card>
      )}
      renderMissingToken={
        <MissingLinkCode
          what="reset"
          remedy={`If that does not work, ask for a fresh link from ${ADMIN_FORGOT_PATH}.`}
        />
      }
    />
  );
}
