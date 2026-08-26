"use client";

/**
 * `app.calevate.tech/auth/sign-in` — where a client's staff sign in (D-174).
 *
 * The client realm is not in `MFA_REQUIRED_REALMS`, so `POST /login` answers
 * `authenticated` here and the form never reaches its second step. It is the SAME form as
 * the admin realm's, and it renders one step or two because the SERVER said so — a client
 * that hard-coded "no second factor on this realm" would be one configuration change away
 * from silently skipping one.
 *
 * Duplicated page rather than a shared one parameterised by realm: every realm-dependent
 * value here is a literal, and CLAUDE.md's "never share session logic" is the rule that
 * makes that worth the repetition.
 */

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { SignInForm } from "@/components/authn/signInForm";
import { SignedOutToast } from "@/components/authn/signedOutToast";
import {
  CLIENT_ACCEPT_INVITE_PATH,
  CLIENT_CONSOLE_PATH,
  CLIENT_FORGOT_PATH,
  clientAuthn,
} from "@/lib/authn/clientAuthn";
import { ClientGuestOnly } from "@/lib/authn/clientSession";

export default function ClientSignInPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console">
        <div className="space-y-4">
          <SignedOutToast realm="client" realmLabel="Calevate" />
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Sign in
          </h1>
          <ClientGuestOnly>
            <SignInForm
              authn={clientAuthn}
              forgotPath={CLIENT_FORGOT_PATH}
              onSignedIn={() => {
                // The console, not the account page — see `CLIENT_CONSOLE_PATH`.
                window.location.assign(CLIENT_CONSOLE_PATH);
              }}
              footer={
                <p className="text-xs text-ink-faint">
                  Invited by a colleague? Open the link they sent you — it sets
                  your password and adds you to their account in one step (
                  {CLIENT_ACCEPT_INVITE_PATH}).
                </p>
              }
            />
          </ClientGuestOnly>
        </div>
      </AuthPageFrame>
    </Providers>
  );
}
