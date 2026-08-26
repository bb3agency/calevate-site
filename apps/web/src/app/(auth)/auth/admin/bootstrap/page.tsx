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
import { AuthPageFrame } from "@/components/authPage";
import { MissingLinkCode, SetPasswordForm } from "@/components/authn/setPasswordForm";
import { Card, NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import { ADMIN_SIGN_IN_PATH, confirmAdminBootstrap } from "@/lib/authn/adminAuthn";

export default function AdminBootstrapPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Operator console">
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Set up the first operator account
          </h1>
          <SetPasswordForm
            realm="admin"
            submitLabel="Set the password"
            intro={
              <>
                <p>
                  This link was issued for one named address by whoever deployed this
                  installation. Choosing a password here makes that address an operator and
                  spends the link.
                </p>
                <p>
                  The address is not shown, and cannot be changed from this page — it is
                  fixed inside the link. If it is wrong, ask for a new one rather than
                  continuing.
                </p>
              </>
            }
            onSubmit={({ token, password }) => confirmAdminBootstrap({ token, password })}
            renderSuccess={() => (
              <Card>
                <div className="space-y-3 text-sm text-ink-muted">
                  <NoticeBox tone="ok" title="The first operator account is ready">
                    <p className="mt-1">
                      Sign in with the address the link was issued for. You will be asked
                      for an emailed six-digit code — the operator console requires one on
                      every sign-in.
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
                what="setup"
                remedy="If that does not work, run scripts/bootstrap_admin.py again to issue a fresh link."
              />
            }
          />
        </div>
      </AuthPageFrame>
    </Providers>
  );
}
