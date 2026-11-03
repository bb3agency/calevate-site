"use client";

/**
 * `/auth/accept-invitation?token=…` — redeem a colleague's invitation (D-174).
 *
 * One call where the Clerk-era flow took two, because there is no vendor to have made the
 * account first: `POST /v1/auth/client/invitations/accept` creates the `users` row, sets
 * the password, burns the invitation under a CAS on `used_at` and issues a session.
 *
 * ## The address is not a field here, and that is a security property
 *
 * It comes from the INVITATION and never from the request, which the API's own docstring
 * calls "strictly stronger than the old comparison" — it removes `invitation_wrong_recipient`
 * from this path entirely. So there is nothing on this screen for an invitee to get wrong,
 * and no branch in which we tell a stranger whose address an invitation was for.
 *
 * ## Nothing is redeemed on mount
 *
 * The `/invite` page argues this at length for the Clerk path and the argument holds
 * harder here: the burn is a CAS on `used_at IS NULL`, so an effect that POSTed on mount
 * would spend the token on a page load — including React Strict Mode's second one in
 * development, whose reward is telling an invitee their brand-new invitation has already
 * been used. Redemption is a button press, by the person the audit row is about to name.
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthCard, AuthHeading, AuthPageFrame } from "@/components/authPage";
import { GoogleSignIn } from "@/components/authn/googleSignIn";
import { MissingLinkCode, SetPasswordForm } from "@/components/authn/setPasswordForm";
import { NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import { ROLE_COPY } from "@/lib/api/members";
import {
  CLIENT_SIGN_IN_PATH,
  acceptInvitation,
  type AcceptedInvitation,
} from "@/lib/authn/clientAuthn";

export default function AcceptInvitationPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console">
        <AuthCard>
          <AuthHeading title="Accept your invitation" />
          <SetPasswordForm<AcceptedInvitation>
            realm="client"
            submitLabel="Accept and create my account"
            askForName
            intro={(token) => (
              <>
                <div className="mb-2">
                  <GoogleSignIn
                    invitationToken={token}
                    label="Accept with Google"
                    divider="or choose a password"
                  />
                </div>
                <p>
                  A password creates your account and joins the business.
                </p>
                <p>
                  Already have an account? Enter its password.
                </p>
                <p className="text-xs text-ink-faint">
                  Your email comes from the invitation.
                </p>
              </>
            )}
            onSubmit={({ token, password, name }) => acceptInvitation({ token, password, name })}
            renderSuccess={(result) => <Joined result={result} />}
            renderMissingToken={
              <MissingLinkCode
                what="invitation"
                remedy="Or ask whoever invited you for a fresh link."
              />
            }
          />
        </AuthCard>
      </AuthPageFrame>
    </Providers>
  );
}

/** Done — and every word of it is the server's own answer. */
function Joined({ result }: { result: AcceptedInvitation }) {
  const role = lookup(ROLE_COPY, result.role);
  return (
    <div>
      <div className="space-y-3 text-sm text-ink-muted">
        <NoticeBox tone="ok" title={`You joined ${result.slug} as ${role?.label ?? result.role}`}>
          {role && <p className="mt-1">{role.can}</p>}
        </NoticeBox>
        <p>You are signed in. This invite link is now used up.</p>
        <Link href={`/c/${result.slug}`} className={`${PRIMARY_BUTTON} w-full justify-center`}>
          Open the dashboard
        </Link>
        <p className="text-xs text-ink-faint">
          Next time,{" "}
          <Link href={CLIENT_SIGN_IN_PATH} className="text-brand-strong underline underline-offset-2 dark:text-brand-bright">
            sign in
          </Link>{" "}
          with the address the invitation was sent to.
        </p>
      </div>
    </div>
  );
}
