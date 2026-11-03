"use client";

/**
 * `/auth/admin/bootstrap?token=…` — the first administrator's setup link (D-171, D-174).
 *
 * How a deployment acquires its first operator. Unauthenticated by necessity: there is
 * nobody to authenticate as until it succeeds. What stands in for a session is the token —
 * 256 bits, mailed to an address a deploying operator named on the command line, single-use,
 * one hour, and refused outright once the named account already has a password, so a leaked
 * link from a finished deploy opens nothing.
 *
 * **Admin realm only, structurally.** `POST /v1/auth/client/bootstrap/confirm` is not
 * declared on the client router at all and answers 404, and there is no client-realm
 * spelling of this page either — see `lib/authn/adminAuthn.ts`.
 *
 * The email transport is an external blocker (AUTH-MIGRATION §9 Q2 / §11: "a real email
 * transport … until an account exists, the bootstrap link is read off the operator's own
 * terminal"), so today this link is copied from `scripts/bootstrap_admin.py`'s output. The
 * page is identical either way; only where the operator got the link differs.
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthCard, AuthHeading, AuthPageFrame } from "@/components/authPage";
import { MissingLinkCode, SetPasswordForm } from "@/components/authn/setPasswordForm";
import { NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import { ADMIN_SIGN_IN_PATH, confirmAdminBootstrap } from "@/lib/authn/adminAuthn";

export default function AdminBootstrapPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Operator console">
        <AuthCard>
          <AuthHeading title="Set up the first operator account" />
          <SetPasswordForm
            realm="admin"
            submitLabel="Set the password"
            intro={
              <>
                <p>
                  Your password makes the linked address an operator.
                </p>
                <p className="text-xs text-ink-faint">
                  The address is fixed in the link. Wrong one? Get a new link.
                </p>
              </>
            }
            onSubmit={({ token, password }) => confirmAdminBootstrap({ token, password })}
            renderSuccess={() => (
              <div>
                <div className="space-y-3 text-sm text-ink-muted">
                  <NoticeBox tone="ok" title="The first operator account is ready">
                    Sign in with this address and an emailed code.
                  </NoticeBox>
                  <Link href={ADMIN_SIGN_IN_PATH} className={`${PRIMARY_BUTTON} w-full justify-center`}>
                    Go to sign-in
                  </Link>
                </div>
              </div>
            )}
            renderMissingToken={
              <MissingLinkCode
                what="setup"
                remedy="Or run scripts/bootstrap_admin.py for a fresh link."
              />
            }
          />
        </AuthCard>
      </AuthPageFrame>
    </Providers>
  );
}
