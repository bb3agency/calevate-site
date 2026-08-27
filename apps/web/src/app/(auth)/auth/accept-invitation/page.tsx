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
import { AuthPageFrame } from "@/components/authPage";
import { MissingLinkCode, SetPasswordForm } from "@/components/authn/setPasswordForm";
import { Card, NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
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
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Accept your invitation
          </h1>
          <SetPasswordForm<AcceptedInvitation>
            realm="client"
            submitLabel="Accept and create my account"
            askForName
            intro={
              <>
                <p>
                  Choosing a password here creates your Calevate account and adds you to
                  the business that invited you, in one step.
                </p>
                <p>
                  The email address comes from the invitation itself, so there is nothing
                  to type and nothing to get wrong. We can only name the business after you
                  accept — an invitation names its account to its recipient and to nobody
                  else.
                </p>
              </>
            }
            onSubmit={({ token, password, name }) => acceptInvitation({ token, password, name })}
            renderSuccess={(result) => <Joined result={result} />}
            renderMissingToken={
              <MissingLinkCode
                what="invitation"
                remedy="If that does not work, ask whoever invited you to send a fresh link — they can create one from Settings → Team."
              />
            }
          />
        </div>
      </AuthPageFrame>
    </Providers>
  );
}

/** Done — and every word of it is the server's own answer. */
function Joined({ result }: { result: AcceptedInvitation }) {
  const role = lookup(ROLE_COPY, result.role);
  return (
    <Card>
      <div className="space-y-3 text-sm text-ink-muted">
        <NoticeBox tone="ok" title={`You joined ${result.slug} as ${role?.label ?? result.role}`}>
          {role && <p className="mt-1">{role.can}</p>}
        </NoticeBox>
        <p>
          You are signed in. Bookmark the dashboard — it is where you sign in from now on,
          and the link you followed has been used up.
        </p>
        <Link href={`/c/${result.slug}`} className={PRIMARY_BUTTON}>
          Open the dashboard
        </Link>
        <p className="text-xs text-ink-faint">
          Signed out later?{" "}
          <Link href={CLIENT_SIGN_IN_PATH} className="text-brand-strong underline underline-offset-2">
            Sign in here
          </Link>{" "}
          with the address the invitation was sent to.
        </p>
      </div>
    </Card>
  );
}
